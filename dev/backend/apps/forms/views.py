"""
审稿表单模块视图集 - 对应PRD §6.2.4 / §6.2.5 / §6.3.3

视图集清单：
- ReviewFormViewSet：审稿表单
    - get_form：GET 获取审稿表单（模板快照+稿件信息），审稿人通过assignment获取
- ReviewOpinionViewSet：审稿意见
    - submit：POST 提交审稿意见（校验+状态机+通知）
    - save_draft：POST 保存草稿（自动保存）
    - my_opinion：GET 获取当前审稿人对某任务的意见
    - task_opinions：GET 获取某任务的所有审稿意见（双盲保护）
"""
import logging

from django.db import IntegrityError, transaction
from django.utils import timezone
from rest_framework import status, viewsets
from rest_framework.decorators import action
from rest_framework.permissions import IsAuthenticated
from rest_framework.response import Response

from apps.tasks.models import ReviewTask, ReviewAssignment
from apps.tasks.state_machine import StateMachineService, StateMachineError
from apps.notifications.services import NotificationService
from apps.users.models import User

from .models import AIReviewJob, ReviewForm, ReviewOpinion
from .serializers import (
    ReviewFormSerializer,
    ReviewOpinionSerializer,
    ReviewOpinionSubmitSerializer,
    ReviewOpinionDraftSerializer,
)
from .services import FormService

logger = logging.getLogger(__name__)


