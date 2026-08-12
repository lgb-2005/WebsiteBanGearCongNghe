import json
import re
import time
from collections import defaultdict
from typing import List, Dict, Tuple, Optional, Set

import requests
from bs4 import BeautifulSoup
from django.core.management.base import BaseCommand
from django.db import transaction
from django.utils.text import slugify

from products.models import Product, AttributeGroup, AttributeValue, ProductAttribute, Category


CANONICAL_LABELS = {
    'mau-sac': ['Màu sắc', 'màu sắc', 'màu', 'color', 'colour'],
    'ket-noi': ['Kết nối', 'connection', 'connectivity', 'connect', 'kiểu kết nối', 'phương thức kết nối', 'cổng kết nối', 'kết nối không dây', 'cổng giao tiếp'],
    'dpi': ['DPI', 'độ phân giải', 'resolution', 'sensor resolution'],
    'polling-rate': ['Polling Rate', 'polling', 'tốc độ báo cáo', 'report rate', 'usb report rate', 'tốc độ phản hồi'],
    'form-chuot': ['Form chuột', 'kiểu dáng', 'thiết kế chuột', 'shape', 'form factor', 'ergonomic', 'đối xứng'],
    'cam-bien': ['Cảm biến', 'sensor', 'sensor type', 'loại cảm biến', 'optical sensor'],
    'trong-luong': ['Trọng lượng', 'weight', 'trọng lượng sản phẩm'],
    'kich-thuoc': ['Kích thước', 'kích thước sản phẩm', 'dimensions', 'product dimensions', 'kích cỡ'],
    'so-nut': ['Số nút', 'number of buttons', 'buttons', 'số lượng nút', 'nút bấm'],
    'layout': ['Layout', 'kích thước/layout', 'size', 'form factor', 'số lượng phím'],
    'switch': ['Switch', 'kiểu switch', 'loại switch', 'switch type', 'key switch'],
    'keycap': ['Keycap', 'chất liệu keycap', 'keycap material'],
    'den-led': ['Đèn LED', 'led', 'rgb', 'backlight', 'lighting'],
    'loai-tai-nghe': ['Loại tai nghe', 'kiểu tai nghe', 'headphone type', 'earcup style', 'over-ear', 'on-ear', 'in-ear'],
    'microphone': ['Microphone', 'micro', 'mic', 'tích hợp micro', 'có micro'],
    'chong-on': ['Chống ồn', 'noise cancelling', 'noise canceling', 'active noise cancellation', 'anc', 'tính năng chống ồn'],
    'dai-tan': ['Dải tần đáp ứng', 'frequency response', 'tần số phản hồi', 'frequency range', 'dải tần'],
    'tro-khang': ['Trở kháng', 'impedance', 'trở kháng'],
    'do-nhay': ['Độ nhạy', 'sensitivity', 'độ nhạy mic', 'microphone sensitivity'],
    'snr': ['SNR', 'signal-to-noise ratio', 'tỷ số tín hiệu'],
    'huong-thu-am': ['Hướng thu âm', 'polar pattern', 'polar patterns', 'hướng thu', 'pickup pattern', 'pattern'],
    'loai-micro': ['Loại microphone', 'loại micro', 'microphone type', 'kiểu micro', 'condenser', 'dynamic'],
    'chan-de': ['Chân đế kèm theo', 'chân đế', 'stand', 'giá đỡ', 'tripod'],
    'thoi-luong-pin': ['Thời lượng pin', 'battery life', 'thời gian sử dụng pin', 'usage time'],
    'thoi-gian-bao-hanh': ['Bảo hành', 'warranty', 'thời gian bảo hành'],
    'tuong-thich': ['Tương thích', 'compatibility', 'tương thích với', 'hệ điều hành tương thích', 'hệ điều hành', 'os support', 'tương thích'],
    'loai-tay-cam': ['Loại tay cầm', 'controller type', 'kiểu tay cầm', 'type'],
    'rung': ['Rung / Haptic feedback', 'rung', 'vibration', 'haptic', 'force feedback'],
    'pin': ['Pin / Nguồn', 'pin', 'nguồn', 'power source', 'battery'],
}


