from . import views
from django.urls import path

from .views import BrandCreateView, BrandDeleteView, BrandListView, BrandUpdateView, category_products, product_create_api, product_detail, product_reviews_json, search_products

app_name = 'products'

urlpatterns = [
    path('search/', search_products, name='search_products'),
    path('danh-muc/<slug:category_slug>/', category_products, name='category_products'),
    path('products/<slug:slug>/', product_detail, name='product_detail'),
    path('brands/', BrandListView.as_view(), name='brand_list'),
    path('brands/create/', BrandCreateView.as_view(), name='brand_create'),
    path('brands/<int:pk>/edit/', BrandUpdateView.as_view(), name='brand_update'),
    path('brands/<int:pk>/delete/', BrandDeleteView.as_view(), name='brand_delete'),
    path('api/products/create/', product_create_api, name='product_create_api'),
    path('favorite/<slug:slug>/', views.toggle_favorite, name='toggle_favorite'),
    path('favorites/', views.favorite_list, name='favorite_list'),
    path('review/<slug:slug>/', views.add_review, name='add_review'),
    path('products/<slug:slug>/reviews/', product_reviews_json, name='product_reviews_json'),
]
