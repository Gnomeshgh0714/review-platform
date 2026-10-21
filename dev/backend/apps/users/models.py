from django.db import models
from django.contrib.auth.models import AbstractUser
from django.utils import timezone


class User(AbstractUser):
    """用户实体 - 对应PRD §6.2.1 User实体"""

    class Role(models.TextChoices):
        REVIEWER = 'REVIEWER', '审稿人'
        EDITOR = 'EDITOR', '编辑部'
        AUTHOR = 'AUTHOR', '作者'

    user_id = models.CharField(max_length=64, primary_key=True, editable=False)
    name = models.CharField('姓名', max_length=100)
    email = models.EmailField('邮箱', unique=True)
    roles = models.JSONField('角色列表', default=list)
    institution = models.CharField('所属机构', max_length=200, blank=True)
    research_areas = models.JSONField('研究方向标签', default=list)
    created_at = models.DateTimeField('创建时间', auto_now_add=True)
    updated_at = models.DateTimeField('更新时间', auto_now=True)

    username = None
    first_name = None
    last_name = None

    USERNAME_FIELD = 'email'
    REQUIRED_FIELDS = ['name']

    def save(self, *args, **kwargs):
        if not self.user_id:
            # 生成用户ID: U-YYYYMMDD-NNNN
            today = timezone.now().strftime('%Y%m%d')
            count = User.objects.filter(
                user_id__startswith=f'U-{today}'
            ).count()
            self.user_id = f'U-{today}-{count + 1:04d}'
        super().save(*args, **kwargs)

    def __str__(self):
        return f'{self.name} ({self.user_id})'

    @property
    def is_editor(self):
        return 'EDITOR' in (self.roles or [])

    @property
    def is_reviewer(self):
        return 'REVIEWER' in (self.roles or [])

    @property
    def is_author(self):
        return 'AUTHOR' in (self.roles or [])


class UserAIConfig(models.Model):
    """用户AI模型配置 - 允许用户自定义LLM API"""
    
    class Provider(models.TextChoices):
        OPENAI_COMPATIBLE = 'openai_compatible', 'OpenAI兼容API'
        ANTHROPIC = 'anthropic', 'Anthropic Claude'
        GOOGLE = 'google', 'Google Gemini'
        SYSTEM_DEFAULT = 'system_default', '系统默认(GLM-4)'
    
    config_id = models.BigAutoField(primary_key=True)
    user = models.OneToOneField(
        User, on_delete=models.CASCADE, 
        related_name='ai_config', verbose_name='所属用户'
    )
    provider = models.CharField(
        'API类型', max_length=30, 
        choices=Provider.choices, default=Provider.SYSTEM_DEFAULT
    )
    api_key = models.CharField('API密钥', max_length=500, blank=True)
    model_name = models.CharField('模型名称', max_length=100, blank=True)
    base_url = models.CharField('API地址', max_length=500, blank=True)
    is_active = models.BooleanField('启用自定义配置', default=False)
    created_at = models.DateTimeField('创建时间', auto_now_add=True)
    updated_at = models.DateTimeField('更新时间', auto_now=True)
    
    class Meta:
        db_table = 'user_ai_config'
    
    def __str__(self):
        return f'{self.user.name} - {self.provider}'
    
    @property
    def effective_api_key(self):
        """返回实际生效的API Key（用户配置或系统默认）"""
        if self.is_active and self.api_key:
            return self.api_key
        return None
    
    @property
    def effective_base_url(self):
        """返回实际生效的Base URL"""
        if self.is_active and self.base_url:
            return self.base_url
        return None
    
    @property
    def effective_model(self):
        """返回实际生效的模型名称"""
        if self.is_active and self.model_name:
            return self.model_name
        return None
