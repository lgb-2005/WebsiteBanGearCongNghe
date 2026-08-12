from .models import Category


def nav_categories(request):
    categories = Category.objects.filter(parent__isnull=True).order_by('name')
    return {'nav_categories': categories}
