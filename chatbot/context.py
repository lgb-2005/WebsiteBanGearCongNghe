from dataclasses import dataclass, field
from typing import Any, Optional


@dataclass
class ChatContext:
    user: Optional[Any] = None
    session_id: str = ''
    page_context: dict = field(default_factory=dict)
    analytics_session_id: Optional[str] = None
    purchase_intent: dict = field(default_factory=dict)

    @property
    def is_authenticated(self):
        return bool(self.user is not None and getattr(self.user, 'is_authenticated', False))

    @property
    def owner_key(self):
        if self.is_authenticated:
            return f'user:{self.user.pk}'
        return f'session:{self.session_id or "anonymous"}'

    @classmethod
    def from_request(cls, request, page_context=None, include_purchase_intent=True):
        if not request.session.session_key:
            request.session.save()

        user = request.user if getattr(request, 'user', None) and request.user.is_authenticated else None

        ctx = cls(
            user=user,
            session_id=request.session.session_key or '',
            page_context=page_context or {},
        )
        if include_purchase_intent:
            ctx.load_purchase_intent(request)
        return ctx

    def load_purchase_intent(self, request):
        from analytics.ml.purchase_intent import get_customer_purchase_intent_payload
        self.purchase_intent = get_customer_purchase_intent_payload(request=request)
        self.analytics_session_id = self.purchase_intent.get('user_session')
        return self.purchase_intent
