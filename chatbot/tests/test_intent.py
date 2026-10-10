from django.core.cache import cache
from django.test import SimpleTestCase, TestCase

from chatbot.intent.aliases import (
    ATTRIBUTE_ALIASES,
    BOOLEAN_LIKE_GROUPS,
    CATEGORY_ALIASES,
    CLEAN_GROUPS,
    DIRTY_GROUPS,
    FILTERABLE_GROUPS,
    SUGGESTABLE_GROUPS,
    USABLE_GROUPS,
)
from chatbot.intent.resolver import (
    normalize,
    parse_price,
    resolve_aliases,
    validate_filters_against_db,
)

from .factories import make_category, make_group, make_value


class NormalizeTests(SimpleTestCase):
    def test_strips_vietnamese_diacritics(self):
        self.assertEqual(normalize('Chuột Không Dây'), 'chuot khong day')

    def test_handles_d_with_stroke(self):
        self.assertEqual(normalize('Đen'), 'den')
        self.assertEqual(normalize('Đối xứng'), 'doi xung')

    def test_collapses_whitespace(self):
        self.assertEqual(normalize('  ban   phim\tco '), 'ban phim co')

    def test_empty_input(self):
        self.assertEqual(normalize(''), '')
        self.assertEqual(normalize(None), '')


class ParsePriceTests(SimpleTestCase):
    def test_under_million(self):
        self.assertEqual(parse_price('tư vấn chuột dưới 1 triệu'), (None, 1_000_000))

    def test_under_with_tr_shorthand(self):
        self.assertEqual(parse_price('bàn phím dưới 2tr'), (None, 2_000_000))

    def test_under_with_k(self):
        self.assertEqual(parse_price('tai nghe dưới 500k'), (None, 500_000))

    def test_above(self):
        self.assertEqual(parse_price('chuột trên 2 triệu'), (2_000_000, None))

    def test_explicit_range(self):
        self.assertEqual(parse_price('từ 1 đến 2 triệu'), (1_000_000, 2_000_000))

    def test_range_with_both_units(self):
        self.assertEqual(parse_price('giá từ 500k đến 1 triệu'), (500_000, 1_000_000))

    def test_range_reversed_is_sorted(self):
        self.assertEqual(parse_price('từ 2 triệu đến 1 triệu'), (1_000_000, 2_000_000))

    def test_around_expands_twenty_percent(self):
        self.assertEqual(parse_price('tầm 1 triệu'), (800_000, 1_200_000))

    def test_thousand_separators(self):
        self.assertEqual(parse_price('dưới 1.500.000'), (None, 1_500_000))

    def test_decimal_with_unit(self):
        self.assertEqual(parse_price('khoảng 1,5 triệu'), (1_200_000, 1_800_000))

    def test_no_price_mentioned(self):
        self.assertEqual(parse_price('tư vấn chuột gaming'), (None, None))

    def test_small_number_without_unit_is_not_a_price(self):
        """'có 2 nút' không được hiểu thành giá 2 đồng."""
        self.assertEqual(parse_price('chuột có 2 nút'), (None, None))

    def test_dpi_is_not_a_price(self):
        self.assertEqual(parse_price('chuột 26000 dpi'), (None, None))

    def test_khong_day_does_not_trigger_k_unit(self):
        self.assertEqual(parse_price('chuột không dây'), (None, None))


class ResolveCategoryTests(SimpleTestCase):
    def test_keyboard(self):
        self.assertEqual(resolve_aliases('tư vấn bàn phím cơ')['category_slug'], 'ban-phim')

    def test_mouse(self):
        self.assertEqual(resolve_aliases('chuột nào tốt')['category_slug'], 'chuot')

    def test_headphone(self):
        self.assertEqual(resolve_aliases('tai nghe chống ồn')['category_slug'], 'tai-nghe')

    def test_microphone(self):
        self.assertEqual(resolve_aliases('micro thu âm')['category_slug'], 'microphone')

    def test_gamepad(self):
        self.assertEqual(resolve_aliases('tay cầm chơi PS5')['category_slug'], 'tay-cam')

    def test_mic_does_not_match_inside_microphone_word(self):
        """Ranh giới từ: 'mic' không được khớp bên trong 'microphone'."""
        self.assertEqual(resolve_aliases('microphone')['category_slug'], 'microphone')

    def test_no_category(self):
        self.assertIsNone(resolve_aliases('shop có giảm giá gì không')['category_slug'])


