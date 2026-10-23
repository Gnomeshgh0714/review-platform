from rest_framework import status, viewsets
from rest_framework.decorators import action
from rest_framework.permissions import IsAuthenticated
from rest_framework.response import Response
from django.db import transaction
from django.utils import timezone
from datetime import timedelta
import logging

from .models import ReviewTask, ReviewAssignment, Template, StateLog
from .serializers import (ReviewTaskSerializer, ReviewTaskCreateSerializer,
                          ReviewAssignmentSerializer, TemplateSerializer, StateLogSerializer)
from .state_machine import StateMachineService, StateMachineError
from apps.notifications.services import NotificationService
from apps.forms.models import ReviewOpinion
from apps.summaries.models import SummaryReport

logger = logging.getLogger(__name__)


class ReviewTaskViewSet(viewsets.ModelViewSet):
    """审稿任务视图集"""

    def get_queryset(self):
        user = self.request.user
        qs = ReviewTask.objects.all()
        # 按角色过滤
        if user.is_editor:
            pass  # 编辑部可见全部
        elif user.is_reviewer:
            # 审稿人仅可见分配给自己的任务（评审意见 V1.2 严重#7：
            # 已拒绝/已过期的分配不再保有任务可见性，随分配生命周期收敛；
            # 保留 INVITED 以便查看邀请详情后再决定接受与否）
            qs = qs.filter(
                assignments__reviewer=user,
                assignments__assignment_status__in=[
                    'INVITED', 'ACCEPTED', 'REVIEWING', 'SUBMITTED', 'OVERDUE',
                ],
            ).distinct()
        elif user.is_author:
            # 作者仅可见自己的稿件
            qs = qs.filter(author_user_id=user)
        return qs.select_related('author_user_id', 'created_by').prefetch_related('assignments')

    def get_serializer_class(self):
        if self.action == 'create':
            return ReviewTaskCreateSerializer
        return ReviewTaskSerializer

    def create(self, request, *args, **kwargs):
        """创建审稿任务（仅编辑部）"""
        if not request.user.is_editor:
            return Response({'error': '仅编辑部可创建任务'}, status=403)

        serializer = self.get_serializer(data=request.data)
        serializer.is_valid(raise_exception=True)

        with transaction.atomic():
            task = serializer.save(
                created_by=request.user,
                status='PENDING',
            )
            # 发送通知给作者
            NotificationService.send_task_created(task)

        return Response(
            ReviewTaskSerializer(task).data,
            status=status.HTTP_201_CREATED
        )

    # 评审意见 V1.2 致命#2（轮1#15）：默认 update/partial_update/destroy 是
    # 免权限收口的旁路通道，与 read_only_fields 漏洞组合可改任务任意字段
    def update(self, request, *args, **kwargs):
        """任务整体修改仅编辑部"""
        if not request.user.is_editor:
            return Response({'error': '仅编辑部可修改任务'}, status=403)
        return super().update(request, *args, **kwargs)

    def partial_update(self, request, *args, **kwargs):
        """任务部分修改（PATCH）仅编辑部"""
        if not request.user.is_editor:
            return Response({'error': '仅编辑部可修改任务'}, status=403)
        return super().partial_update(request, *args, **kwargs)

    def destroy(self, request, *args, **kwargs):
        """任务删除仅编辑部（轮1#66：防审稿人/作者删稿灭迹）"""
        if not request.user.is_editor:
            return Response({'error': '仅编辑部可删除任务'}, status=403)
        return super().destroy(request, *args, **kwargs)

    @action(detail=True, methods=['post'])
    def assign_reviewers(self, request, pk=None):
        """分配审稿人（仅编辑部）"""
        if not request.user.is_editor:
            return Response({'error': '仅编辑部可分配审稿人'}, status=403)

        task = self.get_object()
        if task.status not in ['PENDING', 'ASSIGNED']:
            return Response({'error': f'当前状态({task.status})不允许分配审稿人'}, status=400)

        reviewer_ids = request.data.get('reviewer_user_ids', [])
        deadline_str = request.data.get('deadline')
        invitation_note = request.data.get('invitation_note', '')

        if not reviewer_ids:
            return Response({'error': '请至少选择1位审稿人'}, status=400)

        # V1.2 建议#13：稿件作者本人不可审自己的稿件（双盲与利益冲突
        # 防线，服务端硬性拦截——前端选择器不应出现作者，但服务端为准）
        if task.author_user_id and task.author_user_id in reviewer_ids:
            return Response(
                {'error': '审稿人列表包含稿件作者本人，请重新选择'},
                status=400,
            )

        from apps.users.models import User
        reviewers = User.objects.filter(user_id__in=reviewer_ids, roles__contains=['REVIEWER'])
        if len(reviewers) != len(reviewer_ids):
            return Response({'error': '部分用户不存在或非审稿人角色'}, status=400)

        # 邀请有效期3天
        # V1.2 建议#7：业务时区为 Asia/Shanghai，日期计算用 localdate()
        # （timezone.now().date() 取 UTC 日期，东八区 00:00-08:00 期间会
        # 比本地日期少一天）
        invitation_expiry = timezone.localdate() + timedelta(days=3)
        task_deadline = deadline_str if deadline_str else (timezone.localdate() + timedelta(days=14))

        created = []
        with transaction.atomic():
            for reviewer in reviewers:
                # 检查是否已分配（评审意见 V1.2 严重#10 伴生：仅「仍在参与中」的
                # 分配算重复——回退/拒绝/过期后的历史分配不阻止新一轮重新邀请，
                # 否则 rollback 后编辑部永远无法重新邀请同一批审稿人）
                if ReviewAssignment.objects.filter(
                    task=task, reviewer=reviewer,
                    assignment_status__in=['INVITED', 'ACCEPTED', 'REVIEWING', 'SUBMITTED'],
                ).exists():
                    continue

                assignment = ReviewAssignment.objects.create(
                    task=task,
                    reviewer=reviewer,
                    deadline=task_deadline,
                    invitation_note=invitation_note,
                    invitation_expiry=invitation_expiry,
                    assigned_by=request.user,
                )
                # 发送邀请通知
                NotificationService.send_invitation(task, reviewer, assignment)
                created.append(assignment)

            # 状态转换：PENDING -> ASSIGNED
            if task.status == 'PENDING' and created:
                StateMachineService.execute_transition(
                    task, 'ASSIGNED', request.user, '编辑部分配审稿人'
                )

        return Response({
            'message': f'成功分配{len(created)}位审稿人',
            'assignments': ReviewAssignmentSerializer(created, many=True).data,
        })

    @action(detail=True, methods=['post'])
    def accept_invitation(self, request, pk=None):
        """审稿人接受邀请"""
        task = self.get_object()
        user = request.user

        try:
            assignment = ReviewAssignment.objects.get(task=task, reviewer=user)
        except ReviewAssignment.DoesNotExist:
            return Response({'error': '未找到分配记录'}, status=404)

        if assignment.assignment_status != 'INVITED':
            return Response({'error': f'当前状态({assignment.assignment_status})不允许接受'}, status=400)

        with transaction.atomic():
            assignment.assignment_status = 'ACCEPTED'
            assignment.accepted_at = timezone.now()
            assignment.save()

            # 通知编辑部
            NotificationService.send_accept(assignment)

            # 状态转换：ASSIGNED -> REVIEWING（首位接受时）
            if task.status == 'ASSIGNED':
                StateMachineService.execute_transition(
                    task, 'REVIEWING', user, '首位审稿人接受邀请'
                )

        return Response({'message': '已接受邀请'})

    @action(detail=True, methods=['post'])
    def reject_invitation(self, request, pk=None):
        """审稿人拒绝邀请"""
        task = self.get_object()
        user = request.user
        reason = request.data.get('reason', '')

        try:
            assignment = ReviewAssignment.objects.get(task=task, reviewer=user)
        except ReviewAssignment.DoesNotExist:
            return Response({'error': '未找到分配记录'}, status=404)

        if assignment.assignment_status != 'INVITED':
            return Response({'error': f'当前状态({assignment.assignment_status})不允许拒绝'}, status=400)

        with transaction.atomic():
            # 评审意见 V1.2 严重#6：行锁下重读任务，串行化并发拒绝——
            # 最后两位审稿人同时拒绝时，避免双双在旧快照上判定「还有对方未拒」
            # 而漏判全员拒绝回退（现状仅有日度 process_scheduled 兜底）
            task = ReviewTask.objects.select_for_update().get(task_id=task.task_id)
            assignment.assignment_status = 'REJECTED'
            assignment.rejected_at = timezone.now()
            assignment.rejected_reason = reason
            assignment.save()

            # 通知编辑部
            NotificationService.send_reject(assignment, reason)

            # 检查是否全部拒绝
            remaining = task.assignments.filter(assignment_status='INVITED').count()
            accepted = task.assignments.filter(assignment_status='ACCEPTED').count()
            if remaining == 0 and accepted == 0:
                # 全部拒绝，回退到PENDING
                StateMachineService.handle_all_rejected(task, user)
                # 递增重试计数
                StateMachineService.increment_retry_count(task)

        return Response({'message': '已拒绝邀请'})

    @action(detail=True, methods=['post'])
    def force_summarize(self, request, pk=None):
        """编辑强制提前汇总（部分未提交时）"""
        if not request.user.is_editor:
            return Response({'error': '仅编辑部可操作'}, status=403)

        task = self.get_object()
        if task.status != 'REVIEWING':
            return Response({'error': '仅审稿中状态可强制汇总'}, status=400)

        # PRD AC-T-11：需填写原因
        reason = (request.data.get('reason') or '').strip()
        if not reason:
            return Response({'error': '必须填写强制汇总原因'}, status=400)

        # PRD AC-T-11：至少1份意见已提交
        submitted_count = ReviewOpinion.objects.filter(
            task=task, status='SUBMITTED',
        ).count()
        if submitted_count < 1:
            return Response(
                {'error': '强制汇总要求至少已有1份已提交的审稿意见'},
                status=400,
            )

        # PRD AC-T-11：未提交审稿人被标记（置为EXPIRED，不再参与本轮）
        # （评审意见 V1.2 一般项同型加固：标记与状态转换同一事务，避免
        # 转换失败后 EXPIRED 已落库的半完成状态）
        with transaction.atomic():
            marked = task.assignments.filter(
                assignment_status__in=['INVITED', 'ACCEPTED', 'REVIEWING'],
            ).update(assignment_status='EXPIRED')

            # reason 以「强制」开头是状态机放行 REVIEWING->SUBMITTED 的约定
            StateMachineService.execute_transition(
                task, 'SUBMITTED', request.user, f'强制提前汇总：{reason}'
            )
        return Response({
            'message': '已强制汇总',
            'marked_expired': marked,
            'submitted_opinions': submitted_count,
        })

    @action(detail=True, methods=['post'])
    def handle_overdue(self, request, pk=None):
        """处理全部超时（编辑部选择：强制汇总 or 回退待分配）

        评审意见 V1.2 严重#8/严重#10：
        - summarize 分支对齐 force_summarize 的 AC-T-11 三要素（REVIEWING 状态门/
          ≥1份已提交意见/未提交者置 EXPIRED），封堵绕过校验的姊妹通道——
          0 意见任务直入 SUBMITTED 后将无报告可汇总，永久死局；
        - rollback 分支清退旧轮（已提交意见转 SUPERSEDED、未提交分配置 EXPIRED），
          旧轮数据不再污染新一轮的聚合、≥1 校验与全员交齐判定；
          重邀同一审稿人由 assign_reviewers 的活跃分配去重放行。
        """
        if not request.user.is_editor:
            return Response({'error': '仅编辑部可操作'}, status=403)

        task = self.get_object()
        action_type = request.data.get('action', '')  # 'summarize' or 'rollback'

        if task.status != 'REVIEWING':
            return Response(
                {'error': f'仅审稿中状态可处理超时，当前状态: {task.status}'},
                status=400,
            )

        if action_type == 'summarize':
            # AC-T-11 对齐：至少1份意见已提交
            submitted_count = ReviewOpinion.objects.filter(
                task=task, status='SUBMITTED',
            ).count()
            if submitted_count < 1:
                return Response(
                    {'error': '强制汇总要求至少已有1份已提交的审稿意见'},
                    status=400,
                )
            with transaction.atomic():
                # AC-T-11 对齐：未提交审稿人标记 EXPIRED（与 force_summarize 同口径）
                marked = task.assignments.filter(
                    assignment_status__in=['INVITED', 'ACCEPTED', 'REVIEWING'],
                ).update(assignment_status='EXPIRED')
                StateMachineService.handle_all_overdue(
                    task, request.user, force_summarize=True,
                )
            return Response({
                'message': '已基于已提交意见强制汇总',
                'marked_expired': marked,
                'submitted_opinions': submitted_count,
            })
        elif action_type == 'rollback':
            with transaction.atomic():
                # 旧轮清退：已提交意见转 SUPERSEDED（保留为历史记录，不进入新一轮
                # 聚合/规则引擎/发布门控——所有消费方均按 status='SUBMITTED' 过滤），
                # 未提交分配置 EXPIRED（不能保存草稿/提交，也不阻塞新一轮自动转
                # SUBMITTED）。与状态转换同一事务，转换失败则清退一并回滚
                ReviewOpinion.objects.filter(
                    task=task, status='SUBMITTED',
                ).update(status='SUPERSEDED')
                marked = task.assignments.filter(
                    assignment_status__in=['INVITED', 'ACCEPTED', 'REVIEWING'],
                ).update(assignment_status='EXPIRED')
                StateMachineService.handle_all_overdue(
                    task, request.user, force_summarize=False,
                )
            StateMachineService.increment_retry_count(task)
            # V1.2 建议#15：PRD 超时处理第三选项「重新分配新审稿人（截止
            # 日期≥7天）」经由「回退后重新邀请」达成——回退到 PENDING 后
            # 分配通道重新可用，文案中向编辑部说明该路径
            return Response({
                'message': (
                    '已回退到待分配，已提交意见保留为历史记录；'
                    '如需更换审稿人，可重新分配（建议新截止日期不早于 7 天）'
                ),
                'marked_expired': marked,
            })
        else:
            return Response({'error': 'action必须为summarize或rollback'}, status=400)

    @action(detail=True, methods=['post'])
    def make_decision(self, request, pk=None):
        """录入终审决策（仅编辑部）"""
        if not request.user.is_editor:
            return Response({'error': '仅编辑部可录入决策'}, status=403)

        task = self.get_object()
        if task.status != 'SUMMARIZED':
            return Response({'error': '仅已汇总状态可录入决策'}, status=400)

        decision = request.data.get('decision', '')
        notes = request.data.get('notes', '')
        publish = request.data.get('publish', True)

        if not decision or not notes:
            return Response({'error': '决策结果和说明必填'}, status=400)

        if len(notes) < 100:
            return Response({'error': '决策说明至少100字'}, status=400)

        with transaction.atomic():
            task.final_decision = decision
            task.decision_notes = notes
            task.publish_opinions_to_author = publish
            # 先落库再转换（评审意见 V1.1 致命#6）：execute_transition 内部会
            # select_for_update 重取行，未 save 的内存字段会被丢弃
            task.save(update_fields=[
                'final_decision', 'decision_notes', 'publish_opinions_to_author',
            ])
            task = StateMachineService.execute_transition(
                task, 'DECIDED', request.user, f'终审决策: {decision}'
            )
            # 通知作者（定版裁决 O-1，2026-10-23：publish=False 时仍通知终审决策
            # 结果；send_decide 内部按 publish_opinions_to_author 区分意见公开
            # 状态文案，不含审稿意见详情）
            NotificationService.send_decide(task, decision)
            # 知识库自动归档（PRD §5.3.1：DECIDED 后自动触发第一阶段匿名化）
            # 评审意见 V1.2 严重#4：内层 atomic 形成保存点——归档发生数据库级
            # 错误时仅回滚到保存点，外层决策事务照常提交，「失败不阻断」的
            # 语义才真正成立（此前 IntegrityError 会连带吞掉终审决策落库）
            try:
                with transaction.atomic():
                    from apps.knowledge.services import AnonymizationService
                    report = SummaryReport.objects.filter(
                        task=task,
                    ).order_by('-generated_at').first()
                    AnonymizationService.auto_anonymize(task, report)
            except ValueError:
                pass  # 已存在归档记录（幂等）
            except Exception as e:
                # 归档失败不阻断决策主流程，但不能只静默吞掉
                # V1.2 一般#25：升级 error 日志并通知编辑部人工补归档
                #（PRD §5.3.1：归档缺失会导致该案例从知识库永久缺失）
                logger.error(
                    '知识库归档失败(不阻断决策): task=%s, error=%s',
                    task.task_id, e,
                )
                try:
                    NotificationService._notify_multiple(
                        NotificationService._get_editor_users(),
                        task,
                        'REMIND',
                        '知识库归档失败待人工处理',
                        f'任务 {task.task_id} 终审决策已录入，但知识库自动归档失败，'
                        f'请人工排查补归档。错误信息：{e}',
                    )
                except Exception as notify_err:
                    logger.error('归档失败告警通知发送失败: %s', notify_err)

        return Response({
            'message': '终审决策已录入',
            'task': ReviewTaskSerializer(task, context={'request': request}).data,
        })

    @action(detail=False, methods=['get'])
    def dashboard(self, request):
        """编辑部看板 - 按状态/学科/截止日期/超时筛选"""
        if not request.user.is_editor:
            return Response({'error': '仅编辑部可访问'}, status=403)

        qs = self.get_queryset()

        # 筛选
        status_filter = request.query_params.get('status', '')
        if status_filter:
            qs = qs.filter(status=status_filter)

        subject = request.query_params.get('subject', '')
        if subject:
            qs = qs.filter(subject_area=subject)

        overdue_only = request.query_params.get('overdue', '') == 'true'
        if overdue_only:
            # V1.2 一般#24：超时口径此前用任务期望完成日期（task.deadline），
            # 与分配记录口径（assignments.deadline，process_scheduled 的
            # _mark_overdue 同源）不一致；改按「已接受/审稿中且分配截止日
            # 已过」判定，多分配 join 后去重
            qs = qs.filter(
                # V1.2 建议#7：超时口径同步用本地日期，与 process_scheduled
                # 的 _mark_overdue 保持同一时区基准
                assignments__deadline__lt=timezone.localdate(),
                assignments__assignment_status__in=['ACCEPTED', 'REVIEWING'],
            ).distinct()

        # 排序
        sort = request.query_params.get('sort', '-created_at')
        qs = qs.order_by(sort)

        # 分页
        page = self.paginate_queryset(qs)
        if page is not None:
            serializer = ReviewTaskSerializer(page, many=True)
            return self.get_paginated_response(serializer.data)

        serializer = ReviewTaskSerializer(qs, many=True)
        return Response(serializer.data)

    @action(detail=False, methods=['get'])
    def my_tasks(self, request):
        """审稿人任务列表"""
        if not request.user.is_reviewer:
            return Response({'error': '仅审稿人可访问'}, status=403)

        assignments = ReviewAssignment.objects.filter(
            reviewer=request.user
        ).select_related('task').order_by('-deadline')

        status_filter = request.query_params.get('status', '')
        if status_filter:
            assignments = assignments.filter(assignment_status=status_filter)

        serializer = ReviewAssignmentSerializer(assignments, many=True)
        return Response({
            'count': len(serializer.data),
            'results': serializer.data,
        })

    @action(detail=False, methods=['get'])
    def my_articles(self, request):
        """作者稿件列表"""
        if not request.user.is_author:
            return Response({'error': '仅作者可访问'}, status=403)

        tasks = ReviewTask.objects.filter(
            author_user_id=request.user
        ).order_by('-created_at')

        serializer = ReviewTaskSerializer(tasks, many=True, context={'request': request})
        return Response({
            'count': len(serializer.data),
            'results': serializer.data,
        })

    @action(detail=True, methods=['get'])
    def state_logs(self, request, pk=None):
        """查看任务状态变更历史"""
        task = self.get_object()
        logs = StateLog.objects.filter(task=task).order_by('-created_at')
        serializer = StateLogSerializer(logs, many=True)
        # 双盲保护（PRD AC-T-13）：作者视角下隐藏审稿人操作者身份
        if not request.user.is_editor:
            reviewer_ids = set(
                task.assignments.values_list('reviewer_id', flat=True)
            )
            for item, log in zip(serializer.data, logs):
                if log.operator_user_id and log.operator_user_id in reviewer_ids:
                    item['operator_name'] = '审稿人'
        return Response(serializer.data)


