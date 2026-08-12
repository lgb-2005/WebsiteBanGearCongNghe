from django.contrib import admin
from django.contrib import messages

from .forms import AttributeGroupForm, AttributeValueForm, ProductAdminForm
from .models import (
    AttributeGroup,
    AttributeValue,
    Brand,
    Category,
    Product,
    ProductImage,
    ProductReview,
)

class ProductImageInline(admin.TabularInline):
    model = ProductImage
    extra = 1

class ProductAttributeInline(admin.TabularInline):
    model = Product.attributes.rel.related_model
    extra = 1
    autocomplete_fields = ('attribute_value',)

    def get_formset(self, request, obj=None, **kwargs):
        request._product_admin_obj = obj
        return super().get_formset(request, obj, **kwargs)

    def formfield_for_foreignkey(self, db_field, request, **kwargs):
        if db_field.name == 'attribute_value':
            queryset = AttributeValue.objects.select_related('group').filter(is_active=True, group__is_active=True).order_by(
                'group__display_order',
                'group__name',
                'display_order',
                'value',
            )
            product = getattr(request, '_product_admin_obj', None)
            if product and product.category_id:
                filter_groups = AttributeGroup.get_filter_groups_for_category(product.category)
                queryset = queryset.filter(group__in=filter_groups)
            kwargs['queryset'] = queryset
        return super().formfield_for_foreignkey(db_field, request, **kwargs)


class AttributeValueInline(admin.TabularInline):
    model = AttributeValue
    form = AttributeValueForm
    extra = 0
    fields = ('value', 'slug', 'display_order', 'is_active', 'hex_color')
    ordering = ('display_order', 'value')


@admin.action(description='Vô hiệu hóa nhóm thuộc tính đã chọn')
def deactivate_attribute_groups(modeladmin, request, queryset):
    updated_count = queryset.update(is_active=False)
    modeladmin.message_user(request, f'Đã vô hiệu hóa {updated_count} nhóm thuộc tính.', level=messages.SUCCESS)


@admin.action(description='Vô hiệu hóa giá trị thuộc tính đã chọn')
def deactivate_attribute_values(modeladmin, request, queryset):
    updated_count = queryset.update(is_active=False)
    modeladmin.message_user(request, f'Đã vô hiệu hóa {updated_count} giá trị thuộc tính.', level=messages.SUCCESS)

@admin.register(AttributeGroup)
class AttributeGroupAdmin(admin.ModelAdmin):
    form = AttributeGroupForm
    list_display = ('name', 'slug', 'filter_type', 'data_type', 'is_filterable', 'is_active', 'display_order', 'used_by_products_count')
    list_filter = ('is_filterable', 'is_active', 'filter_type', 'data_type', 'categories')
    search_fields = ('name', 'slug')
    ordering = ('display_order', 'name')
    list_editable = ('display_order', 'is_filterable', 'is_active')
    filter_horizontal = ('categories',)
    prepopulated_fields = {'slug': ('name',)}
    inlines = [AttributeValueInline]
    actions = [deactivate_attribute_groups]

    def delete_model(self, request, obj):
        if obj.has_product_usage():
            obj.is_active = False
            obj.save(update_fields=['is_active'])
            self.message_user(request, 'Nhóm thuộc tính đang được sử dụng nên đã được chuyển sang trạng thái vô hiệu hóa.', level=messages.WARNING)
            return
        super().delete_model(request, obj)

@admin.register(AttributeValue)
class AttributeValueAdmin(admin.ModelAdmin):
    form = AttributeValueForm
    list_display = ('value', 'group', 'slug', 'display_order', 'is_active', 'hex_color', 'usage_count')
    list_filter = ('group', 'is_active', 'group__filter_type', 'group__data_type')
    search_fields = ('value', 'slug', 'group__name')
    ordering = ('group__display_order', 'group__name', 'display_order', 'value')
    autocomplete_fields = ('group',)
    list_editable = ('display_order', 'is_active', 'hex_color')
    actions = [deactivate_attribute_values]

    def delete_model(self, request, obj):
        if obj.has_product_usage():
            obj.deactivate()
            self.message_user(request, 'Giá trị thuộc tính đang được sử dụng nên đã được chuyển sang trạng thái vô hiệu hóa.', level=messages.WARNING)
            return
        super().delete_model(request, obj)

@admin.register(Brand)
class BrandAdmin(admin.ModelAdmin):
    list_display = ('id', 'name')
    search_fields = ('name',)
    ordering = ('name',)

@admin.register(Product)
class ProductAdmin(admin.ModelAdmin):
    form = ProductAdminForm
    list_display = ('id', 'name', 'brand', 'category', 'price', 'stock')
    list_filter = ('brand', 'category')
    search_fields = ('name', 'slug', 'brand__name')
    ordering = ('name',)
    autocomplete_fields = ('brand', 'category')
    inlines = [ProductImageInline]

@admin.register(Category)
class CategoryAdmin(admin.ModelAdmin):
    list_display = ('id', 'name', 'slug', 'parent')
    search_fields = ('name', 'slug')
    ordering = ('name',)
    prepopulated_fields = {'slug': ('name',)}

@admin.register(ProductReview)
class ProductReviewAdmin(admin.ModelAdmin):
    list_display = ('id', 'product', 'user', 'rating', 'created_at')
    list_filter = ('rating',)
    search_fields = ('product__name', 'user__email')
