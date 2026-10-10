from .catalog import get_catalog_overview, get_filter_options, get_product_detail, search_products
from .compare import compare_products


TOOL_REGISTRY = {
    'get_catalog_overview': get_catalog_overview,
    'get_filter_options': get_filter_options,
    'search_products': search_products,
    'get_product_detail': get_product_detail,
    'compare_products': compare_products,
}


def get_tool(name):
    return TOOL_REGISTRY[name]


def list_tools():
    return list(TOOL_REGISTRY)
