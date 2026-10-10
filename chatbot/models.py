from django.db import models

from accounts.models import User
from core.models import BaseModel


class Conversation(BaseModel):
    user = models.ForeignKey(
        User,
        on_delete=models.SET_NULL,
        null=True,
        blank=True,
        related_name='chat_conversations',
    )
    session_id = models.CharField(
        max_length=255,
        null=True,
        blank=True,
        db_index=True,
    )
    title = models.CharField(max_length=255, blank=True)
    clarify_count = models.PositiveSmallIntegerField(default=0)
    is_active = models.BooleanField(default=True)

    class Meta:
        ordering = ('-updated_at',)
        verbose_name = 'Hội thoại chatbot'
        verbose_name_plural = 'Hội thoại chatbot'
        indexes = [
            models.Index(fields=['user', '-updated_at']),
            models.Index(fields=['session_id', '-updated_at']),
        ]

    def __str__(self):
        owner = self.user.email if self.user_id else (self.session_id or 'guest')
        return f'#{self.pk} - {owner}'

    def ensure_title(self, text):
        if self.title:
            return

        cleaned = ' '.join((text or '').split())
        if not cleaned:
            return

        self.title = cleaned[:60]
        self.save(update_fields=['title', 'updated_at'])


class Message(BaseModel):
    ROLE_USER = 'user'
    ROLE_ASSISTANT = 'assistant'
    ROLE_TOOL = 'tool'

    ROLE_CHOICES = [
        (ROLE_USER, 'Người dùng'),
        (ROLE_ASSISTANT, 'Trợ lý'),
        (ROLE_TOOL, 'Tool'),
    ]

    conversation = models.ForeignKey(
        Conversation,
        on_delete=models.CASCADE,
        related_name='messages',
    )
    role = models.CharField(max_length=20, choices=ROLE_CHOICES)
    content = models.TextField(blank=True)

    tool_name = models.CharField(max_length=100, blank=True)
    tool_payload = models.JSONField(null=True, blank=True)

    products = models.JSONField(null=True, blank=True)
    comparison = models.JSONField(null=True, blank=True)

    token_count = models.IntegerField(null=True, blank=True)

    class Meta:
        ordering = ('created_at', 'id')
        verbose_name = 'Tin nhắn chatbot'
        verbose_name_plural = 'Tin nhắn chatbot'
        indexes = [
            models.Index(fields=['conversation', 'created_at']),
        ]

    def __str__(self):
        preview = ' '.join((self.content or '').split())[:50]
        return f'[{self.role}] {preview}'


class ChatTurnLog(BaseModel):
    STATUS_OK = 'ok'
    STATUS_RATE_LIMITED = 'rate_limited'
    STATUS_API_ERROR = 'api_error'
    STATUS_TOOL_ERROR = 'tool_error'
    STATUS_TIMEOUT = 'timeout'
    STATUS_DISABLED = 'disabled'

    STATUS_CHOICES = [
        (STATUS_OK, 'OK'),
        (STATUS_RATE_LIMITED, 'Vượt rate limit'),
        (STATUS_API_ERROR, 'Lỗi API'),
        (STATUS_TOOL_ERROR, 'Lỗi tool'),
        (STATUS_TIMEOUT, 'Timeout'),
        (STATUS_DISABLED, 'Chatbot bị tắt'),
    ]

    conversation = models.ForeignKey(
        Conversation,
        on_delete=models.CASCADE,
        related_name='turn_logs',
        null=True,
        blank=True,
    )

    user_message = models.TextField(blank=True)
    resolved_aliases = models.JSONField(null=True, blank=True)
    tool_calls = models.JSONField(null=True, blank=True)
    loop_rounds = models.PositiveSmallIntegerField(default=0)

    provider = models.CharField(max_length=50, blank=True)
    model_name = models.CharField(max_length=100, blank=True)

    prompt_tokens = models.IntegerField(null=True, blank=True)
    completion_tokens = models.IntegerField(null=True, blank=True)
    latency_ms = models.IntegerField(default=0)

    final_answer = models.TextField(blank=True)
    status = models.CharField(
        max_length=20,
        choices=STATUS_CHOICES,
        default=STATUS_OK,
        db_index=True,
    )
    error_detail = models.TextField(blank=True)

    class Meta:
        ordering = ('-created_at',)
        verbose_name = 'Log lượt chat'
        verbose_name_plural = 'Log lượt chat'
        indexes = [
            models.Index(fields=['-created_at']),
            models.Index(fields=['status', '-created_at']),
        ]

    def __str__(self):
        return f'{self.created_at:%Y-%m-%d %H:%M:%S} | {self.status} | {self.latency_ms}ms'

    @property
    def tool_names(self):
        if not self.tool_calls:
            return []
        return [call.get('name', '') for call in self.tool_calls]
