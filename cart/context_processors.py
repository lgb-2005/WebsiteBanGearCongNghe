from .services import get_cart_count


def cart_context(request):
    return {
        'cart_count': get_cart_count(request),
    }
