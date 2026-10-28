"""AI 审稿异步任务执行器（决策 #026，F-3）

后台线程 + AIReviewJob 状态表实现 AI 审稿异步化，不引入 Celery
（#011/#023 两次排除的项目既定路线）。POST /api/forms/ai_review/
创建 job 后调用 submit_ai_review_job 提交到本模块的线程池即返回，
前端轮询 GET /api/forms/ai_review_status/?job_id= 取结果。

设计口径：
- 模块级 ThreadPoolExecutor(max_workers=2)：LLM 调用 timeout=120s，
  最多两个审稿任务并发，第三个排队（先到先执行，PENDING -> RUNNING）。
- 状态机 PENDING -> RUNNING -> SUCCEEDED/FAILED；终态结果/错误落库，
  页面刷新或离开后结果不丢（前端可重新提交生成新任务）。
- **关键技术纪律**：线程内 try/finally 调 close_old_connections() 关闭
  本线程的 DB 连接。Django 每个线程独立持连，工作线程若不关连接，
  连接会跨任务存活直至进程重启，长跑下持续累积最终耗尽 PG 连接数
  （max_connections 默认 100）。close_old_connections 同时兜底连接
  超时/中断的重建，是 Django 官方对长驻线程的标准做法。
"""
import logging
from concurrent.futures import ThreadPoolExecutor

from django.db import close_old_connections
from django.utils import timezone

from .models import AIReviewJob

logger = logging.getLogger(__name__)

# 模块级线程池（进程内单例）：随 gunicorn worker 进程存亡，
# 进程重启时未完成的 job 停留在 PENDING/RUNNING，由
# process_scheduled 管理命令的超时清扫段兜底置 FAILED
executor = ThreadPoolExecutor(max_workers=2, thread_name_prefix='ai-review')


def run_ai_review_job(job_id):
    """线程池工作函数：执行单个 AI 审稿任务并把状态落库。

    由 submit_ai_review_job 提交到 executor，不直接在请求线程调用。
    任何异常都吞掉并落 FAILED（含任务行已被删除的极端情形），绝不让
    异常逃逸出线程污染线程池。
    """
    try:
        close_old_connections()
        try:
            job = AIReviewJob.objects.get(job_id=job_id)
        except AIReviewJob.DoesNotExist:
            logger.warning('AI 审稿任务不存在，跳过执行: job=%s', job_id)
            return

        try:
            job.status = AIReviewJob.Status.RUNNING
            job.save(update_fields=['status', 'updated_at'])

            # 延迟导入避免 ai_review（含 PyMuPDF）在应用启动期被连带加载
            from .ai_review import AIReviewService
            result = AIReviewService.generate_review(job.task)

            job.result = result
            job.status = AIReviewJob.Status.SUCCEEDED
            job.finished_at = timezone.now()
            job.save(update_fields=['result', 'status', 'finished_at', 'updated_at'])
            logger.info(
                'AI 审稿任务完成: job=%s, task=%s, recommendation=%s',
                job.job_id, job.task_id, (result or {}).get('recommendation'),
            )
        except Exception as e:  # noqa: BLE001 - 线程内异常必须落库不外抛
            # FileNotFoundError（稿件不存在）/ ValueError（未配 API Key、
            # 路径越界、LLM 失败）等原同步链路的异常全部转为 job 终态
            job.status = AIReviewJob.Status.FAILED
            job.error = str(e) or e.__class__.__name__
            job.finished_at = timezone.now()
            job.save(update_fields=['error', 'status', 'finished_at', 'updated_at'])
            logger.error('AI 审稿任务失败: job=%s, error=%s', job_id, job.error)
    finally:
        # 关键技术纪律：工作线程用完连接即关，防止长跑累积连接
        close_old_connections()


def submit_ai_review_job(job):
    """把已创建的 AIReviewJob 提交到线程池异步执行（视图层调用）。

    提交失败（如线程池已 shutdown 的极端情形）不抛给请求方，
    直接置 FAILED，用户可从状态端点看到失败原因后重新提交。
    """
    try:
        executor.submit(run_ai_review_job, job.job_id)
    except Exception as e:  # noqa: BLE001 - 提交失败降级为任务失败
        job.status = AIReviewJob.Status.FAILED
        job.error = f'任务提交线程池失败: {e}'
        job.finished_at = timezone.now()
        job.save(update_fields=['error', 'status', 'finished_at', 'updated_at'])
        logger.error('AI 审稿任务提交失败: job=%s, error=%s', job.job_id, e)
