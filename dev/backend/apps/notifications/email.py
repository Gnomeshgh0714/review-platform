"""T-02 邮件通道封装（生产部署批 #023：路线 A 同步 SMTP，不动 Celery）

设计口径（用户裁决，见决策 #023）：
- 通知类型 → 邮件主题/正文模板集中定义（EMAIL_TEMPLATES，一处维护）；
  站内信正文作为邮件正文主体（同源不漂移），收尾引导语按类型定制；
- django.core.mail.send_mail 同步发送，发送/渲染失败 logger.warning 后
  返回 False，绝不阻断站内信创建（与 notifications.services._notify_multiple
  吞单条失败的容错风格一致）；
- 收件人 email 为空直接跳过（部分账号仅站内信可达）；
- Django 测试运行器自动切内存后端（mail.outbox），测试断言不实际外发；
  本地默认 console 后端打印到 stdout（见 settings.py EMAIL_* 注释）。
"""
import logging

from django.conf import settings
from django.core.mail import send_mail

logger = logging.getLogger(__name__)

# 通知类型 → 邮件主题/正文模板（集中定义，一处维护）。
# 九种类型与 apps/notifications/models.py 的 Notification.Type 一一对应；
# 占位符经 str.format 渲染，常用键：{title}（站内信标题，作邮件主题）、
# {content}（站内信正文，作邮件正文主体）、{user_name}（收件人姓名）、
# {task_title}（关联稿件标题，无任务时空串）——见 send_notification_email
EMAIL_TEMPLATES = {
    'TASK_CREATED': {
        'subject': '{title}',
        'body': '{content}\n\n请登录审稿协作平台，在「我的稿件」中查看审稿进度。',
    },
    'INVITATION': {
        'subject': '{title}',
        'body': '{content}\n\n请在邀请有效期内登录审稿协作平台接受或拒绝邀请。',
    },
    'ACCEPT': {
        'subject': '{title}',
        'body': '{content}\n\n请登录审稿协作平台关注该稿件的审稿进度。',
    },
    'REJECT': {
        'subject': '{title}',
        'body': '{content}\n\n请登录审稿协作平台尽快为该稿件重新分配审稿人。',
    },
    'SUBMIT': {
        'subject': '{title}',
        'body': '{content}\n\n请登录审稿协作平台查看详细审稿意见。',
    },
    'SUMMARIZE': {
        'subject': '{title}',
        'body': '{content}\n\n请登录审稿协作平台查看汇总报告并做出终审决策。',
    },
    'DECIDE': {
        'subject': '{title}',
        'body': '{content}\n\n请登录审稿协作平台查看终审决策详情。',
    },
    'REMIND': {
        'subject': '{title}',
        'body': '{content}\n\n请尽快登录审稿协作平台完成审稿意见提交。',
    },
    'OVERDUE': {
        'subject': '{title}',
        'body': '{content}\n\n请登录审稿协作平台尽快处理超时任务。',
    },
    # 用户创建第二触点（PRD §6.2.1：编辑部创建账号后系统发送邀请邮件）。
    # 非 Notification.Type，由 apps/users/views.py 的用户创建路径直接调用
    'ACCOUNT_INVITATION': {
        'subject': '【审稿协作平台】您的账号已创建',
        'body': (
            '编辑部已在审稿协作平台为您创建账号。\n\n'
            '姓名：{user_name}\n'
            '登录邮箱：{email}\n'
            '初始密码：{initial_password}\n\n'
            '请使用上述邮箱与初始密码登录平台，首次登录后请尽快修改密码。'
        ),
    },
}

# 未知类型的兜底模板（未来新增通知类型未配模板时邮件仍可发出）
_DEFAULT_TEMPLATE = {
    'subject': '{title}',
    'body': '{content}\n\n请登录审稿协作平台查看详情。',
}


def send_notification_email(user, ntype, context=None):
    """给 user 同步发送 ntype 类型的通知邮件。

    :param user: 收件用户（apps.users.models.User）
    :param ntype: 通知类型（Notification.Type 枚举值，或 'ACCOUNT_INVITATION'）
    :param context: dict 模板占位符上下文（title/content/task_title 等；
        未提供的占位符按空串渲染，不抛错）
    :return: bool 是否实际发出（收件人无邮箱 / 渲染失败 / 发送失败为 False）

    容错口径：任何失败仅 logger.warning，绝不向调用方抛异常——站内信是
    主通道，邮件是增强通道，不能因邮件故障阻断业务通知。
    """
    email = (getattr(user, 'email', '') or '').strip()
    if not email:
        logger.info(
            '邮件跳过(收件人邮箱为空): user=%s, type=%s',
            getattr(user, 'user_id', None), ntype,
        )
        return False

    template = EMAIL_TEMPLATES.get(ntype, _DEFAULT_TEMPLATE)
    ctx = {
        'user_name': getattr(user, 'name', '') or '',
        'title': '', 'content': '', 'task_title': '',
    }
    ctx.update(context or {})
    try:
        subject = template['subject'].format(**ctx)
        body = template['body'].format(**ctx)
        send_mail(
            subject, body,
            settings.DEFAULT_FROM_EMAIL, [email],
            fail_silently=False,
        )
        logger.info(
            '邮件已发送: to=%s, type=%s, subject=%s', email, ntype, subject)
        return True
    except Exception as e:
        logger.warning(
            '邮件发送失败(不阻断站内信): to=%s, type=%s, error=%s',
            email, ntype, e,
        )
        return False
