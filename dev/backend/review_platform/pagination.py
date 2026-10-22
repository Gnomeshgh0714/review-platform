"""全局分页器。

评审意见 V1.2 一般#1：DRF 默认 PageNumberPagination 不识别 page_size
查询参数，前端已传的 page_size（通知列表 50、仪表盘 5 等）被静默忽略，
一律退回 PAGE_SIZE=20。统一提供 page_size 覆盖能力并以 100 为上限，
防止一次拉全表。
"""

from rest_framework.pagination import PageNumberPagination


class StandardPagination(PageNumberPagination):
    page_size_query_param = 'page_size'
    max_page_size = 100
