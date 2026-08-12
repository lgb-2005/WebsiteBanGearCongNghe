from django.urls import path

from .views import add_to_cart_view, cart_detail, remove_cart_view, update_cart_view

app_name = 'cart'

urlpatterns = [
    path('gio-hang/', cart_detail, name='cart_detail'),
    path('gio-hang/them/', add_to_cart_view, name='add_to_cart'),
    path('gio-hang/cap-nhat/', update_cart_view, name='update_cart'),
    path('gio-hang/xoa/', remove_cart_view, name='remove_cart'),
]
