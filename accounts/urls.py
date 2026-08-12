from django.urls import path
from . import views

app_name = 'accounts'

urlpatterns = [
    path('dang-ky/', views.register, name='register'),
    path('dang-nhap/', views.login_view, name='login'),
    path('dang-xuat/', views.logout_view, name='logout'),
    path('profile/', views.profile, name='profile'),
    path('profile/edit/', views.profile_edit, name='profile_edit'),
    path('profile/update/', views.update_profile, name='update_profile'),
    path('profile/change-password/', views.change_password, name='change_password'),
]
