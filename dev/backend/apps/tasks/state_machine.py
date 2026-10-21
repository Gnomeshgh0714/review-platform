"""
状态机服务 - 对应PRD §2.3.3状态流转规则
覆盖全部11条转换路径（含REVIEWING->PENDING异常回退）
"""
from django.db import transaction
from django.utils import timezone
from apps.tasks.models import ReviewTask, ReviewAssignment, StateLog


class StateMachineError(Exception):
    """状态转换异常"""
    pass


# 合法状态转换定义（对应PRD V1.1 §2.3.3状态流转规则表）
VALID_TRANSITIONS = {
    # 正常路径
    ('PENDING', 'ASSIGNED'): '分配审稿人（至少1位接受邀请后触发）',
    ('ASSIGNED', 'REVIEWING'): '首位审稿人接受邀请',
    ('REVIEWING', 'SUBMITTED'): '全部已接受审稿人均提交意见 / 编辑强制提前汇总',
    ('SUBMITTED', 'SUMMARIZED'): '编辑触发汇总报告生成',
    ('SUMMARIZED', 'DECIDED'): '编辑录入终审决策',
    # 异常路径
    ('ASSIGNED', 'PENDING'): '全部审稿人均拒绝邀请',
    ('REVIEWING', 'PENDING'): '全部已接受审稿人超时且无可提交意见',  # C-01新增
    ('REVIEWING', 'SUBMITTED'): '部分已提交后其余全部超时，编辑选择强制汇总',  # C-01新增
    # P1预留（P0不实现，仅定义）
    # ('DECIDED', 'REVIEWING'): '退稿重审（P1预留，P0不实现）',
}