class ReviewFormViewSet(viewsets.GenericViewSet):
    """审稿表单视图集 - 仅提供查询，表单由任务创建时自动生成"""

    queryset = ReviewForm.objects.all()
    serializer_class = ReviewFormSerializer
    permission_classes = [IsAuthenticated]

    def get_queryset(self):
        """按角色过滤可见表单"""
        user = self.request.user
        qs = ReviewForm.objects.select_related('task', 'template')
        if user.is_editor:
            pass  # 编辑部可见全部
        elif user.is_reviewer:
            # 审稿人仅可见分配给自己的任务表单
            qs = qs.filter(task__assignments__reviewer=user).distinct()
        elif user.is_author:
            # 作者仅可见自己稿件的表单
            qs = qs.filter(task__author_user_id=user)
        else:
            qs = qs.none()
        return qs

    @action(detail=False, methods=['get'])
    def get_form(self, request):
        """
        获取审稿表单（加载模板快照+稿件信息）

        审稿人通过 task_id 获取，系统自动查找其 assignment 关联的表单。
        模板快照在表单创建时冻结，不受后续模板变更影响。

        Query params:
            - task_id: 任务ID（必填）
        """
        task_id = request.query_params.get('task_id')
        if not task_id:
            return Response(
                {'error': '缺少参数 task_id'},
                status=status.HTTP_400_BAD_REQUEST,
            )

        user = request.user

        # 权限校验：审稿人需有分配记录，作者需为稿件作者，编辑部可见全部
        try:
            task = ReviewTask.objects.get(task_id=task_id)
        except ReviewTask.DoesNotExist:
            return Response(
                {'error': '任务不存在'},
                status=status.HTTP_404_NOT_FOUND,
            )

        if user.is_reviewer:
            # 审稿人：检查是否有分配记录
            assignment = ReviewAssignment.objects.filter(
                task=task, reviewer=user
            ).first()
            if not assignment:
                return Response(
                    {'error': '您未被分配到此审稿任务'},
                    status=status.HTTP_403_FORBIDDEN,
                )
            # 审稿人需已接受邀请才能查看表单
            if assignment.assignment_status not in ['ACCEPTED', 'REVIEWING', 'SUBMITTED']:
                return Response(
                    {'error': f'当前分配状态({assignment.assignment_status})不允许查看表单'},
                    status=status.HTTP_403_FORBIDDEN,
                )
        elif user.is_author:
            if task.author_user_id != user:
                return Response(
                    {'error': '无权访问此任务表单'},
                    status=status.HTTP_403_FORBIDDEN,
                )
        elif user.is_editor:
            pass  # 编辑部可见全部
        else:
            return Response(
                {'error': '无权访问'},
                status=status.HTTP_403_FORBIDDEN,
            )

        # 获取表单（表单在任务创建时已自动生成）
        try:
            form = ReviewForm.objects.get(task=task)
        except ReviewForm.DoesNotExist:
            # 兜底：表单不存在时自动创建
            form = FormService.create_form_for_task(task)

        serializer = ReviewFormSerializer(form)
        return Response(serializer.data)

    @action(detail=False, methods=['post'])
    def ai_review(self, request):
        """
        POST AI 辅助审稿 - 提交异步任务自动生成审稿意见草稿（决策 #026，F-3）

        调用 LLM（reviewer agent）自动分析稿件，生成四维评分+评语+推荐意见，
        审稿人可在 AI 结果基础上修改后提交。

        原同步链路（请求线程内直接调 generate_review 阻塞最长 120s）改后台
        线程执行：本校验链（权限门+分配校验）原样保留，尾部改为创建
        AIReviewJob 后提交线程池秒回，前端轮询 ai_review_status 取结果。

        Request body:
            - task_id: 任务ID（必填）

        Returns（201，异步受理口径）:
            - job_id: AIR-YYYYMMDD-NNNN 任务ID
            - status: PENDING/RUNNING（终态经 ai_review_status 查询）
        """
        user = request.user
        if not user.is_reviewer:
            return Response(
                {'error': '仅审稿人可使用 AI 审稿功能'},
                status=status.HTTP_403_FORBIDDEN,
            )

        task_id = request.data.get('task_id')
        if not task_id:
            return Response(
                {'error': '缺少参数 task_id'},
                status=status.HTTP_400_BAD_REQUEST,
            )

        try:
            task = ReviewTask.objects.get(task_id=task_id)
        except ReviewTask.DoesNotExist:
            return Response(
                {'error': '任务不存在'},
                status=status.HTTP_404_NOT_FOUND,
            )

        # 校验审稿人是否有分配记录
        try:
            assignment = ReviewAssignment.objects.get(task=task, reviewer=user)
        except ReviewAssignment.DoesNotExist:
            return Response(
                {'error': '您未被分配到此审稿任务'},
                status=status.HTTP_403_FORBIDDEN,
            )

        if assignment.assignment_status not in ['ACCEPTED', 'REVIEWING']:
            return Response(
                {'error': f'当前分配状态({assignment.assignment_status})不允许审稿'},
                status=status.HTTP_400_BAD_REQUEST,
            )

        # 创建异步任务并提交线程池（秒回；LLM 调用移入后台线程）。
        # 原同步链路的 FileNotFoundError/ValueError 异常不再在请求内处理，
        # 一律由工作线程写入 job.error，前端从状态端点读取
        from .ai_jobs import submit_ai_review_job
        job = AIReviewJob.objects.create(task=task, reviewer=user)
        submit_ai_review_job(job)
        logger.info(
            'AI 审稿任务已提交: job=%s, task=%s, reviewer=%s',
            job.job_id, task.task_id, user.user_id,
        )
        return Response(
            {'job_id': job.job_id, 'status': job.status},
            status=status.HTTP_201_CREATED,
        )

    @action(detail=False, methods=['get'])
    def ai_review_status(self, request):
        """
        GET 查询 AI 审稿任务状态（决策 #026，配套 ai_review 轮询）

        仅任务提交人本人可查（他人 job 一律 403，含编辑部——防越权枚举
        job_id 读他人审稿结果）。

        Query params:
            - job_id: 任务ID（必填，AIR-YYYYMMDD-NNNN）

        Returns:
            - job_id / status / result / error / created_at / finished_at
              （result 仅 SUCCEEDED 时非空，结构与原同步响应一致）
        """
        job_id = request.query_params.get('job_id')
        if not job_id:
            return Response(
                {'error': '缺少参数 job_id'},
                status=status.HTTP_400_BAD_REQUEST,
            )

        try:
            job = AIReviewJob.objects.get(job_id=job_id)
        except AIReviewJob.DoesNotExist:
            return Response(
                {'error': '任务不存在'},
                status=status.HTTP_404_NOT_FOUND,
            )

        if job.reviewer_id != request.user.user_id:
            return Response(
                {'error': '无权查询他人的 AI 审稿任务'},
                status=status.HTTP_403_FORBIDDEN,
            )

        return Response({
            'job_id': job.job_id,
            'status': job.status,
            'result': job.result,
            'error': job.error,
            'created_at': job.created_at,
            'finished_at': job.finished_at,
        })

    @action(detail=False, methods=['post'])
    def validate_references(self, request):
        """
        POST 参考文献验证 - 从稿件 PDF 提取参考文献并交叉验证真实性

        调用 CrossRef / OpenAlex API 批量验证参考文献。
        编辑部和审稿人均可使用。

        Request body:
            - task_id: 任务ID（必填）

        Returns:
            - total: 参考文献总数
            - verified / partial_match / mismatch / not_found: 各状态计数
            - results: [{input, status, title, authors, year, journal, doi, match_confidence, ...}]
        """
        user = request.user
        if not (user.is_reviewer or user.is_editor):
            return Response(
                {'error': '仅审稿人和编辑部可使用参考文献验证功能'},
                status=status.HTTP_403_FORBIDDEN,
            )

        task_id = request.data.get('task_id')
        if not task_id:
            return Response(
                {'error': '缺少参数 task_id'},
                status=status.HTTP_400_BAD_REQUEST,
            )

        try:
            task = ReviewTask.objects.get(task_id=task_id)
        except ReviewTask.DoesNotExist:
            return Response(
                {'error': '任务不存在'},
                status=status.HTTP_404_NOT_FOUND,
            )

        # 审稿人需有分配记录，且分配处于有效审稿状态
        # （评审意见 V1.2 严重#7：与 ai_review 同口径——拒绝/过期/超时标记后
        # 不再放行，防止走参考文献验证旁路读稿件）
        if user.is_reviewer and not user.is_editor:
            assignment = ReviewAssignment.objects.filter(
                task=task, reviewer=user
            ).first()
            if not assignment:
                return Response(
                    {'error': '您未被分配到此审稿任务'},
                    status=status.HTTP_403_FORBIDDEN,
                )
            if assignment.assignment_status not in ['ACCEPTED', 'REVIEWING']:
                return Response(
                    {'error': f'当前分配状态({assignment.assignment_status})不允许使用参考文献验证'},
                    status=status.HTTP_400_BAD_REQUEST,
                )

        try:
            from .ref_validation import ReferenceValidationService
            result = ReferenceValidationService.validate_task_references(task)
            logger.info(
                '参考文献验证完成: task=%s, total=%d, verified=%d',
                task.task_id, result.get('total', 0), result.get('verified', 0),
            )
            return Response(result, status=status.HTTP_200_OK)

        except FileNotFoundError as e:
            return Response(
                {'error': f'稿件文件不存在: {str(e)}'},
                status=status.HTTP_404_NOT_FOUND,
            )
        except Exception as e:
            logger.error('参考文献验证异常: task=%s, error=%s', task.task_id, str(e))
            return Response(
                {'error': f'参考文献验证失败: {str(e)}'},
                status=status.HTTP_500_INTERNAL_SERVER_ERROR,
            )