CATEGORY_LABEL_PRIORITY = {
    'Chuột': ['kich-thuoc', 'trong-luong', 'form-chuot', 'cam-bien', 'dpi', 'polling-rate', 'ket-noi', 'so-nut', 'mau-sac'],
    'Bàn phím': ['layout', 'switch', 'keycap', 'den-led', 'ket-noi', 'trong-luong', 'kich-thuoc', 'mau-sac'],
    'Tai nghe': ['loai-tai-nghe', 'microphone', 'chong-on', 'dai-tan', 'tro-khang', 'ket-noi', 'trong-luong', 'thoi-luong-pin', 'mau-sac'],
    'Microphone': ['loai-micro', 'huong-thu-am', 'dai-tan', 'do-nhay', 'snr', 'tro-khang', 'ket-noi', 'chan-de', 'mau-sac'],
    'Tay cầm': ['loai-tay-cam', 'tuong-thich', 'ket-noi', 'rung', 'pin', 'trong-luong', 'kich-thuoc', 'mau-sac'],
}


CATEGORY_GROUPS = {
    'Chuột': ['mau-sac', 'ket-noi', 'dpi', 'polling-rate', 'form-chuot', 'cam-bien', 'trong-luong', 'kich-thuoc', 'so-nut'],
    'Bàn phím': ['mau-sac', 'ket-noi', 'layout', 'switch', 'keycap', 'den-led', 'trong-luong', 'kich-thuoc'],
    'Tai nghe': ['mau-sac', 'ket-noi', 'loai-tai-nghe', 'microphone', 'chong-on', 'dai-tan', 'tro-khang', 'trong-luong', 'thoi-luong-pin'],
    'Microphone': ['mau-sac', 'ket-noi', 'loai-micro', 'huong-thu-am', 'dai-tan', 'do-nhay', 'snr', 'chan-de', 'tro-khang'],
    'Tay cầm': ['mau-sac', 'ket-noi', 'tuong-thich', 'loai-tay-cam', 'rung', 'pin', 'trong-luong', 'kich-thuoc'],
}


CATEGORY_PRIORITIES = {
    'Chuột': ['ket-noi', 'dpi', 'polling-rate', 'cam-bien', 'trong-luong', 'kich-thuoc', 'so-nut', 'form-chuot', 'mau-sac'],
    'Bàn phím': ['ket-noi', 'layout', 'switch', 'keycap', 'den-led', 'trong-luong', 'kich-thuoc', 'mau-sac'],
    'Tai nghe': ['ket-noi', 'loai-tai-nghe', 'microphone', 'chong-on', 'dai-tan', 'tro-khang', 'trong-luong', 'thoi-luong-pin', 'mau-sac'],
    'Microphone': ['ket-noi', 'loai-micro', 'huong-thu-am', 'dai-tan', 'do-nhay', 'snr', 'tro-khang', 'chan-de', 'mau-sac'],
    'Tay cầm': ['ket-noi', 'tuong-thich', 'loai-tay-cam', 'rung', 'pin', 'trong-luong', 'kich-thuoc', 'mau-sac'],
}


SOURCE_DOMAINS = {
    'logitech': ['logitech.com', 'logitechg.com', 'support.logi.com'],
    'razer': ['razer.com', 'mysupport.razer.com'],
    'asus': ['asus.com', 'rog.asus.com'],
    'hyperx': ['hyperx.com', 'hp.com'],
    'akko': ['akkogear.com'],
    'aula': ['aulacorp.com'],
    'rapoo': ['rapoo.com'],
    'msi': ['msi.com'],
    'acer': ['acer.com', 'predator.acer.com'],
    'sony': ['sony.com', 'playstation.com'],
    'nzxt': ['nzxt.com'],
    'elgato': ['elgato.com'],
    'dareu': ['dareu.com'],
    'edra': ['edra.com'],
    'keychron': ['keychron.com'],
    'flydigi': ['flydigi.com'],
    'aolion': ['aolion.com'],
    'bigbigwon': ['bigbigwon.com'],
    'easysmx': ['easysmx.com'],
}


TRUSTED_RETAILERS = ['gearvn.com', 'phongvu.vn', 'memoryzone.com.vn', 'anphatpc.com.vn', 'hanoicomputer.vn', 'tnc.com.vn']


