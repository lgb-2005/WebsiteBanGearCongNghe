from .models import Product


class ProductSerializer:
    def __init__(self, product, request=None):
        self.product = product
        self.request = request

    def _build_absolute_uri(self, url):
        if not url:
            return url
        if self.request is not None:
            return self.request.build_absolute_uri(url)
        return url

    def data(self):
        image_urls = []
        for image_url in self.product.image_urls:
            image_urls.append(self._build_absolute_uri(image_url))

        main_image = self.product.main_image
        if hasattr(main_image, 'url'):
            main_image_url = self._build_absolute_uri(main_image.url)
        else:
            main_image_url = main_image

        return {
            'id': self.product.id,
            'name': self.product.name,
            'slug': self.product.slug,
            'description': self.product.description,
            'price': str(self.product.price),
            'discount_price': str(self.product.discount_price) if self.product.discount_price is not None else None,
            'stock': self.product.stock,
            'brand_id': self.product.brand_id,
            'category_id': self.product.category_id,
            'main_image': self._build_absolute_uri(main_image_url) if main_image_url else None,
            'images': image_urls,
        }
