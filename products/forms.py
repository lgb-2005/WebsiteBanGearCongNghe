from django import forms
from django.conf import settings
from django.utils.text import slugify
from django.db.models import Prefetch
from decimal import Decimal, InvalidOperation

import bleach
from .models import AttributeGroup, AttributeValue, Brand, Category, Product, ProductAttribute, ProductImage, ProductReview

try:
    from django_ckeditor_5.widgets import CKEditor5Widget
except ImportError:
    CKEditor5Widget = None

class ProductReviewForm(forms.ModelForm):
    class Meta:
        model = ProductReview
        fields = ['rating', 'comment']

        widgets = {
            'rating': forms.NumberInput(attrs={
                'class': 'form-control',
                'min': 1,
                'max': 5
            }),

            'comment': forms.Textarea(attrs={
                'class': 'form-control',
                'rows': 4
            })
        }
        
class MultipleFileInput(forms.ClearableFileInput):
    allow_multiple_selected = True


class MultipleFileField(forms.FileField):
    def __init__(self, *args, **kwargs):
        kwargs.setdefault('widget', MultipleFileInput())
        super().__init__(*args, **kwargs)

    def clean(self, data, initial=None):
        single_file_clean = super().clean
        if isinstance(data, (list, tuple)):
            return [single_file_clean(item, initial) for item in data]
        return single_file_clean(data, initial)


class BrandForm(forms.ModelForm):
    class Meta:
        model = Brand
        fields = ['name']

    def __init__(self, *args, **kwargs):
        super().__init__(*args, **kwargs)
        self.fields['name'].label = 'Tên thương hiệu'
        self.fields['name'].widget.attrs.update({
            'class': 'form-control',
            'placeholder': 'Nhập tên thương hiệu',
        })

    def clean_name(self):
        name = (self.cleaned_data.get('name') or '').strip()

        if not name:
            return name

        existing_brand = Brand.objects.filter(name__iexact=name)
        if self.instance.pk:
            existing_brand = existing_brand.exclude(pk=self.instance.pk)

        if existing_brand.exists():
            raise forms.ValidationError(f'Thương hiệu "{name}" đã tồn tại.')

        return name


class CategoryForm(forms.ModelForm):
    class Meta:
        model = Category
        fields = ['name', 'slug', 'parent']

    def __init__(self, *args, **kwargs):
        super().__init__(*args, **kwargs)
        self.fields['name'].label = 'Tên danh mục'
        self.fields['slug'].label = 'Slug'
        self.fields['parent'].label = 'Danh mục cha'
        self.fields['parent'].required = False
        self.fields['parent'].queryset = Category.objects.order_by('name')
        self.fields['parent'].empty_label = 'Danh mục gốc'
        self.fields['name'].widget.attrs.update({
            'class': 'form-control',
            'placeholder': 'Nhập tên danh mục',
        })
        self.fields['slug'].widget.attrs.update({
            'class': 'form-control',
            'placeholder': 'tu-dong-tu-ten-hoac-nhap-thu-cong',
        })
        self.fields['parent'].widget.attrs.update({
            'class': 'form-control',
        })

        if self.instance.pk:
            self.fields['parent'].queryset = self.fields['parent'].queryset.exclude(pk=self.instance.pk)

    def clean(self):
        cleaned_data = super().clean()
        name = (cleaned_data.get('name') or '').strip()
        slug = (cleaned_data.get('slug') or '').strip()
        parent = cleaned_data.get('parent')

        if not name:
            return cleaned_data

        if not slug:
            slug = slugify(name)
            cleaned_data['slug'] = slug

        existing_category = Category.objects.filter(name__iexact=name, parent=parent)
        if self.instance.pk:
            existing_category = existing_category.exclude(pk=self.instance.pk)

        if existing_category.exists():
            raise forms.ValidationError(f'Danh mục "{name}" đã tồn tại ở cùng cấp.')

        if slug:
            existing_slug = Category.objects.filter(slug__iexact=slug)
            if self.instance.pk:
                existing_slug = existing_slug.exclude(pk=self.instance.pk)
            if existing_slug.exists():
                self.add_error('slug', 'Slug danh mục đã tồn tại.')

        return cleaned_data

    def clean_slug(self):
        raw_slug = (self.cleaned_data.get('slug') or '').strip()
        return slugify(raw_slug) if raw_slug else ''


