"""Tầng 1 của pipeline hiểu ý: rule/alias cứng, deterministic, test được.

Chạy TRƯỚC khi gọi LLM. Nếu tầng này không match rõ thì mới để LLM suy luận.
"""

import logging
import re
import unicodedata

from django.core.cache import cache

from .aliases import (
    ATTRIBUTE_ALIASES,
    BOOLEAN_LIKE_GROUPS,
    CATEGORY_ALIASES,
    KEYWORD_ALIASES,
    SORT_ALIASES,
)

logger = logging.getLogger(__name__)

VALID_PAIRS_CACHE_KEY = 'chatbot:valid_attribute_pairs:v1'
VALID_PAIRS_CACHE_TTL = 3600

# Khi cả hai alias trong cặp cùng match, chỉ giữ một (xem _resolve_conflicts).
ALIAS_CONFLICTS = [
    ('wireless', 'wired'),
    ('compact', 'fullsize'),
    ('in_ear', 'over_ear'),
    ('ergonomic', 'symmetric'),
    ('cardioid', 'omnidirectional'),
]

SORT_CHOICES = ('relevance', 'price_asc', 'price_desc', 'rating', 'popular')


# --- Chuẩn hoá văn bản --------------------------------------------------------

def normalize(text):
    """Lowercase + bỏ dấu tiếng Việt. ``đ``/``Đ`` phải xử lý tay vì NFD không tách."""
    if not text:
        return ''

    text = text.lower().replace('đ', 'd')
    text = unicodedata.normalize('NFD', text)
    text = ''.join(char for char in text if unicodedata.category(char) != 'Mn')
    text = unicodedata.normalize('NFC', text)
    return re.sub(r'\s+', ' ', text).strip()


def _keyword_pattern(keyword):
    return re.compile(
        r'(?<![0-9a-z])' + re.escape(keyword) + r'(?![0-9a-z])'
    )


def _find(normalized_text, keyword):
    """Trả vị trí match đầu tiên theo ranh giới từ, hoặc None."""
    match = _keyword_pattern(normalize(keyword)).search(normalized_text)
    return match.start() if match else None


# --- Parser giá tiếng Việt ----------------------------------------------------

_UNIT_MULTIPLIERS = (
    ('trieu', 1_000_000),
    ('tr', 1_000_000),
    ('nghin', 1_000),
    ('ngan', 1_000),
    ('k', 1_000),
)

_AMOUNT = r'(\d+(?:[.,]\d+)*)\s*(?:(trieu|tr|nghin|ngan|k)(?![0-9a-z]))?'

# Không ai đặt ngân sách dưới mốc này; số nhỏ hơn mà không kèm đơn vị thì
# gần như chắc chắn là DPI / số nút / số phím, không phải giá.
_MIN_PLAUSIBLE_PRICE = 1000

_RANGE_RE = re.compile(
    r'(?:tu|khoang|trong khoang|gia)?\s*' + _AMOUNT +
    r'\s*(?:den|-|–|toi|~)\s*' + _AMOUNT
)
_MAX_RE = re.compile(
    r'(?:duoi|khong qua|toi da|it hon|re hon|<=?|nho hon)\s*' + _AMOUNT
)
_MIN_RE = re.compile(
    r'(?:tren|hon|cao hon|lon hon|>=?|tu)\s*' + _AMOUNT + r'(?:\s*tro len)?'
)
_AROUND_RE = re.compile(
    r'(?:khoang|tam|co|chung|xap xi)\s*' + _AMOUNT
)


def _parse_amount(raw_number, unit):
    if not raw_number:
        return None

    cleaned = raw_number
    if re.fullmatch(r'\d{1,3}(?:[.,]\d{3})+', cleaned):
        cleaned = re.sub(r'[.,]', '', cleaned)
    else:
        cleaned = cleaned.replace(',', '.')

    try:
        amount = float(cleaned)
    except ValueError:
        return None

    if unit:
        for prefix, multiplier in _UNIT_MULTIPLIERS:
            if unit == prefix:
                amount *= multiplier
                break

    if amount <= 0:
        return None

    if not unit and amount < _MIN_PLAUSIBLE_PRICE:
        return None

    return int(round(amount))


