class ProviderError(Exception):
    """Lỗi chung từ LLM provider."""

    def __init__(self, message: str, original=None):
        super().__init__(message)
        self.message = message
        self.original = original


class QuotaExceeded(ProviderError):
    """Provider trả 429 / hết quota."""


class ProviderTimeout(ProviderError):
    """Provider không phản hồi trong thời gian cho phép."""