class AttributeGroupForm(forms.ModelForm):
    class Meta:
        model = AttributeGroup
        fields = [
            'name',
            'slug',
            'filter_type',
            'data_type',
            'categories',
            'display_order',
            'is_filterable',
            'is_active',
        ]

    def __init__(self, *args, **kwargs):
        super().__init__(*args, **kwargs)
        self.fields['categories'].required = False
        self.fields['categories'].queryset = Category.objects.order_by('name')

        for field_name, field in self.fields.items():
            existing_class = field.widget.attrs.get('class', '')
            if isinstance(field.widget, forms.CheckboxInput):
                field.widget.attrs['class'] = f"{existing_class} form-check-input".strip()
            elif isinstance(field.widget, forms.CheckboxSelectMultiple):
                field.widget.attrs['class'] = f"{existing_class} admin-checkbox-grid".strip()
            else:
                field.widget.attrs['class'] = f"{existing_class} admin-form-control".strip()

        self.fields['name'].label = 'Tên nhóm thuộc tính'
        self.fields['slug'].label = 'Slug'
        self.fields['filter_type'].label = 'Kiểu bộ lọc'
        self.fields['data_type'].label = 'Kiểu dữ liệu'
        self.fields['categories'].label = 'Danh mục áp dụng'
        self.fields['display_order'].label = 'Thứ tự hiển thị'
        self.fields['is_filterable'].label = 'Hiển thị ở bộ lọc'
        self.fields['is_active'].label = 'Đang hoạt động'
        self.fields['name'].widget.attrs['placeholder'] = 'Ví dụ: Màu sắc'
        self.fields['slug'].widget.attrs['placeholder'] = 'mau-sac'
        self.fields['display_order'].widget.attrs['placeholder'] = '0'

    def clean_name(self):
        name = (self.cleaned_data.get('name') or '').strip()
        existing_queryset = AttributeGroup.objects.filter(name__iexact=name)
        if self.instance.pk:
            existing_queryset = existing_queryset.exclude(pk=self.instance.pk)
        if existing_queryset.exists():
            raise forms.ValidationError(f'Nhóm thuộc tính "{name}" đã tồn tại.')
        return name

    def clean_slug(self):
        slug = slugify((self.cleaned_data.get('slug') or '').strip())
        if not slug:
            raise forms.ValidationError('Vui lòng nhập slug hợp lệ.')
        existing_queryset = AttributeGroup.objects.filter(slug=slug)
        if self.instance.pk:
            existing_queryset = existing_queryset.exclude(pk=self.instance.pk)
        if existing_queryset.exists():
            raise forms.ValidationError('Slug nhóm thuộc tính đã tồn tại.')
        return slug


