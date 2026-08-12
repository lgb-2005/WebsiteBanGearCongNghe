from django.core.management.base import BaseCommand
from django.db import transaction
from django.utils.text import slugify

from products.models import AttributeGroup, AttributeValue, Category


ATTRIBUTE_SEED_DATA = {
    'Tai nghe': [
        {
            'name': 'Màu sắc',
            'slug': 'mau-sac',
            'filter_type': AttributeGroup.FILTER_TYPE_COLOR,
            'data_type': AttributeGroup.DATA_TYPE_TEXT,
            'display_order': 10,
            'values': ['Đen', 'Trắng', 'Hồng', 'Xanh'],
        },
        {
            'name': 'Kết nối',
            'slug': 'ket-noi',
            'filter_type': AttributeGroup.FILTER_TYPE_CHECKBOX,
            'data_type': AttributeGroup.DATA_TYPE_TEXT,
            'display_order': 20,
            'values': ['Bluetooth', '2.4GHz Wireless', 'USB', '3.5mm'],
        },
        {
            'name': 'Loại tai nghe',
            'slug': 'loai-tai-nghe',
            'filter_type': AttributeGroup.FILTER_TYPE_CHECKBOX,
            'data_type': AttributeGroup.DATA_TYPE_TEXT,
            'display_order': 30,
            'values': ['Over-ear', 'On-ear', 'In-ear', 'Gaming'],
        },
        {
            'name': 'Chống ồn',
            'slug': 'chong-on',
            'filter_type': AttributeGroup.FILTER_TYPE_RADIO,
            'data_type': AttributeGroup.DATA_TYPE_BOOLEAN,
            'display_order': 40,
            'values': ['Có', 'Không'],
        },
        {
            'name': 'Microphone',
            'slug': 'microphone',
            'filter_type': AttributeGroup.FILTER_TYPE_RADIO,
            'data_type': AttributeGroup.DATA_TYPE_BOOLEAN,
            'display_order': 50,
            'values': ['Có', 'Không'],
        },
    ],
    'Chuột': [
        {
            'name': 'Màu sắc',
            'slug': 'mau-sac',
            'filter_type': AttributeGroup.FILTER_TYPE_COLOR,
            'data_type': AttributeGroup.DATA_TYPE_TEXT,
            'display_order': 10,
            'values': ['Đen', 'Trắng', 'Xám'],
        },
        {
            'name': 'Kết nối',
            'slug': 'ket-noi',
            'filter_type': AttributeGroup.FILTER_TYPE_CHECKBOX,
            'data_type': AttributeGroup.DATA_TYPE_TEXT,
            'display_order': 20,
            'values': ['Bluetooth', '2.4GHz Wireless', 'USB'],
        },
        {
            'name': 'Form chuột',
            'slug': 'form-chuot',
            'filter_type': AttributeGroup.FILTER_TYPE_CHECKBOX,
            'data_type': AttributeGroup.DATA_TYPE_TEXT,
            'display_order': 30,
            'values': ['Đối xứng', 'Ergonomic'],
        },
        {
            'name': 'DPI',
            'slug': 'dpi',
            'filter_type': AttributeGroup.FILTER_TYPE_RANGE,
            'data_type': AttributeGroup.DATA_TYPE_NUMBER,
            'display_order': 40,
            'values': ['800', '1600', '3200', '6400', '12000'],
        },
    ],
    'Bàn phím': [
        {
            'name': 'Màu sắc',
            'slug': 'mau-sac',
            'filter_type': AttributeGroup.FILTER_TYPE_COLOR,
            'data_type': AttributeGroup.DATA_TYPE_TEXT,
            'display_order': 10,
            'values': ['Đen', 'Trắng', 'Xám'],
        },
        {
            'name': 'Kết nối',
            'slug': 'ket-noi',
            'filter_type': AttributeGroup.FILTER_TYPE_CHECKBOX,
            'data_type': AttributeGroup.DATA_TYPE_TEXT,
            'display_order': 20,
            'values': ['Bluetooth', '2.4GHz Wireless', 'USB', 'Type-C'],
        },
        {
            'name': 'Layout',
            'slug': 'layout',
            'filter_type': AttributeGroup.FILTER_TYPE_RADIO,
            'data_type': AttributeGroup.DATA_TYPE_TEXT,
            'display_order': 30,
            'values': ['Fullsize', 'TKL', '75%', '65%'],
        },
        {
            'name': 'Switch',
            'slug': 'switch',
            'filter_type': AttributeGroup.FILTER_TYPE_CHECKBOX,
            'data_type': AttributeGroup.DATA_TYPE_TEXT,
            'display_order': 40,
            'values': ['Red', 'Blue', 'Brown', 'Black'],
        },
    ],
    'Microphone': [
        {
            'name': 'Màu sắc',
            'slug': 'mau-sac',
            'filter_type': AttributeGroup.FILTER_TYPE_COLOR,
            'data_type': AttributeGroup.DATA_TYPE_TEXT,
            'display_order': 10,
            'values': ['Đen', 'Trắng', 'Hồng', 'Xám', 'Bạc', 'Xanh'],
        },
        {
            'name': 'Kết nối',
            'slug': 'ket-noi',
            'filter_type': AttributeGroup.FILTER_TYPE_CHECKBOX,
            'data_type': AttributeGroup.DATA_TYPE_TEXT,
            'display_order': 20,
            'values': ['USB', 'XLR', '3.5mm', 'Bluetooth', 'Wireless', 'Type-C'],
        },
        {
            'name': 'Loại microphone',
            'slug': 'loai-micro',
            'filter_type': AttributeGroup.FILTER_TYPE_CHECKBOX,
            'data_type': AttributeGroup.DATA_TYPE_TEXT,
            'display_order': 30,
            'values': ['Condenser', 'Dynamic', 'USB Microphone', 'Streaming', 'Gaming', 'Podcast'],
        },
        {
            'name': 'Hướng thu âm',
            'slug': 'huong-thu-am',
            'filter_type': AttributeGroup.FILTER_TYPE_CHECKBOX,
            'data_type': AttributeGroup.DATA_TYPE_TEXT,
            'display_order': 40,
            'values': ['Cardioid', 'Omnidirectional', 'Bidirectional', 'Stereo'],
        },
        {
            'name': 'Dải tần đáp ứng',
            'slug': 'dai-tan',
            'filter_type': AttributeGroup.FILTER_TYPE_RANGE,
            'data_type': AttributeGroup.DATA_TYPE_TEXT,
            'display_order': 50,
            'values': ['20Hz - 20kHz'],
        },
        {
            'name': 'Độ nhạy',
            'slug': 'do-nhay',
            'filter_type': AttributeGroup.FILTER_TYPE_RANGE,
            'data_type': AttributeGroup.DATA_TYPE_TEXT,
            'display_order': 60,
            'values': ['-36dB'],
        },
        {
            'name': 'SNR',
            'slug': 'snr',
            'filter_type': AttributeGroup.FILTER_TYPE_RANGE,
            'data_type': AttributeGroup.DATA_TYPE_TEXT,
            'display_order': 70,
            'values': ['≥ 110dB'],
        },
        {
            'name': 'Chân đế kèm theo',
            'slug': 'chan-de',
            'filter_type': AttributeGroup.FILTER_TYPE_RADIO,
            'data_type': AttributeGroup.DATA_TYPE_BOOLEAN,
            'display_order': 80,
            'values': ['Có', 'Không'],
        },
    ],
    'Tay cầm': [
        {
            'name': 'Màu sắc',
            'slug': 'mau-sac',
            'filter_type': AttributeGroup.FILTER_TYPE_COLOR,
            'data_type': AttributeGroup.DATA_TYPE_TEXT,
            'display_order': 10,
            'values': ['Đen', 'Trắng', 'Xám', 'Xanh', 'Đỏ', 'Cam', 'Hồng', 'Xanh lá'],
        },
        {
            'name': 'Kết nối',
            'slug': 'ket-noi',
            'filter_type': AttributeGroup.FILTER_TYPE_CHECKBOX,
            'data_type': AttributeGroup.DATA_TYPE_TEXT,
            'display_order': 20,
            'values': ['USB', 'Bluetooth', 'Wireless', '2.4GHz', 'Type-C'],
        },
        {
            'name': 'Tương thích',
            'slug': 'tuong-thich',
            'filter_type': AttributeGroup.FILTER_TYPE_CHECKBOX,
            'data_type': AttributeGroup.DATA_TYPE_TEXT,
            'display_order': 30,
            'values': ['PC', 'PS4', 'PS5', 'Xbox', 'Switch', 'Android', 'iOS'],
        },
        {
            'name': 'Loại tay cầm',
            'slug': 'loai-tay-cam',
            'filter_type': AttributeGroup.FILTER_TYPE_RADIO,
            'data_type': AttributeGroup.DATA_TYPE_TEXT,
            'display_order': 40,
            'values': ['Gamepad', 'Controller', 'Joystick', 'Steering Wheel', 'Arcade Stick'],
        },
        {
            'name': 'Rung / Haptic feedback',
            'slug': 'rung',
            'filter_type': AttributeGroup.FILTER_TYPE_RADIO,
            'data_type': AttributeGroup.DATA_TYPE_BOOLEAN,
            'display_order': 50,
            'values': ['Có', 'Không'],
        },
        {
            'name': 'Pin / Nguồn',
            'slug': 'pin',
            'filter_type': AttributeGroup.FILTER_TYPE_RADIO,
            'data_type': AttributeGroup.DATA_TYPE_TEXT,
            'display_order': 60,
            'values': ['Pin sạc', 'Pin AA', 'Có dây'],
        },
    ],
}


