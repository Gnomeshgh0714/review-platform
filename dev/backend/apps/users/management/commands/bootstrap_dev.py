"""
开发环境引导命令 - 补齐 T-00 收尾项「首次启动无法登录」的缺口

用途（幂等，可重复执行）：
1. 创建演示用户（编辑部1名 + 审稿人3名 + 作者1名）
2. 初始化预设四维审稿模板（apps/tasks/views.py init_default_templates）
3. 初始化知识库种子数据（apps/knowledge/seed_data.py init_seed_data）

用法：
    python manage.py bootstrap_dev

演示账号密码取环境变量 BOOTSTRAP_PASSWORD（默认 Demo@2026），
详见 backend/.env.example。
"""
import os

from django.core.management.base import BaseCommand

from apps.users.models import User

# 演示账号清单：(邮箱, 姓名, 角色, 研究方向)
DEMO_ACCOUNTS = [
    ('editor@review.local', '编辑部·演示', ['EDITOR'], []),
    ('reviewer1@review.local', '审稿人一·演示', ['REVIEWER'],
     ['气候经济学', '劳动经济学', '应用计量']),
    ('reviewer2@review.local', '审稿人二·演示', ['REVIEWER'],
     ['环境经济学', '政策评估']),
    ('reviewer3@review.local', '审稿人三·演示', ['REVIEWER'],
     ['宏观经济学', '发展经济学']),
    ('author@review.local', '作者·演示', ['AUTHOR'], []),
]


class Command(BaseCommand):
    help = '创建演示用户并初始化模板与知识库种子数据（幂等）'

    def handle(self, *args, **options):
        password = os.environ.get('BOOTSTRAP_PASSWORD', 'Demo@2026')

        self.stdout.write('== 1/3 创建演示用户 ==')
        created = []
        for email, name, roles, research_areas in DEMO_ACCOUNTS:
            user, is_created = User.objects.get_or_create(
                email=email,
                defaults={
                    'name': name,
                    'roles': roles,
                    'research_areas': research_areas,
                    'institution': '审稿协作平台（演示）',
                },
            )
            if is_created:
                user.set_password(password)
                user.is_active = True
                user.save()
                created.append(email)
                self.stdout.write(self.style.SUCCESS(f'  已创建 {email}（{"、".join(roles)}）'))
            else:
                self.stdout.write(f'  已存在 {email}，跳过')

        # 2. 初始化预设模板
        self.stdout.write('== 2/3 初始化预设四维审稿模板 ==')
        from apps.tasks.views import init_default_templates
        init_default_templates()

        # 3. 初始化知识库种子数据
        self.stdout.write('== 3/3 初始化知识库种子数据 ==')
        from apps.knowledge.seed_data import init_seed_data
        init_seed_data()

        self.stdout.write('')
        if created:
            self.stdout.write(self.style.SUCCESS(
                f'引导完成：新建 {len(created)} 个演示账号，密码均为 {password}（请尽快修改）。'
            ))
            self.stdout.write('登录入口：POST /api/users/login/ {"email": "...", "password": "..."}')
        else:
            self.stdout.write('引导完成：演示账号均已存在，未做变更。')
