from analytics.models import Session, Event

ANALYTICS_SESSION_KEY = 'analytics_session_id'


def get_or_create_analytics_session(request):
    session_id = request.session.get(ANALYTICS_SESSION_KEY)

    analytics_session = None

    if session_id:
        analytics_session = Session.objects.filter(pk=session_id).first()

    if analytics_session is None:
        user_agent = request.META.get('HTTP_USER_AGENT', '')
        ua = user_agent.lower()
        device_type = 'mobile' if any(k in ua for k in ['mobile', 'android', 'iphone']) else 'desktop'

        analytics_session = Session.objects.create(
            user=request.user if getattr(request.user, 'is_authenticated', False) else None,
            ip_address=request.META.get('REMOTE_ADDR'),
            user_agent=user_agent,
            device_type=device_type,
        )
        request.session[ANALYTICS_SESSION_KEY] = str(analytics_session.pk)

    return analytics_session


def track_event(request, event_type, product=None, event_value=None, metadata=None):
    try:
        analytics_session = get_or_create_analytics_session(request)
        Event.objects.create(
            session=analytics_session,
            user=request.user if getattr(request.user, 'is_authenticated', False) else None,
            event_type=event_type,
            product=product,
            event_value=event_value,
            metadata=metadata if metadata is not None else {},
        )
    except Exception as e:
        print(f'[analytics] track_event error: {e}')
