from django.core.paginator import Paginator
from django.http import JsonResponse
from django.shortcuts import render, redirect
from django.utils import timezone
from django.contrib.auth import login, logout, authenticate, update_session_auth_hash
from django.contrib.auth.decorators import login_required
from django.db.models import Q

from products.models import Favorite
from .forms import ChangePasswordForm, RegisterForm, UpdateProfileForm
from .models import User
from cart.services import merge_session_cart_to_user
from orders.models import Order
from orders.services import link_customer_to_user

def translate_error_message(message):
    text = str(message)

    exact_messages = {
        'This field is required.': 'Vui lòng nhập trường này.',
        'Enter a valid email address.': 'Vui lòng nhập địa chỉ email hợp lệ.',
        'The two password fields didn’t match.': 'Hai mật khẩu không khớp nhau.',
        'This password is too common.': 'Mật khẩu này quá phổ biến.',
        'This password is entirely numeric.': 'Mật khẩu không được chỉ bao gồm chữ số.',
    }

    if text in exact_messages:
        return exact_messages[text]

    if text.startswith('This password is too short. It must contain at least '):
        min_length = ''.join(char for char in text if char.isdigit())
        if min_length:
            return f'Mật khẩu quá ngắn. Vui lòng nhập ít nhất {min_length} ký tự.'
        return 'Mật khẩu quá ngắn.'

    if text.startswith('The password is too similar to the '):
        return 'Mật khẩu quá giống với thông tin cá nhân của bạn.'

    return text


def serialize_form_errors(form):
    return {
        field: [translate_error_message(error) for error in errors]
        for field, errors in form.errors.items()
    }

def register(request):
    if request.method == 'POST':
        form = RegisterForm(request.POST)
        
        if form.is_valid():
            try:
                user = form.save()
                link_customer_to_user(user)
                login(request, user)
                merge_session_cart_to_user(request)
                try:
                    from analytics.services import get_or_create_analytics_session
                    session = get_or_create_analytics_session(request)
                    if session and not session.user_id:
                        session.user = user
                        session.save(update_fields=['user', 'updated_at'])
                except Exception:
                    pass
                return JsonResponse({
                    'success': True,
                    'message': 'Đăng ký tài khoản thành công! Chào mừng bạn đến với TechGear.',
                    'redirect_url': '/'
                })
                
            except Exception as e:
                print(f"Register error: {e}")
                return JsonResponse({
                    'success': False,
                    'message': 'Có lỗi xảy ra khi tạo tài khoản. Vui lòng thử lại sau.'
                }, status=500)
        
        return JsonResponse({
            'success': False,
            'message': 'Vui lòng kiểm tra lại thông tin đăng ký.',
            'errors': serialize_form_errors(form)
        }, status=400)

    form = RegisterForm()

    return render(request, 'accounts/register.html', {'form': form})

def login_view(request):
    if request.method == 'POST':
        email = (request.POST.get('email') or '').strip()
        password = request.POST.get('password') or ''
        
        user = authenticate(request, username=email, password=password)
        
        if user is not None:
            if user.is_staff or user.is_superuser:
                return JsonResponse({
                    'success': False,
                    'message': 'Tài khoản quản trị vui lòng đăng nhập tại trang admin dashboard.'
                }, status=403)

            login(request, user)
            merge_session_cart_to_user(request)
            try:
                from analytics.services import get_or_create_analytics_session
                session = get_or_create_analytics_session(request)
                if session and not session.user_id:
                    session.user = user
                    session.save(update_fields=['user', 'updated_at'])
            except Exception:
                pass
            return JsonResponse({
                'success': True,
                'message': 'Đăng nhập thành công! Chào mừng bạn quay lại.',
                'redirect_url': '/'
            })

        locked_user = User.objects.filter(email__iexact=email, is_active=False).first()
        if locked_user is not None and locked_user.check_password(password):
            return JsonResponse({
                'success': False,
                'message': 'Tài khoản của bạn đã bị khóa. Vui lòng liên hệ quản trị viên.'
            }, status=403)
 
        return JsonResponse({
            'success': False,
            'message': 'Email hoặc mật khẩu không chính xác.'
        }, status=400)
    
    return render(request, 'accounts/login.html')

def logout_view(request):
    is_admin_user = bool(
        request.user.is_authenticated
        and (request.user.is_staff or request.user.is_superuser)
    )

    logout(request)

    if request.headers.get('X-Requested-With') == 'XMLHttpRequest':
        return JsonResponse({
            'success': True,
            'message': 'Bạn đã đăng xuất khỏi hệ thống.',
            'redirect_url': '/'
        })

    if is_admin_user:
        return redirect('core:admin_login')

    return redirect('login')


def format_currency(value):
    if value is None:
        return "0đ"

    try:
        return f"{int(value):,}đ".replace(",", ".")
    except (ValueError, TypeError):
        return "0đ"