class Command(BaseCommand):
    help = 'Enrich and normalize product attributes from official/retailer sources.'

    def add_arguments(self, parser):
        parser.add_argument('--dry-run', action='store_true', help='Do not write to DB')
        parser.add_argument('--limit', type=int, default=0, help='Limit number of products')
        parser.add_argument('--category', type=str, default='', help='Filter by category name')
        parser.add_argument('--url-cache', type=str, default='', help='JSON file mapping product_id to source URL')
        parser.add_argument('--spec-cache', type=str, default='', help='JSON file mapping product_id to list of text chunks')
        parser.add_argument('--skip-web', action='store_true', help='Skip web enrichment, only normalize existing data')
        parser.add_argument('--delay', type=float, default=1.5, help='Delay between web requests in seconds')
        parser.add_argument('--output-report', type=str, default='enrich_report.json', help='Report file path')

    def handle(self, *args, **options):
        self.dry_run = options['dry_run']
        self.delay = options['delay']
        self.skip_web = options['skip_web']
        self.report_path = options['output_report']
        self.stats = defaultdict(int)
        self.product_logs = []
        self.session_cache = {}
        self.session = requests.Session()
        self.session.headers.update({
            'User-Agent': 'Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/125.0.0.0 Safari/537.36',
            'Accept-Language': 'vi-VN,vi;q=0.9,en;q=0.8',
        })

        self.url_cache = self._load_url_cache(options['url_cache'])
        self.spec_cache = self._load_spec_cache(options['spec_cache'])
        self.group_cache = {}
        self.value_cache = {}

        qs = Product.objects.select_related('brand', 'category').prefetch_related('attributes__attribute_value__group')
        if options['category']:
            qs = qs.filter(category__name__iexact=options['category'])
        if options['limit']:
            qs = qs[:options['limit']]
        products = list(qs)

        self.stdout.write(f'Starting enrichment for {len(products)} products...')
        for product in products:
            self._enrich_product(product)
            time.sleep(self.delay)

        self._write_report()
        self._print_summary()

    def _load_url_cache(self, path: str) -> Dict[int, str]:
        if not path:
            return {}
        try:
            with open(path, 'r', encoding='utf-8') as f:
                data = json.load(f)
            return {int(k): v for k, v in data.items()}
        except Exception as e:
            self.stdout.write(self.style.WARNING(f'Could not load URL cache: {e}'))
            return {}

    def _load_spec_cache(self, path: str) -> Dict[int, List[str]]:
        if not path:
            return {}
        try:
            with open(path, 'r', encoding='utf-8') as f:
                data = json.load(f)
            return {int(k): v if isinstance(v, list) else [v] for k, v in data.items()}
        except Exception as e:
            self.stdout.write(self.style.WARNING(f'Could not load spec cache: {e}'))
            return {}

    def _enrich_product(self, product: Product):
        log = {
            'id': product.id,
            'name': product.name,
            'brand': product.brand.name if product.brand else None,
            'category': product.category.name,
            'actions': [],
            'source_url': None,
            'source_type': None,
        }

        existing_specs = self._parse_product_information(product.product_information or '')
        name_hints = self._extract_name_hints(product.name, product.category.name)
        web_specs = {}

        if not self.skip_web and self._is_insufficient(existing_specs, product.category.name):
            # Prefer spec cache (text snippets)
            if product.id in self.spec_cache:
                chunks = self.spec_cache[product.id]
                web_specs = self._extract_specs_from_text('\n'.join(chunks), product.category.name)
                log['source_url'] = 'spec_cache'
                log['source_type'] = 'spec_cache'
                if web_specs:
                    self.stats['spec_cache_found'] += 1
                else:
                    self.stats['spec_cache_empty'] += 1
            else:
                url = self._resolve_source(product)
                if url:
                    log['source_url'] = url
                    if any(d in url for d in self._brand_domains(product.brand)):
                        log['source_type'] = 'official'
                    elif any(d in url for d in TRUSTED_RETAILERS):
                        log['source_type'] = 'retailer'
                    else:
                        log['source_type'] = 'other'
                    web_specs = self._extract_specs(url, product.category.name)
                    if web_specs:
                        self.stats['web_specs_found'] += 1
                    else:
                        self.stats['web_specs_empty'] += 1
                else:
                    self.stats['no_source'] += 1
                    web_specs = {}

        merged = self._merge_specs(existing_specs, web_specs, product.category.name, log)
        normalized, meta = self._normalize_specs(merged, product.category.name)
        for group_slug, values in name_hints.items():
            if group_slug not in normalized:
                normalized[group_slug] = values
            else:
                for v in values:
                    if v not in normalized[group_slug]:
                        normalized[group_slug].append(v)

        if not normalized and not web_specs:
            # keep original if nothing to enrich
            log['actions'].append('no_spec_data')
            self.stats['no_spec_data'] += 1
            if not self.dry_run:
                self._sync_attributes(product, normalized, log)
            return

        new_pi = self._format_product_information(normalized, meta, product.category.name)
        if self._should_update_pi(product.product_information or '', new_pi):
            log['actions'].append(f'update product_information')
            if not self.dry_run:
                product.product_information = new_pi
                product.save(update_fields=['product_information'])
            self.stats['pi_updated'] += 1
        else:
            self.stats['pi_unchanged'] += 1

        if not self.dry_run:
            self._sync_attributes(product, normalized, log)
        else:
            # compute what would change
            current = {f"{a.attribute_value.group.slug}:{a.attribute_value.slug}" for a in product.attributes.all()}
            target = self._target_attribute_set(normalized, product.category.name)
            if current != target:
                log['actions'].append(f'would sync attributes: {len(target)} values')
            else:
                log['actions'].append('attributes unchanged')

        if log['actions']:
            self.stats['updated'] += 1
        else:
            self.stats['unchanged'] += 1
        self.product_logs.append(log)

    def _is_insufficient(self, specs: Dict[str, List[str]], category: str) -> bool:
        if not specs:
            return True
        # If only brand/warranty/model lines, consider insufficient
        non_meta = [k for k in specs if k not in ['Thương hiệu', 'Bảo hành', 'Model', 'Dòng sản phẩm']]
        if not non_meta:
            return True
        expected = CATEGORY_PRIORITIES.get(category, [])
        found = sum(1 for k in expected if any(self._label_to_slug(k) in self._label_to_slug(label) for label in specs))
        return found < max(2, len(expected) // 2)

    def _parse_product_information(self, text: str) -> Dict[str, List[str]]:
        specs = defaultdict(list)
        for raw in text.splitlines():
            line = raw.strip()
            if not line or ':' not in line:
                continue
            label, value = [p.strip() for p in line.split(':', 1)]
            if not label or not value:
                continue
            for v in self._split_values(value):
                if v:
                    specs[label].append(v)
        return dict(specs)

    def _split_values(self, value: str) -> List[str]:
        # split by common delimiters
        parts = re.split(r'[,;/|&]|\+|\bvà\b', value, flags=re.IGNORECASE)
        return [p.strip() for p in parts if p.strip()]

    def _resolve_source(self, product: Product) -> Optional[str]:
        if product.id in self.url_cache:
            return self.url_cache[product.id]

        brand = (product.brand.name if product.brand else '').lower()
        name = product.name
        # Remove category prefix and color suffix for query
        query_core = self._clean_name_for_query(name)
        queries = []
        # Official site query
        domains = self._brand_domains(product.brand)
        if domains:
            queries.append(f'{query_core} site:{domains[0]}')
        # Retailer fallback
        for retailer in ['phongvu.vn', 'gearvn.com']:
            queries.append(f'{query_core} site:{retailer}')

        for query in queries:
            if query in self.session_cache:
                return self.session_cache[query]
            # We can't call search engine reliably from script; placeholder for URL cache usage
            time.sleep(0.2)

        return None

    def _brand_domains(self, brand) -> List[str]:
        if not brand:
            return []
        b = brand.name.lower().replace(' ', '')
        return SOURCE_DOMAINS.get(b, [])

    def _clean_name_for_query(self, name: str) -> str:
        # remove category words and color suffixes
        name = re.sub(r'^(Chuột|Bàn phím|Tai nghe|Microphone|Tay cầm|Chuột gaming|Chuột không dây|Bàn phím không dây|Tai nghe không dây|Micro|Mic|cơ|gaming|có dây|không dây)\s+', '', name, flags=re.IGNORECASE)
        name = re.sub(r'\s+(Black|White|Đen|Trắng|Xám|Hồng|Xanh|Xanh lá|Xanh dương|Cam|Đỏ|Tím|Vàng|Camo|Alpine|Green|Blue|Purple|Red|Gray|Grey|Silver|Gold|Pink|Quartz|Mercury|Snow|Storm|Miku|Black&Gold|Black&Gray|Gradient)(\s+.*)?$', '', name, flags=re.IGNORECASE)
        return name.strip()

    def _extract_specs_from_text(self, text: str, category: str) -> Dict[str, List[str]]:
        specs = defaultdict(list)
        lines = text.splitlines()
        # Markdown tables: | label | value |
        for line in lines:
            line = line.strip()
            if line.startswith('|') and line.endswith('|') and line.count('|') >= 3:
                cells = [c.strip() for c in line.split('|')[1:-1]]
                if len(cells) >= 2 and cells[0] and cells[1]:
                    label, value = cells[0], cells[1]
                    # skip separator rows
                    if set(value) <= {'-', ':'} or set(label) <= {'-', ':'}:
                        continue
                    specs.setdefault(label, []).extend(self._split_values(value))
        # Header-value pairs: ## Label\nValue or - Label: Value
        current_label = None
        for line in lines:
            line = line.strip()
            if line.startswith('##') or line.startswith('**') or (line and line[0].isalpha() and line.endswith(':')):
                current_label = re.sub(r'^#+\s*', '', line).strip(': *')
                continue
            if line.startswith('-') and ':' in line:
                part = line[1:].strip()
                if ':' in part:
                    label, value = part.split(':', 1)
                    specs.setdefault(label.strip(), []).extend(self._split_values(value.strip()))
                continue
            if current_label and line and not line.startswith('#') and not line.startswith('|') and not line.startswith('-'):
                specs.setdefault(current_label, []).extend(self._split_values(line))
                current_label = None
        return dict(specs)

    def _extract_specs(self, url: str, category: str) -> Dict[str, List[str]]:
        try:
            r = self.session.get(url, timeout=30)
            r.raise_for_status()
        except Exception as e:
            self.stdout.write(self.style.WARNING(f'Fetch failed: {url} -> {e}'))
            return {}

        soup = BeautifulSoup(r.text, 'html.parser')
        specs = {}

        # Generic table extraction
        for table in soup.find_all('table'):
            for row in table.find_all('tr'):
                cells = row.find_all(['td', 'th'])
                if len(cells) >= 2:
                    label = cells[0].get_text(strip=True)
                    value = cells[1].get_text(strip=True)
                    if label and value:
                        specs.setdefault(label, []).extend(self._split_values(value))

        # Generic dl extraction
        for dl in soup.find_all('dl'):
            dts = dl.find_all('dt')
            dds = dl.find_all('dd')
            for dt, dd in zip(dts, dds):
                label = dt.get_text(strip=True)
                value = dd.get_text(strip=True)
                if label and value:
                    specs.setdefault(label, []).extend(self._split_values(value))

        # Generic div/section pairs by class
        for selector in ['div.spec-item', 'div.product-spec', 'div.tech-spec', 'div.specification', 'div.spec']:
            for el in soup.select(selector):
                label = el.find(class_=re.compile('label|title|name', re.I))
                value = el.find(class_=re.compile('value|text|data', re.I))
                if label and value:
                    specs.setdefault(label.get_text(strip=True), []).extend(self._split_values(value.get_text(strip=True)))

        return specs

    def _extract_name_hints(self, name: str, category: str) -> Dict[str, List[str]]:
        hints = defaultdict(list)
        lower = name.lower()
        # Connection hints (only from explicit keywords in name)
        if 'bluetooth' in lower:
            hints['ket-noi'].append('Bluetooth')
        if any(k in lower for k in ['lightspeed', 'wireless', 'không dây', '2.4g', '2.4ghz']):
            if '2.4GHz Wireless' not in hints['ket-noi']:
                hints['ket-noi'].append('2.4GHz Wireless')
        if any(k in lower for k in ['có dây', 'wired', 'usb']):
            if 'USB' not in hints['ket-noi']:
                hints['ket-noi'].append('USB')
        if 'type-c' in lower or 'type c' in lower:
            if 'Type-C' not in hints['ket-noi']:
                hints['ket-noi'].append('Type-C')
        # Polling rate hint
        if '8k' in lower or '8000hz' in lower:
            if '8000 Hz' not in hints['polling-rate']:
                hints['polling-rate'].append('8000 Hz')
        # Layout hints for keyboards
        if category == 'Bàn phím':
            if '98' in name:
                if '96%' not in hints['layout']:
                    hints['layout'].append('96%')
            if 'tkl' in lower:
                if 'TKL' not in hints['layout']:
                    hints['layout'].append('TKL')
            if '75' in name:
                if '75%' not in hints['layout']:
                    hints['layout'].append('75%')
            if '60' in name:
                if '60%' not in hints['layout']:
                    hints['layout'].append('60%')
            if '65' in name:
                if '65%' not in hints['layout']:
                    hints['layout'].append('65%')
        # Headset type hint
        if category == 'Tai nghe':
            if 'earbuds' in lower or 'in-ear' in lower:
                if 'In-ear' not in hints['loai-tai-nghe']:
                    hints['loai-tai-nghe'].append('In-ear')
            elif 'over-ear' in lower or 'over ear' in lower:
                if 'Over-ear' not in hints['loai-tai-nghe']:
                    hints['loai-tai-nghe'].append('Over-ear')
        # Microphone hint
        if category == 'Microphone':
            if 'usb' in lower:
                if 'USB' not in hints['ket-noi']:
                    hints['ket-noi'].append('USB')
        return dict(hints)

    def _merge_specs(self, existing: Dict[str, List[str]], web: Dict[str, List[str]], category: str, log: Dict) -> Dict[str, List[str]]:
        merged = defaultdict(set)
        for label, values in existing.items():
            for v in values:
                merged[label].add(v)
        for label, values in web.items():
            for v in values:
                merged[label].add(v)
        return {k: list(v) for k, v in merged.items()}

    def _normalize_specs(self, specs: Dict[str, List[str]], category: str) -> Tuple[Dict[str, List[str]], Dict[str, List[str]]]:
        normalized = defaultdict(list)
        meta = defaultdict(list)
        for label, values in specs.items():
            group_slug = self._map_label_to_group(label, category)
            if not group_slug:
                # keep as meta if not a recognized spec label
                meta[label] = values
                continue
            for v in values:
                nv = self._normalize_value(v, group_slug)
                if nv and nv not in normalized[group_slug]:
                    normalized[group_slug].append(nv)
        return dict(normalized), dict(meta)

    def _map_label_to_group(self, label: str, category: str) -> Optional[str]:
        lower = label.lower()
        # Check category-relevant groups first (by priority order)
        priority = CATEGORY_LABEL_PRIORITY.get(category, [])
        for group_slug in priority:
            for alias in CANONICAL_LABELS.get(group_slug, []):
                if alias.lower() in lower:
                    return group_slug
        # Fallback to all groups
        for group_slug, aliases in CANONICAL_LABELS.items():
            if group_slug in priority:
                continue
            for alias in aliases:
                if alias.lower() in lower:
                    return group_slug
        return None

    def _normalize_value(self, value: str, group_slug: str) -> Optional[str]:
        value = value.strip()
        if not value or value in ['-', 'N/A', 'n/a', 'Không có', 'không']:
            return None

        if group_slug == 'ket-noi':
            return self._normalize_connection(value)
        if group_slug == 'mau-sac':
            return self._normalize_color(value)
        if group_slug == 'dpi':
            return self._normalize_dpi(value)
        if group_slug == 'polling-rate':
            return self._normalize_polling_rate(value)
        if group_slug in ['trong-luong', 'kich-thuoc']:
            return self._normalize_dimension_weight(value, group_slug)
        if group_slug == 'form-chuot':
            return self._normalize_form(value)
        if group_slug == 'layout':
            return self._normalize_layout(value)
        if group_slug == 'loai-tai-nghe':
            return self._normalize_headphone_type(value)
        if group_slug in ['microphone', 'chong-on', 'rung']:
            return self._normalize_boolean(value)
        return value

    def _normalize_connection(self, value: str) -> Optional[str]:
        lower = value.lower()
        if any(k in lower for k in ['bluetooth', 'bluetooth®']):
            return 'Bluetooth'
        if any(k in lower for k in ['2.4g', '2.4ghz', 'lightspeed', 'wireless', 'không dây', 'rf', 'swiftr', 'nealink']):
            return '2.4GHz Wireless'
        if 'type-c' in lower or 'usb-c' in lower or 'usb type-c' in lower:
            return 'Type-C'
        if 'usb' in lower or 'có dây' in lower or 'wired' in lower:
            return 'USB'
        if '3.5mm' in lower or '3.5 mm' in lower:
            return '3.5mm'
        if 'xlr' in lower:
            return 'XLR'
        return None

    def _normalize_color(self, value: str) -> Optional[str]:
        color_map = {
            'black': 'Đen', 'đen': 'Đen', 'dark': 'Đen',
            'white': 'Trắng', 'trắng': 'Trắng', 'snow': 'Trắng',
            'gray': 'Xám', 'grey': 'Xám', 'xám': 'Xám',
            'red': 'Đỏ', 'đỏ': 'Đỏ',
            'blue': 'Xanh dương', 'xanh dương': 'Xanh dương', 'xanh': 'Xanh dương',
            'green': 'Xanh lá', 'xanh lá': 'Xanh lá', 'alpine': 'Xanh lá',
            'pink': 'Hồng', 'hồng': 'Hồng', 'quartz': 'Hồng', 'magenta': 'Hồng',
            'purple': 'Tím', 'tím': 'Tím',
            'yellow': 'Vàng', 'vàng': 'Vàng', 'gold': 'Vàng',
            'orange': 'Cam', 'cam': 'Cam',
            'silver': 'Bạc', 'bạc': 'Bạc',
        }
        lower = value.lower()
        for k, v in color_map.items():
            if k in lower:
                return v
        return value

    def _normalize_dpi(self, value: str) -> Optional[str]:
        # extract max number from range
        nums = re.findall(r'\d[\d\s,.]*', value)
        nums = [int(n.replace('.', '').replace(',', '').replace(' ', '')) for n in nums if n.replace('.', '').replace(',', '').replace(' ', '').isdigit()]
        if nums:
            return f'{max(nums)} DPI'
        return None

    def _normalize_polling_rate(self, value: str) -> Optional[str]:
        nums = re.findall(r'\d+', value)
        if nums:
            return f'{max([int(n) for n in nums])} Hz'
        return None

    def _normalize_dimension_weight(self, value: str, group: str) -> Optional[str]:
        # extract numbers and units
        if group == 'trong-luong':
            m = re.search(r'(\d+(?:\.\d+)?)\s*(g|kg|gram)', value, re.I)
            if m:
                num = float(m.group(1))
                unit = m.group(2).lower()
                if unit == 'kg':
                    num *= 1000
                return f'{num:g} g'
        if group == 'kich-thuoc':
            nums = re.findall(r'\d+(?:\.\d+)?', value)
            if len(nums) >= 2:
                return ' x '.join(nums[:3]) + ' mm'
        return None

    def _normalize_form(self, value: str) -> Optional[str]:
        lower = value.lower()
        if 'ergonomic' in lower or 'công thái học' in lower or 'phải' in lower:
            return 'Ergonomic'
        if 'ambidextrous' in lower or 'đối xứng' in lower or 'symmetrical' in lower or 'trái' in lower:
            return 'Đối xứng'
        return None

    def _normalize_layout(self, value: str) -> Optional[str]:
        lower = value.lower()
        if 'full-size' in lower or '100%' in lower or '108' in lower or '104' in lower:
            return 'Fullsize'
        if 'tkl' in lower or '87' in lower or 'tenkeyless' in lower:
            return 'TKL'
        if '75%' in lower or '75' in lower:
            return '75%'
        if '65%' in lower or '65' in lower or '68' in lower:
            return '65%'
        if '60%' in lower or '60' in lower:
            return '60%'
        if '96' in lower or '98' in lower:
            return '96%'
        return value

    def _normalize_headphone_type(self, value: str) -> Optional[str]:
        lower = value.lower()
        if 'over-ear' in lower or 'overear' in lower or 'over ear' in lower:
            return 'Over-ear'
        if 'on-ear' in lower or 'onear' in lower or 'on ear' in lower:
            return 'On-ear'
        if 'in-ear' in lower or 'inear' in lower or 'in ear' in lower or 'earbuds' in lower:
            return 'In-ear'
        return None

    def _normalize_boolean(self, value: str) -> Optional[str]:
        lower = value.lower()
        if any(k in lower for k in ['có', 'yes', 'true', 'có thể', 'hỗ trợ', 'supported', 'detachable', 'tháo rời']):
            return 'Có'
        if any(k in lower for k in ['không', 'no', 'false', 'none', 'không hỗ trợ']):
            return 'Không'
        return value

    def _format_product_information(self, specs: Dict[str, List[str]], meta: Dict[str, List[str]], category: str) -> str:
        lines = []
        # meta lines first (brand, warranty, model)
        for label, values in meta.items():
            lines.append(f'{label}: {self._join_values(values)}')
        priority = CATEGORY_LABEL_PRIORITY.get(category, [])
        # add known groups in priority order
        for group_slug in priority:
            if group_slug in specs:
                values = specs[group_slug]
                label = self._group_label(group_slug)
                lines.append(f'{label}: {self._join_values(values)}')
        # add remaining groups
        for group_slug, values in specs.items():
            if group_slug not in priority:
                label = self._group_label(group_slug)
                lines.append(f'{label}: {self._join_values(values)}')
        return '\n'.join(lines)

    def _group_label(self, group_slug: str) -> str:
        # canonical label is first alias
        return CANONICAL_LABELS.get(group_slug, [group_slug])[0]

    def _join_values(self, values: List[str]) -> str:
        return ' + '.join(values)

    def _should_update_pi(self, old: str, new: str) -> bool:
        return old.strip() != new.strip()

    def _sync_attributes(self, product: Product, specs: Dict[str, List[str]], log: Dict):
        category = product.category
        current_ids = set(product.attributes.values_list('id', flat=True))
        target_values = []

        for group_slug, values in specs.items():
            group = self._get_or_create_group(group_slug, category)
            for value_text in values:
                attr_value = self._get_or_create_value(group, value_text)
                target_values.append(attr_value)

        to_delete_ids = current_ids - {v.id for v in target_values}
        if to_delete_ids:
            log['actions'].append(f'delete {len(to_delete_ids)} old attributes')
            if not self.dry_run:
                ProductAttribute.objects.filter(id__in=to_delete_ids).delete()
        to_add = [v for v in target_values if v.id not in {a.attribute_value_id for a in product.attributes.all()}]
        if to_add:
            log['actions'].append(f'add {len(to_add)} attributes')
            if not self.dry_run:
                ProductAttribute.objects.bulk_create([
                    ProductAttribute(product=product, attribute_value=v) for v in to_add
                ])
        if not to_delete_ids and not to_add:
            log['actions'].append('attributes unchanged')

    def _target_attribute_set(self, specs: Dict[str, List[str]], category: str) -> Set[str]:
        result = set()
        for group_slug, values in specs.items():
            for value_text in values:
                result.add(f'{group_slug}:{slugify(value_text)}')
        return result

    def _get_or_create_group(self, group_slug: str, category: Category) -> AttributeGroup:
        if group_slug in self.group_cache:
            return self.group_cache[group_slug]
        group, created = AttributeGroup.objects.get_or_create(
            slug=group_slug,
            defaults={
                'name': self._group_label(group_slug),
                'filter_type': AttributeGroup.FILTER_TYPE_CHECKBOX,
                'data_type': AttributeGroup.DATA_TYPE_TEXT,
                'display_order': 0,
                'is_filterable': True,
            }
        )
        if category not in group.categories.all():
            group.categories.add(category)
        self.group_cache[group_slug] = group
        return group

    def _get_or_create_value(self, group: AttributeGroup, value_text: str) -> AttributeValue:
        key = (group.id, value_text)
        if key in self.value_cache:
            return self.value_cache[key]
        value_slug = slugify(value_text) or 'value'
        try:
            attr_value = AttributeValue.objects.get(group=group, value=value_text)
        except AttributeValue.DoesNotExist:
            try:
                attr_value = AttributeValue.objects.get(group=group, slug=value_slug)
            except AttributeValue.DoesNotExist:
                attr_value = AttributeValue.objects.create(
                    group=group, value=value_text, slug=value_slug, display_order=0
                )
        self.value_cache[key] = attr_value
        return attr_value

    def _label_to_slug(self, label: str) -> str:
        return slugify(label)

    def _write_report(self):
        report = {
            'stats': dict(self.stats),
            'logs': self.product_logs,
        }
        with open(self.report_path, 'w', encoding='utf-8') as f:
            json.dump(report, f, ensure_ascii=False, indent=2)
        self.stdout.write(f'Report saved to {self.report_path}')

    def _print_summary(self):
        self.stdout.write(self.style.SUCCESS('=== Enrichment Summary ==='))
        for k, v in sorted(self.stats.items()):
            self.stdout.write(f'  {k}: {v}')