class AttributeValueForm(forms.ModelForm):
    class Meta:
        model = AttributeValue
        fields = ['group', 'value', 'slug', 'display_order', 'is_active', 'hex_color']

    def __init__(self, *args, **kwargs):
        super().__init__(*args, **kwargs)
        self.fields['group'].queryset = AttributeGroup.objects.order_by('display_order', 'name')

        for field_name, field in self.fields.items():
            existing_class = field.widget.attrs.get('class', '')
            if isinstance(field.widget, forms.CheckboxInput):
                field.widget.attrs['class'] = f"{existing_class} form-check-input".strip()
            else:
                field.widget.attrs['class'] = f"{existing_class} admin-form-control".strip()

        self.fields['group'].label = 'Nhóm thuộc tính'
        self.fields['value'].label = 'Giá trị'
        self.fields['slug'].label = 'Slug'
        self.fields['display_order'].label = 'Thứ tự hiển thị'
        self.fields['is_active'].label = 'Đang hoạt động'
        self.fields['hex_color'].label = 'Màu HEX'
        self.fields['value'].widget.attrs['placeholder'] = 'Ví dụ: Titanium'
        self.fields['slug'].widget.attrs['placeholder'] = 'titanium'
        self.fields['display_order'].widget.attrs['placeholder'] = '0'
        self.fields['hex_color'].widget.attrs['placeholder'] = '#FFFFFF'

    def clean_value(self):
        value = ProductAdminForm.normalize_attribute_value(self.cleaned_data.get('value'))
        if not value:
            raise forms.ValidationError('Vui lòng nhập giá trị thuộc tính.')
        return value

    def clean_slug(self):
        raw_slug = (self.cleaned_data.get('slug') or '').strip()
        return slugify(raw_slug) if raw_slug else ''

    def clean_hex_color(self):
        hex_color = (self.cleaned_data.get('hex_color') or '').strip().upper()
        if not hex_color:
            return ''
        if len(hex_color) != 7 or not hex_color.startswith('#'):
            raise forms.ValidationError('Mã màu HEX phải có định dạng như #FFFFFF.')
        valid_digits = '0123456789ABCDEF'
        if any(char not in valid_digits for char in hex_color[1:]):
            raise forms.ValidationError('Mã màu HEX không hợp lệ.')
        return hex_color

    def clean(self):
        cleaned_data = super().clean()
        group = cleaned_data.get('group')
        value = cleaned_data.get('value')
        slug = cleaned_data.get('slug')

        if group and value:
            existing_queryset = AttributeValue.objects.filter(group=group, value__iexact=value)
            if self.instance.pk:
                existing_queryset = existing_queryset.exclude(pk=self.instance.pk)
            if existing_queryset.exists():
                self.add_error('value', f'Giá trị "{value}" đã tồn tại trong nhóm này.')

        if group and slug:
            existing_queryset = AttributeValue.objects.filter(group=group, slug=slug)
            if self.instance.pk:
                existing_queryset = existing_queryset.exclude(pk=self.instance.pk)
            if existing_queryset.exists():
                self.add_error('slug', 'Slug giá trị thuộc tính đã tồn tại trong nhóm này.')

        return cleaned_data