class TemplateViewSet(viewsets.ModelViewSet):
    """审稿模板视图集"""
    queryset = Template.objects.all()
    serializer_class = TemplateSerializer
    permission_classes = [IsAuthenticated]

    def get_queryset(self):
        qs = Template.objects.all()
        status_filter = self.request.query_params.get('status', 'ACTIVE')
        if status_filter:
            qs = qs.filter(status=status_filter)
        return qs

    def create(self, request, *args, **kwargs):
        if not request.user.is_editor:
            return Response({'error': '仅编辑部可创建模板'}, status=403)
        serializer = self.get_serializer(data=request.data)
        serializer.is_valid(raise_exception=True)
        template = serializer.save(created_by=request.user)
        return Response(TemplateSerializer(template).data, status=201)

    # 评审意见 V1.2 致命#2（轮1#16）：模板默认写通道同样只收口了 create，
    # update/partial_update/destroy 一并限定编辑部
    def update(self, request, *args, **kwargs):
        if not request.user.is_editor:
            return Response({'error': '仅编辑部可修改模板'}, status=403)
        return super().update(request, *args, **kwargs)

    def partial_update(self, request, *args, **kwargs):
        if not request.user.is_editor:
            return Response({'error': '仅编辑部可修改模板'}, status=403)
        return super().partial_update(request, *args, **kwargs)

    def destroy(self, request, *args, **kwargs):
        if not request.user.is_editor:
            return Response({'error': '仅编辑部可删除模板'}, status=403)
        return super().destroy(request, *args, **kwargs)

    @action(detail=True, methods=['post'])
    def toggle_status(self, request, pk=None):
        """启用/停用模板"""
        if not request.user.is_editor:
            return Response({'error': '仅编辑部可操作'}, status=403)
        template = self.get_object()
        template.status = 'INACTIVE' if template.status == 'ACTIVE' else 'ACTIVE'
        template.save()
        return Response({'message': f'模板已{"停用" if template.status == "INACTIVE" else "启用"}'})


def init_default_templates():
    """初始化预设四维模板"""
    if Template.objects.filter(template_type='SYSTEM_DEFAULT').exists():
        return

    Template.objects.create(
        template_name='通用四维审稿模板',
        template_type='SYSTEM_DEFAULT',
        subject_area='',  # 通用
        dimensions=[
            {'dimensionId': 'D1', 'dimensionName': '研究意义', 'description': '研究问题的学术价值与现实意义', 'minWords': 50},
            {'dimensionId': 'D2', 'dimensionName': '创新性', 'description': '理论创新、方法创新或数据创新', 'minWords': 50},
            {'dimensionId': 'D3', 'dimensionName': '研究方法', 'description': '研究设计的合理性、方法的适当性', 'minWords': 50},
            {'dimensionId': 'D4', 'dimensionName': '写作水平', 'description': '论文结构、逻辑表达、规范性', 'minWords': 50},
        ],
        status='ACTIVE',
    )
    print('预设四维审稿模板已创建')
