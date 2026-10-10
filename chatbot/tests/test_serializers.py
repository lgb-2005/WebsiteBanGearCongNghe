from django.test import SimpleTestCase, TestCase

from chatbot.serializers import (
    final_price_of,
    strip_rich_text,
    to_llm,
    to_money,
    to_ui,
)
from products.models import Product

from .factories import make_brand, make_category, make_group, make_product, make_value


class StripRichTextTests(SimpleTestCase):
    def test_removes_html_tags(self):
        self.assertEqual(strip_rich_text('<p>Chuột <strong>gaming</strong></p>'), 'Chuột gaming')

    def test_unescapes_entities(self):
        self.assertEqual(strip_rich_text('<p>DPI &gt; 20000 &amp; nhẹ</p>'), 'DPI > 20000 & nhẹ')

    def test_collapses_whitespace(self):
        self.assertEqual(strip_rich_text('<p>a</p>\n\n<p>b</p>'), 'a b')

    def test_truncates_on_word_boundary(self):
        text = strip_rich_text('<p>' + 'alpha beta ' * 50 + '</p>', limit=20)
        self.assertTrue(text.endswith('...'))
        self.assertLessEqual(len(text), 24)

    def test_empty_input(self):
        self.assertEqual(strip_rich_text(''), '')
        self.assertEqual(strip_rich_text(None), '')


class MoneyTests(SimpleTestCase):
    def test_to_money_rounds_to_integer(self):
        self.assertEqual(to_money('1000000.49'), 1_000_000)

    def test_to_money_none(self):
        self.assertIsNone(to_money(None))


class SerializerTests(TestCase):
    def setUp(self):
        self.category = make_category(slug='chuot', name='Chuột')
        self.brand = make_brand('Logitech')

        self.connectivity = make_group(
            slug='ket-noi', name='Kết nối', categories=[self.category], display_order=20,
        )
        self.form = make_group(
            slug='form-chuot', name='Form chuột', categories=[self.category], display_order=30,
        )
        self.weight = make_group(
            slug='trong-luong', name='Trọng lượng', categories=[self.category], display_order=0,
        )

        self.product = make_product(
            category=self.category,
            brand=self.brand,
            name='Chuột Logitech G502',
            slug='chuot-logitech-g502',
            price='1290000',
            discount_price='990000',
            stock=8,
            rating='4.60',
            description='<p>Chuột gaming cảm biến <strong>Hero 25K</strong></p>',
            product_information='<p>Bảo hành 24 tháng</p>',
            attribute_values=[
                make_value(self.connectivity, value='USB', slug='usb'),
                make_value(self.form, value='Ergonomic', slug='ergonomic'),
                make_value(self.weight, value='121 g', slug='121-g'),
            ],
        )

    def _reload(self):
        return Product.objects.with_related_data().get(pk=self.product.pk)

    def test_final_price_prefers_discount(self):
        self.assertEqual(final_price_of(self._reload()), 990_000)

    def test_to_llm_shape(self):
        payload = to_llm(self._reload())

        self.assertEqual(payload['slug'], 'chuot-logitech-g502')
        self.assertEqual(payload['brand'], 'Logitech')
        self.assertEqual(payload['category'], 'Chuột')
        self.assertEqual(payload['price'], 1_290_000)
        self.assertEqual(payload['final_price'], 990_000)
        self.assertEqual(payload['discount_percent'], 23)
        self.assertTrue(payload['in_stock'])
        self.assertEqual(payload['rating'], 4.6)

    def test_to_llm_summary_is_plain_text(self):
        payload = to_llm(self._reload())
        self.assertNotIn('<', payload['summary'])
        self.assertIn('Hero 25K', payload['summary'])

    def test_to_llm_excludes_ui_only_fields(self):
        payload = to_llm(self._reload())
        for forbidden in ('image', 'url', 'view_count', 'add_to_cart'):
            self.assertNotIn(forbidden, payload)

    def test_to_llm_specs_sorted_by_group_display_order(self):
        payload = to_llm(self._reload())
        self.assertEqual(
            list(payload['key_specs'].keys()),
            ['Trọng lượng', 'Kết nối', 'Form chuột'],
        )

    def test_to_llm_limits_spec_groups(self):
        extra_groups = [
            make_group(slug=f'g{index}', name=f'G{index}',
                       categories=[self.category], display_order=90 + index)
            for index in range(6)
        ]
        for index, group in enumerate(extra_groups):
            self.product.attributes.create(
                attribute_value=make_value(group, value=f'V{index}', slug=f'v{index}')
            )

        payload = to_llm(self._reload())
        self.assertEqual(len(payload['key_specs']), 5)

    def test_to_llm_include_all_specs(self):
        payload = to_llm(self._reload(), include_all_specs=True)

        self.assertEqual(len(payload['key_specs']), 3)
        self.assertEqual(payload['stock'], 8)
        self.assertEqual(payload['extra_info'], 'Bảo hành 24 tháng')
        self.assertTrue(payload['product_code'].startswith('SP'))

    def test_to_ui_shape(self):
        payload = to_ui(self._reload())

        self.assertEqual(payload['url'], '/products/chuot-logitech-g502/')
        self.assertEqual(payload['add_to_cart'], {
            'product_id': self.product.pk,
            'url': '/gio-hang/them/',
        })
        self.assertEqual(payload['final_price'], 990_000)
        self.assertEqual(payload['discount_percent'], 23)
        self.assertEqual(payload['stock'], 8)

    def test_no_discount_product(self):
        product = make_product(
            category=self.category,
            name='Chuột rẻ',
            slug='chuot-re',
            price='200000',
            stock=0,
        )
        reloaded = Product.objects.with_related_data().get(pk=product.pk)

        payload = to_llm(reloaded)
        self.assertEqual(payload['final_price'], 200_000)
        self.assertEqual(payload['discount_percent'], 0)
        self.assertFalse(payload['in_stock'])

    def test_serializers_do_not_trigger_extra_queries(self):
        """Serializer phải sống hoàn toàn trên prefetch của with_related_data()."""
        product = self._reload()

        with self.assertNumQueries(0):
            to_llm(product, include_reviews=True)
            to_ui(product)
