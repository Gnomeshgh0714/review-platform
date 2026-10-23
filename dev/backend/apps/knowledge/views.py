"""
审稿知识库视图集 - 对应PRD §3.1.12 审稿知识库功能

接口（挂载于 api/knowledge/）：
- GET    knowledge/search/                    检索知识库（审稿人+编辑部）
- GET    knowledge/<str:knowledge_id>/detail/ 查看详情（记录访问日志）
- GET    knowledge/pending_reviews/           待审核列表（仅编辑部）
- POST   knowledge/<str:knowledge_id>/review/ 审核匿名化（仅编辑部）
- GET    knowledge/export/                    导出数据（仅编辑部）

注：模板管理已在tasks app中实现（TemplateViewSet），此处不重复。
"""
import logging

from django.conf import settings
from rest_framework import status, viewsets
from rest_framework.decorators import action
from rest_framework.permissions import IsAuthenticated
from rest_framework.response import Response

from .models import KnowledgeItem
from .serializers import (
    KnowledgeItemSerializer,
    KnowledgeItemBriefSerializer,
    AnonymizationReviewSerializer,
)
from .services import KnowledgeService, AnonymizationService

logger = logging.getLogger(__name__)


class KnowledgeViewSet(viewsets.ViewSet):
    """审稿知识库视图集"""

    permission_classes = [IsAuthenticated]

    # ==================== 检索 ====================

    @action(detail=False, methods=['get'])
    def search(self, request):
        """
        GET 检索知识库（审稿人+编辑部可用，作者无权限）

        查询参数：
        - keyword: 关键词全文搜索
        - subject_area: 学科领域
        - manuscript_type: 稿件类型
        - final_decision: 终审决策
        - recommendation: 推荐意见（ACCEPT/MINOR_REVISION/MAJOR_REVISION/REJECT）
        - score_range: 评分区间（high/mid_high/mid/low）
        - date_start: 审稿日期起始（YYYY-MM）
        - date_end: 审稿日期截止（YYYY-MM）
        - page: 页码（默认1，每页20条）

        仅返回anonymization_status=APPROVED的条目。
        结果为空时返回冷启动模板评分指引。
        """
        user = request.user

        # 权限校验：作者无权限
        if user.is_author and not (user.is_reviewer or user.is_editor):
            return Response({'error': '作者无权访问审稿知识库'}, status=403)

        # 仅审稿人和编辑部可检索
        if not (user.is_reviewer or user.is_editor):
            return Response({'error': '无权访问审稿知识库'}, status=403)

        query_params = dict(request.query_params)
        result = KnowledgeService.search(query_params)

        # 记录检索访问日志
        from .models import AccessLog
        AccessLog.objects.create(
            user=user,
            action='SEARCH_KB',
            target_id='',
            ip_address=self._get_client_ip(request),
        )

        return Response(result)

    # ==================== 详情 ====================

    # #018 修复1：DRF 3.18.3 的 ViewSetMixin.as_view() 会无条件执行
    # cls.detail = None（detail 为保留 initkwarg），urls.py 任一次 as_view()
    # 调用都会把名为 detail 的方法覆盖为 None，导致 GET
    # /api/knowledge/<id>/detail/ 必 500（TypeError: NoneType not callable）。
    # 方法改名 item_detail 规避保留字，url_path 保持原样 → 对外 URL 不变。
    @action(detail=False, methods=['get'], url_path=r'(?P<knowledge_id>[^/]+)/detail')
    def item_detail(self, request, knowledge_id=None):
        """
        GET 查看知识库条目详情（记录访问日志）

        审稿人+编辑部可查看匿名化条目详情。
        作者无权限。
        """
        user = request.user

        # 权限校验
        if user.is_author and not (user.is_reviewer or user.is_editor):
            return Response({'error': '作者无权访问审稿知识库'}, status=403)
        if not (user.is_reviewer or user.is_editor):
            return Response({'error': '无权访问审稿知识库'}, status=403)

        try:
            data = KnowledgeService.get_detail(
                knowledge_id, user,
                ip_address=self._get_client_ip(request),
            )
        except ValueError as e:
            return Response({'error': str(e)}, status=404)

        return Response(data)

    # ==================== 待审核列表 ====================

    @action(detail=False, methods=['get'])
    def pending_reviews(self, request):
        """
        GET 待审核列表（仅编辑部）

        返回anonymization_status=PENDING_REVIEW或REJECTED的条目，
        供编辑部审核。
        """
        user = request.user
        if not user.is_editor:
            return Response({'error': '仅编辑部可查看待审核列表'}, status=403)

        qs = KnowledgeItem.objects.filter(
            anonymization_status__in=[
                KnowledgeItem.AnonymizationStatus.PENDING_REVIEW,
                KnowledgeItem.AnonymizationStatus.REJECTED,
            ]
        ).order_by('-created_at')

        # 分页
        try:
            page = int(request.query_params.get('page', 1))
        except (TypeError, ValueError):
            page = 1
        if page < 1:
            page = 1
        per_page = 20

        total_count = qs.count()
        total_pages = (total_count + per_page - 1) // per_page
        start = (page - 1) * per_page
        items = qs[start:start + per_page]

        serializer = KnowledgeItemSerializer(items, many=True)
        return Response({
            'count': total_count,
            'page': page,
            'total_pages': total_pages,
            'results': serializer.data,
        })

    # ==================== 审核匿名化 ====================

    @action(detail=False, methods=['post'], url_path=r'(?P<knowledge_id>[^/]+)/review')
    def review_anonymization(self, request, knowledge_id=None):
        """
        POST 审核匿名化（仅编辑部）

        请求体：
        {
            "decision": "APPROVED|REJECTED|PERMANENTLY_EXCLUDED",
            "notes": "审核备注（可选）"
        }

        - APPROVED: 不可逆归档
        - REJECTED: 可修改后重新提交
        - PERMANENTLY_EXCLUDED: 永久不归档
        """
        user = request.user
        if not user.is_editor:
            return Response({'error': '仅编辑部可审核匿名化'}, status=403)

        serializer = AnonymizationReviewSerializer(data=request.data)
        serializer.is_valid(raise_exception=True)

        decision = serializer.validated_data['decision']
        notes = serializer.validated_data.get('notes', '')

        try:
            item = KnowledgeService.review_anonymization(
                knowledge_id, user, decision, notes
            )
        except KnowledgeItem.DoesNotExist:
            # 定版裁决 O-3（2026-10-23）：不存在的条目统一 404，对齐 detail 端点
            return Response(
                {'error': f'知识库条目 {knowledge_id} 不存在'}, status=404)
        except ValueError as e:
            # 状态不允许审核等业务校验错误，保持 400
            return Response({'error': str(e)}, status=400)

        return Response(KnowledgeItemSerializer(item).data)

    # ==================== 导出 ====================

    @action(detail=False, methods=['get'])
    def export(self, request):
        """
        GET 导出数据（仅编辑部）

        批量导出匿名化数据（上限1000条），仅含APPROVED状态条目。
        导出数据不含source_task_id（防止溯源）。
        """
        user = request.user
        if not user.is_editor:
            return Response({'error': '仅编辑部可导出数据'}, status=403)

        format_param = request.query_params.get('format', 'json')
        data = KnowledgeService.export_data(user, format=format_param)

        return Response({
            'count': len(data),
            'format': format_param,
            'data': data,
        })

    # ==================== 辅助方法 ====================

    @staticmethod
    def _get_client_ip(request):
        """获取客户端IP

        V1.2 建议#12：X-Forwarded-For 首段可被客户端任意伪造，
        仅在 settings.TRUST_X_FORWARDED_FOR=True（确认部署在可信
        反向代理之后）时才取 XFF，否则以 REMOTE_ADDR 为准
        """
        x_forwarded_for = request.META.get('HTTP_X_FORWARDED_FOR')
        if x_forwarded_for and settings.TRUST_X_FORWARDED_FOR:
            ip = x_forwarded_for.split(',')[0].strip()
        else:
            ip = request.META.get('REMOTE_ADDR')
        return ip
