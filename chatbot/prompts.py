"""System prompt + helper xây dựng context cho chatbot."""

SYSTEM_PROMPT = """Bạn là trợ lý tư vấn sản phẩm của TechGear, một cửa hàng chuyên bàn phím, chuột, tai nghe, microphone và tay cầm chơi game.

NHIỆM VỤ CHÍNH:
- Hiểu nhu cầu khách hàng tiếng Việt.
- Gọi công cụ (tool) để lấy dữ liệu sản phẩm CHÍNH XÁC từ database.
- TUYỆT ĐỐI KHÔNG tự bịa giá, tồn kho, thông số hay đánh giá. Mọi con số phải từ tool.
- Trả lời ngắn gọn, thân thiện, tối đa 3–4 câu khi có kết quả.

CÔNG CỤ CÓ THỂ DÙNG:
- get_catalog_overview: khi khách hỏi chung chung "cửa hàng bán gì".
- get_filter_options(category_slug): để biết các filter hợp lệ trước khi search.
- search_products: tìm sản phẩm theo keyword, danh mục, giá, thương hiệu, thuộc tính.
- get_product_detail(slug): khi khách hỏi chi tiết 1 sản phẩm.
- compare_products(slugs): khi khách muốn so sánh 2–4 sản phẩm.

QUY TẮC GỌI TOOL:
- Nếu ý định của khách rõ ràng (có loại sản phẩm + khoảng giá/ngân sách hoặc mục đích), hãy gọi search_products ngay.
- Nếu ý định chưa rõ hoặc khách hỏi "có gì", gọi get_catalog_overview hoặc get_filter_options trước.
- Chỉ gọi tối đa 1 tool trong mỗi lượt.

QUY TẮC HỎI LẠI (CLARIFY):
- Nếu khách chưa cho đủ 2 trong 3 yếu tố: (a) loại sản phẩm, (b) khoảng giá/ngân sách, (c) mục đích sử dụng chính → hãy hỏi lại ĐÚNG MỘT câu ngắn gọn nhất để lấy yếu tố quan trọng nhất còn thiếu.
- Chỉ hỏi lại tối đa 2 lượt liên tiếp. Sau đó dù thiếu thông tin cũng phải tìm kiếm với những gì đang có.
- KHÔNG tự bịa khoảng giá hay thuộc tính.

KHI KHÔNG CÓ KẾT QUẢ:
- Nếu tool trả về danh sách rỗng hoặc có "relaxation", hãy diễn giải tự nhiên theo gợi ý nới lỏng (ví dụ: tăng ngân sách một chút, bỏ filter ít quan trọng).
- Không bao giờ nói "không có" một cách cụt ngủn.

ĐỊNH DẠNG TRẢ LỜI:
- Dùng Markdown cơ bản: in đậm tên sản phẩm, gạch đầu dòng nếu cần.
- Giá luôn định dạng kiểu Việt Nam (VD: 1.200.000đ).
- Nếu cung cấp link, chỉ nên là đường dẫn tương đối (/products/slug/).

{context_block}

GỢI Ý TỪ HỆ THỐNG (alias đã nhận diện, có thể bỏ qua nếu không khớp ngữ cảnh):
{aliases}
""".strip()


FORCED_SEARCH_PROMPT = """Đã hỏi lại 2 lượt. Hãy tìm kiếm ngay với thông tin hiện có, đừng hỏi thêm."""


def _format_price(value):
    if value is None:
        return 'chưa rõ'
    try:
        value = int(value)
        if value >= 1_000_000:
            return f'{value / 1_000_000:.2f} triệu'.replace('.', ',') + 'đ'
        return f'{value:,}đ'.replace(',', '.')
    except (ValueError, TypeError):
        return str(value)


def _format_aliases(resolved):
    if not resolved:
        return 'Không nhận diện được alias nào.'

    lines = []
    cat = resolved.get('category_slug')
    if cat:
        lines.append(f'- Danh mục gợi ý: {cat}')

    attrs = resolved.get('attributes') or {}
    if attrs:
        for group, values in attrs.items():
            lines.append(f'- Thuộc tính gợi ý: {group} = {", ".join(values)}')

    keywords = resolved.get('keywords') or []
    if keywords:
        lines.append(f'- Keyword gợi ý: {", ".join(keywords)}')

    sort = resolved.get('sort_by')
    if sort:
        lines.append(f'- Sắp xếp gợi ý: {sort}')

    price_min = resolved.get('price_min')
    price_max = resolved.get('price_max')
    if price_min is not None or price_max is not None:
        if price_min is not None and price_max is not None:
            lines.append(f'- Khoảng giá: {_format_price(price_min)} - {_format_price(price_max)}')
        elif price_max is not None:
            lines.append(f'- Giá tối đa: {_format_price(price_max)}')
        else:
            lines.append(f'- Giá tối thiểu: {_format_price(price_min)}')

    return '\n'.join(lines) or 'Không nhận diện được alias nào.'


def _build_context_block(page_context):
    if not page_context:
        return 'Bạn đang ở trang chủ hoặc không có ngữ cảnh trang cụ thể.'

    page_type = page_context.get('type')
    if page_type == 'product_detail':
        slug = page_context.get('slug') or 'không rõ'
        return f'Người dùng đang xem trang chi tiết sản phẩm: {slug}. Có thể trả lời nhanh về sản phẩm này hoặc so sánh với sản phẩm khác.'

    if page_type == 'category':
        slug = page_context.get('slug') or 'không rõ'
        return f'Người dùng đang xem danh mục: {slug}.'

    return 'Bạn đang ở một trang khác trong website.'


def build_system_prompt(resolved_aliases=None, page_context=None):
    context_block = _build_context_block(page_context)
    aliases = _format_aliases(resolved_aliases)
    return SYSTEM_PROMPT.format(
        context_block=context_block,
        aliases=aliases,
    )


def build_forced_search_message():
    return FORCED_SEARCH_PROMPT
