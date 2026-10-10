from django.core.cache import cache
from django.test import TestCase

from chatbot.tools.catalog import get_catalog_overview, get_filter_options, get_product_detail, search_products
from products.models import ProductReview

from .factories import make_brand, make_category, make_group, make_product, make_user, make_value


class CatalogToolTests(TestCase):
    def setUp(self):
        cache.clear()

        self.mouse = make_category(slug='chuot', name='Chuột')
        self.keyboard = make_category(slug='ban-phim', name='Bàn phím')
        self.logitech = make_brand('Logitech')
        self.razer = make_brand('Razer')
        self.user = make_user(email='reviewer@example.com', name='Reviewer')

        self.connectivity = make_group(slug='ket-noi', name='Kết nối', categories=[self.mouse, self.keyboard])
        self.layout = make_group(slug='layout', name='Layout', categories=[self.keyboard], display_order=30)
        self.switch = make_group(slug='switch', name='Switch', categories=[self.keyboard], display_order=40)
        self.dirty_pin = make_group(slug='pin', name='Pin / Nguồn', categories=[self.keyboard], display_order=60)
        self.boolean_noise = make_group(
            slug='chong-on',
            name='Chống ồn',
            categories=[self.mouse],
            display_order=40,
            data_type='boolean',
            filter_type='radio',
        )

        self.wireless = make_value(self.connectivity, value='Wireless', slug='wireless')
        self.bluetooth = make_value(self.connectivity, value='Bluetooth', slug='bluetooth')
        self.usb = make_value(self.connectivity, value='USB', slug='usb')
        self.tkl = make_value(self.layout, value='TKL', slug='tkl')
        self.linear = make_value(self.switch, value='Linear', slug='linear')
        self.pin_dirty = make_value(self.dirty_pin, value='500mAh - 150h', slug='500mah-150h')
        self.anc_yes = make_value(self.boolean_noise, value='Có', slug='co')
        self.anc_dirty = make_value(self.boolean_noise, value='32 Ohm', slug='32-ohm')

        self.mouse_wireless = make_product(
            category=self.mouse,
            brand=self.logitech,
            name='Chuột Logitech G Pro Wireless',
            slug='chuot-logitech-g-pro-wireless',
            price='1500000',
            discount_price='1200000',
            stock=5,
            rating='4.80',
            description='<p>Chuột gaming wireless siêu nhẹ</p>',
            attribute_values=[self.wireless],
        )
        self.mouse_wired = make_product(
            category=self.mouse,
            brand=self.razer,
            name='Chuột Razer DeathAdder V3',
            slug='chuot-razer-deathadder-v3',
            price='900000',
            stock=12,
            rating='4.50',
            description='<p>Chuột gaming có dây cho FPS</p>',
            attribute_values=[self.usb],
        )
        self.keyboard_wireless = make_product(
            category=self.keyboard,
            brand=self.logitech,
            name='Bàn phím Logitech TKL Wireless',
            slug='ban-phim-logitech-tkl-wireless',
            price='1800000',
            stock=3,
            rating='4.70',
            description='<p>Bàn phím cơ không dây TKL switch linear</p>',
            product_information='<p>Pin 500mAh - 150h</p>',
            attribute_values=[self.wireless, self.tkl, self.linear, self.pin_dirty],
        )
        self.keyboard_budget = make_product(
            category=self.keyboard,
            brand=self.razer,
            name='Bàn phím Razer Budget',
            slug='ban-phim-razer-budget',
            price='700000',
            stock=0,
            rating='4.10',
            description='<p>Bàn phím có dây giá rẻ</p>',
            attribute_values=[self.usb],
        )

    def tearDown(self):
        cache.clear()

    def test_get_catalog_overview(self):
        payload = get_catalog_overview()
        self.assertEqual(payload['total_products'], 4)
        self.assertEqual(payload['price_min'], 700000)
        self.assertEqual(payload['price_max'], 1800000)
        self.assertIn('Logitech', payload['brands'])
        self.assertEqual({item['slug'] for item in payload['categories']}, {'chuot', 'ban-phim'})

    def test_get_filter_options_only_returns_suggestable_groups(self):
        payload = get_filter_options('ban-phim')
        group_slugs = [item['group_slug'] for item in payload['filters']]
        self.assertIn('ket-noi', group_slugs)
        self.assertIn('layout', group_slugs)
        self.assertIn('switch', group_slugs)
        self.assertNotIn('pin', group_slugs)

    def test_get_filter_options_boolean_group_only_co_khong(self):
        payload = get_filter_options('chuot')
        noise = next(item for item in payload['filters'] if item['group_slug'] == 'chong-on')
        self.assertEqual([value['slug'] for value in noise['values']], ['co'])

    def test_search_by_keyword(self):
        payload = search_products(keyword='g pro wireless', category_slug='chuot')
        self.assertTrue(payload['found'])
        self.assertEqual(payload['results'][0]['slug'], 'chuot-logitech-g-pro-wireless')

    def test_search_by_brand_name(self):
        payload = search_products(category_slug='chuot', brand_name='Razer')
        self.assertEqual([item['slug'] for item in payload['results']], ['chuot-razer-deathadder-v3'])

    def test_search_by_price_range_uses_effective_price(self):
        payload = search_products(category_slug='chuot', price_max=1250000)
        self.assertEqual(
            [item['slug'] for item in payload['results']],
            ['chuot-logitech-g-pro-wireless', 'chuot-razer-deathadder-v3'],
        )

    def test_search_by_attributes(self):
        payload = search_products(category_slug='ban-phim', attributes={'layout': ['tkl'], 'switch': ['linear']})
        self.assertEqual([item['slug'] for item in payload['results']], ['ban-phim-logitech-tkl-wireless'])

    def test_search_invalid_attribute_is_dropped(self):
        payload = search_products(category_slug='ban-phim', attributes={'layout': ['khong-ton-tai']})
        self.assertEqual(len(payload['results']), 2)
        self.assertEqual(payload['filters_applied']['attributes'], {})

    def test_search_in_stock(self):
        payload = search_products(category_slug='ban-phim', in_stock=True)
        self.assertEqual([item['slug'] for item in payload['results']], ['ban-phim-logitech-tkl-wireless'])

    def test_search_limit_is_enforced(self):
        payload = search_products(limit=99)
        self.assertLessEqual(len(payload['results']), 8)

    def test_search_unknown_category(self):
        payload = search_products(category_slug='khong-co')
        self.assertFalse(payload['found'])
        self.assertEqual(payload['message'], 'Danh mục không tồn tại.')

    def test_get_product_detail_found(self):
        ProductReview.objects.create(user=self.user, product=self.mouse_wireless, rating=5, comment='Rat tot')
        payload = get_product_detail(slug='chuot-logitech-g-pro-wireless')
        self.assertTrue(payload['found'])
        self.assertEqual(payload['product']['slug'], 'chuot-logitech-g-pro-wireless')
        self.assertIn('Kết nối', payload['product']['key_specs'])

    def test_get_product_detail_not_found_returns_suggestions(self):
        payload = get_product_detail(slug='chuot-logitech-g-pro')
        self.assertFalse(payload['found'])
        self.assertEqual(payload['ui_suggestions'][0]['slug'], 'chuot-logitech-g-pro-wireless')
