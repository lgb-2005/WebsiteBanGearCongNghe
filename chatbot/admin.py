from django.contrib import admin

from .models import ChatTurnLog, Conversation, Message


class MessageInline(admin.TabularInline):
    model = Message
    extra = 0
    fields = ('created_at', 'role', 'content', 'tool_name')
    readonly_fields = ('created_at', 'role', 'content', 'tool_name')
    can_delete = False
    show_change_link = True

    def has_add_permission(self, request, obj):
        return False


@admin.register(Conversation)
class ConversationAdmin(admin.ModelAdmin):
    list_display = ('id', 'title', 'user', 'session_id', 'is_active', 'created_at', 'updated_at')
    list_filter = ('is_active', 'created_at')
    search_fields = ('title', 'session_id', 'user__email')
    readonly_fields = ('created_at', 'updated_at')
    inlines = (MessageInline,)


@admin.register(Message)
class MessageAdmin(admin.ModelAdmin):
    list_display = ('id', 'conversation', 'role', 'tool_name', 'token_count', 'created_at')
    list_filter = ('role', 'created_at')
    search_fields = ('content', 'tool_name')
    readonly_fields = (
        'conversation', 'role', 'content', 'tool_name', 'tool_payload',
        'products', 'comparison', 'token_count', 'created_at', 'updated_at',
    )

    def has_add_permission(self, request):
        return False


@admin.register(ChatTurnLog)
class ChatTurnLogAdmin(admin.ModelAdmin):
    list_display = (
        'created_at', 'provider', 'model_name', 'loop_rounds',
        'latency_ms', 'prompt_tokens', 'completion_tokens', 'status',
    )
    list_filter = ('status', 'provider', 'model_name', 'created_at')
    search_fields = ('user_message', 'final_answer', 'error_detail')
    date_hierarchy = 'created_at'
    readonly_fields = tuple(
        field.name for field in ChatTurnLog._meta.fields
    )

    def has_add_permission(self, request):
        return False

    def has_change_permission(self, request, obj=None):
        return False
