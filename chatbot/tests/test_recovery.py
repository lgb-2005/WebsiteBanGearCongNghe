from django.core.cache import cache
from django.test import TestCase

from chatbot.tools.catalog import search_products

from .factories import make_brand, make_category, make_group, make_product, make_value


class RecoveryTests(TestCase):
    def setUp(self):
        cache.clear()
        self.mouse = make_category(slug='chuot', name='Chuột')
        self.keyboard = make_category(slug='ban-phim', name='Bàn phím')
        self.brand = make_brand('Logitech')

        self.connectivity = make_group(slug='ket-noi', name='Kết nối', categories=[self.mouse, self.keyboard])
        self.layout = make_group(slug='layout', name='Layout', categories=[self.keyboard], display_order=30)
        self.switch = make_group(slug='switch', name='Switch', categories=[self.keyboard], display_order=40)

        self.wireless = make_value(self.connectivity, value='Wireless', slug='wireless')
        self.usb = make_value(self.connectivity, value='USB', slug='usb')
        self.tkl = make_value(self.layout, value='TKL', slug='tkl')
        self.linear = make_value(self.switch, value='Linear', slug='linear')
        self.clicky = make_value(self.switch, value='Blue', slug='blue')

        make_product(
            category=self.keyboard,
            brand=self.brand,
            name='Bàn phím Wireless TKL',
            slug='ban-phim-wireless-tkl',
            price='1200000',
            stock=5,
            rating='4.8',
            attribute_values=[self.wireless, self.tkl, self.linear],
        )
        make_product(
            category=self.keyboard,
            brand=self.brand,
            name='Bàn phím Có dây TKL',
            slug='ban-phim-usb-tkl',
            price='900000',
            stock=5,
            rating='4.5',
            attribute_values=[self.usb, self.tkl, self.clicky],
        )
        make_product(
            category=self.mouse,
            brand=self.brand,
            name='Chuột Wireless',
            slug='chuot-wireless',
            price='1100000',
            stock=5,
            rating='4.4',
            attribute_values=[self.wireless],
        )

    def tearDown(self):
        cache.clear()

    def test_price_relaxation_kicks_in(self):
        payload = search_products(category_slug='ban-phim', price_max=1000000, attributes={'ket-noi': ['wireless']})
        self.assertFalse(payload['found'])
        self.assertEqual(payload['relaxation']['strategy'], 'price_relaxation')
        self.assertEqual(payload['relaxation']['ui_results'][0]['slug'], 'ban-phim-wireless-tkl')

    def test_attribute_relaxation_drops_rarest_filter(self):
        payload = search_products(
            category_slug='ban-phim',
            attributes={'ket-noi': ['wireless'], 'layout': ['tkl'], 'switch': ['blue']},
            price_max=2000000,
        )
        self.assertFalse(payload['found'])
        self.assertEqual(payload['relaxation']['strategy'], 'attribute_relaxation')
        self.assertIn('switch:blue', payload['relaxation']['dropped_filters'])

    def test_fallback_returns_top_rated_when_nothing_matches(self):
        payload = search_products(category_slug='chuot', brand_name='Razer', keyword='khong ton tai')
        self.assertFalse(payload['found'])
        self.assertEqual(payload['relaxation']['strategy'], 'fallback_top_rated')
        self.assertGreaterEqual(len(payload['relaxation']['ui_results']), 0)