def get_order_status_badge(status):
    status_map = {
        'pending': {
            'label': 'Chờ xử lý',
            'class_name': 'status-pending',
        },
        'processing': {
            'label': 'Đang xử lý',
            'class_name': 'status-processing',
        },
        'completed': {
            'label': 'Hoàn thành',
            'class_name': 'status-completed',
        },
        'cancelled': {
            'label': 'Đã hủy',
            'class_name': 'status-cancelled',
        },
    }

    return status_map.get(
        status,
        {
            'label': status,
            'class_name': 'status-pending',
        }
    )
    

@login_required
def profile(request):
    favorites = (
        Favorite.objects
        .filter(user=request.user)
        .select_related('product')
        .prefetch_related('product__images')
        .order_by('-created_at')
    )

    formatted_favorites = []

    for favorite in favorites:
        product = favorite.product

        current_price = (
            product.discount_price
            if product.discount_price
            else product.price
        )

        old_price = (
            product.price
            if product.discount_price
            else None
        )

        discount_percent = None

        if product.discount_price:
            try:
                discount_percent = int(
                    round(
                        ((product.price - product.discount_price)
                        / product.price) * 100
                    )
                )
            except:
                discount_percent = None

        formatted_favorites.append({
            'product': product,
            'current_price': format_currency(current_price),
            'old_price': format_currency(old_price) if old_price else '',
            'discount_percent': discount_percent,
        })

    fav_page_num = request.GET.get('fav_page', 1)
    fav_paginator = Paginator(formatted_favorites, 10)
    try:
        fav_page = fav_paginator.page(fav_page_num)
    except Exception:
        fav_page = fav_paginator.page(1)

    search = ' '.join((request.GET.get('search') or '').split())
    status_filter = (request.GET.get('status') or '').strip()

    orders = (
    Order.objects
    .filter(customer__user=request.user)
    )

    if search:
        orders = orders.filter(
            Q(order_code__icontains=search)
            | Q(items__product__name__icontains=search)
        ).distinct()

    if status_filter == 'completed':
        orders = orders.filter(status='completed')
    elif status_filter == 'incomplete':
        orders = orders.filter(status__in=['pending', 'processing'])

    order_page_num = request.GET.get('order_page', 1)
    order_paginator = Paginator(list(
        orders.prefetch_related('items', 'items__product', 'items__product__images')
        .order_by('-created_at')
    ), 5)
    try:
        order_page_obj = order_paginator.page(order_page_num)
    except Exception:
        order_page_obj = order_paginator.page(1)

    formatted_orders = []

    for order in order_page_obj.object_list:
        order_status = get_order_status_badge(order.status)
        order_products = []

        for item in order.items.all():
            product = item.product
            product_images = product.image_urls

            order_products.append({
                'name': product.name,
                'slug': product.slug,
                'image_url': product_images[0] if product_images else '',
                'quantity': item.quantity,
                'price': format_currency(item.price),
                'line_total': format_currency(item.price * item.quantity),
            })

        formatted_orders.append({
        'order_code': order.order_code,
        'created_at': order.created_at.strftime('%d-%m-%Y, %I:%M %p'),
        'total_price': format_currency(order.total_price),
        'status': order_status['label'],
        'status_class': order_status['class_name'],
        'products': order_products,
    })

    return render(
    request,
    'accounts/profile.html',
    {
        'user': request.user,
        'favorites': fav_page.object_list,
        'fav_page': fav_page,
        'orders': formatted_orders,
        'order_page': order_page_obj,
        'order_search': search,
        'order_status_filter': status_filter,
        'orders_result_count': order_paginator.count,
        'orders_has_filters': bool(search or status_filter),
    })

@login_required
def profile_edit(request):
    return JsonResponse({
        'success': False,
        'message': 'Chức năng chỉnh sửa thông tin cá nhân đang được phát triển.'
    }, status=501)


@login_required
def update_profile(request):
    if request.method == "POST":
        form = UpdateProfileForm(request.POST, request.FILES, instance=request.user)

        if form.is_valid():
            form.save()
            return JsonResponse({
                'success': True,
                'message': 'Cập nhật thành công'
            })

        return JsonResponse({
            'success': False,
            'errors': form.errors
        })


@login_required
def change_password(request):
    if request.method == "POST":
        form = ChangePasswordForm(request.POST)

        if form.is_valid():
            if not request.user.check_password(form.cleaned_data['old_password']):
                return JsonResponse({
                    'success': False,
                    'errors': {'old_password': ['Sai mật khẩu cũ']}
                })

            request.user.set_password(form.cleaned_data['new_password'])
            request.user.save()
            update_session_auth_hash(request, request.user)

            return JsonResponse({
                'success': True,
                'message': 'Đổi mật khẩu thành công'
            })

        return JsonResponse({
            'success': False,
            'errors': form.errors
        })