class ProductAdminForm(forms.ModelForm):
    price = forms.CharField()
    discount_price = forms.CharField(required=False)
    deleted_images = forms.ModelMultipleChoiceField(
        queryset=ProductImage.objects.none(),
        required=False,
        widget=forms.MultipleHiddenInput,
    )
    brand = forms.ModelChoiceField(
        queryset=Brand.objects.order_by('name'),
        required=False,
        empty_label='Chọn thương hiệu',
    )
    images = MultipleFileField(required=False)

    class Meta:
        model = Product
        fields = [
            'name',
            'slug',
            'description',
            'product_information',
            'price',
            'discount_price',
            'stock',
            'brand',
            'category',
            'images',
            'deleted_images',
        ]
        widgets = {}

    def __init__(self, *args, **kwargs):
        super().__init__(*args, **kwargs)
        self.dynamic_attribute_fields = []
        self.dynamic_attribute_bound_fields = []
        self.dynamic_attribute_sections = []
        self.dynamic_attribute_groups = {}
        self.uses_ckeditor5_widget = CKEditor5Widget is not None

        description_widget_attrs = {
            'class': 'django_ckeditor_5 admin-form-control ckeditor-description-field',
            'placeholder': 'Mô tả về sản phẩm',
        }

        if self.uses_ckeditor5_widget:
            self.fields['description'].widget = CKEditor5Widget(
                config_name='product_description',
                attrs=description_widget_attrs,
            )
        else:
            self.fields['description'].widget = forms.Textarea(
                attrs={
                    'class': 'admin-form-control ckeditor-description-field',
                    'rows': 8,
                    'placeholder': 'Mô tả về sản phẩm',
                }
            )

        self.fields['product_information'].widget = forms.Textarea(
            attrs={
                'class': 'admin-form-control',
                'rows': 10,
                'placeholder': 'Tên kết nối: USB\r\nĐộ phân giải: 200 - 8.000 DPI\r\nTương thích: Windows, macOS',
            }
        )

        for field_name, field in self.fields.items():
            existing_class = field.widget.attrs.get('class', '')
            if 'admin-form-control' not in existing_class.split():
                field.widget.attrs['class'] = f"{existing_class} admin-form-control".strip()
            if field_name == 'description':
                field.widget.attrs.pop('rows', None)

        self.fields['brand'].queryset = Brand.objects.order_by('name')
        self.fields['category'].queryset = Category.objects.order_by('name')
        self.fields['images'].label = 'Ảnh sản phẩm'
        self.fields['images'].widget.attrs['accept'] = 'image/*'
        self.fields['deleted_images'].queryset = ProductImage.objects.none()

        self.fields['name'].widget.attrs['placeholder'] = 'Tên sản phẩm'
        self.fields['slug'].widget.attrs['placeholder'] = 'Slug sản phẩm'
        self.fields['price'].widget.attrs['placeholder'] = '0'
        self.fields['discount_price'].widget.attrs['placeholder'] = '0'
        self.fields['stock'].widget.attrs['placeholder'] = '0'

        if self.instance.pk:
            self.initial['price'] = self.format_currency(self.instance.price)
            if self.instance.discount_price is not None:
                self.initial['discount_price'] = self.format_currency(self.instance.discount_price)
            self.fields['deleted_images'].queryset = self.instance.images.all()

        selected_category = self.get_selected_category()
        self.configure_dynamic_attribute_fields(selected_category)

    def get_selected_category(self):
        category = None
        category_id = self.data.get('category') or self.initial.get('category') or getattr(self.instance, 'category_id', None)

        if isinstance(category_id, Category):
            return category_id

        if category_id:
            try:
                category = Category.objects.filter(pk=category_id).first()
            except (TypeError, ValueError):
                category = None

        return category

    def get_attribute_groups_for_category(self, category):
        if category is None:
            return AttributeGroup.objects.none()

        return AttributeGroup.objects.filter(
            categories=category,
            is_active=True,
        ).prefetch_related(
            Prefetch('values', queryset=AttributeValue.objects.filter(is_active=True).order_by('display_order', 'value'))
        ).order_by('display_order', 'name').distinct()

    def get_selected_attribute_value_ids(self):
        if not self.instance.pk:
            return set()

        return set(self.instance.attributes.values_list('attribute_value_id', flat=True))

    def configure_dynamic_attribute_fields(self, category):
        attribute_groups = list(self.get_attribute_groups_for_category(category))
        selected_value_ids = self.get_selected_attribute_value_ids()

        for group in attribute_groups:
            field_name = f'attr_{group.slug}'
            custom_field_name = f'custom_attr_{group.slug}'
            queryset = group.values.all().order_by('display_order', 'value')
            widget = forms.CheckboxSelectMultiple()
            if group.filter_type == AttributeGroup.FILTER_TYPE_SELECT:
                widget = forms.SelectMultiple(attrs={'class': 'admin-form-control'})

            self.fields[field_name] = forms.ModelMultipleChoiceField(
                queryset=queryset,
                required=False,
                widget=widget,
                label=group.name,
            )

            initial_values = [value.pk for value in queryset if value.pk in selected_value_ids]
            if initial_values:
                self.initial[field_name] = initial_values

            self.fields[custom_field_name] = forms.CharField(
                required=False,
                label=f'Thêm mới {group.name.lower()}',
                widget=forms.TextInput(
                    attrs={
                        'class': 'admin-form-control',
                        'placeholder': f'Nhập {group.name.lower()} mới',
                    }
                ),
            )

            self.dynamic_attribute_fields.append(field_name)
            self.dynamic_attribute_bound_fields.append(self[field_name])
            self.dynamic_attribute_groups[field_name] = group
            self.dynamic_attribute_sections.append(
                {
                    'group': group,
                    'select_field': self[field_name],
                    'custom_field': self[custom_field_name],
                }
            )

    @staticmethod
    def format_currency(value):
        if value in (None, ''):
            return ''
        return str(int(value))

    @staticmethod
    def parse_currency(value):
        normalized = (value or '').replace('VNĐ', '').replace('vnd', '').replace(',', '').replace('.', '').strip()
        if normalized == '':
            return None
        try:
            return Decimal(normalized)
        except (InvalidOperation, TypeError, ValueError):
            raise forms.ValidationError('Giá trị tiền tệ không hợp lệ.')

    @staticmethod
    def normalize_attribute_value(value):
        normalized = ' '.join((value or '').split()).strip()
        if not normalized:
            return ''
        return normalized[:1].upper() + normalized[1:]

    def clean_slug(self):
        slug = (self.cleaned_data.get('slug') or '').strip()
        name = (self.cleaned_data.get('name') or '').strip()
        final_slug = slug or slugify(name)

        if not final_slug:
            raise forms.ValidationError('Vui lòng nhập tên sản phẩm hoặc slug hợp lệ.')

        existing_product = Product.objects.filter(slug=final_slug)
        if self.instance.pk:
            existing_product = existing_product.exclude(pk=self.instance.pk)

        if existing_product.exists():
            raise forms.ValidationError('Slug sản phẩm đã tồn tại.')

        return final_slug

    def clean_price(self):
        value = self.parse_currency(self.cleaned_data.get('price'))
        if value is None:
            raise forms.ValidationError('Vui lòng nhập giá gốc.')
        return value

    def clean_discount_price(self):
        value = self.parse_currency(self.cleaned_data.get('discount_price'))
        return value

    def clean_deleted_images(self):
        deleted_images = self.cleaned_data.get('deleted_images')
        if not self.instance.pk:
            return ProductImage.objects.none()
        return deleted_images.filter(product=self.instance)

    def clean_description(self):
        description = self.cleaned_data.get('description') or ''
        return bleach.clean(
            description,
            tags=settings.RICH_TEXT_ALLOWED_TAGS,
            attributes=settings.RICH_TEXT_ALLOWED_ATTRIBUTES,
            protocols=settings.RICH_TEXT_ALLOWED_PROTOCOLS,
            strip=True,
        )

    def clean_product_information(self):
        product_information = (self.cleaned_data.get('product_information') or '').strip()
        if not product_information:
            return ''

        normalized_lines = []
        for raw_line in product_information.splitlines():
            line = raw_line.strip()
            if not line:
                continue
            if ':' not in line:
                raise forms.ValidationError('Mỗi dòng thông tin sản phẩm phải có định dạng "Tên: Giá trị".')
            label, value = [part.strip() for part in line.split(':', 1)]
            if not label or not value:
                raise forms.ValidationError('Mỗi dòng thông tin sản phẩm phải có đủ tên và giá trị.')
            normalized_lines.append(f'{label}: {value}')

        return '\n'.join(normalized_lines)

    def clean(self):
        cleaned_data = super().clean()
        price = cleaned_data.get('price')
        discount_price = cleaned_data.get('discount_price')

        if price is not None and discount_price is not None and discount_price > price:
            self.add_error('discount_price', 'Giá khuyến mãi không được lớn hơn giá gốc.')

        for field_name in self.dynamic_attribute_fields:
            group = self.dynamic_attribute_groups.get(field_name)
            if group is None:
                continue

            custom_field_name = f'custom_attr_{group.slug}'
            normalized_custom_value = self.normalize_attribute_value(cleaned_data.get(custom_field_name))
            cleaned_data[custom_field_name] = normalized_custom_value

        return cleaned_data

    def save_product_attributes(self, product):
        attribute_rows = []
        seen_attribute_value_ids = set()

        for field_name in self.dynamic_attribute_fields:
            group = self.dynamic_attribute_groups.get(field_name)
            for value in self.cleaned_data.get(field_name, []):
                if value.pk in seen_attribute_value_ids:
                    continue
                seen_attribute_value_ids.add(value.pk)
                attribute_rows.append(ProductAttribute(product=product, attribute_value=value))

            if group is None:
                continue

            custom_field_name = f'custom_attr_{group.slug}'
            custom_value = self.cleaned_data.get(custom_field_name)
            if not custom_value:
                continue

            attribute_value = group.values.filter(value__iexact=custom_value).first()
            if attribute_value is None:
                attribute_value = AttributeValue.objects.create(
                    group=group,
                    value=custom_value,
                )

            if attribute_value.pk in seen_attribute_value_ids:
                continue

            seen_attribute_value_ids.add(attribute_value.pk)
            attribute_rows.append(ProductAttribute(product=product, attribute_value=attribute_value))

        ProductAttribute.objects.filter(product=product).delete()
        if attribute_rows:
            ProductAttribute.objects.bulk_create(attribute_rows)

    def save(self, commit=True):
        product = super().save(commit=commit)
        if commit:
            self.save_product_attributes(product)
        return product

    def save_images(self, product):
        for image in self.cleaned_data.get('deleted_images', []):
            if image.image:
                image.image.delete(save=False)
            image.delete()

        for image in self.files.getlist('images'):
            ProductImage.objects.create(product=product, image=image)
