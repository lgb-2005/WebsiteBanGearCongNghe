"""
Management command: import_products
Usage:
    python manage.py import_products
    python manage.py import_products --file path/to/custom.json
    python manage.py import_products --source gearvn-keyboards
    python manage.py import_products --source gearvn-keyboards --limit 30
    python manage.py import_products --source gearvn-headsets
    python manage.py import_products --source gearvn-headsets --limit 30
    python manage.py import_products --source gearvn-microphones
    python manage.py import_products --source gearvn-microphones --limit 30
    python manage.py import_products --dry-run
"""

import json
import os
import re
import sys
import time
import urllib.request
import urllib.error

from bs4 import BeautifulSoup
from pathlib import Path

from django.conf import settings
from django.core.management.base import BaseCommand
from django.utils.text import slugify


class Command(BaseCommand):
    help = 'Import products from a JSON file or scrape from GearVN/EZPC. Skips products that already exist (by slug or name).'

    DEFAULT_JSON = Path(__file__).parent / 'products_data.json'
    IMAGE_DIR = Path(settings.MEDIA_ROOT) / 'products'
    USER_AGENT = 'Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36'

    SOURCE_URL = 'https://gearvn.com/collections/ban-phim-may-tinh/products.json?limit=100'
    HEADSET_SOURCE_URL = 'https://gearvn.com/collections/tai-nghe-may-tinh/products.json?limit=100'
    MICROPHONE_SOURCE_URL = 'https://gearvn.com/collections/microphone/products.json?limit=100'
    EZPC_CONTROLLER_SOURCE_URL = 'https://ezpc.vn/tay-cam-choi-game.html'
    EZPC_BASE_URL = 'https://ezpc.vn'

    CONNECTION_MAP = {
        'có dây': 'USB', 'usb': 'USB', 'usb 2.0': 'USB', 'usb-a': 'USB',
        'type-c': 'Type-C', 'usb-c': 'Type-C',
        '3.5mm': '3.5mm', '3.5 mm': '3.5mm', 'jack 3.5': '3.5mm',
        'không dây': '2.4GHz Wireless', 'wireless': '2.4GHz Wireless', '2.4ghz': '2.4GHz Wireless',
        'bluetooth': 'Bluetooth',
    }
    MICROPHONE_CONNECTION_MAP = {
        'usb': 'USB', 'usb-a': 'USB',
        'xlr': 'XLR', 'cổng xlr': 'XLR',
        '3.5mm': '3.5mm', '3.5 mm': '3.5mm', 'jack 3.5': '3.5mm',
        'type-c': 'Type-C', 'usb-c': 'Type-C',
        'bluetooth': 'Bluetooth', 'wireless': 'Wireless', 'không dây': 'Wireless',
    }
    POLAR_PATTERN_MAP = {
        'cardioid': 'Cardioid', 'supercardioid': 'Cardioid', 'super-cardioid': 'Cardioid',
        'omni': 'Omnidirectional', 'omnidirectional': 'Omnidirectional', 'toàn hướng': 'Omnidirectional',
        'bidirectional': 'Bidirectional', 'figure-8': 'Bidirectional', '8 hình': 'Bidirectional',
        'stereo': 'Stereo',
    }
    MICROPHONE_TYPE_MAP = {
        'condenser': 'Condenser',
        'dynamic': 'Dynamic',
        'usb microphone': 'USB Microphone',
        'streaming': 'Streaming', 'stream': 'Streaming', 'streamer': 'Streaming',
        'gaming': 'Gaming',
        'podcast': 'Podcast', 'podcaster': 'Podcast',
    }
    CONTROLLER_COMPATIBILITY_MAP = {
        'pc': 'PC', 'laptop': 'PC', 'máy tính': 'PC',
        'ps4': 'PS4', 'playstation 4': 'PS4', 'dualshock': 'PS4',
        'ps5': 'PS5', 'playstation 5': 'PS5',
        'xbox': 'Xbox', 'xbox one': 'Xbox', 'xbox series': 'Xbox',
        'switch': 'Switch', 'nintendo switch': 'Switch',
        'android': 'Android',
        'ios': 'iOS', 'iphone': 'iOS', 'ipad': 'iOS',
    }
    CONTROLLER_TYPE_MAP = {
        'gamepad': 'Gamepad', 'controller': 'Controller', 'tay cầm': 'Gamepad',
        'joystick': 'Joystick', 'steering wheel': 'Steering Wheel', 'arcade stick': 'Arcade Stick',
    }
    CONTROLLER_BRAND_LIST = [
        'Flydigi', 'Aolion', 'BigBig Won', 'EasySMX', 'Sony', 'Microsoft', 'Xbox', 'Nintendo',
        'Razer', 'Logitech', 'GameSir', '8BitDo', 'Hori', 'Dareu', 'Rapoo', 'Redragon', 'MSI', 'Asus',
    ]
    CONTROLLER_BRAND_MAP = {
        'dualshock': 'Sony', 'ps4': 'Sony', 'playstation': 'Sony', 'ps5': 'Sony',
        'xbox': 'Microsoft', 'xbox one': 'Microsoft', 'xbox series': 'Microsoft',
        'nintendo': 'Nintendo', 'switch': 'Nintendo',
    }
    LAYOUT_MAP = {
        'full size': 'Fullsize', 'fullsize': 'Fullsize', 'full-size': 'Fullsize',
        '98%': 'Fullsize', '96%': 'Fullsize', '99 phím': 'Fullsize', '104 phím': 'Fullsize',
        '108 phím': 'Fullsize', '102 phím': 'Fullsize', '100 phím': 'Fullsize', '105 phím': 'Fullsize',
        'tkl': 'TKL', '87 phím': 'TKL', '86 phím': 'TKL', '84 phím': 'TKL',
        '75%': '75%', '80 phím': '75%', '75 phím': '75%',
        '65%': '65%', '68 phím': '65%',
        '60%': '60%', '61 phím': '60%',
    }
    COLOR_MAP = {
        'đen': 'Đen', 'black': 'Đen', 'graphite': 'Đen', 'obsidian': 'Đen', 'phantom black': 'Đen', 'carbon black': 'Đen',
        'trắng': 'Trắng', 'white': 'Trắng', 'snow': 'Trắng', 'glacier': 'Trắng', 'ivory': 'Trắng',
        'xám': 'Xám', 'gray': 'Xám', 'grey': 'Xám', 'silver': 'Xám', 'xám đen': 'Xám', 'xám bạc': 'Xám',
        'xanh dương': 'Xanh dương', 'blue': 'Xanh dương', 'navy': 'Xanh dương', 'xanh đậm': 'Xanh dương',
        'xanh lá': 'Xanh lá', 'green': 'Xanh lá',
        'hồng': 'Hồng', 'pink': 'Hồng', 'prunus lannesiana': 'Hồng',
        'tím': 'Tím', 'purple': 'Tím', 'violet': 'Tím',
        'đỏ': 'Đỏ', 'red': 'Đỏ',
        'vàng': 'Vàng', 'gold': 'Vàng', 'golden': 'Vàng',
        'cam': 'Cam', 'orange': 'Cam',
        'nâu': 'Nâu', 'brown': 'Nâu',
        'bạc': 'Bạc', 'silver': 'Bạc',
        'xanh': 'Xanh',
    }
    LAYOUT_TAG_KEYS = ('spec_layout', 'filter_layout', 'filter_kích thước', 'hl_size')
    CONNECTION_TAG_KEYS = ('spec_kết nối', 'filter_kết nối', 'hl_connect', 'filter_phương thức kết nối')
    SWITCH_TAG_KEYS = ('spec_switch', 'filter_switch')
    COLOR_TAG_KEYS = ('filter_màu sắc', 'hl_color', 'spec_màu sắc')
    MICROPHONE_CONNECTION_TAG_KEYS = ('spec_cổng kết nối', 'spec_kết nối', 'filter_kết nối', 'hl_connect')
    POLAR_PATTERN_TAG_KEYS = ('spec_hướng thu âm', 'filter_hướng thu âm', 'hl_pattern')
    FREQ_RESPONSE_TAG_KEYS = ('spec_dải tần đáp ứng', 'spec_dải tần', 'filter_dải tần')
    SENSITIVITY_TAG_KEYS = ('spec_độ nhạy', 'spec_sensitivity', 'filter_độ nhạy')
    SNR_TAG_KEYS = ('spec_snr', 'spec_tỷ số tín hiệu/nhiễu', 'filter_snr')
    STAND_TAG_KEYS = ('spec_phụ kiện kèm theo', 'filter_phụ kiện', 'hl_accessory')
    SWITCH_BRANDS = [
        'akko', 'nx', 'rog', 'cherry', 'gateron', 'kailh', 'outemu', 'reaper', 'nimbus', 'gl', 'magnetic',
        'red', 'blue', 'brown', 'black', 'linear', 'tactile', 'clicky',
    ]
    STOP_WORDS = {
        'cho', 'với', 'của', 'và', 'nhằm', 'đem', 'mang', 'lại', 'trong', 'được', 'để', 'cùng', 'có', 'tại',
        'nhà', 'máy', 'loại', 'từ', 'theo', 'sau', 'khi', 'mà', 'này', 'đó', 'vì', 'nên', 'cũng', 'đã', 'sẽ',
        'đang', 'còn', 'rất', 'các', 'một', 'những', 'mỗi', 'tất', 'cả', 'từng', 'mọi', 'sử', 'dụng', 'trang',
        'bị', 'sở', 'hữu', 'tích', 'hợp', 'hỗ', 'trợ', 'giúp', 'thích', 'phù', 'vào', 'ra', 'lên', 'xuống',
        'đi', 'đến', 'lại', 'với', 'của', 'cho', 'lại', 'vào', 'ra', 'lên', 'xuống', 'đi', 'đến',
    }

    def add_arguments(self, parser):
        parser.add_argument(
            '--file', '-f',
            type=str,
            default=str(self.DEFAULT_JSON),
            help='Path to JSON data file (default: products_data.json next to this command)',
        )
        parser.add_argument(
            '--source',
            type=str,
            default=None,
            choices=['gearvn-keyboards', 'gearvn-headsets', 'gearvn-microphones', 'ezpc-controllers'],
            help='Scrape products from GearVN instead of reading a JSON file.',
        )
        parser.add_argument(
            '--limit',
            type=int,
            default=30,
            help='Maximum number of products to import when using --source.',
        )
        parser.add_argument(
            '--dry-run',
            action='store_true',
            help='Validate and preview without writing to the database or downloading images.',
        )
        parser.add_argument(
            '--save',
            action='store_true',
            help='When using --source, also save the scraped JSON to a reference file.',
        )

    def _out(self, msg, style_func=None):
        """Safe write: encode non-ASCII chars for Windows cp1252 terminals."""
        if style_func:
            msg = style_func(msg)
        safe = msg.encode(sys.stdout.encoding or 'utf-8', errors='replace').decode(sys.stdout.encoding or 'utf-8', errors='replace')
        self.stdout.write(safe)

    def handle(self, *args, **options):
        from products.models import (
            AttributeGroup, AttributeValue, Brand, Category,
            Product, ProductAttribute, ProductImage,
        )
        from decimal import Decimal

        dry_run = options['dry_run']
        limit = options['limit']

        if options['source'] == 'gearvn-keyboards':
            products_data = self._scrape_gearvn_keyboards(limit=limit)
            json_path = Path('keyboards_data.json')
        elif options['source'] == 'gearvn-headsets':
            products_data = self._scrape_gearvn_headsets(limit=limit)
            json_path = Path('headsets_data.json')
        elif options['source'] == 'gearvn-microphones':
            products_data = self._scrape_gearvn_microphones(limit=limit)
            json_path = Path('microphones_data.json')
        elif options['source'] == 'ezpc-controllers':
            products_data = self._scrape_ezpc_controllers(limit=limit)
            json_path = Path('controllers_data.json')
        else:
            json_path = Path(options['file'])
            if not json_path.exists():
                self.stderr.write(self.style.ERROR(f'File not found: {json_path}'))
                return
            with open(json_path, encoding='utf-8') as f:
                products_data = json.load(f)

        if options['source'] and options['save']:
            with open(json_path, 'w', encoding='utf-8') as f:
                json.dump(products_data, f, ensure_ascii=False, indent=2)
            self._out(f'  Da luu JSON tham khảo: {json_path}', self.style.NOTICE)

        self._out(f'{"[DRY RUN] " if dry_run else ""}Importing {len(products_data)} products...', self.style.MIGRATE_HEADING)

        # Pre-load lookup tables once — no N+1
        category_map = {c.name.lower(): c for c in Category.objects.all()}
        brand_map    = {b.name.lower(): b for b in Brand.objects.all()}
        attr_group_map = {g.slug: g for g in AttributeGroup.objects.prefetch_related('values').all()}
        # attr_value_map: {group_slug: {value_lower: AttributeValue}}
        attr_value_map = {}
        for g_slug, group in attr_group_map.items():
            attr_value_map[g_slug] = {v.value.lower(): v for v in group.values.filter(is_active=True)}

        # Pre-load existing slugs to avoid DB-level duplicate-key failures on long handles
        slug_max_length = Product._meta.get_field('slug').max_length
        used_slugs = set(Product.objects.values_list('slug', flat=True))

        if not dry_run:
            self.IMAGE_DIR.mkdir(parents=True, exist_ok=True)

        created = skipped = failed = 0

        for idx, item in enumerate(products_data, start=1):
            name = (item.get('name') or '').strip()
            raw_slug = (item.get('slug') or slugify(name)).strip()

            if not name or not raw_slug:
                self._out(f'  [{idx}] Bo qua: thieu name/slug', self.style.WARNING)
                failed += 1
                continue

            slug = self._ensure_unique_slug(raw_slug, used_slugs, slug_max_length)
            used_slugs.add(slug)
            item['slug'] = slug

            # --- Skip duplicates ---
            if Product.objects.filter(slug=slug).exists() or Product.objects.filter(name=name).exists():
                self._out(f'  [{idx}] BO QUA (da ton tai): {name}')
                skipped += 1
                continue

            # --- Resolve category ---
            cat_name = (item.get('category') or '').strip().lower()
            category = category_map.get(cat_name)
            if category is None:
                self._out(f'  [{idx}] Bo qua: khong tim thay danh muc "{item.get("category")}" -- {name}', self.style.WARNING)
                failed += 1
                continue

            # --- Resolve brand (auto-create if missing) ---
            brand_name_raw = (item.get('brand') or '').strip()
            brand = brand_map.get(brand_name_raw.lower())
            if brand is None and brand_name_raw and not dry_run:
                brand, _ = Brand.objects.get_or_create(name=brand_name_raw)
                brand_map[brand_name_raw.lower()] = brand
                self._out(f'    Tao moi Brand: {brand_name_raw}', self.style.NOTICE)

            # --- Price ---
            try:
                price = Decimal(str(item['price']))
                discount_price = Decimal(str(item['discount_price'])) if item.get('discount_price') else None
            except Exception:
                self._out(f'  [{idx}] Bo qua: gia khong hop le -- {name}', self.style.WARNING)
                failed += 1
                continue

            if dry_run:
                brand_display = brand.name if brand else brand_name_raw or 'N/A'
                self._out(f'  [{idx}] [DRY RUN] Se tao: {name} | {price}d | {category.name} | {brand_display}')
                created += 1
                continue

            # --- Create product ---
            product = Product.objects.create(
                name=name,
                slug=slug,
                description=item.get('description', ''),
                product_information=item.get('product_information', ''),
                price=price,
                discount_price=discount_price,
                stock=int(item.get('stock', 0)),
                brand=brand,
                category=category,
                is_active=True,
            )

            # --- Attributes ---
            attrs_spec = item.get('attributes', {})
            attr_rows = []
            seen_value_ids = set()

            for group_slug, values_list in attrs_spec.items():
                group = attr_group_map.get(group_slug)
                if group is None:
                    self._out(f'    Canh bao: khong tim thay nhom thuoc tinh "{group_slug}" -- bo qua', self.style.WARNING)
                    continue

                group_values = attr_value_map.get(group_slug, {})

                for val_str in values_list:
                    val_lower = val_str.strip().lower()
                    attr_value = group_values.get(val_lower)

                    if attr_value is None:
                        # Auto-create new AttributeValue
                        normalized = val_str.strip()
                        attr_value = AttributeValue.objects.create(
                            group=group,
                            value=normalized,
                        )
                        # Update local cache
                        attr_value_map[group_slug][val_lower] = attr_value
                        self._out(f'    Tao moi AttributeValue: [{group.name}] {normalized}', self.style.NOTICE)

                    if attr_value.pk not in seen_value_ids:
                        seen_value_ids.add(attr_value.pk)
                        attr_rows.append(ProductAttribute(product=product, attribute_value=attr_value))

            if attr_rows:
                ProductAttribute.objects.bulk_create(attr_rows)

            # --- Images ---
            image_urls = item.get('image_urls', [])
            downloaded = 0
            for img_url in image_urls:
                filename = self._download_image(img_url, product.slug, downloaded)
                if filename:
                    rel_path = f'products/{filename}'
                    ProductImage.objects.create(product=product, image=rel_path)
                    downloaded += 1
                    time.sleep(0.3)  # polite delay

            self._out(f'  [{idx}] OK: {name} | {downloaded}/{len(image_urls)} anh', self.style.SUCCESS)
            created += 1

        # --- Summary ---
        self._out('')
        self._out('=== KET QUA ===', self.style.MIGRATE_HEADING)
        self._out(f'  Tao moi : {created}', self.style.SUCCESS)
        self._out(f'  Bo qua  : {skipped}', self.style.WARNING)
        if failed:
            self._out(f'  Loi     : {failed}', self.style.ERROR)

    # ------------------------------------------------------------------
    # GearVN scraping helpers
    # ------------------------------------------------------------------

    @staticmethod
    def _ensure_unique_slug(raw_slug, used_slugs, max_length=50):
        """Truncate and/or suffix a slug so it fits the DB field and stays unique."""
        base = slugify(raw_slug)[:max_length]
        candidate = base
        counter = 1
        while candidate in used_slugs:
            suffix = f'-{counter}'
            candidate = base[:max_length - len(suffix)] + suffix
            counter += 1
        return candidate

    def _scrape_gearvn_keyboards(self, limit=30):
        """Fetch keyboard products from GearVN and return a list of import dicts."""
        return self._scrape_gearvn_collection(
            self.SOURCE_URL, 'Bàn phím', limit,
            lambda p: self._transform_gearvn_product(p, 'Bàn phím', self._extract_keyboard_attrs)
        )

    def _scrape_gearvn_headsets(self, limit=30):
        """Fetch headset products from GearVN and return a list of import dicts."""
        return self._scrape_gearvn_collection(
            self.HEADSET_SOURCE_URL, 'Tai nghe gaming', limit,
            lambda p: self._transform_gearvn_product(p, 'Tai nghe', self._extract_headset_attrs)
        )

    def _scrape_gearvn_microphones(self, limit=30):
        """Fetch microphone products from GearVN and return a list of import dicts."""
        raw = self._scrape_gearvn_collection(
            self.MICROPHONE_SOURCE_URL, None, limit,
            lambda p: self._transform_gearvn_product(p, 'Microphone', self._extract_microphone_attrs)
        )
        # Exclude accessories (pop filters, stands, cables, generic accessories)
        exclude_keywords = {'màng lọc', 'pop filter', 'phụ kiện', 'giá đỡ', 'chân đế', 'cáp', 'cable', 'boom arm'}
        return [p for p in raw if not any(k in p['name'].lower() for k in exclude_keywords)]

    def _scrape_gearvn_collection(self, source_url, product_type, limit, transform_fn):
        """Fetch products from a GearVN collection JSON and transform them."""
        type_label = product_type if product_type else 'tat ca'
        self._out(f'Dang tai danh sach san pham tu GearVN (type={type_label})...', self.style.MIGRATE_HEADING)
        req = urllib.request.Request(source_url, headers={'User-Agent': self.USER_AGENT})
        with urllib.request.urlopen(req, timeout=30) as resp:
            data = json.loads(resp.read().decode('utf-8'))

        products = data.get('products', [])
        if product_type:
            filtered = [p for p in products if p.get('product_type') == product_type]
        else:
            filtered = products
        if len(filtered) < limit:
            self._out(f'  Canh bao: chi tim thay {len(filtered)} san pham (yeu cau {limit}).', self.style.WARNING)

        selected = filtered[:limit]
        result = []
        for idx, p in enumerate(selected, start=1):
            self._out(f'  [{idx}] Xu ly: {p["title"]}')
            result.append(transform_fn(p))
        return result

    def _transform_gearvn_product(self, product, category, attr_extractor):
        from decimal import Decimal

        title = product.get('title', '').strip()
        handle = product.get('handle', '').strip()
        slug = slugify(handle) or slugify(title)
        body_html = product.get('body_html', '')
        tags = product.get('tags', '') or ''
        vendor = (product.get('vendor') or '').strip()
        variant = (product.get('variants') or [{}])[0]
        price_str = variant.get('price') or '0'
        compare_str = variant.get('compare_at_price') or ''
        stock = int(variant.get('inventory_quantity', 0) or 0)

        sale = Decimal(price_str)
        compare = Decimal(compare_str) if compare_str else None
        # DB semantics: price = original/listed price, discount_price = current sale price
        if compare and compare > sale:
            price = str(compare)
            discount_price = str(sale)
        else:
            price = str(sale)
            discount_price = None

        image_urls = [img['src'] for img in product.get('images', [])[:3]]

        return {
            'name': title,
            'slug': slug,
            'description': self._extract_description(body_html),
            'product_information': f'Thương hiệu: {vendor}' if vendor else '',
            'price': price,
            'discount_price': discount_price,
            'stock': stock,
            'brand': vendor,
            'category': category,
            'image_urls': image_urls,
            'attributes': attr_extractor(title, body_html, tags),
        }

    @staticmethod
    def _extract_description(body_html):
        """Return the first h2 + first meaningful p from the GearVN body_html."""
        if not body_html:
            return ''
        h2_match = re.search(r'<h2[^>]*>.*?</h2>', body_html, flags=re.S | re.I)
        if not h2_match:
            return ''
        h2_html = h2_match.group(0)
        after = body_html[h2_match.end():]
        p_match = re.search(r'<p[^>]*>.*?</p>', after, flags=re.S | re.I)
        if not p_match:
            return h2_html
        p_html = p_match.group(0)
        p_text = re.sub(r'<[^>]+>', '', p_html).strip()
        if not p_text:
            after2 = after[p_match.end():]
            p_match2 = re.search(r'<p[^>]*>.*?</p>', after2, flags=re.S | re.I)
            if p_match2:
                p_html = p_match2.group(0)
        return h2_html + p_html

    def _extract_keyboard_attrs(self, title, body_html, tags):
        title_lower = title.lower()
        body_text = self._strip_html(body_html).lower()
        full_text = title_lower + ' ' + body_text
        tag_list = [t.strip() for t in (tags or '').split(',')]
        attrs = {}

        # Connection
        conn = []
        for tag in tag_list:
            if ':' in tag:
                key, val = tag.lower().split(':', 1)
                if key in self.CONNECTION_TAG_KEYS:
                    for v in val.split('/'):
                        m = self._map_connection(v)
                        if m and m not in conn:
                            conn.append(m)
        if not conn:
            if 'bluetooth' in full_text:
                conn.append('Bluetooth')
            if '2.4ghz' in full_text or ('wireless' in full_text and 'wireless' in title_lower) or 'không dây' in full_text:
                conn.append('2.4GHz Wireless')
            if 'usb' in full_text or 'type-c' in full_text or 'có dây' in full_text:
                conn.append('USB')
        attrs['ket-noi'] = conn

        # Layout
        layout = None
        for tag in tag_list:
            if ':' in tag:
                key, val = tag.lower().split(':', 1)
                if key in self.LAYOUT_TAG_KEYS:
                    mapped = self._map_layout(val)
                    if mapped:
                        layout = mapped
        if not layout:
            if 'fullsize' in full_text or 'full size' in full_text or '98%' in full_text or '96%' in full_text or '99 phím' in full_text or '108 phím' in full_text or '104 phím' in full_text or '102 phím' in full_text or '100 phím' in full_text or '105 phím' in full_text:
                layout = 'Fullsize'
            elif 'tkl' in full_text or '87 phím' in full_text or '86 phím' in full_text or '84 phím' in full_text:
                layout = 'TKL'
            elif '75%' in full_text or '75 phím' in full_text or '80 phím' in full_text:
                layout = '75%'
            elif '65%' in full_text or '68 phím' in full_text:
                layout = '65%'
            elif '60%' in full_text or '61 phím' in full_text:
                layout = '60%'
        if layout:
            attrs['layout'] = [layout]

        # Switch
        switch = None
        for tag in tag_list:
            if ':' in tag:
                key, val = tag.lower().split(':', 1)
                if key in self.SWITCH_TAG_KEYS:
                    switch = val.strip().title()
                    break
        if not switch:
            switch_patterns = [
                r'akko\s+v3\s+([^<>()/]{2,40})\s+switch',
                r'akko\s+([^<>()/]{2,50})\s+switch',
                r'cherry\s*mx\s+([^<>()/]{2,30})\s+switch',
                r'gateron\s+([^<>()/]{2,30})\s+switch',
                r'kailh\s+([^<>()/]{2,30})\s+switch',
                r'outemu\s+([^<>()/]{2,30})\s+switch',
                r'nx\s+([^<>()/]{2,30})\s+switch',
                r'reaper\s+switch',
                r'nimbus\s+v3\s+switch',
                r'star\s+vector\s+switch',
                r'aether\s+magnetic\s+switch',
                r'magnetic\s+switch',
                r'gl\s+low[\-\s]?profile\s+(tactile|clicky|linear)',
                r'(red|blue|brown|black|linear|tactile|clicky)\s+switch',
            ]
            for pat in switch_patterns:
                m = re.search(pat, title_lower, re.I)
                if m:
                    switch = m.group(0).strip().title()
                    break
        if not switch:
            if 'logitech g915' in title_lower:
                m = re.search(r'\b(tactile|clicky|linear)\b', title_lower, re.I)
                if m:
                    switch = f"GL Low-profile {m.group(1).capitalize()}"
        if not switch:
            for m in re.finditer(r'\bswitch\b', full_text, re.I):
                start = m.end()
                words = []
                for word in re.findall(r'\S+', full_text[start:]):
                    if not re.fullmatch(r'[a-zA-Z0-9]+', word):
                        break
                    words.append(word)
                    if len(words) >= 5:
                        break
                while words and words[-1].lower() in self.STOP_WORDS:
                    words.pop()
                if words:
                    candidate = ' '.join(words).lower()
                    if any(b in candidate for b in self.SWITCH_BRANDS):
                        switch = ' '.join(w.title() for w in words)
                        break
        if not switch:
            m = re.search(r'\bnx\s+(snow|storm)\b', full_text, re.I)
            if m:
                switch = f"NX {m.group(1).capitalize()} Switch"
        if not switch:
            if 'cơ học' in full_text or 'mechanical switch' in full_text or 'switch cơ' in full_text or 'bàn phím cơ' in title_lower:
                switch = 'Cơ học'
            elif 'giả cơ' in title_lower or 'membrane' in full_text:
                switch = 'Membrane'
        if switch:
            attrs['switch'] = [switch]

        # Color
        colors = []
        for tag in tag_list:
            if ':' in tag:
                key, val = tag.lower().split(':', 1)
                if key in self.COLOR_TAG_KEYS:
                    c = self._map_color(val)
                    if c and c not in colors:
                        colors.append(c)
        color_source = title_lower.split('/')[0]
        color_source = re.sub(r'\s+(red|blue|brown|black|linear|tactile|clicky)\s+switch', '', color_source, flags=re.I)
        for k, v in self.COLOR_MAP.items():
            if re.search(r'\b' + re.escape(k) + r'\b', color_source) and v not in colors:
                colors.append(v)
        for tag in tag_list:
            m = re.match(r'ref:([^@,\s]+)', tag, re.I)
            if m:
                ref = m.group(1).lower()
                for k, v in self.COLOR_MAP.items():
                    if k in ref and v not in colors:
                        colors.append(v)
        if colors:
            attrs['mau-sac'] = colors

        return attrs

    def _extract_headset_attrs(self, title, body_html, tags):
        """Extract headset-specific attributes from title, body, and tags."""
        title_lower = title.lower()
        body_text = self._strip_html(body_html).lower()
        full_text = title_lower + ' ' + body_text
        tag_list = [t.strip() for t in (tags or '').split(',')]
        attrs = {}

        # Connection
        conn = []
        for tag in tag_list:
            if ':' in tag:
                key, val = tag.lower().split(':', 1)
                if key in self.CONNECTION_TAG_KEYS:
                    for v in val.split('/'):
                        m = self._map_connection(v)
                        if m and m not in conn:
                            conn.append(m)
        if not conn:
            if 'bluetooth' in full_text:
                conn.append('Bluetooth')
            if '2.4ghz' in full_text or 'wireless' in full_text or 'không dây' in full_text:
                conn.append('2.4GHz Wireless')
            if '3.5mm' in full_text or '3.5 mm' in full_text or 'jack 3.5' in full_text:
                conn.append('3.5mm')
            if 'type-c' in full_text or 'usb-c' in full_text or 'usb type c' in full_text:
                conn.append('Type-C')
            elif 'usb' in full_text or 'có dây' in full_text:
                conn.append('USB')
        attrs['ket-noi'] = conn

        # Type (form factor)
        headset_types = []
        if 'in-ear' in full_text or 'in ear' in full_text or 'earbuds' in full_text:
            headset_types.append('In-ear')
        if 'on-ear' in full_text or 'on ear' in full_text:
            headset_types.append('On-ear')
        if 'over-ear' in full_text or 'over ear' in full_text or 'headset' in full_text:
            headset_types.append('Over-ear')
        if 'gaming' in full_text:
            headset_types.append('Gaming')
        if headset_types:
            attrs['loai-tai-nghe'] = headset_types

        # Microphone
        mic = None
        if any(k in full_text for k in ('không mic', 'không có mic', 'no mic', 'không micro')):
            mic = 'Không'
        elif any(k in full_text for k in ('có mic', 'micro', 'mic ', 'microphone', 'headset', 'gaming')):
            mic = 'Có'
        if mic:
            attrs['microphone'] = [mic]

        # Noise cancellation
        noise_cancelling = None
        if any(k in full_text for k in ('anc', 'active noise cancellation', 'noise cancelling', 'noise canceling', 'chống ồn chủ động')):
            noise_cancelling = 'Có'
        elif 'chống ồn' in full_text:
            noise_cancelling = 'Có'
        else:
            noise_cancelling = 'Không'
        attrs['chong-on'] = [noise_cancelling]

        # Color
        colors = []
        for tag in tag_list:
            if ':' in tag:
                key, val = tag.lower().split(':', 1)
                if key in self.COLOR_TAG_KEYS:
                    c = self._map_color(val)
                    if c and c not in colors:
                        colors.append(c)
        color_source = title_lower.split('/')[0]
        for k, v in self.COLOR_MAP.items():
            if re.search(r'\b' + re.escape(k) + r'\b', color_source) and v not in colors:
                colors.append(v)
        if colors:
            attrs['mau-sac'] = colors

        return attrs

    def _extract_microphone_attrs(self, title, body_html, tags):
        """Extract microphone-specific attributes from title, body, and tags."""
        title_lower = title.lower()
        body_text = self._strip_html(body_html).lower()
        full_text = title_lower + ' ' + body_text
        tag_list = [t.strip() for t in (tags or '').split(',')]
        attrs = {}

        # Connection (e.g. XLR; USB-C)
        conn = []
        for tag in tag_list:
            if ':' in tag:
                key, val = tag.lower().split(':', 1)
                if key in self.MICROPHONE_CONNECTION_TAG_KEYS:
                    for v in re.split(r'[;/,]', val):
                        m = self._map_microphone_connection(v)
                        if m and m not in conn:
                            conn.append(m)
        if not conn:
            for k, m in self.MICROPHONE_CONNECTION_MAP.items():
                if k in full_text and m not in conn:
                    conn.append(m)
        attrs['ket-noi'] = conn

        # Microphone type (condenser / dynamic / USB / streaming / gaming / podcast)
        mic_types = []
        for k, m in self.MICROPHONE_TYPE_MAP.items():
            if k in full_text and m not in mic_types:
                mic_types.append(m)
        if mic_types:
            attrs['loai-micro'] = mic_types

        # Polar pattern
        patterns = []
        for tag in tag_list:
            if ':' in tag:
                key, val = tag.lower().split(':', 1)
                if key in self.POLAR_PATTERN_TAG_KEYS:
                    for v in re.split(r'[;/,]', val):
                        p = self._map_polar_pattern(v)
                        if p and p not in patterns:
                            patterns.append(p)
        if not patterns:
            for k, m in self.POLAR_PATTERN_MAP.items():
                if k in full_text and m not in patterns:
                    patterns.append(m)
        if patterns:
            attrs['huong-thu-am'] = patterns

        # Frequency response
        freq = self._extract_tag_value(tag_list, self.FREQ_RESPONSE_TAG_KEYS)
        if not freq:
            m = re.search(r'(\d+\s*hz?\s*[-–]\s*\d+\s*khz?)', full_text, re.I)
            if m:
                freq = m.group(1).strip()
        if freq:
            attrs['dai-tan'] = [freq.strip()]

        # Sensitivity
        sens = self._extract_tag_value(tag_list, self.SENSITIVITY_TAG_KEYS)
        if not sens:
            m = re.search(r'(-?\d+\s*dB)', full_text, re.I)
            if m:
                sens = m.group(1).strip()
        if sens:
            attrs['do-nhay'] = [sens.strip()]

        # SNR
        snr = self._extract_tag_value(tag_list, self.SNR_TAG_KEYS)
        if not snr:
            m = re.search(r'(≥\s*\d+\s*dB|\d+\s*dB)', full_text, re.I)
            if m:
                snr = m.group(1).strip()
        if snr:
            attrs['snr'] = [snr.strip()]

        # Color
        colors = []
        for tag in tag_list:
            if ':' in tag:
                key, val = tag.lower().split(':', 1)
                if key in self.COLOR_TAG_KEYS:
                    c = self._map_color(val)
                    if c and c not in colors:
                        colors.append(c)
        color_source = title_lower.split('/')[0]
        for k, v in self.COLOR_MAP.items():
            if re.search(r'\b' + re.escape(k) + r'\b', color_source) and v not in colors:
                colors.append(v)
        if colors:
            attrs['mau-sac'] = colors

        # Stand / mount included
        stand = None
        for tag in tag_list:
            if ':' in tag:
                key, val = tag.lower().split(':', 1)
                if key in self.STAND_TAG_KEYS:
                    if any(k in val for k in ('chân đế', 'tripod', 'giá đỡ', 'stand', 'đế kèm', 'giá treo')):
                        stand = 'Có'
                        break
        if stand is None:
            if any(k in full_text for k in ('chân đế', 'tripod', 'giá đỡ', 'stand', 'đế kèm', 'giá treo', 'có chân')):
                stand = 'Có'
            else:
                stand = 'Không'
        attrs['chan-de'] = [stand]

        return attrs

    @staticmethod
    def _strip_html(html):
        return re.sub(r'<[^>]+>', ' ', html)

    @staticmethod
    def _extract_tag_value(tag_list, keys):
        for tag in tag_list:
            if ':' in tag:
                key, val = tag.lower().split(':', 1)
                if key in keys:
                    return val.strip()
        return None

    def _map_connection(self, val):
        v = val.lower().strip()
        for k, m in self.CONNECTION_MAP.items():
            if k in v:
                return m
        return None

    def _map_microphone_connection(self, val):
        v = val.lower().strip()
        for k, m in self.MICROPHONE_CONNECTION_MAP.items():
            if k in v:
                return m
        return None

    def _map_polar_pattern(self, val):
        v = val.lower().strip()
        for k, m in self.POLAR_PATTERN_MAP.items():
            if k in v:
                return m
        return None

    def _map_layout(self, val):
        return self.LAYOUT_MAP.get(val.lower().strip())

    def _map_color(self, val):
        v = val.lower().strip()
        for k, m in self.COLOR_MAP.items():
            if re.search(r'\b' + re.escape(k) + r'\b', v):
                return m
        return None

    # ------------------------------------------------------------------
    # EZPC scraping helpers
    # ------------------------------------------------------------------

    def _fetch_html(self, url):
        req = urllib.request.Request(url, headers={'User-Agent': self.USER_AGENT})
        with urllib.request.urlopen(req, timeout=30) as resp:
            return resp.read().decode('utf-8')

    def _absolute_url(self, path_or_url):
        if path_or_url.startswith('http://') or path_or_url.startswith('https://'):
            return path_or_url
        return self.EZPC_BASE_URL + path_or_url

    def _extract_ezpc_price(self, text):
        if not text:
            return None
        nums = re.findall(r'[\d.]+', text)
        for n in nums:
            clean = n.replace('.', '')
            if clean.isdigit():
                return clean
        return None

    def _scrape_ezpc_controllers(self, limit=20):
        """Fetch controller products from EZPC and return a list of import dicts."""
        self._out('Dang tai danh sach tay cam tu EZPC...', self.style.MIGRATE_HEADING)
        html = self._fetch_html(self.EZPC_CONTROLLER_SOURCE_URL)
        soup = BeautifulSoup(html, 'html.parser')
        containers = soup.select('.p_container')
        if len(containers) < limit:
            self._out(f'  Canh bao: chi tim thay {len(containers)} san pham (yeu cau {limit}).', self.style.WARNING)

        result = []
        for idx, c in enumerate(containers[:limit], start=1):
            name_a = c.select_one('a.p-name')
            if not name_a:
                continue
            name = name_a.get_text(strip=True)
            path = name_a.get('href', '').strip()
            if not path or not path.startswith('/'):
                continue
            self._out(f'  [{idx}] Xu ly: {name}')
            try:
                data = self._transform_ezpc_product(c, path)
                result.append(data)
            except Exception as e:
                self._out(f'    Loi xu ly {name}: {e}', self.style.WARNING)
        return result

    def _transform_ezpc_product(self, list_card, path):
        from decimal import Decimal
        name = list_card.select_one('a.p-name').get_text(strip=True)
        slug = slugify(name)[:50]

        # Parse price from list card (discount = main text, original = span)
        price = None
        discount_price = None
        price_div = list_card.select_one('div.p_price')
        if price_div:
            span = price_div.select_one('span')
            if span:
                discount_price = self._extract_ezpc_price(price_div.get_text(strip=True).replace(span.get_text(strip=True), ''))
                price = self._extract_ezpc_price(span.get_text(strip=True))
            else:
                price = self._extract_ezpc_price(price_div.get_text(strip=True))

        # Fallback image from list card
        list_img = list_card.select_one('a.p-img img')
        list_img_url = None
        if list_img:
            src = list_img.get('src') or list_img.get('data-src')
            if src:
                list_img_url = self._absolute_url(src)

        # Fetch detail page for description and full images
        detail_url = self._absolute_url(path)
        detail_html = self._fetch_html(detail_url)
        detail_soup = BeautifulSoup(detail_html, 'html.parser')
        description = self._extract_ezpc_description(detail_soup)
        image_urls = self._extract_ezpc_images(detail_soup) or ([list_img_url] if list_img_url else [])

        brand = self._extract_ezpc_brand(name)
        product_information = f'Thương hiệu: {brand}' if brand else ''

        # Build attribute text from product-specific sections only
        sections = [
            name,
            self._section_text(detail_soup, '.box_content'),
            self._section_text(detail_soup, '.prod-info'),
            self._section_text(detail_soup, '.dl-info'),
        ]
        full_text = ' '.join(sections)

        return {
            'name': name,
            'slug': slug,
            'description': description,
            'product_information': product_information,
            'price': price or '0',
            'discount_price': discount_price,
            'stock': 0,
            'brand': brand,
            'category': 'Tay cầm',
            'image_urls': image_urls[:3],
            'attributes': self._extract_ezpc_controller_attrs(name, full_text),
        }

    @staticmethod
    def _section_text(soup, selector):
        el = soup.select_one(selector)
        return el.get_text(separator=' ', strip=True) if el else ''

    def _extract_ezpc_description(self, soup):
        """Return first h2 + first meaningful p from the EZPC detail page."""
        box = soup.select_one('.box_content')
        if not box:
            return ''
        h2 = box.find('h2')
        h2_html = str(h2) if h2 and h2.get_text(strip=True) else ''
        p_html = ''
        for p in box.find_all('p'):
            if p.get_text(strip=True):
                p_html = str(p)
                break
        return h2_html + p_html

    def _extract_ezpc_images(self, soup):
        """Return up to 3 full-size product image URLs from the detail page."""
        urls = []
        seen = set()
        for img in soup.find_all('img'):
            src = img.get('src') or img.get('data-src') or img.get('data-original')
            if not src or '/media/product/' not in src:
                continue
            filename = src.split('/')[-1].split('?')[0]
            if re.match(r'^(120|75|250)_', filename):
                continue
            if not self._has_image_ext(src):
                continue
            url = self._absolute_url(src)
            if url not in seen:
                seen.add(url)
                urls.append(url)
        return urls

    @staticmethod
    def _has_image_ext(url):
        path = url.split('?')[0].lower()
        return any(path.endswith(ext) for ext in ('.jpg', '.jpeg', '.png', '.webp', '.gif'))

    def _extract_ezpc_brand(self, name):
        title = name.lower()
        for brand in self.CONTROLLER_BRAND_LIST:
            if brand.lower() in title:
                return brand
        for k, b in getattr(self, 'CONTROLLER_BRAND_MAP', {}).items():
            if k in title:
                return b
        # fallback: first non-generic token
        cleaned = re.sub(r'\[.*?\]', '', name)
        tokens = re.findall(r'[a-zA-Z0-9\u00C0-\u1FFF]+', cleaned.lower())
        skip = {'tay', 'cầm', 'cam', 'không', 'dây', 'có', 'chơi', 'game', 'ps4', 'ps5', 'xbox', 'switch', 'android', 'ios', 'pc', 'chính', 'hãng', 'màu', 'cũ', 'hàng', 'bóc', 'máy', 'bh', 'tháng', 'mới', 'cũ', 'wireless', 'controller', 'gamepad', 'dualshock'}
        for t in tokens:
            if t not in skip and len(t) > 1:
                return t.capitalize()
        return None

    def _extract_ezpc_controller_attrs(self, name, full_text):
        text = (name + ' ' + full_text).lower()
        title = name.lower()
        attrs = {}

        # Connection (use word boundaries to avoid false matches)
        conn = []
        connection_keywords = [
            ('usb', 'USB'), ('type-c', 'Type-C'), ('bluetooth', 'Bluetooth'),
            ('wireless', 'Wireless'), ('không dây', 'Wireless'), ('2.4g', '2.4GHz'),
        ]
        for k, m in connection_keywords:
            if re.search(r'\b' + re.escape(k) + r'\b', text) and m not in conn:
                conn.append(m)
        # Fallback for console controllers that are typically wireless
        if not conn and re.search(r'\b(ps4|dualshock|xbox one|xbox series|xbox)\b', text):
            conn.append('Wireless')
        attrs['ket-noi'] = conn

        # Compatibility
        compat = []
        for k, m in self.CONTROLLER_COMPATIBILITY_MAP.items():
            if re.search(r'\b' + re.escape(k) + r'\b', text) and m not in compat:
                compat.append(m)
        attrs['tuong-thich'] = compat

        # Controller type (prefer title only, default to Gamepad)
        types = []
        for k, m in self.CONTROLLER_TYPE_MAP.items():
            if re.search(r'\b' + re.escape(k) + r'\b', title) and m not in types:
                types.append(m)
        if not types:
            types.append('Gamepad')
        attrs['loai-tay-cam'] = types

        # Vibration / Haptic feedback
        if any(re.search(r'\b' + re.escape(k) + r'\b', text) for k in ('rung', 'vibration', 'haptic')):
            attrs['rung'] = ['Có']
        else:
            attrs['rung'] = ['Không']

        # Power source
        if any(k in text for k in ('pin aa', 'pin tiểu', 'aa battery')):
            attrs['pin'] = ['Pin AA']
        elif any(k in text for k in ('pin sạc', 'pin lithium', 'pin lipo', 'battery')):
            attrs['pin'] = ['Pin sạc']
        elif re.search(r'\bcó dây\b', text) or (re.search(r'\busb\b', text) and not any(re.search(r'\b' + re.escape(k) + r'\b', text) for k in ('wireless', 'bluetooth', 'không dây', '2.4g'))):
            attrs['pin'] = ['Có dây']
        elif any(re.search(r'\b' + re.escape(k) + r'\b', text) for k in ('wireless', 'bluetooth', 'không dây', '2.4g')):
            attrs['pin'] = ['Pin sạc']
        else:
            attrs['pin'] = ['Pin sạc']

        # Color
        colors = []
        color_source = title.split('/')[0]
        for k, v in self.COLOR_MAP.items():
            if re.search(r'\b' + re.escape(k) + r'\b', color_source) and v not in colors:
                colors.append(v)
        if colors:
            attrs['mau-sac'] = colors

        return attrs

    # ------------------------------------------------------------------

    def _download_image(self, url: str, product_slug: str, index: int) -> str | None:
        """Download an image URL to IMAGE_DIR. Returns filename or None on failure."""
        ext = self._get_ext(url)
        filename = f'{product_slug}_{index + 1}{ext}'
        dest = self.IMAGE_DIR / filename

        if dest.exists():
            return filename

        try:
            req = urllib.request.Request(url, headers={'User-Agent': self.USER_AGENT})
            with urllib.request.urlopen(req, timeout=15) as resp:
                data = resp.read()
            with open(dest, 'wb') as f:
                f.write(data)
            return filename
        except urllib.error.HTTPError as e:
            self._out(f'    Anh HTTP {e.code}: {url}', self.style.WARNING)
        except urllib.error.URLError as e:
            self._out(f'    Anh loi URL: {e.reason} -- {url}', self.style.WARNING)
        except Exception as e:
            self._out(f'    Anh loi: {e} -- {url}', self.style.WARNING)
        return None

    @staticmethod
    def _get_ext(url: str) -> str:
        path = url.split('?')[0].lower()
        for ext in ('.jpg', '.jpeg', '.png', '.webp', '.gif'):
            if path.endswith(ext):
                return ext
        return '.jpg'
