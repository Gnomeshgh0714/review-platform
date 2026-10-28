from django.db import IntegrityError, models, transaction
from django.utils import timezone as tz

from apps.tasks.models import ReviewTask, ReviewAssignment, Template
from apps.users.models import User


class AIReviewJob(models.Model):
    """AI 审稿异步任务（决策 #026，F-3）

    POST /api/forms/ai_review/ 不再同步等待 LLM（最长 120s 阻塞请求线程），
    改为创建本表记录 + 后台线程执行（apps/forms/ai_jobs.py，不引入 Celery
    ——#011/#023 两次排除的项目既定路线），前端轮询
    GET /api/forms/ai_review_status/?job_id= 取状态与结果。
    """

    class Status(models.TextChoices):
        PENDING = 'PENDING', '排队中'
        RUNNING = 'RUNNING', '进行中'
        SUCCEEDED = 'SUCCEEDED', '已完成'
        FAILED = 'FAILED', '已失败'

    job_id = models.CharField(max_length=64, primary_key=True, editable=False)
    task = models.ForeignKey(ReviewTask, on_delete=models.CASCADE,
                             related_name='ai_review_jobs', verbose_name='关联任务')
    reviewer = models.ForeignKey(User, on_delete=models.CASCADE,
                                 related_name='ai_review_jobs', verbose_name='提交审稿人')
    status = models.CharField('状态', max_length=20,
                              choices=Status.choices, default=Status.PENDING)
    # 成功后写入 generate_review 的返回结构（dimension_scores/recommendation/
    # overall_comment/suggestions），失败为 null
    result = models.JSONField('审稿结果', null=True, blank=True)
    error = models.TextField('失败原因', blank=True, default='')
    created_at = models.DateTimeField('创建时间', auto_now_add=True)
    updated_at = models.DateTimeField('更新时间', auto_now=True)
    finished_at = models.DateTimeField('完成时间', null=True, blank=True)

    class Meta:
        indexes = [
            models.Index(fields=['status']),
            models.Index(fields=['reviewer']),
        ]

    def save(self, *args, **kwargs):
        """保存 AI 审稿任务。

        job_id（AIR-YYYYMMDD-NNNN）与 ReviewOpinion/ReviewForm 同为「当日计数」
        生成，并发下撞主键的处理同 ReviewOpinion.save：保存点包裹插入、
        冲突回滚到保存点后重新计数重试，重试耗尽按最新计数重算一次直写。
        """
        if not self.job_id:
            today = tz.now().strftime('%Y%m%d')
            for _ in range(6):
                count = AIReviewJob.objects.filter(
                    job_id__startswith=f'AIR-{today}'
                ).count()
                self.job_id = f'AIR-{today}-{count + 1:04d}'
                try:
                    with transaction.atomic():
                        super().save(*args, **kwargs)
                    return
                except IntegrityError:
                    continue  # 他方已提交同号主键：重新计数再试
            count = AIReviewJob.objects.filter(
                job_id__startswith=f'AIR-{today}'
            ).count()
            self.job_id = f'AIR-{today}-{count + 1:04d}'
        super().save(*args, **kwargs)


class ReviewForm(models.Model):
    """审稿表单 - 对应PRD §6.2.4 ReviewForm实体"""

    form_id = models.CharField(max_length=64, primary_key=True, editable=False)
    task = models.OneToOneField(ReviewTask, on_delete=models.CASCADE, related_name='form', verbose_name='关联任务')
    template = models.ForeignKey(Template, on_delete=models.PROTECT, verbose_name='关联模板')
    template_snapshot = models.JSONField('模板快照', default=dict)
    dimensions = models.JSONField('维度配置', default=list)
    created_at = models.DateTimeField('创建时间', auto_now_add=True)

    def save(self, *args, **kwargs):
        if not self.form_id:
            from django.utils import timezone as tz
            # V1.2 一般#7：当日计数在并发下撞主键会 IntegrityError，改为
            # 保存点+重试（同本文件 ReviewOpinion 模式），重试耗尽后兜底直写
            today = tz.now().strftime('%Y%m%d')
            for _ in range(6):
                count = ReviewForm.objects.filter(form_id__startswith=f'RF-{today}').count()
                self.form_id = f'RF-{today}-{count + 1:04d}'
                try:
                    with transaction.atomic():
                        super().save(*args, **kwargs)
                    return
                except IntegrityError:
                    continue
            # V1.3 G1：重试耗尽后按最新计数重算一次再直写（原实现带着
            # 已撞号的 ID 直插必再失败）；仍冲突则抛出由调用方处理
            count = ReviewForm.objects.filter(form_id__startswith=f'RF-{today}').count()
            self.form_id = f'RF-{today}-{count + 1:04d}'
            super().save(*args, **kwargs)
        else:
            super().save(*args, **kwargs)