class ReviewOpinionViewSet(viewsets.GenericViewSet):
    """审稿意见视图集"""

    queryset = ReviewOpinion.objects.all()
    serializer_class = ReviewOpinionSerializer
    permission_classes = [IsAuthenticated]

    def get_queryset(self):
        """按角色过滤可见意见"""
        user = self.request.user
        qs = ReviewOpinion.objects.select_related('task', 'form', 'reviewer', 'assignment')
        if user.is_editor:
            pass  # 编辑部可见全部
        elif user.is_reviewer:
            # 审稿人仅可见自己的意见
            qs = qs.filter(reviewer=user)
        elif user.is_author:
            # 作者见匿名化意见（仅已提交的）
            qs = qs.filter(
                task__author_user_id=user,
                status='SUBMITTED',
            )
        else:
            qs = qs.none()
        return qs

    # ==================== 提交审稿意见 ====================

    @action(detail=False, methods=['post'])
    def submit(self, request):
        """
        提交审稿意见

        校验全部维度评分+综合评语，触发状态机check_and_transition_on_submit，
        发送通知给编辑部。

        Request body:
            - task_id: 任务ID
            - dimension_scores: [{dimensionId, score, comment}, ...]
            - recommendation: ACCEPT/MINOR_REVISION/MAJOR_REVISION/REJECT
            - overall_comment: 综合评语（≥100字）
            - revision_suggestions: [str, ...]（可选）
        """
        user = request.user
        if not user.is_reviewer:
            return Response(
                {'error': '仅审稿人可提交审稿意见'},
                status=status.HTTP_403_FORBIDDEN,
            )

        task_id = request.data.get('task_id')
        if not task_id:
            return Response(
                {'error': '缺少参数 task_id'},
                status=status.HTTP_400_BAD_REQUEST,
            )

        # 获取任务和分配记录
        try:
            task = ReviewTask.objects.get(task_id=task_id)
        except ReviewTask.DoesNotExist:
            return Response(
                {'error': '任务不存在'},
                status=status.HTTP_404_NOT_FOUND,
            )

        try:
            assignment = ReviewAssignment.objects.get(task=task, reviewer=user)
        except ReviewAssignment.DoesNotExist:
            return Response(
                {'error': '未找到分配记录，您未被分配到此任务'},
                status=status.HTTP_404_NOT_FOUND,
            )

        # 状态校验：分配记录必须为ACCEPTED或REVIEWING
        if assignment.assignment_status not in ['ACCEPTED', 'REVIEWING']:
            return Response(
                {'error': f'当前分配状态({assignment.assignment_status})不允许提交意见'},
                status=status.HTTP_400_BAD_REQUEST,
            )

        # 获取表单
        try:
            form = ReviewForm.objects.get(task=task)
        except ReviewForm.DoesNotExist:
            form = FormService.create_form_for_task(task)

        # 检查是否已提交过（同一轮次）
        existing = ReviewOpinion.objects.filter(
            assignment=assignment, round=1, status='SUBMITTED'
        ).first()
        if existing:
            return Response(
                {'error': '您已提交过审稿意见，不可重复提交'},
                status=status.HTTP_400_BAD_REQUEST,
            )

        # 序列化校验
        serializer = ReviewOpinionSubmitSerializer(
            data=request.data, form=form,
        )
        serializer.is_valid(raise_exception=True)
        validated_data = serializer.validated_data

        # 事务提交：保存意见 + 更新分配状态 + 状态机检查 + 通知
        try:
            with transaction.atomic():
                # 获取或创建草稿（如果有草稿则更新为已提交）
                opinion = ReviewOpinion.objects.filter(
                    assignment=assignment, round=1, status='DRAFT'
                ).first()

                if opinion:
                    # 更新草稿为已提交
                    opinion.dimension_scores = validated_data['dimension_scores']
                    opinion.recommendation = validated_data['recommendation']
                    opinion.overall_comment = validated_data['overall_comment']
                    opinion.revision_suggestions = validated_data.get('revision_suggestions', [])
                    opinion.status = 'SUBMITTED'
                    opinion.submitted_at = timezone.now()
                    opinion.save()
                else:
                    # 新建已提交意见
                    opinion = ReviewOpinion.objects.create(
                        task=task,
                        form=form,
                        assignment=assignment,
                        reviewer=user,
                        dimension_scores=validated_data['dimension_scores'],
                        recommendation=validated_data['recommendation'],
                        overall_comment=validated_data['overall_comment'],
                        revision_suggestions=validated_data.get('revision_suggestions', []),
                        status='SUBMITTED',
                        round=1,
                        submitted_at=timezone.now(),
                    )

                # 更新分配记录状态 -> SUBMITTED
                assignment.assignment_status = 'SUBMITTED'
                assignment.submitted_at = timezone.now()
                assignment.save()

                # 状态机：检查是否全部已提交，自动转换任务状态
                StateMachineService.check_and_transition_on_submit(task)

            # 通知编辑部（事务外发送，避免事务回滚影响通知）
            try:
                NotificationService.send_submit(opinion)
            except Exception as e:
                logger.error('发送提交通知失败: %s', str(e))

            logger.info(
                '审稿意见已提交: task=%s, opinion=%s, reviewer=%s',
                task.task_id, opinion.opinion_id, user.user_id,
            )

            return Response(
                ReviewOpinionSerializer(opinion).data,
                status=status.HTTP_201_CREATED,
            )

        except StateMachineError as e:
            return Response(
                {'error': f'状态机转换失败: {str(e)}'},
                status=status.HTTP_400_BAD_REQUEST,
            )
        except Exception as e:
            logger.error('提交审稿意见失败: %s', str(e))
            return Response(
                {'error': f'提交失败: {str(e)}'},
                status=status.HTTP_500_INTERNAL_SERVER_ERROR,
            )

    # ==================== 保存草稿 ====================

    @action(detail=False, methods=['post'])
    def save_draft(self, request):
        """
        保存草稿（自动保存，每60秒间隔）

        草稿不校验完整性和字数下限，仅校验数据类型。
        如已有草稿则更新，否则新建草稿。

        Request body:
            - task_id: 任务ID
            - dimension_scores: [{dimensionId, score, comment}, ...]（可选）
            - recommendation: ACCEPT/MINOR_REVISION/MAJOR_REVISION/REJECT（可选）
            - overall_comment: 综合评语（可选）
            - revision_suggestions: [str, ...]（可选）
        """
        user = request.user
        if not user.is_reviewer:
            return Response(
                {'error': '仅审稿人可保存草稿'},
                status=status.HTTP_403_FORBIDDEN,
            )

        task_id = request.data.get('task_id')
        if not task_id:
            return Response(
                {'error': '缺少参数 task_id'},
                status=status.HTTP_400_BAD_REQUEST,
            )

        # 获取任务和分配记录
        try:
            task = ReviewTask.objects.get(task_id=task_id)
        except ReviewTask.DoesNotExist:
            return Response(
                {'error': '任务不存在'},
                status=status.HTTP_404_NOT_FOUND,
            )

        try:
            assignment = ReviewAssignment.objects.get(task=task, reviewer=user)
        except ReviewAssignment.DoesNotExist:
            return Response(
                {'error': '未找到分配记录'},
                status=status.HTTP_404_NOT_FOUND,
            )

        # V1.2 建议#16：草稿状态门此前仅排除 SUBMITTED——回退后被置
        # EXPIRED/REJECTED 的分配、乃至任务终审 DECIDED 后仍可创建/更新
        # 草稿（新一轮会重新建分配，旧分配的草稿属死数据）；扩展为：
        # 已提交/已拒绝/已过期/已超时的分配不可保存，任务已决策后不可保存
        if assignment.assignment_status in ('SUBMITTED', 'REJECTED', 'EXPIRED', 'OVERDUE'):
            return Response(
                {'error': f'当前分配状态({assignment.assignment_status})不可保存草稿'},
                status=status.HTTP_400_BAD_REQUEST,
            )
        if task.status == 'DECIDED':
            return Response(
                {'error': '任务已完成终审决策，不可保存草稿'},
                status=status.HTTP_400_BAD_REQUEST,
            )

        # 获取表单
        try:
            form = ReviewForm.objects.get(task=task)
        except ReviewForm.DoesNotExist:
            form = FormService.create_form_for_task(task)

        # 序列化校验（草稿校验较宽松）
        serializer = ReviewOpinionDraftSerializer(data=request.data)
        serializer.is_valid(raise_exception=True)
        validated_data = serializer.validated_data

        # 获取或创建草稿
        # V1.2 一般#12：并发自动保存（双开页面/两标签页同时过期触发）时
        # get-or-create 存在竞态——assignment 为 OneToOne，双方同时 create
        # 撞唯一约束直接 500；create 包保存点，IntegrityError 后重取已存在
        # 草稿转更新
        def _apply_draft(op):
            op.dimension_scores = validated_data.get('dimension_scores', [])
            op.recommendation = validated_data.get('recommendation') or ''
            op.overall_comment = validated_data.get('overall_comment') or ''
            op.revision_suggestions = validated_data.get('revision_suggestions', [])
            op.save()

        opinion = ReviewOpinion.objects.filter(
            assignment=assignment, round=1, status='DRAFT'
        ).first()

        if opinion:
            # 更新已有草稿
            _apply_draft(opinion)
        else:
            try:
                with transaction.atomic():
                    opinion = ReviewOpinion.objects.create(
                        task=task,
                        form=form,
                        assignment=assignment,
                        reviewer=user,
                        dimension_scores=validated_data.get('dimension_scores', []),
                        recommendation=validated_data.get('recommendation') or '',
                        overall_comment=validated_data.get('overall_comment') or '',
                        revision_suggestions=validated_data.get('revision_suggestions', []),
                        status='DRAFT',
                        round=1,
                    )
            except IntegrityError:
                # 并发方已建草稿：重取转更新（仍为空则属其他异常，重新抛出）
                opinion = ReviewOpinion.objects.filter(
                    assignment=assignment, round=1, status='DRAFT'
                ).first()
                if opinion is None:
                    raise
                _apply_draft(opinion)

        return Response(
            {
                'message': '草稿已保存',
                'opinion': ReviewOpinionSerializer(opinion).data,
            },
            status=status.HTTP_200_OK,
        )

    # ==================== 获取当前审稿人的意见 ====================

    @action(detail=False, methods=['get'])
    def my_opinion(self, request):
        """
        获取当前审稿人对某任务的意见（草稿或已提交）

        Query params:
            - task_id: 任务ID
        """
        user = request.user
        if not user.is_reviewer:
            return Response(
                {'error': '仅审稿人可访问'},
                status=status.HTTP_403_FORBIDDEN,
            )

        task_id = request.query_params.get('task_id')
        if not task_id:
            return Response(
                {'error': '缺少参数 task_id'},
                status=status.HTTP_400_BAD_REQUEST,
            )

        try:
            task = ReviewTask.objects.get(task_id=task_id)
        except ReviewTask.DoesNotExist:
            return Response(
                {'error': '任务不存在'},
                status=status.HTTP_404_NOT_FOUND,
            )

        # 审稿人只能查看自己的意见
        # V1.2 一般#12：同轮次存在多条记录（草稿+已提交等场景）时 first()
        # 无序取行不稳定，按更新时间倒序取最新一条
        opinion = ReviewOpinion.objects.filter(
            task=task, reviewer=user, round=1,
        ).order_by('-updated_at').first()

        if not opinion:
            return Response(
                {'message': '暂无意见记录'},
                status=status.HTTP_404_NOT_FOUND,
            )

        serializer = ReviewOpinionSerializer(opinion)
        return Response(serializer.data)

    # ==================== 获取任务的所有审稿意见 ====================

    @action(detail=False, methods=['get'])
    def task_opinions(self, request):
        """
        获取某任务的所有审稿意见（双盲保护）

        权限规则：
        - 编辑部：可见全部意见（含审稿人身份）
        - 作者：仅见匿名化意见（双盲保护，移除审稿人身份）
        - 审稿人：不可访问此接口

        Query params:
            - task_id: 任务ID
        """
        user = request.user
        task_id = request.query_params.get('task_id')

        if not task_id:
            return Response(
                {'error': '缺少参数 task_id'},
                status=status.HTTP_400_BAD_REQUEST,
            )

        try:
            task = ReviewTask.objects.get(task_id=task_id)
        except ReviewTask.DoesNotExist:
            return Response(
                {'error': '任务不存在'},
                status=status.HTTP_404_NOT_FOUND,
            )

        # 仅返回已提交的意见
        opinions = ReviewOpinion.objects.filter(
            task=task, status='SUBMITTED',
        ).order_by('submitted_at')

        if user.is_editor:
            # 编辑部：可见全部意见（含审稿人身份）
            serializer = ReviewOpinionSerializer(opinions, many=True)
            return Response({
                'count': len(serializer.data),
                'is_anonymized': False,
                'results': serializer.data,
            })

        elif user.is_author:
            # 作者：仅见匿名化意见（双盲保护）
            # 归属校验（对应评审意见 V1.1 严重#3：IDOR）——作者只能看自己稿件的意见
            if task.author_user_id != user:
                return Response(
                    {'error': '无权访问他人稿件的审稿意见'},
                    status=status.HTTP_403_FORBIDDEN,
                )
            # 仅在任务已决策或已汇总后向作者公开意见
            if task.status not in ['SUMMARIZED', 'DECIDED']:
                return Response(
                    {'error': '审稿意见尚未公开'},
                    status=status.HTTP_403_FORBIDDEN,
                )
            if not task.publish_opinions_to_author:
                return Response(
                    {'error': '编辑部未向作者公开审稿意见'},
                    status=status.HTTP_403_FORBIDDEN,
                )

            # 匿名化处理
            anonymized = [FormService.anonymize_opinion(op) for op in opinions]
            return Response({
                'count': len(anonymized),
                'is_anonymized': True,
                'results': anonymized,
            })

        else:
            return Response(
                {'error': '无权访问此接口'},
                status=status.HTTP_403_FORBIDDEN,
            )
