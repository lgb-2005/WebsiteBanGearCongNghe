from django.conf import settings


def chatbot_settings(request):
    return {
        'CHATBOT_ENABLED': getattr(settings, 'CHATBOT_ENABLED', True),
    }
