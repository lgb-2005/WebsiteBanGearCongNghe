from django import forms
from django.contrib.auth.forms import UserCreationForm
from django.core.exceptions import ValidationError
from django.core.files.uploadedfile import InMemoryUploadedFile
from io import BytesIO
from PIL import Image
from .models import User

class RegisterForm(UserCreationForm):
    email = forms.EmailField(
        required=True,
        widget=forms.EmailInput(attrs={'placeholder': 'Email của bạn'})
    )
    name = forms.CharField(
        max_length=100,
        required=True,
        widget=forms.TextInput(attrs={'placeholder': 'Họ và tên'})
    )
    phone = forms.CharField(
        max_length=20,
        required=False,
        widget=forms.TextInput(attrs={'placeholder': 'Số điện thoại của bạn'})
    )
    province_code = forms.CharField(
    required=False,
    widget=forms.HiddenInput()
    )

    ward_code = forms.CharField(
        required=False,
        widget=forms.HiddenInput()
    )

    province_name = forms.CharField(
    required=False,
    widget=forms.HiddenInput()
)

    ward_name = forms.CharField(
    required=False,
    widget=forms.HiddenInput()
)

    street_address = forms.CharField(
        max_length=500,
        required=False,
        widget=forms.TextInput(
            attrs={
                'placeholder': 'Số nhà, tên đường...'
            }
        )
    )

    class Meta:
        model = User
        fields = [
            'name',
            'email',
            'phone',

            'province_code',
            'province_name',

            'ward_code',
            'ward_name',

            'street_address',

            'password1',
            'password2'
        ]

    def __init__(self, *args, **kwargs):
        super().__init__(*args, **kwargs)

        self.fields['name'].error_messages.update({
            'required': 'Vui lòng nhập họ và tên.',
            'max_length': 'Họ và tên không được vượt quá 100 ký tự.',
        })
        self.fields['email'].error_messages.update({
            'required': 'Vui lòng nhập email.',
            'invalid': 'Vui lòng nhập địa chỉ email hợp lệ.',
        })
        self.fields['phone'].error_messages.update({
            'max_length': 'Số điện thoại không được vượt quá 20 ký tự.',
        })
        self.fields['street_address'].error_messages.update({
            'max_length': 'Địa chỉ chi tiết không được vượt quá 500 ký tự.',
        })
        self.fields['password1'].error_messages.update({
            'required': 'Vui lòng nhập mật khẩu.',
        })
        self.fields['password2'].error_messages.update({
            'required': 'Vui lòng nhập lại mật khẩu.',
        })

    def clean_email(self):
        email = self.cleaned_data.get('email')
        if User.objects.filter(email=email).exists():
            raise ValidationError("Email này đã được sử dụng. Vui lòng chọn email khác.")
        return email

    def clean_phone(self):
        phone = (self.cleaned_data.get('phone') or '').strip()
        if phone and User.objects.filter(phone=phone).exists():
            raise ValidationError("Số điện thoại này đã được sử dụng bởi tài khoản khác.")
        return phone or None

    def clean_password2(self):
        password1 = self.cleaned_data.get('password1')
        password2 = self.cleaned_data.get('password2')
        if password1 and password2 and password1 != password2:
            raise ValidationError("Hai mật khẩu không khớp nhau.")
        return password2

    def save(self, commit=True):
        user = super().save(commit=False)
        user.name = self.cleaned_data['name']
        user.phone = self.cleaned_data.get('phone')

        user.province_code = self.cleaned_data.get(
        'province_code'
        )

        user.province_name = self.cleaned_data.get(
            'province_name'
        )

        user.ward_code = self.cleaned_data.get(
            'ward_code'
        )

        user.ward_name = self.cleaned_data.get(
            'ward_name'
        )

        user.street_address = self.cleaned_data.get(
            'street_address'
        )
        if commit:
            user.save()
        return user
    
class UpdateProfileForm(forms.ModelForm):
    MAX_AVATAR_SIZE_MB = 5
    AVATAR_OUTPUT_SIZE = (400, 400)

    class Meta:
        model = User
        fields = [
            'name',
            'email',
            'phone',

            'province_code',
            'province_name',

            'ward_code',
            'ward_name',

            'street_address',

            'avatar'
        ]

    def clean_email(self):
        email = (self.cleaned_data.get('email') or '').strip()
        if not email:
            if self.instance and self.instance.pk and self.instance.email:
                return self.instance.email
            raise ValidationError("Vui lòng nhập email.")
        qs = User.objects.filter(email=email)
        if self.instance and self.instance.pk:
            qs = qs.exclude(pk=self.instance.pk)
        if qs.exists():
            raise ValidationError("Email này đã được sử dụng bởi tài khoản khác.")
        return email

    def clean_phone(self):
        phone = (self.cleaned_data.get('phone') or '').strip()
        if not phone:
            raise ValidationError("Vui lòng nhập số điện thoại.")
        qs = User.objects.filter(phone=phone)
        if self.instance and self.instance.pk:
            qs = qs.exclude(pk=self.instance.pk)
        if qs.exists():
            raise ValidationError("Số điện thoại này đã được sử dụng bởi tài khoản khác.")
        return phone

    def clean_avatar(self):
        avatar = self.cleaned_data.get('avatar')

        if not avatar:
            return avatar

        if avatar.size > self.MAX_AVATAR_SIZE_MB * 1024 * 1024:
            raise ValidationError("Ảnh đại diện không được lớn hơn 5MB.")

        try:
            image = Image.open(avatar)
            image.verify()
        except Exception:
            raise ValidationError("Tệp tải lên không phải là ảnh hợp lệ.")

        avatar.seek(0)
        content_type = getattr(avatar, 'content_type', '') or ''
        if content_type and content_type.lower() not in ['image/jpeg', 'image/png', 'image/webp']:
            raise ValidationError("Chỉ hỗ trợ ảnh JPG, PNG hoặc WEBP.")

        return avatar

    def save(self, commit=True):
        instance = super().save(commit=False)
        avatar = self.cleaned_data.get('avatar')

        if avatar:
            avatar.seek(0)
            image = Image.open(avatar)
            if image.mode not in ('RGB', 'L'):
                image = image.convert('RGB')
            elif image.mode == 'L':
                image = image.convert('RGB')

            width, height = image.size
            crop_size = min(width, height)
            left = (width - crop_size) / 2
            top = (height - crop_size) / 2
            right = (width + crop_size) / 2
            bottom = (height + crop_size) / 2

            image = image.crop((left, top, right, bottom))
            image = image.resize(self.AVATAR_OUTPUT_SIZE, Image.Resampling.LANCZOS)

            output = BytesIO()
            image.save(output, format='JPEG', quality=90, optimize=True)
            output.seek(0)

            file_name_root = avatar.name.rsplit('.', 1)[0]
            normalized_name = f"{file_name_root}.jpg"
            instance.avatar = InMemoryUploadedFile(
                output,
                'ImageField',
                normalized_name,
                'image/jpeg',
                output.getbuffer().nbytes,
                None
            )

        if commit:
            instance.save()

        return instance

class ChangePasswordForm(forms.Form):
    old_password = forms.CharField(widget=forms.PasswordInput)
    new_password = forms.CharField(widget=forms.PasswordInput)
    confirm_password = forms.CharField(widget=forms.PasswordInput)

    def clean(self):
        cleaned = super().clean()
        new = cleaned.get('new_password')
        confirm = cleaned.get('confirm_password')

        if new != confirm:
            raise forms.ValidationError("Mật khẩu xác nhận không khớp")

        return cleaned