def parse_price(text):
    """Trích (price_min, price_max) từ câu tiếng Việt. Trả (None, None) nếu không rõ."""
    normalized_text = normalize(text)
    if not normalized_text:
        return None, None

    range_match = _RANGE_RE.search(normalized_text)
    if range_match:
        low_number, low_unit, high_number, high_unit = range_match.groups()
        # "tu 1 den 2 trieu" -> đơn vị của cận dưới mượn từ cận trên
        low = _parse_amount(low_number, low_unit or high_unit)
        high = _parse_amount(high_number, high_unit)
        if low and high and low > high:
            low, high = high, low
        if low or high:
            return low, high

    max_match = _MAX_RE.search(normalized_text)
    if max_match:
        high = _parse_amount(*max_match.groups())
        if high:
            return None, high

    min_match = _MIN_RE.search(normalized_text)
    if min_match:
        low = _parse_amount(*min_match.groups())
        if low:
            return low, None

    around_match = _AROUND_RE.search(normalized_text)
    if around_match:
        center = _parse_amount(*around_match.groups())
        if center:
            return int(center * 0.8), int(center * 1.2)

    return None, None


# --- Resolve alias ------------------------------------------------------------

def _match_category(normalized_text):
    best = None
    for category_slug, keywords in CATEGORY_ALIASES.items():
        for keyword in keywords:
            position = _find(normalized_text, keyword)
            if position is None:
                continue
            candidate = (len(keyword), -position, category_slug)
            if best is None or candidate > best:
                best = candidate
    return best[2] if best else None


def _match_attribute_aliases(normalized_text):
    """Trả {alias_key: (position, keyword_length)} của lần match SỚM NHẤT."""
    matches = {}
    for alias_key, spec in ATTRIBUTE_ALIASES.items():
        best = None
        for keyword in spec['keywords']:
            position = _find(normalized_text, keyword)
            if position is None:
                continue
            candidate = (position, -len(keyword))
            if best is None or candidate < best:
                best = candidate
        if best:
            matches[alias_key] = (best[0], -best[1])
    return matches


def _resolve_conflicts(matches):
    """Khi cả hai alias đối lập cùng match: giữ alias xuất hiện SỚM HƠN trong câu,
    vì người dùng thường nói ý chính trước ("bàn phím nhỏ gọn, không cần fullsize").
    Nếu cùng vị trí thì giữ alias có keyword dài hơn.

    Hạn chế đã biết: tầng rule không hiểu phủ định ("không cần..."). Heuristic
    vị trí xử lý được phần lớn trường hợp; phần còn lại để LLM ở tầng 2 sửa.
    """
    for left, right in ALIAS_CONFLICTS:
        if left not in matches or right not in matches:
            continue

        left_position, left_length = matches[left]
        right_position, right_length = matches[right]

        if left_position < right_position:
            loser = right
        elif right_position < left_position:
            loser = left
        else:
            loser = right if left_length >= right_length else left

        matches.pop(loser, None)

    return matches


def _match_keywords(normalized_text):
    found = []
    for alias_key, keywords in KEYWORD_ALIASES.items():
        if any(_find(normalized_text, keyword) is not None for keyword in keywords):
            found.append(alias_key)
    return found


def _match_sort(normalized_text):
    best = None
    for sort_key, keywords in SORT_ALIASES.items():
        for keyword in keywords:
            position = _find(normalized_text, keyword)
            if position is None:
                continue
            candidate = (len(keyword), -position, sort_key)
            if best is None or candidate > best:
                best = candidate
    return best[2] if best else None