class StateMachineService:
    """状态机服务 - 校验和执行状态转换"""

    @staticmethod
    def validate_transition(task, target_state, operator_user=None, reason=''):
        """校验状态转换是否合法"""
        current = task.status
        key = (current, target_state)

        if key not in VALID_TRANSITIONS:
            raise StateMachineError(
                f'非法状态转换: {current} -> {target_state}。'
                f'合法转换: {VALID_TRANSITIONS.get(key, "未定义")}'
            )

        # 特殊校验
        if target_state == 'ASSIGNED':
            # PENDING->ASSIGNED: 需要至少有分配记录
            assignments = task.assignments.filter(
                assignment_status__in=['INVITED', 'ACCEPTED']
            ).count()
            if assignments == 0:
                raise StateMachineError('无法转为已分配：无审稿人分配记录')

        elif target_state == 'REVIEWING' and current == 'ASSIGNED':
            # ASSIGNED->REVIEWING: 需要至少1位审稿人接受
            accepted = task.assignments.filter(assignment_status='ACCEPTED').count()
            if accepted == 0:
                raise StateMachineError('无法转为审稿中：无审稿人接受邀请')

        elif target_state == 'SUBMITTED' and current == 'REVIEWING':
            # REVIEWING->SUBMITTED: 需要全部已接受审稿人提交，或编辑强制汇总
            accepted = task.assignments.filter(assignment_status='ACCEPTED')
            if not reason.startswith('强制'):
                not_submitted = accepted.exclude(assignment_status='SUBMITTED').count()
                if not_submitted > 0:
                    raise StateMachineError(
                        f'无法转为已提交：还有{not_submitted}位审稿人未提交'
                    )

        elif target_state == 'PENDING' and current == 'REVIEWING':
            # REVIEWING->PENDING: 全部超时或编辑选择回退
            accepted = task.assignments.filter(assignment_status__in=['ACCEPTED', 'OVERDUE'])
            submitted = accepted.filter(assignment_status='SUBMITTED').count()
            if submitted > 0 and not reason.startswith('编辑选择回退'):
                raise StateMachineError(
                    '已有审稿人提交意见，回退需编辑明确选择"回退待分配，已提交意见保留为历史记录"'
                )

        return True

    @staticmethod
    @transaction.atomic
    def execute_transition(task, target_state, operator_user=None, reason=''):
        """
        执行状态转换（事务+行锁，确保并发安全）
        对应PRD V1.1 C-04并发控制策略
        """
        # 行锁：防止并发转换
        task = ReviewTask.objects.select_for_update().get(task_id=task.task_id)

        # 校验
        StateMachineService.validate_transition(task, target_state, operator_user, reason)

        old_state = task.status
        task.status = target_state
        task.version += 1  # 乐观锁版本号
        task.save()

        # 记录状态日志
        StateLog.objects.create(
            task=task,
            from_state=old_state,
            to_state=target_state,
            operator_type='EDITOR' if operator_user else 'SYSTEM',
            operator_user=operator_user,
            trigger_reason=reason or VALID_TRANSITIONS.get((old_state, target_state), ''),
        )

        return task

    @staticmethod
    @transaction.atomic
    def check_and_transition_on_submit(task):
        """
        审稿人提交意见后检查是否全部已提交
        如全部已提交则自动转为SUBMITTED状态
        对应PRD V1.1 C-04并发提交处理
        """
        # 行锁：防止并发提交竞态条件
        task = ReviewTask.objects.select_for_update().get(task_id=task.task_id)

        if task.status != 'REVIEWING':
            return task  # 任务不在审稿中状态，不处理

        # 参与本轮审稿的分配：已接受/审稿中/已提交
        # （排除 REJECTED/EXPIRED/OVERDUE——他们不算「已接受待提交」）
        # 注意：不能只查 ACCEPTED——最后一人提交时全员已变为 SUBMITTED，
        # 空集会导致提前返回、自动转换永不触发（AC-T-14 测试实测命中）
        participants = task.assignments.filter(
            assignment_status__in=['ACCEPTED', 'REVIEWING', 'SUBMITTED']
        )
        if participants.count() == 0:
            return task

        not_submitted = participants.exclude(assignment_status='SUBMITTED').count()
        if not_submitted == 0:
            # 全部已提交，自动转换
            old_state = task.status
            task.status = 'SUBMITTED'
            task.version += 1
            task.save()

            StateLog.objects.create(
                task=task,
                from_state=old_state,
                to_state='SUBMITTED',
                operator_type='SYSTEM',
                operator_user=None,
                trigger_reason='全部已接受审稿人均提交意见，系统自动转换',
            )

        return task

    @staticmethod
    @transaction.atomic
    def handle_all_rejected(task, operator_user=None):
        """全部审稿人拒绝邀请 -> 回退到PENDING"""
        return StateMachineService.execute_transition(
            task, 'PENDING', operator_user, '全部审稿人均拒绝邀请'
        )

    @staticmethod
    @transaction.atomic
    def handle_all_overdue(task, operator_user=None, force_summarize=False):
        """
        全部审稿人超时处理
        - force_summarize=False: 回退到PENDING
        - force_summarize=True: 基于已提交意见强制汇总
        对应PRD V1.1 C-01新增路径
        """
        if force_summarize:
            return StateMachineService.execute_transition(
                task, 'SUBMITTED', operator_user,
                '强制汇总：部分已提交后其余全部超时，编辑选择强制汇总'
            )
        else:
            return StateMachineService.execute_transition(
                task, 'PENDING', operator_user,
                '编辑选择回退待分配，已提交意见保留为历史记录'
            )

    @staticmethod
    @transaction.atomic
    def increment_retry_count(task):
        """
        递增任务级重试次数
        超过3次标记"分配困难"并通知主编
        对应PRD V1.1 N-02/S-02
        """
        task = ReviewTask.objects.select_for_update().get(task_id=task.task_id)
        task.retry_count += 1
        task.save()

        if task.retry_count > 3:
            from apps.notifications.services import NotificationService
            NotificationService.notify_editor_in_chief(
                task=task,
                message=f'任务 {task.task_id} 分配困难，已有 {task.retry_count} 次重试'
            )

        return task.retry_count