class ReviewOpinion(models.Model):
    """审稿意见 - 对应PRD §6.2.5 ReviewOpinion实体"""

    class Recommendation(models.TextChoices):
        ACCEPT = 'ACCEPT', '接收'
        MINOR_REVISION = 'MINOR_REVISION', '小修'
        MAJOR_REVISION = 'MAJOR_REVISION', '大修'
        REJECT = 'REJECT', '拒稿'

    class Status(models.TextChoices):
        DRAFT = 'DRAFT', '草稿'
        SUBMITTED = 'SUBMITTED', '已提交'
        # 评审意见 V1.2 严重#10：超时回退待分配时，旧轮已提交意见转此状态，
        # 保留为历史记录但不再进入任何聚合/发布口径（消费方均按 SUBMITTED 过滤）
        SUPERSEDED = 'SUPERSEDED', '已废弃（回退历史）'

    opinion_id = models.CharField(max_length=64, primary_key=True, editable=False)
    task = models.ForeignKey(ReviewTask, on_delete=models.CASCADE, related_name='opinions', verbose_name='关联任务')
    form = models.ForeignKey(ReviewForm, on_delete=models.CASCADE, verbose_name='关联表单')
    assignment = models.OneToOneField(ReviewAssignment, on_delete=models.CASCADE, verbose_name='关联分配记录')
    reviewer = models.ForeignKey(User, on_delete=models.CASCADE, verbose_name='审稿人')
    dimension_scores = models.JSONField('维度评分', default=list)  # [{dimensionId, score, comment}]
    recommendation = models.CharField('总体推荐', max_length=30, choices=Recommendation.choices)
    overall_comment = models.TextField('综合评语')
    revision_suggestions = models.JSONField('修改建议', default=list, blank=True)
    status = models.CharField('状态', max_length=20, choices=Status.choices, default=Status.DRAFT)
    round = models.IntegerField('审稿轮次', default=1)  # P1预留，P0=1
    submitted_at = models.DateTimeField('提交时间', null=True, blank=True)
    created_at = models.DateTimeField('创建时间', auto_now_add=True)
    updated_at = models.DateTimeField('更新时间', auto_now=True)

    class Meta:
        indexes = [
            models.Index(fields=['task']),
            models.Index(fields=['status']),
        ]

    def save(self, *args, **kwargs):
        """保存审稿意见。

        ID 生成（RO-YYYYMMDD-NNNN）采用「当日计数」：并发提交时各事务互相
        看不到未提交的行，可能生成相同主键（AC-T-14 并发提交实测命中）。
        处理：用保存点包裹插入，主键冲突时回滚到保存点、重新计数后重试，
        冲突被限制在保存点内，不污染外层提交事务。
        """
        if not self.opinion_id:
            today = tz.now().strftime('%Y%m%d')
            for _ in range(6):
                count = ReviewOpinion.objects.filter(
                    opinion_id__startswith=f'RO-{today}'
                ).count()
                self.opinion_id = f'RO-{today}-{count + 1:04d}'
                try:
                    with transaction.atomic():
                        super().save(*args, **kwargs)
                    return
                except IntegrityError:
                    continue  # 他方已提交同号主键：重新计数再试
            # V1.3 G1：重试耗尽后按最新计数重算一次再直写（原「直接抛出」
            # 前未重算，带撞号 ID 直插必再失败）；仍冲突则抛出由调用方处理
            count = ReviewOpinion.objects.filter(
                opinion_id__startswith=f'RO-{today}'
            ).count()
            self.opinion_id = f'RO-{today}-{count + 1:04d}'
        super().save(*args, **kwargs)