class ResolveAttributeTests(SimpleTestCase):
    def test_wireless(self):
        result = resolve_aliases('chuột không dây')
        self.assertIn('ket-noi', result['attributes'])
        self.assertIn('wireless', result['attributes']['ket-noi'])

    def test_compact_layout(self):
        result = resolve_aliases('bàn phím nhỏ gọn')
        self.assertEqual(set(result['attributes']['layout']), {'tkl', '65', '75'})

    def test_rgb(self):
        result = resolve_aliases('bàn phím có RGB')
        self.assertIn('rgb', result['attributes']['den-led'])

    def test_silent_switch(self):
        result = resolve_aliases('bàn phím switch êm')
        self.assertIn('linear', result['attributes']['switch'])

    def test_anc_only_uses_boolean_value(self):
        result = resolve_aliases('tai nghe chống ồn')
        self.assertEqual(result['attributes']['chong-on'], ['co'])

    def test_symmetric_uses_mangled_slug(self):
        """'Đối xứng' có slug thật là 'oi-xung' vì slugify xoá chữ Đ."""
        result = resolve_aliases('chuột đối xứng')
        self.assertEqual(result['attributes']['form-chuot'], ['oi-xung'])

    def test_black_color_uses_mangled_slug(self):
        result = resolve_aliases('bàn phím màu đen')
        self.assertEqual(result['attributes']['mau-sac'], ['en'])

    def test_in_ear(self):
        result = resolve_aliases('tai nghe nhét tai')
        self.assertEqual(result['attributes']['loai-tai-nghe'], ['in-ear'])

    def test_platform_playstation(self):
        result = resolve_aliases('tay cầm cho PS5')
        self.assertIn('ps5', result['attributes']['tuong-thich'])

    def test_no_attribute_match(self):
        self.assertEqual(resolve_aliases('xin chào')['attributes'], {})


class ResolveConflictTests(SimpleTestCase):
    def test_wireless_beats_wired_when_keyword_longer(self):
        result = resolve_aliases('chuột không dây có usb receiver')
        self.assertIn('wireless', result['matched'])
        self.assertNotIn('wired', result['matched'])

    def test_compact_beats_fullsize(self):
        result = resolve_aliases('bàn phím nhỏ gọn không cần fullsize')
        self.assertIn('compact', result['matched'])
        self.assertNotIn('fullsize', result['matched'])


class ResolveKeywordTests(SimpleTestCase):
    def test_gaming_goes_to_keyword_not_attribute(self):
        """Không tồn tại group 'usage' trong DB nên 'gaming' phải thành keyword."""
        result = resolve_aliases('chuột gaming')
        self.assertIn('gaming', result['keywords'])
        self.assertNotIn('usage', result['attributes'])

    def test_office(self):
        self.assertIn('office', resolve_aliases('bàn phím cho văn phòng')['keywords'])

    def test_stream(self):
        self.assertIn('stream', resolve_aliases('micro để livestream')['keywords'])

    def test_battery(self):
        self.assertIn('battery', resolve_aliases('chuột pin trâu')['keywords'])

    def test_gamepad_word_does_not_leak_gaming_keyword(self):
        """'gamepad' chứa 'game' nhưng ranh giới từ phải ngăn match."""
        self.assertNotIn('gaming', resolve_aliases('gamepad')['keywords'])


class ResolveSortTests(SimpleTestCase):
    def test_cheap(self):
        self.assertEqual(resolve_aliases('chuột giá rẻ')['sort_by'], 'price_asc')

    def test_best_seller(self):
        self.assertEqual(resolve_aliases('bàn phím bán chạy')['sort_by'], 'popular')

    def test_high_rating(self):
        self.assertEqual(resolve_aliases('tai nghe đánh giá cao')['sort_by'], 'rating')

    def test_premium(self):
        self.assertEqual(resolve_aliases('chuột cao cấp')['sort_by'], 'price_desc')

    def test_no_sort(self):
        self.assertIsNone(resolve_aliases('chuột Logitech')['sort_by'])


class ResolveCombinedTests(SimpleTestCase):
    def test_full_sentence(self):
        result = resolve_aliases('tư vấn chuột gaming không dây dưới 1 triệu')

        self.assertEqual(result['category_slug'], 'chuot')
        self.assertIn('wireless', result['attributes']['ket-noi'])
        self.assertIn('gaming', result['keywords'])
        self.assertIsNone(result['price_min'])
        self.assertEqual(result['price_max'], 1_000_000)

    def test_unaccented_input_still_matches(self):
        result = resolve_aliases('ban phim co nho gon khong day tu 1 den 2 trieu')

        self.assertEqual(result['category_slug'], 'ban-phim')
        self.assertIn('wireless', result['attributes']['ket-noi'])
        self.assertEqual(result['attributes']['layout'], ['tkl', '65', '75'])
        self.assertEqual((result['price_min'], result['price_max']), (1_000_000, 2_000_000))


