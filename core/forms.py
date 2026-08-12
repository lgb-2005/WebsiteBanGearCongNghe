from django import forms
from .models import Banner


class BannerForm(forms.ModelForm):
    class Meta:
        model = Banner
        fields = [
            'image',
            'cta_url',
            'position',
            'display_order',
            'start_at',
            'end_at',
            'is_active',
        ]
        widgets = {
            'start_at': forms.DateTimeInput(
                attrs={'type': 'datetime-local', 'class': 'admin-form-control'},
                format='%Y-%m-%dT%H:%M',
            ),
            'end_at': forms.DateTimeInput(
                attrs={'type': 'datetime-local', 'class': 'admin-form-control'},
                format='%Y-%m-%dT%H:%M',
            ),
        }

    def __init__(self, *args, **kwargs):
        super().__init__(*args, **kwargs)
        self.fields['image'].label = 'Hình ảnh'
        self.fields['cta_url'].label = 'Đường dẫn khi click'
        self.fields['position'].label = 'Vị trí'
        self.fields['display_order'].label = 'Thứ tự hiển thị'
        self.fields['start_at'].label = 'Bắt đầu hiển thị'
        self.fields['end_at'].label = 'Kết thúc hiển thị'
        self.fields['is_active'].label = 'Đang hoạt động'

        for field_name, field in self.fields.items():
            existing_class = field.widget.attrs.get('class', '')
            if isinstance(field.widget, forms.CheckboxInput):
                field.widget.attrs['class'] = f"{existing_class} form-check-input".strip()
            else:
                field.widget.attrs['class'] = f"{existing_class} admin-form-control".strip()

        self.fields['cta_url'].widget.attrs['placeholder'] = 'VD: /products/'
        self.fields['display_order'].widget.attrs['placeholder'] = '0'

    def clean_image(self):
        image = self.cleaned_data.get('image')
        if not self.instance.pk and not image:
            raise forms.ValidationError('Vui lòng chọn hình ảnh cho banner.')
        return image

    def clean_display_order(self):
        display_order = self.cleaned_data.get('display_order')
        if display_order is None or display_order < 0:
            raise forms.ValidationError('Thứ tự hiển thị phải lớn hơn hoặc bằng 0.')
        return display_order

    def clean(self):
        cleaned_data = super().clean()
        start_at = cleaned_data.get('start_at')
        end_at = cleaned_data.get('end_at')

        if start_at and end_at and end_at < start_at:
            raise forms.ValidationError('Thời gian kết thúc phải sau hoặc bằng thời gian bắt đầu.')

        return cleaned_data