class Command(BaseCommand):
    help = 'Seed initial category-based product attributes and values.'

    @transaction.atomic
    def handle(self, *args, **options):
        created_groups = 0
        created_values = 0

        for category_name, groups in ATTRIBUTE_SEED_DATA.items():
            category = Category.objects.filter(name__iexact=category_name).first()
            if category is None:
                self.stdout.write(self.style.WARNING(f'Bỏ qua danh mục chưa tồn tại: {category_name}'))
                continue

            for group_data in groups:
                group, group_created = AttributeGroup.objects.get_or_create(
                    slug=group_data['slug'],
                    defaults={
                        'name': group_data['name'],
                        'is_filterable': True,
                        'display_order': group_data['display_order'],
                        'filter_type': group_data['filter_type'],
                        'data_type': group_data['data_type'],
                    },
                )
                if not group_created:
                    group.name = group_data['name']
                    group.is_filterable = True
                    group.display_order = group_data['display_order']
                    group.filter_type = group_data['filter_type']
                    group.data_type = group_data['data_type']
                    group.save(update_fields=['name', 'is_filterable', 'display_order', 'filter_type', 'data_type'])
                else:
                    created_groups += 1

                group.categories.add(category)

                for raw_value in group_data['values']:
                    _, value_created = AttributeValue.objects.get_or_create(
                        group=group,
                        value=raw_value,
                        defaults={'slug': slugify(raw_value)},
                    )
                    if value_created:
                        created_values += 1

        self.stdout.write(
            self.style.SUCCESS(
                f'Seeded attributes successfully. New groups: {created_groups}, new values: {created_values}.'
            )
        )
