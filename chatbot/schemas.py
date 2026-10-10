"""JSON schema cho tool calling provider-agnostic.

Hiện tại dùng cho Gemini, nhưng cố ý giữ format đơn giản để tái sử dụng cho Groq/OpenRouter.
"""

TOOL_SCHEMAS = [
    {
        'name': 'get_catalog_overview',
        'description': 'Lấy tổng quan catalog: danh mục, thương hiệu, khoảng giá, số lượng sản phẩm.',
        'parameters': {
            'type': 'object',
            'properties': {},
        },
    },
    {
        'name': 'get_filter_options',
        'description': 'Lấy các filter hợp lệ cho một danh mục sản phẩm.',
        'parameters': {
            'type': 'object',
            'properties': {
                'category_slug': {
                    'type': 'string',
                    'description': 'Slug danh mục, ví dụ: chuot, ban-phim, tai-nghe.',
                },
            },
            'required': ['category_slug'],
        },
    },
    {
        'name': 'search_products',
        'description': 'Tìm sản phẩm bằng keyword, danh mục, thương hiệu, giá, thuộc tính và tình trạng còn hàng.',
        'parameters': {
            'type': 'object',
            'properties': {
                'keyword': {
                    'type': 'string',
                    'description': 'Keyword tự do để tìm theo tên, mã sản phẩm, thương hiệu, mô tả.',
                },
                'category_slug': {
                    'type': 'string',
                    'description': 'Slug danh mục.',
                },
                'brand_name': {
                    'oneOf': [
                        {'type': 'string'},
                        {'type': 'array', 'items': {'type': 'string'}},
                    ],
                    'description': 'Tên thương hiệu, không phải slug. Có thể là string hoặc list string.',
                },
                'price_min': {
                    'type': 'number',
                    'description': 'Giá thấp nhất tính theo VND.',
                },
                'price_max': {
                    'type': 'number',
                    'description': 'Giá cao nhất tính theo VND.',
                },
                'attributes': {
                    'type': 'object',
                    'description': 'Map {group_slug: [value_slug,...]}. Chỉ dùng slug có thật trong DB.',
                    'additionalProperties': {
                        'type': 'array',
                        'items': {'type': 'string'},
                    },
                },
                'in_stock': {
                    'type': 'boolean',
                    'description': 'Nếu true thì chỉ lấy sản phẩm còn hàng.',
                },
                'sort_by': {
                    'type': 'string',
                    'enum': ['relevance', 'price_asc', 'price_desc', 'rating', 'popular'],
                    'description': 'Cách sắp xếp kết quả.',
                },
                'limit': {
                    'type': 'integer',
                    'minimum': 1,
                    'maximum': 8,
                    'description': 'Số sản phẩm tối đa cần lấy.',
                },
            },
        },
    },
    {
        'name': 'get_product_detail',
        'description': 'Lấy chi tiết một sản phẩm, bao gồm thông số và review mới nhất.',
        'parameters': {
            'type': 'object',
            'properties': {
                'slug': {
                    'type': 'string',
                    'description': 'Slug sản phẩm.',
                },
                'product_code': {
                    'type': 'string',
                    'description': 'Mã sản phẩm kiểu SPXXXXXXX.',
                },
            },
        },
    },
    {
        'name': 'compare_products',
        'description': 'So sánh từ 2 đến 4 sản phẩm theo giá và thông số khác nhau/giống nhau.',
        'parameters': {
            'type': 'object',
            'properties': {
                'slugs': {
                    'type': 'array',
                    'items': {'type': 'string'},
                    'minItems': 2,
                    'maxItems': 4,
                    'description': 'Danh sách slug sản phẩm cần so sánh.',
                },
            },
            'required': ['slugs'],
        },
    },
]


def get_tool_schema(name):
    for schema in TOOL_SCHEMAS:
        if schema['name'] == name:
            return schema
    raise KeyError(name)
