from django.core.cache import cache
from django.test import TestCase

from chatbot.tools.compare import compare_products

from .factories import make_brand, make_category, make_group, make_product, make_value


class CompareProductsTests(TestCase):
    def setUp(self):
        cache.clear()
        self.keyboard = make_category(slug='ban-phim', name='Bàn phím')
        self.brand = make_brand('Logitech')

        self.connectivity = make_group(slug='ket-noi', name='Kết nối', categories=[self.keyboard], display_order=20)
        self.layout = make_group(slug='layout', name='Layout', categories=[self.keyboard], display_order=30)
        self.switch = make_group(slug='switch', name='Switch', categories=[self.keyboard], display_order=40)

        self.wireless = make_value(self.connectivity, value='Wireless', slug='wireless')
        self.usb = make_value(self.connectivity, value='USB', slug='usb')
        self.tkl = make_value(self.layout, value='TKL', slug='tkl')
        self.fullsize = make_value(self.layout, value='Fullsize', slug='fullsize')
        self.linear = make_value(self.switch, value='Linear', slug='linear')

        self.a = make_product(
            category=self.keyboard,
            brand=self.brand,
            name='A',
            slug='a',
            price='1000000',
            discount_price='900000',
            attribute_values=[self.wireless, self.tkl, self.linear],
        )
        self.b = make_product(
            category=self.keyboard,
            brand=self.brand,
            name='B',
            slug='b',
            price='1200000',
            attribute_values=[self.usb, self.tkl, self.linear],
        )
        self.c = make_product(
            category=self.keyboard,
            brand=self.brand,
            name='C',
            slug='c',
            price='1500000',
            attribute_values=[self.usb, self.fullsize],
        )

    def tearDown(self):
        cache.clear()

    def test_requires_at_least_two_products(self):
        payload = compare_products(['a'])
        self.assertFalse(payload['found'])
        self.assertEqual(payload['message'], 'Cần ít nhất 2 sản phẩm để so sánh.')

    def test_compare_products_shape(self):
        payload = compare_products(['a', 'b'])
        self.assertTrue(payload['found'])
        self.assertEqual([item['slug'] for item in payload['products']], ['a', 'b'])
        self.assertEqual(payload['price_row']['values'], [900000, 1200000])

    def test_rows_are_split_into_same_and_different(self):
        payload = compare_products(['a', 'b'])
        diff_groups = {row['group_slug'] for row in payload['rows_different']}
        same_groups = {row['group_slug'] for row in payload['rows_same']}
        self.assertIn('ket-noi', diff_groups)
        self.assertIn('layout', same_groups)
        self.assertIn('switch', same_groups)

    def test_sorts_by_display_order(self):
        payload = compare_products(['a', 'c'])
        ordered = [row['group_slug'] for row in payload['rows_different'] + payload['rows_same']]
        self.assertEqual(ordered[:3], ['ket-noi', 'layout', 'switch'])

    def test_missing_slugs_are_reported(self):
        payload = compare_products(['a', 'khong-co', 'b'])
        self.assertEqual(payload['missing_slugs'], ['khong-co'])

    def test_limits_to_four_products(self):
        d = make_product(category=self.keyboard, brand=self.brand, name='D', slug='d', price='1600000')
        e = make_product(category=self.keyboard, brand=self.brand, name='E', slug='e', price='1700000')
        payload = compare_products(['a', 'b', 'c', 'd', 'e'])
        self.assertEqual(len(payload['products']), 4)
