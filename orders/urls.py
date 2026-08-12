from django.urls import path
from . import views

app_name = 'orders'

urlpatterns = [
    path('checkout/', views.checkout, name='checkout'),
    path('place-order/', views.place_order, name='place_order'),
    path('payment/vnpay/return/', views.vnpay_return, name='vnpay_return'),
    path('payment/vnpay/ipn/', views.vnpay_ipn, name='vnpay_ipn'),
    path('payment/vnpay/result/', views.vnpay_payment_result, name='vnpay_payment_result'),
    path('<str:order_code>/', views.order_detail, name='order_detail'),
]