class AliasIntegrityTests(SimpleTestCase):
    def test_every_attribute_alias_declares_keywords_and_attributes(self):
        for alias_key, spec in ATTRIBUTE_ALIASES.items():
            with self.subTest(alias=alias_key):
                self.assertTrue(spec.get('keywords'), f'{alias_key} thiếu keywords')
                self.assertTrue(spec.get('attributes'), f'{alias_key} thiếu attributes')

    def test_category_alias_keys_are_slug_like(self):
        for category_slug in CATEGORY_ALIASES:
            with self.subTest(category=category_slug):
                self.assertRegex(category_slug, r'^[a-z0-9-]+$')

    def test_alias_keywords_are_normalized(self):
        """Keyword phải viết ở dạng đã bỏ dấu để resolver match đúng."""
        for alias_key, spec in ATTRIBUTE_ALIASES.items():
            for keyword in spec['keywords']:
                with self.subTest(alias=alias_key, keyword=keyword):
                    self.assertEqual(keyword, normalize(keyword))

    def test_group_quality_sets_are_disjoint(self):
        """Mỗi AttributeGroup chỉ được thuộc đúng một nhóm chất lượng."""
        sets = {
            'CLEAN': CLEAN_GROUPS,
            'USABLE': USABLE_GROUPS,
            'BOOLEAN': set(BOOLEAN_LIKE_GROUPS),
            'DIRTY': DIRTY_GROUPS,
        }

        labels = list(sets)
        for index, left in enumerate(labels):
            for right in labels[index + 1:]:
                with self.subTest(pair=f'{left}/{right}'):
                    self.assertEqual(
                        sets[left] & sets[right],
                        set(),
                        f'{left} và {right} bị trùng group',
                    )

    def test_dirty_groups_are_never_suggestable(self):
        self.assertEqual(SUGGESTABLE_GROUPS & DIRTY_GROUPS, set())

    def test_attribute_aliases_only_target_filterable_groups(self):
        for alias_key, spec in ATTRIBUTE_ALIASES.items():
            for group_slug in spec['attributes']:
                with self.subTest(alias=alias_key, group=group_slug):
                    self.assertIn(
                        group_slug,
                        FILTERABLE_GROUPS,
                        f'{alias_key} trỏ tới group không được phép filter',
                    )


class ValidateFiltersAgainstDbTests(TestCase):
    def setUp(self):
        cache.clear()

        self.mouse = make_category(slug='chuot', name='Chuột')
        self.keyboard = make_category(slug='ban-phim', name='Bàn phím')

        self.connectivity = make_group(
            slug='ket-noi',
            name='Kết nối',
            categories=[self.mouse, self.keyboard],
        )
        make_value(self.connectivity, value='Wireless', slug='wireless')
        make_value(self.connectivity, value='USB', slug='usb')

        self.layout = make_group(
            slug='layout',
            name='Layout',
            categories=[self.keyboard],
            display_order=30,
        )
        make_value(self.layout, value='TKL', slug='tkl')

        self.anc = make_group(slug='chong-on', name='Chống ồn', categories=[self.mouse])
        make_value(self.anc, value='Có', slug='co')
        make_value(self.anc, value='32 Ohm', slug='32-ohm')

    def tearDown(self):
        cache.clear()

    def test_keeps_valid_pairs(self):
        cleaned = validate_filters_against_db({'ket-noi': ['wireless']})
        self.assertEqual(cleaned, {'ket-noi': ['wireless']})

    def test_drops_unknown_value_slug(self):
        cleaned = validate_filters_against_db({'ket-noi': ['wireless', 'khong-ton-tai']})
        self.assertEqual(cleaned, {'ket-noi': ['wireless']})

    def test_drops_unknown_group(self):
        cleaned = validate_filters_against_db({'usage': ['gaming']})
        self.assertEqual(cleaned, {})

    def test_drops_group_not_applicable_to_category(self):
        cleaned = validate_filters_against_db({'layout': ['tkl']}, category_slug='chuot')
        self.assertEqual(cleaned, {})

    def test_keeps_group_applicable_to_category(self):
        cleaned = validate_filters_against_db({'layout': ['tkl']}, category_slug='ban-phim')
        self.assertEqual(cleaned, {'layout': ['tkl']})

    def test_boolean_group_rejects_garbage_value(self):
        """chong-on khai boolean nên chỉ nhận co/khong, bỏ '32-ohm' dù tồn tại trong DB."""
        cleaned = validate_filters_against_db({'chong-on': ['co', '32-ohm']})
        self.assertEqual(cleaned, {'chong-on': ['co']})

    def test_accepts_single_string_value(self):
        cleaned = validate_filters_against_db({'ket-noi': 'wireless'})
        self.assertEqual(cleaned, {'ket-noi': ['wireless']})

    def test_deduplicates_values(self):
        cleaned = validate_filters_against_db({'ket-noi': ['wireless', 'wireless']})
        self.assertEqual(cleaned, {'ket-noi': ['wireless']})

    def test_empty_input(self):
        self.assertEqual(validate_filters_against_db({}), {})
        self.assertEqual(validate_filters_against_db(None), {})

    def test_inactive_value_is_dropped(self):
        value = make_value(self.connectivity, value='Bluetooth', slug='bluetooth')
        value.is_active = False
        value.save(update_fields=['is_active'])
        cache.clear()

        cleaned = validate_filters_against_db({'ket-noi': ['bluetooth']})
        self.assertEqual(cleaned, {})
