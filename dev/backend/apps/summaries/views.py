"""
汇总报告视图集 - 对应PRD §3.1.6 审稿意见汇总功能

接口：
- generate：POST 触发汇总报告生成（仅编辑部，任务需为SUBMITTED状态）
- detail：GET 查看汇总报告详情（通过task_id查找）
- list：GET 汇总报告列表（编辑部）
- match_rule_preview：POST 预览规则匹配结果（不生成报告，仅返回匹配的规则，用于调试）
"""
from collections import Counter
from rest_framework import status, viewsets
from rest_framework.decorators import action
from rest_framework.response import Response
from rest_framework.pagination import PageNumberPagination

from apps.tasks.models import ReviewTask
from apps.tasks.state_machine import StateMachineError
from apps.forms.models import ReviewOpinion

from .models import SummaryReport
from .serializers import SummaryReportSerializer, SummaryReportBriefSerializer
from .services import SummaryService


class SummaryReportViewSet(viewsets.ViewSet):
    """汇总报告视图集 - 仅编辑部可操作"""

    # ==================== 列表 ====================

    def list(self, request):
        """GET 汇总报告列表（仅编辑部）"""
        if not request.user.is_editor:
            return Response({'error': '仅编辑部可访问'}, status=403)

        reports = SummaryReport.objects.select_related('task').order_by('-generated_at')

        # 支持按任务状态筛选
        task_status = request.query_params.get('task_status', '')
        if task_status:
            reports = reports.filter(task__status=task_status)

        # 支持按任务ID搜索
        task_id = request.query_params.get('task_id', '')
        if task_id:
            reports = reports.filter(task__task_id=task_id)

        # 分页
        paginator = PageNumberPagination()
        page = paginator.paginate_queryset(reports, request, view=self)
        if page is not None:
            serializer = SummaryReportBriefSerializer(page, many=True)
            return paginator.get_paginated_response(serializer.data)

        serializer = SummaryReportBriefSerializer(reports, many=True)
        return Response({
            'count': len(serializer.data),
            'results': serializer.data,
        })

    # ==================== 详情（通过 report_id，router标准路由） ====================

    def retrieve(self, request, pk=None):
        """GET 查看汇总报告详情（pk = report_id）"""
        if not request.user.is_editor:
            return Response({'error': '仅编辑部可访问'}, status=403)

        try:
            report = SummaryReport.objects.select_related('task').get(report_id=pk)
        except SummaryReport.DoesNotExist:
            return Response({'error': '汇总报告不存在'}, status=404)

        serializer = SummaryReportSerializer(report)
        return Response(serializer.data)

    # ==================== 详情（通过 task_id，自定义路由） ====================

    def detail(self, request, task_id=None):
        """GET 查看汇总报告详情（通过 task_id 查找）"""
        if not request.user.is_editor:
            return Response({'error': '仅编辑部可访问'}, status=403)

        try:
            report = SummaryReport.objects.select_related('task').get(task__task_id=task_id)
        except SummaryReport.DoesNotExist:
            return Response({'error': f'任务 {task_id} 的汇总报告不存在'}, status=404)

        serializer = SummaryReportSerializer(report)
        return Response(serializer.data)

    # ==================== 生成汇总报告 ====================

    def generate(self, request):
        """POST 触发汇总报告生成（仅编辑部，任务需为SUBMITTED状态）"""
        if not request.user.is_editor:
            return Response({'error': '仅编辑部可生成汇总报告'}, status=403)

        task_id = request.data.get('task_id')
        if not task_id:
            return Response({'error': '请提供task_id'}, status=400)

        try:
            task = ReviewTask.objects.get(task_id=task_id)
        except ReviewTask.DoesNotExist:
            return Response({'error': '任务不存在'}, status=404)

        if task.status != 'SUBMITTED':
            return Response(
                {'error': f'仅已提交(SUBMITTED)状态可生成汇总报告，当前状态: {task.status}'},
                status=400,
            )

        try:
            report = SummaryService.generate_report(task, operator_user=request.user)
        except StateMachineError as e:
            return Response({'error': str(e)}, status=400)
        except ValueError as e:
            return Response({'error': str(e)}, status=400)

        serializer = SummaryReportSerializer(report)
        return Response(serializer.data, status=status.HTTP_201_CREATED)

    # ==================== 规则匹配预览（调试用） ====================

    def match_rule_preview(self, request):
        """POST 预览规则匹配结果（不生成报告，仅返回匹配的规则，用于调试）"""
        if not request.user.is_editor:
            return Response({'error': '仅编辑部可访问'}, status=403)

        # 支持两种输入模式：
        # 1. 提供 task_id：从该任务已提交的审稿意见中计算推荐分布
        # 2. 直接提供 recommendation_distribution + reviewer_count
        task_id = request.data.get('task_id')

        if task_id:
            try:
                task = ReviewTask.objects.get(task_id=task_id)
            except ReviewTask.DoesNotExist:
                return Response({'error': '任务不存在'}, status=404)

            opinions = ReviewOpinion.objects.filter(
                task=task, status='SUBMITTED', round=1,
            )
            reviewer_count = opinions.count()
            if reviewer_count == 0:
                return Response({'error': '该任务无已提交的审稿意见'}, status=400)

            # 计算推荐分布
            rec_counter = Counter(op.recommendation for op in opinions)
            recommendation_distribution = {
                'ACCEPT': rec_counter.get('ACCEPT', 0),
                'MINOR_REVISION': rec_counter.get('MINOR_REVISION', 0),
                'MAJOR_REVISION': rec_counter.get('MAJOR_REVISION', 0),
                'REJECT': rec_counter.get('REJECT', 0),
                'total': reviewer_count,
            }
        else:
            recommendation_distribution = request.data.get('recommendation_distribution', {})
            reviewer_count = request.data.get('reviewer_count',
                                              recommendation_distribution.get('total', 0))

            # 规范化推荐分布
            recommendation_distribution = {
                'ACCEPT': int(recommendation_distribution.get('ACCEPT', 0)),
                'MINOR_REVISION': int(recommendation_distribution.get('MINOR_REVISION', 0)),
                'MAJOR_REVISION': int(recommendation_distribution.get('MAJOR_REVISION', 0)),
                'REJECT': int(recommendation_distribution.get('REJECT', 0)),
                'total': int(reviewer_count),
            }

        if reviewer_count == 0:
            return Response({'error': '审稿人数量为0，无法匹配规则'}, status=400)

        rule_result = SummaryService.match_rule(recommendation_distribution, reviewer_count)

        return Response({
            'recommendation_distribution': recommendation_distribution,
            'reviewer_count': reviewer_count,
            'matchedRuleId': rule_result['matchedRuleId'],
            'conclusion': rule_result['conclusion'],
            'advisoryOnly': rule_result.get('advisoryOnly', False),
        })