def resolve_aliases(text):
    """Tầng 1: suy ra filter từ luật cứng. Không gọi DB, không gọi LLM."""
    normalized_text = normalize(text)

    attribute_matches = _resolve_conflicts(_match_attribute_aliases(normalized_text))

    attributes = {}
    for alias_key in attribute_matches:
        for group_slug, value_slugs in ATTRIBUTE_ALIASES[alias_key]['attributes'].items():
            bucket = attributes.setdefault(group_slug, [])
            for value_slug in value_slugs:
                if value_slug not in bucket:
                    bucket.append(value_slug)

    price_min, price_max = parse_price(text)

    return {
        'category_slug': _match_category(normalized_text),
        'attributes': attributes,
        'keywords': _match_keywords(normalized_text),
        'sort_by': _match_sort(normalized_text),
        'price_min': price_min,
        'price_max': price_max,
        'matched': sorted(attribute_matches.keys()),
    }


# --- Validate ngược với DB ----------------------------------------------------

def _load_valid_pairs():
    """Trả {(group_slug, value_slug), ...} của mọi AttributeValue đang active."""
    cached = cache.get(VALID_PAIRS_CACHE_KEY)
    if cached is not None:
        return cached

    from products.models import AttributeValue

    pairs = set(
        AttributeValue.objects.filter(
            is_active=True,
            group__is_active=True,
        ).values_list('group__slug', 'slug')
    )

    cache.set(VALID_PAIRS_CACHE_KEY, pairs, VALID_PAIRS_CACHE_TTL)
    return pairs


def _load_groups_for_category(category_slug):
    """Trả set group_slug áp dụng cho category (group không gắn category nào = áp dụng tất cả)."""
    from django.db.models import Q

    from products.models import AttributeGroup

    cache_key = f'chatbot:groups_for_category:v1:{category_slug}'
    cached = cache.get(cache_key)
    if cached is not None:
        return cached

    groups = set(
        AttributeGroup.objects.filter(is_active=True).filter(
            Q(categories__isnull=True) | Q(categories__slug=category_slug)
        ).values_list('slug', flat=True)
    )

    cache.set(cache_key, groups, VALID_PAIRS_CACHE_TTL)
    return groups


def validate_filters_against_db(attributes, category_slug=None):
    """Chỉ giữ cặp (group_slug, value_slug) tồn tại thật và hợp lệ với category.

    Cặp không hợp lệ bị loại bỏ kèm warning, KHÔNG raise (cạm bẫy: LLM/alias
    có thể bịa slug, không được để vỡ request).
    """
    if not attributes:
        return {}

    valid_pairs = _load_valid_pairs()
    allowed_groups = _load_groups_for_category(category_slug) if category_slug else None

    cleaned = {}
    dropped = []

    for group_slug, raw_values in attributes.items():
        if allowed_groups is not None and group_slug not in allowed_groups:
            dropped.append(f'{group_slug}:* (group không áp dụng cho {category_slug})')
            continue

        if isinstance(raw_values, str):
            raw_values = [raw_values]

        boolean_whitelist = BOOLEAN_LIKE_GROUPS.get(group_slug)

        kept = []
        for value_slug in raw_values or []:
            value_slug = str(value_slug).strip()
            if not value_slug:
                continue
            if boolean_whitelist and value_slug not in boolean_whitelist:
                dropped.append(f'{group_slug}:{value_slug} (group boolean, chỉ nhận co/khong)')
                continue
            if (group_slug, value_slug) not in valid_pairs:
                dropped.append(f'{group_slug}:{value_slug} (không tồn tại trong DB)')
                continue
            if value_slug not in kept:
                kept.append(value_slug)

        if kept:
            cleaned[group_slug] = kept

    if dropped:
        logger.warning('chatbot: bỏ %d filter không hợp lệ: %s', len(dropped), '; '.join(dropped))

    return cleaned


def normalize_sort_by(sort_by):
    if sort_by in SORT_CHOICES:
        return sort_by
    return 'relevance'


def invalidate_filter_caches():
    """Gọi khi dữ liệu thuộc tính thay đổi (dùng trong test hoặc signal)."""
    cache.delete(VALID_PAIRS_CACHE_KEY)
