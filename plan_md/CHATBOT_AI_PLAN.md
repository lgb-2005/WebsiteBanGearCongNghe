# KẾ HOẠCH PHÁT TRIỂN CHATBOT AI TƯ VẤN SẢN PHẨM — TECHGEAR

## 1. NGỮ CẢNH DỰ ÁN

### 1.1 Tech stack hiện tại

| Thành phần | Giá trị |
|---|---|
| Framework | Django 5.2.13 |
| Database | MySQL 8 (`tg1`, localhost:3306) |
| Frontend | Django Templates + vanilla JS (không SPA, không DRF) |
| Auth | Custom user `accounts.User`, `USERNAME_FIELD = 'email'`, không có `username` |
| Rich text | `django_ckeditor_5` (optional, có guard `CKEDITOR_AVAILABLE`) |
| Apps | `core`, `accounts`, `products`, `cart`, `orders`, `analytics` |
| Locale | `LANGUAGE_CODE = 'vi'`, `TIME_ZONE = 'Asia/Ho_Chi_Minh'`, `USE_TZ = False` |

### 1.2 Schema liên quan (đã khảo sát)

**`products/models.py`**

- `Category(BaseModel)` — self-FK `parent`, `name`, `slug` (auto-gen trong `save()`).
- `Brand` — chỉ có `name` (unique), `db_table = "brands"`. **Không có slug.**
- `Product(BaseModel)` — `slug`, `product_code` (auto `SP` + 7 ký tự), `name`, `description` (HTML), `product_information` (HTML), `price`, `discount_price`, `stock`, `brand` (FK nullable), `category` (FK PROTECT), `image_url`, `view_count`, `rating`, `is_active`, `deleted_at`.
  - Property: `main_image`, `image_urls`, `discount_percent`.
  - Manager: `Product.objects` = `ProductManager` từ `ProductQuerySet`.
- `ProductQuerySet.with_related_data()` — select_related `brand`, `category`; prefetch `images`, `reviews__user`, `attributes` (đã sort theo `group__display_order`).
- `ProductQuerySet.filter_by_attributes(**filters)` — nhận `{group_slug: [value_slug, ...]}`, OR trong cùng group, AND giữa các group, có `.distinct()`.
- **EAV 3 tầng**: `AttributeGroup` (`slug`, `display_order`, `filter_type`, `data_type`, `is_filterable`, `is_active`, M2M `categories`) → `AttributeValue` (`group` FK, `value`, `slug`, `display_order`, `is_active`, `hex_color`) → `ProductAttribute` (`product`, `attribute_value`, `custom_value`, property `resolved_value`).
- `AttributeGroup.get_filter_groups_for_category(category)` — classmethod đã xử lý cha/con + prefetch values active.
- `ProductImage` — `product` FK, `image`.
- `ProductReview(BaseModel)` — `user`, `product`, `rating`, `comment`, `is_visible`, unique `(user, product)`.
- `Favorite` — `user`, `product`, unique together.

**`orders/models.py`**

- `Customer(BaseModel)` — `user` OneToOne **nullable**, `full_name`, `email`, `phone`.
- `Order(BaseModel)` — `order_code` (unique), `customer` FK **nullable** (hỗ trợ guest), `receiver_name`, `receiver_phone`, `receiver_email`, `shipping_address`, `total_price`, `status`, `payment_method`, `payment_status`, `tracking_number`. Có property `effective_customer_name/email/phone`.
- `OrderItem(BaseModel)` — `order`, `product`, `quantity`, `price`.

**`cart/models.py`**

- `CartItem(BaseModel)` — `user` nullable + `session_id` (pattern hỗ trợ guest → **chatbot sẽ copy pattern này**), `product`, `quantity`.

### 1.3 Cạm bẫy đã phát hiện — PHẢI tuân thủ

| # | Cạm bẫy | Cách xử lý |
|---|---|---|
| T1 | `Order` **không có** field `user`. | Check quyền qua `order.customer.user_id == request.user.id`. Guest order có `customer = None`. |
| T2 | `Brand` không có `slug`. | Tool nhận `brand_name` (string), lọc `brand__name__iexact` hoặc `brand__name__in`. |
| T3 | `description` / `product_information` là **HTML CKEditor**. | Luôn `django.utils.html.strip_tags` + `html.unescape` + collapse whitespace trước khi đưa vào prompt. |
| T4 | MySQL: Django **không** hỗ trợ FULLTEXT native (`SearchVector` chỉ cho Postgres). | MVP dùng `icontains` đa field + scoring thủ công. FULLTEXT (`RunSQL` tạo index + raw `MATCH...AGAINST`) đẩy sang V2. |
| T5 | EAV khiến `compare_products` dễ N+1. | Bắt buộc `with_related_data()`, không bao giờ loop query trong Python. |
| T6 | Soft delete qua `is_active` + `deleted_at`. | **Mọi** query sản phẩm phải có `.filter(is_active=True, deleted_at__isnull=True)`. |
| T7 | `Favorite.__str__` dùng `self.user.username` nhưng `User.username = None`. | Bug có sẵn, **không thuộc scope chatbot**. Chỉ ghi nhận, không sửa trong phạm vi này. |
| T8 | Không có DRF. | Dùng plain Django `JsonResponse` + `@require_POST` + CSRF token. |
| T9 | Free tier Gemini có hạn (~1.500 req/ngày). | Rate limit + cache là **bắt buộc ở MVP**, không để V2. |
| T10 | **Không tồn tại group `usage`** (gaming/office). | Alias "gaming"/"văn phòng" **không map được sang attribute** → map sang `keyword` search hoặc `category_slug`. |
| T11 | `slugify` của Django **loại bỏ ký tự `Đ/đ`**: `Đen`→`en`, `Đỏ`→`o`, `Đối xứng`→`oi-xung`, `thiết bị di động`→`thiet-bi-di-ong`. | **Tuyệt đối không suy luận slug từ tiếng Việt.** Alias phải dùng slug *copy nguyên văn* từ Phụ lục A. |
| T12 | **Dữ liệu EAV bẩn**: `thoi-luong-pin` chứa `Gasket Mount giờ`; `chong-on` chứa `1.3mm±0.30mm`, `32 Ohm`; `snr` có `110-db` / `110db` / `110db-2` trùng nghĩa. | `get_filter_options` dùng **whitelist group sạch** (`CLEAN_GROUPS`) khi gợi ý cho LLM. Group bẩn chỉ hiện khi user hỏi trực tiếp. |
| T13 | `data_type` **khai báo sai so với dữ liệu**: `chong-on`/`microphone`/`rung`/`chan-de` khai `boolean` nhưng chứa text tự do; `dpi` khai `number` nhưng value là string `"25000 DPI"`. | **Không** làm numeric range filter trên EAV. Range chỉ áp dụng cho `Product.price`. DPI/pin xử lý như text match. |
| T14 | `loai-tay-cam` gắn cho **cả** `ban-phim` và `tay-cam` (lỗi dữ liệu). | Không sửa dữ liệu trong scope này. Tool cứ đọc theo DB; ghi nhận trong báo cáo. |
| T15 | `venv/` **hỏng** (trỏ tới Python 3.13 của user `Admin` không còn tồn tại). Môi trường thật: **Python 3.14 hệ thống, Django 6.0.6, MariaDB** (không phải Django 5.2.13 / MySQL 8 như header settings ghi). `django_ckeditor_5` **chưa cài** → `CKEDITOR_AVAILABLE = False`. | Mọi lệnh dùng `python` (hệ thống), **không** dùng `venv\Scripts\python.exe`. |

---

## 2. KIẾN TRÚC

### 2.1 Quyết định: Tool Calling, KHÔNG phải RAG vector

Dữ liệu TechGear là **có cấu trúc** (giá, tồn kho, EAV). Vector search sẽ trả lời sai các truy vấn kiểu "chuột dưới 1 triệu còn hàng". Vì vậy:

```
User message
    │
    ▼
Django view  ──► rate limit ──► load history (10 msg) 
    │
    ▼
Alias/Rule layer (tầng 1)  ← luật cứng, deterministic, test được
    │  (nếu chưa rõ ý)
    ▼
Gemini 2.0 Flash (tầng 2)  ← suy luận mềm + quyết định gọi tool
    │
    ├──► functionCall ──► Tool registry ──► Django ORM ──► functionResponse
    │         (lặp tối đa 3 vòng)
    ▼
Final answer (text) + products[] (UI serializer) + comparison{}
    │
    ▼
ChatTurnLog (audit)  +  Message (persist)
    │
    ▼
JS widget: markdown + product card + compare table
```

### 2.2 Tầng alias/rule — thiết kế 2 tầng (theo góp ý #1)

**Lý do**: để 100% cho LLM map ý → filter thì không ổn định, khó test, tốn token, khó giải thích trong báo cáo.

File: `chatbot/intent/aliases.py`

**Mỗi alias trả về 1 trong 4 loại kết quả** (vì không phải ý nào cũng map được sang EAV — xem T10):

| Loại | Ý nghĩa | Ví dụ |
|---|---|---|
| `attributes` | cặp `(group_slug, value_slug)` **chính xác theo Phụ lục A** | "không dây" → `ket-noi: [wireless, bluetooth, 24ghz]` |
| `category` | gợi ý `category_slug` | "bàn phím cơ" → `ban-phim` |
| `keyword` | đẩy vào keyword search (khi EAV không có group tương ứng) | "gaming" → keyword `gaming` |
| `sort` | gợi ý `sort_by` | "rẻ nhất" → `price_asc`, "bán chạy" → `popular` |

```python
# chatbot/intent/aliases.py  — slug COPY NGUYÊN VĂN từ DB, không tự suy luận (T11)

CATEGORY_ALIASES = {
    'ban-phim':   ['bàn phím', 'ban phim', 'keyboard', 'phím cơ', 'phim co', 'kb'],
    'chuot':      ['chuột', 'chuot', 'mouse'],
    'tai-nghe':   ['tai nghe', 'headphone', 'headset', 'tai phone', 'earbud'],
    'microphone': ['micro', 'microphone', 'mic', 'thu âm'],
    'tay-cam':    ['tay cầm', 'tay cam', 'gamepad', 'controller', 'joystick', 'vô lăng'],
}

ATTRIBUTE_ALIASES = {
    'wireless':  {'keywords': ['không dây', 'khong day', 'wireless', 'bluetooth', '2.4ghz'],
                  'attributes': {'ket-noi': ['wireless', '24ghz', '24ghz-wireless', 'bluetooth']}},
    'wired':     {'keywords': ['có dây', 'co day', 'wired', 'dây', 'usb'],
                  'attributes': {'ket-noi': ['usb', 'type-c']}},
    'jack_35':   {'keywords': ['jack 3.5', '3.5mm', 'cắm jack'],
                  'attributes': {'ket-noi': ['35mm']}},
    'compact':   {'keywords': ['nhỏ gọn', 'nho gon', 'compact', 'tkl', 'mini', '75%', '65%'],
                  'attributes': {'layout': ['tkl', '65', '75']}},
    'fullsize':  {'keywords': ['fullsize', 'full size', 'đầy đủ', '104 phím'],
                  'attributes': {'layout': ['fullsize', '96']}},
    'linear':    {'keywords': ['êm', 'silent', 'yên tĩnh', 'linear', 'red switch', 'switch đỏ'],
                  'attributes': {'switch': ['linear', 'red', 'red-switch']}},
    'tactile':   {'keywords': ['tactile', 'brown', 'switch nâu', 'khấc'],
                  'attributes': {'switch': ['tactile', 'brown']}},
    'clicky':    {'keywords': ['clicky', 'blue', 'switch xanh', 'tiếng click'],
                  'attributes': {'switch': ['blue', 'gl-low-profile-clicky']}},
    'rgb':       {'keywords': ['rgb', 'led', 'đèn', 'chroma', 'nhiều màu'],
                  'attributes': {'den-led': ['rgb', 'led-rgb', '6-zone-razer-chroma-rgb', 'yes']}},
    'anc':       {'keywords': ['chống ồn', 'chong on', 'anc', 'khử ồn'],
                  'attributes': {'chong-on': ['co', 'app-adjustable-hybrid-anc']}},
    'has_mic':   {'keywords': ['có mic', 'kèm mic', 'mic đàm thoại'],
                  'attributes': {'microphone': ['co']}},
    'over_ear':  {'keywords': ['over ear', 'trùm tai', 'full tai'],
                  'attributes': {'loai-tai-nghe': ['over-ear', 'on-ear']}},
    'in_ear':    {'keywords': ['in ear', 'nhét tai', 'true wireless'],
                  'attributes': {'loai-tai-nghe': ['in-ear']}},
    'ergonomic': {'keywords': ['ergonomic', 'ôm tay', 'thuận tay phải'],
                  'attributes': {'form-chuot': ['ergonomic']}},
    'symmetric': {'keywords': ['đối xứng', 'doi xung', 'ambidextrous'],
                  'attributes': {'form-chuot': ['oi-xung']}},   # <-- 'Đối xứng' -> 'oi-xung' (T11)
    'haptic':    {'keywords': ['rung', 'haptic', 'phản hồi rung'],
                  'attributes': {'rung': ['co']}},
    'condenser': {'keywords': ['condenser', 'thu âm phòng', 'studio'],
                  'attributes': {'loai-micro': ['condenser']}},
    'cardioid':  {'keywords': ['cardioid', 'thu 1 hướng', 'một hướng'],
                  'attributes': {'huong-thu-am': ['cardioid', 'unidirectional']}},
    'with_stand':{'keywords': ['kèm chân đế', 'có chân đế', 'arm'],
                  'attributes': {'chan-de': ['co']}},
}

# Không có group 'usage' trong DB (T10) -> các ý này chỉ đẩy vào keyword
KEYWORD_ALIASES = {
    'gaming':  ['gaming', 'chiến game', 'chơi game', 'game', 'fps', 'esport', 'moba'],
    'office':  ['văn phòng', 'van phong', 'office', 'làm việc', 'học tập', 'code'],
    'stream':  ['stream', 'livestream', 'youtube', 'podcast', 'thu âm'],
    'battery': ['pin trâu', 'pin lâu', 'pin khỏe', 'pin bền'],
    'light':   ['siêu nhẹ', 'nhẹ', 'lightweight'],
}

SORT_ALIASES = {
    'price_asc':  ['rẻ nhất', 'giá rẻ', 'tiết kiệm', 'sinh viên', 'bình dân'],
    'price_desc': ['cao cấp', 'đắt nhất', 'flagship', 'xịn nhất'],
    'rating':     ['đánh giá cao', 'tốt nhất', 'review tốt', 'nhiều sao'],
    'popular':    ['bán chạy', 'phổ biến', 'nhiều người mua', 'hot'],
}

# Phân loại chất lượng dữ liệu — 4 tập PHỦ KÍN 29 group trong DB (T12/T13)
CLEAN_GROUPS   = {...}   # 12 group: value hữu hạn, đúng nghĩa -> luôn gợi ý
USABLE_GROUPS  = {...}   # 7 group: text tự do -> chỉ dùng khi user hỏi trực tiếp
BOOLEAN_LIKE_GROUPS = {...}  # 4 group: khai boolean nhưng bẩn -> chỉ 'co'/'khong'
DIRTY_GROUPS   = {...}   # 6 group: chứa rác -> KHÔNG bao giờ gợi ý

SUGGESTABLE_GROUPS = CLEAN_GROUPS | set(BOOLEAN_LIKE_GROUPS)   # gợi ý cho LLM
FILTERABLE_GROUPS  = SUGGESTABLE_GROUPS | USABLE_GROUPS        # được phép filter
```

**Parser giá tiếng Việt** (`parse_price`) — làm ở tầng rule, deterministic, không tốn token:

| Mẫu câu | Kết quả |
|---|---|
| `dưới 1 triệu` / `dưới 2tr` / `dưới 500k` | `(None, X)` |
| `trên 2 triệu` / `từ 1tr trở lên` | `(X, None)` |
| `từ 1 đến 2 triệu` / `500k - 1 triệu` | `(X, Y)`, tự sort nếu ngược |
| `tầm 1 triệu` / `khoảng 1,5 triệu` | `(0.8X, 1.2X)` |
| `dưới 1.500.000` | nhận dấu phân cách nghìn kiểu VN |
| `có 2 nút` / `26000 dpi` | `(None, None)` — chặn bởi `_MIN_PLAUSIBLE_PRICE = 1000` |

**Quy tắc vận hành (BẮT BUỘC)**

1. `resolve_aliases(text)` chạy **trước** khi gọi LLM, trả về dict:
   `{"attributes": {...}, "category_slug": str|None, "keywords": [...], "sort_by": str|None, "matched": [alias_key...]}`
2. **Normalize trước khi match**: lowercase + strip dấu. `đ`/`Đ` phải **replace thủ công** sang `d` vì `unicodedata.NFD` **không** tách được. Match theo **ranh giới từ** (`(?<![0-9a-z])kw(?![0-9a-z])`), không phải substring thuần — nếu không thì `mic` sẽ khớp trong `microphone` và `game` khớp trong `gamepad`.
2b. **Giải xung đột alias** (`ALIAS_CONFLICTS`): khi 2 alias đối lập cùng match (`wireless` vs `wired`, `compact` vs `fullsize`...), giữ alias **xuất hiện SỚM HƠN** trong câu, vì người dùng nói ý chính trước ("bàn phím nhỏ gọn, không cần fullsize"). Cùng vị trí thì giữ keyword dài hơn.
   > Hạn chế đã biết: tầng rule **không hiểu phủ định**. Heuristic vị trí xử lý được phần lớn; phần còn lại để LLM ở tầng 2 sửa.
3. Filter từ alias được **validate ngược với DB** (`validate_filters_against_db`): chỉ giữ cặp `(group_slug, value_slug)` tồn tại thật, `is_active=True`, **và group đó có gắn với category đang xét**. Cặp không hợp lệ → bỏ + `logger.warning`, **không** raise.
4. Kết quả alias đưa vào prompt như **gợi ý**, model vẫn có quyền bỏ nếu ngữ cảnh không phù hợp.
5. Nếu **không** match → để LLM tự suy luận, nhưng bắt buộc gọi `get_filter_options` trước để biết slug hợp lệ.
6. Alias dictionary phải có **unit test riêng** (≥30 input tiếng Việt → expected output). Đây là phần số liệu đẹp cho báo cáo.
7. **Khi dữ liệu DB thay đổi** (thêm `AttributeValue` mới), chạy lại dump ở Phụ lục A và cập nhật alias.

**Không thể** kiểm tra alias chết bằng unit test (test chạy trên DB **rỗng**). Thay vào đó dùng management command chạy trên DB thật:

```powershell
python manage.py chatbot_check_aliases
```

Command kiểm 3 việc: (1) category slug tồn tại, (2) mọi cặp `(group, value)` trong alias tồn tại, (3) 4 tập phân loại group **không giao nhau** và **phủ kín** mọi group trong DB.

### 2.3 Chính sách hỏi lại — clarify ở mức prompt, không phải tool (theo góp ý #2 + A)

Không tạo tool `clarify_intent`. Thay vào đó đưa vào `SYSTEM_PROMPT` dưới dạng **policy**:

```
QUY TẮC HỎI LẠI:
- Nếu người dùng chưa cho biết ĐỦ 2 trong 3 yếu tố sau: (a) loại sản phẩm,
  (b) khoảng giá, (c) nhu cầu sử dụng chính → hãy hỏi lại ĐÚNG MỘT câu ngắn
  gọn nhất để lấy yếu tố quan trọng nhất còn thiếu. TUYỆT ĐỐI không gọi
  search_products trong lượt đó.
- Chỉ hỏi lại tối đa 2 lượt liên tiếp. Sau đó phải tìm kiếm với thông tin
  đang có, dù chưa đầy đủ.
- Không bao giờ tự bịa khoảng giá hay thuộc tính mà người dùng chưa nói.
```

Engine thực thi kèm: biến `clarify_count` trong `Conversation` (hoặc đếm từ history) — nếu đã hỏi lại 2 lượt mà vẫn mơ hồ thì engine **chèn chỉ thị cứng** `"Hãy tìm kiếm ngay với thông tin hiện có."` vào prompt lượt 3.

### 2.4 No-result recovery (theo góp ý B)

Khi `search_products` trả `0` kết quả, **tool tự thực hiện** chuỗi nới lỏng (không giao cho LLM tự đoán), trả về cấu trúc:

```json
{
  "results": [],
  "relaxation": {
    "applied": ["price_max: 1000000 -> 1200000"],
    "dropped_filters": ["rgb"],
    "suggestions": [ {product...}, {product...}, {product...} ]
  }
}
```

**Thứ tự nới lỏng (cố định, deterministic, test được)**

1. Nới `price_max` thêm **+20%** (và `price_min` giảm 20%).
2. Bỏ **attribute ít phổ biến nhất** (đếm `ProductAttribute` theo `attribute_value`) — bỏ từng cái một, tối đa 2 cái.
3. Mở rộng category lên **category cha**.
4. Cuối cùng: trả 3 sản phẩm **cùng category, rating cao nhất**.

Mỗi bước dừng ngay khi có `>= 1` kết quả. Tối đa **4 query phụ** để không nổ thời gian phản hồi.

Prompt dặn model diễn giải tự nhiên, ví dụ:
> "Không có mẫu nào dưới 1 triệu vừa không dây vừa có RGB. Nếu tăng lên khoảng 1.2 triệu thì mình có 3 lựa chọn phù hợp."

### 2.5 Hai serializer riêng biệt (theo góp ý C)

File: `chatbot/serializers.py`

**`to_llm(product)`** — tối giản token:

```json
{
  "slug": "chuot-logitech-g502",
  "name": "Chuột Logitech G502 Hero",
  "brand": "Logitech",
  "category": "Chuột",
  "price": 1290000,
  "final_price": 990000,
  "in_stock": true,
  "rating": 4.6,
  "key_specs": {"Kết nối": "Có dây", "DPI": "25600", "Số nút": "11"},
  "summary": "Chuột gaming cảm biến Hero 25K, 11 nút lập trình..."
}
```

- `key_specs`: **tối đa 5** group có `display_order` nhỏ nhất.
- `summary`: `strip_tags(description)` cắt **≤ 200 ký tự**.
- **Không** gửi: `image_url`, `view_count`, `created_at`, `product_code` (trừ khi user hỏi), full description.

**`to_ui(product)`** — giàu thông tin cho render:

```json
{
  "slug": "...", "name": "...", "url": "/products/chuot-logitech-g502/",
  "image": "/media/products/xxx.jpg",
  "price": 1290000, "discount_price": 990000, "discount_percent": 23,
  "rating": 4.6, "review_count": 12,
  "in_stock": true, "stock": 8,
  "add_to_cart": {"product_id": 42}
}
```

Response trả về client gồm cả 2: LLM thấy bản gọn, UI render bản giàu. Message lưu bản `to_ui` vào `Message.products` (JSONField) để reload lại hội thoại vẫn thấy card.

---

## 3. PHẠM VI — MVP vs V2 (ĐÃ CHỐT)

### 3.1 MVP (bắt buộc hoàn thành trước khi làm bất kỳ item V2)

**Tools (5)**
- `get_catalog_overview`
- `get_filter_options`
- `search_products`
- `get_product_detail`
- `compare_products`

**Engine**
- 1 provider: Gemini
- Tool-calling loop tối đa **3** vòng
- History **10** message gần nhất
- System prompt tiếng Việt (có policy hỏi lại)
- Tầng alias/rule 2 tầng

**UI**
- Chat widget (bong bóng góc phải)
- Product card
- Compare table (mặc định chỉ hiện điểm khác biệt)
- Quick prompts

**Safety**
- Rate limit
- Cache tool result
- Validate params
- Strip HTML
- Fallback khi API lỗi/hết quota

**Observability**
- `ChatTurnLog` — log đầy đủ tool call (xem mục 6)

### 3.2 V2 (KHÔNG làm sớm)

- `get_order_status` (cần thiết kế bảo mật 2 yếu tố — xem mục 5.3)
- Groq provider làm fallback
- Personalization: gợi ý theo `Order` history / `Favorite` / `CartItem` / sản phẩm đã xem
- Cross-sell phụ kiện, tư vấn build cấu hình trọn bộ
- SSE streaming
- MySQL FULLTEXT search
- Analytics dashboard cho admin

> **Lý do hoãn personalization**: dễ làm phức tạp logic, khó test đúng/sai, dẫn tới "demo nhiều tính năng nhưng lõi chưa chắc".
> **Lý do hoãn SSE**: giá trị của chatbot này nằm ở *đúng tool / đúng filter / đúng dữ liệu / UI card-compare tốt*, không nằm ở streaming.

---

## 4. ĐẶC TẢ TOOL (MVP)

Mọi tool: hàm thuần Python trong `chatbot/tools/`, nhận kwargs đã validate, trả `dict` JSON-serializable. **Không** nhận `request` trực tiếp — nhận `ctx` (dataclass chứa `user`, `session_id`, `page_context`) để dễ test.

### 4.1 `get_catalog_overview()`

- **Params**: không.
- **Trả về**: cây `Category` 2 cấp (`{name, slug, children[]}`), danh sách `Brand.name`, `price_min`/`price_max` toàn shop, tổng số sản phẩm active.
- **Mục đích**: cho LLM biết shop bán gì → không bịa danh mục.
- **Cache**: 1 giờ.

### 4.2 `get_filter_options(category_slug)`

- **Params**: `category_slug` (bắt buộc).
- **Nguồn**: `AttributeGroup.get_filter_groups_for_category(category)`.
- **Trả về**: `[{group_slug, group_name, data_type, filter_type, values: [{slug, value}]}]`, **chỉ** value `is_active=True`, giới hạn **20 value/group** (ưu tiên `display_order`).
- **Mục đích**: LLM biết slug hợp lệ → không bịa filter.
- **Cache**: 1 giờ, key theo `category_slug`.

### 4.3 `search_products(...)`

| Param | Kiểu | Ghi chú |
|---|---|---|
| `keyword` | string | tìm trong `name`, `product_code`, `brand__name`, `description` (đã strip) |
| `category_slug` | string | |
| `brand_name` | string / list | **theo tên**, không slug (cạm bẫy T2) |
| `price_min` / `price_max` | number | so với **giá hiệu lực** = `COALESCE(discount_price, price)` |
| `attributes` | object | `{group_slug: [value_slug,...]}` → `filter_by_attributes()` |
| `in_stock` | bool | `stock__gt=0` |
| `sort_by` | enum | `relevance` \| `price_asc` \| `price_desc` \| `rating` \| `popular` |
| `limit` | int | default 5, **ép max 8** |

**Keyword search MVP (theo góp ý #5)** — không vector, không FULLTEXT, nhưng tử tế:

```
Q(name__icontains=kw) | Q(product_code__iexact=kw)
| Q(brand__name__icontains=kw) | Q(description__icontains=kw)
```
+ scoring thủ công qua `Case/When`: `product_code` khớp = 100, `name` khớp đầu = 50, `name` chứa = 30, `brand` = 20, `description` = 5. Tách keyword thành token, AND giữa các token khi > 1 token.

**Bắt buộc**:
- `.filter(is_active=True, deleted_at__isnull=True)` (T6)
- `.with_related_data()` (T5)
- `annotate(effective_price=Coalesce('discount_price','price'))` để filter/sort giá cho đúng
- Nếu `0` kết quả → chạy no-result recovery (mục 2.4)
- Trả về **cả** `to_llm[]` và `to_ui[]`
- Cache key của `search_products` phải **hash bằng MD5** từ params đã normalize. Không dùng `repr(dict)` trực tiếp vì sẽ sinh `CacheKeyWarning` trên backend kiểu memcached.

### 4.4 `get_product_detail(slug | product_code)`

- Trả về: full `to_llm` + **toàn bộ** specs group theo `display_order`, `3` review mới nhất (`is_visible=True`) rút gọn 150 ký tự, `review_count`, `avg_rating`.
- Kèm `to_ui` để render card lớn.
- Nếu không tìm thấy → trả `{"found": false, "suggestions": [...]}` (3 sản phẩm tên gần giống).

### 4.5 `compare_products(slugs[])` — chuẩn hoá hiển thị (theo góp ý #4)

- **Params**: `slugs` — **2 đến 4** phần tử. < 2 → báo lỗi có message hướng dẫn; > 4 → cắt còn 4.
- **Thuật toán**:
  1. Load các product bằng `with_related_data()` (1 query).
  2. Gom **union** các `AttributeGroup` xuất hiện ở ít nhất 1 sản phẩm.
  3. **Sắp xếp theo `AttributeGroup.display_order`, rồi `name`** — KHÔNG hardcode thứ tự business. Lý do: `display_order` đã có trong model và admin tự cấu hình được; hardcode sẽ phải sửa code mỗi khi thêm nhóm mới.
  4. Với mỗi group × mỗi product → `ProductAttribute.resolved_value`, thiếu thì `"—"`.
  5. Đánh dấu `is_different = len(set(values)) > 1`.
- **Trả về**:

```json
{
  "products": [ {to_llm...} ],
  "ui_products": [ {to_ui...} ],
  "rows_different": [ {"group": "Kết nối", "values": ["Có dây","Không dây"], "is_different": true} ],
  "rows_same":      [ {"group": "Bảo hành", "values": ["24 tháng","24 tháng"], "is_different": false} ],
  "price_row": {"group": "Giá", "values": [990000, 1450000], "is_different": true}
}
```

- **UI**: mặc định render **`rows_different` + `price_row`**; có nút *"Xem tất cả thông số"* để bung thêm `rows_same`.
- **LLM**: chỉ nhận `rows_different` + `price_row` (tiết kiệm token — phần giống nhau không cần bình luận).

### 4.6 No-result recovery — triển khai thực tế ở `chatbot/tools/recovery.py`

Thứ tự đúng như plan, nhưng có **1 lưu ý theo dữ liệu thật**:

1. **Price relaxation**: nới `price_min` -20%, `price_max` +20%
2. **Attribute relaxation**: bỏ tối đa 2 value có `usage_count` thấp nhất (đếm qua `ProductAttribute`)
3. **Parent category**: chỉ chạy nếu category hiện tại có `parent_id`
4. **Fallback top-rated**: trả top sản phẩm theo `rating`, `view_count`

> **Lưu ý quan trọng**: ở DB hiện tại (Phụ lục A), 5 category đều là **top-level**, nên bước 3 gần như **không có tác dụng ở dữ liệu thật hiện tại**. Vẫn giữ code vì schema `Category.parent` có tồn tại và có thể dùng về sau.

---

## 5. AN TOÀN & CHI PHÍ

### 5.1 Rate limit — `chatbot/throttling.py`

- Key: `user.id` nếu đăng nhập, ngược lại `session_id`.
- Mặc định `CHATBOT_RATE_LIMIT_PER_HOUR = 20`, cấu hình qua `.env`.
- Backend: Django cache (`locmem` dev, Redis nếu có).
- Vượt limit → HTTP 429 + message tiếng Việt thân thiện, **không** gọi Gemini.

### 5.2 Validate & chống prompt injection

- **Không bao giờ** cho LLM sinh SQL thô hoặc tên field. Tool chỉ nhận enum/slug/number đã validate.
- Slug không tồn tại trong DB → bỏ + log warning, **không** raise cho user thấy.
- `limit` ép `min(limit, 8)`; `price_min/max` ép `>= 0`; `slugs` ép độ dài 2–4.
- Nội dung do user nhập **không** được nối vào vị trí system instruction, chỉ vào `role: user`.
- Output của tool được bọc trong `functionResponse`, không trộn vào text prompt.

### 5.3 `get_order_status` — thiết kế bảo mật (V2, theo góp ý #3)

**Vấn đề**: `Order.order_code` có thể bị đoán → chỉ `order_code` là **KHÔNG đủ**, sẽ rò rỉ thông tin khách hàng.

**Quy tắc bắt buộc khi triển khai V2**:

| Trường hợp | Điều kiện truy cập |
|---|---|
| User đã đăng nhập | `order.customer` not null **AND** `order.customer.user_id == ctx.user.id` |
| Guest (`order.customer` null hoặc `customer.user` null) | Yêu cầu **order_code + (receiver_email HOẶC receiver_phone)** khớp chính xác. So sánh email `iexact`, phone sau khi normalize bỏ ký tự không phải số. |
| Không thoả | Trả `{"found": false}` — **thông điệp giống hệt** trường hợp đơn không tồn tại, để tránh enumeration oracle |

Thêm: rate limit riêng cho tool này (vd 5 lần/giờ/session) để chặn brute-force. Log mọi lần thất bại vào `ChatTurnLog`.

### 5.4 Cache

- `get_catalog_overview`, `get_filter_options`: TTL 1 giờ.
- `search_products`: TTL 5 phút, cache key = hash của params đã normalize.
- `get_product_detail`: TTL 10 phút.
- Invalidate: để TTL tự hết (đơn giản, đủ dùng cho khoá luận).

### 5.5 Fallback

| Lỗi | Hành vi |
|---|---|
| Hết quota / 429 từ Gemini | Message: "Trợ lý đang quá tải, bạn thử lại sau ít phút nhé" + link trang danh mục liên quan |
| Timeout (> 20s) | Message xin lỗi + gợi ý quick prompt |
| Tool raise exception | Log full traceback, trả `{"error": "..."}` cho LLM để nó xin lỗi tự nhiên, **không** hiện traceback cho user |
| `CHATBOT_ENABLED=false` | Ẩn widget hoàn toàn ở template |

---

## 6. OBSERVABILITY — `ChatTurnLog` (theo góp ý #7)

Model riêng, **có ở MVP** vì là nguồn số liệu cho phần thực nghiệm khoá luận.

```
ChatTurnLog(BaseModel)
  conversation      FK
  user_message      TextField
  resolved_aliases  JSONField   # output tầng 1
  tool_calls        JSONField   # [{name, params, result_size_bytes, duration_ms, cache_hit}]
  loop_rounds       PositiveSmallIntegerField
  provider          CharField   # "gemini"
  model_name        CharField   # "gemini-2.0-flash"
  prompt_tokens     IntegerField null
  completion_tokens IntegerField null
  latency_ms        IntegerField
  final_answer      TextField
  status            CharField   # ok | rate_limited | api_error | tool_error | timeout
  error_detail      TextField blank
```

Đăng ký vào Django admin với `list_display` = (`created_at`, `provider`, `loop_rounds`, `latency_ms`, `status`) và readonly — tiện xuất số liệu.

**Dùng cho**: debug prompt, so sánh Gemini vs Groq (V2), viết phần thực nghiệm, đo tỷ lệ gọi tool đúng.

---

## 7. CẤU TRÚC FILE

```
chatbot/
├── __init__.py
├── apps.py                     # ChatbotConfig
├── admin.py                    # Conversation, Message, ChatTurnLog (readonly)
├── models.py                   # Conversation, Message, ChatTurnLog
├── migrations/
├── urls.py                     # app_name = 'chatbot'
├── views.py                    # chat_api, history_api, new_conversation_api
├── engine.py                   # ChatEngine: vòng lặp tool-calling
├── prompts.py                  # SYSTEM_PROMPT (vi) + build_context_block()
├── schemas.py                  # JSON Schema khai báo 5 tool cho Gemini
├── serializers.py              # to_llm(), to_ui(), strip_rich_text()
├── throttling.py               # check_rate_limit(ctx)
├── context.py                  # @dataclass ChatContext(user, session_id, page_context)
├── intent/
│   ├── __init__.py
│   ├── aliases.py              # CATEGORY/ATTRIBUTE/KEYWORD/SORT_ALIASES + 4 tập group
│   └── resolver.py             # normalize, parse_price, resolve_aliases,
│                               # validate_filters_against_db
├── management/commands/
│   └── chatbot_check_aliases.py   # đối chiếu alias với DB THẬT
├── providers/
│   ├── __init__.py
│   ├── base.py                 # LLMProvider (ABC): generate(messages, tools) -> LLMResult
│   ├── gemini.py               # GeminiProvider
│   └── exceptions.py           # QuotaExceeded, ProviderTimeout, ProviderError
├── tools/
│   ├── __init__.py
│   ├── registry.py             # TOOL_REGISTRY: name -> callable
│   ├── catalog.py              # overview, filter_options, search, detail
│   ├── compare.py              # compare_products + chuẩn hoá row
│   ├── recovery.py             # no-result relaxation ladder
│   └── orders.py               # (V2) get_order_status
└── tests/
    ├── __init__.py
    ├── factories.py            # helper tạo Category/Group/Value/Product
    ├── test_intent.py          # normalize, parse_price, resolve_aliases, validate
    ├── test_search.py
    ├── test_compare.py
    ├── test_recovery.py
    ├── test_serializers.py
    ├── test_throttling.py
    └── test_engine.py          # mock provider, không gọi API thật

static/
├── css/chatbot.css
└── js/chatbot.js

templates/chatbot/
├── widget.html                 # include vào templates/base.html
└── _message_templates.html     # <template> cho card + compare table
```

---

## 8. MODELS CHI TIẾT

```
Conversation(BaseModel)
  user         FK(accounts.User, null=True, blank=True, on_delete=SET_NULL)
  session_id   CharField(255, null=True, blank=True, db_index=True)   # pattern từ CartItem
  title        CharField(255, blank=True)                            # auto từ msg đầu, 60 ký tự
  is_active    BooleanField(default=True)
  Meta: ordering = ('-updated_at',), index (user, -updated_at), (session_id, -updated_at)

Message(BaseModel)
  ROLE_CHOICES = [('user','User'),('assistant','Assistant'),('tool','Tool')]
  conversation  FK(Conversation, related_name='messages', on_delete=CASCADE)
  role          CharField(20, choices=ROLE_CHOICES)
  content       TextField(blank=True)
  tool_name     CharField(100, blank=True)
  tool_payload  JSONField(null=True, blank=True)   # params + result (đã truncate)
  products      JSONField(null=True, blank=True)   # to_ui[] để reload render lại card
  comparison    JSONField(null=True, blank=True)   # bảng so sánh
  token_count   IntegerField(null=True, blank=True)
  Meta: ordering = ('created_at', 'id')
```

**Load history**: `conversation.messages.filter(role__in=['user','assistant']).order_by('-created_at')[:10]` rồi reverse. **Không** đưa `role='tool'` vào history các lượt sau (chỉ dùng trong lượt hiện tại) → tiết kiệm token lớn.

---

## 9. API

### `POST /chatbot/api/message/`

Request:
```json
{
  "message": "tư vấn chuột gaming dưới 1 triệu",
  "conversation_id": 12,
  "page_context": {"type": "product_detail", "slug": "chuot-logitech-g502"}
}
```

Response 200:
```json
{
  "conversation_id": 12,
  "reply": "Với ngân sách dưới 1 triệu...",
  "products": [ {to_ui...} ],
  "comparison": null,
  "meta": {"loop_rounds": 2, "latency_ms": 1840, "tools": ["get_filter_options","search_products"]}
}
```

Response 429 / 503: `{"error": "...", "reply": "<message thân thiện>", "retry_after": 600}`

### `GET /chatbot/api/history/?conversation_id=12`
Trả danh sách message (kèm `products`, `comparison` đã lưu) để restore UI sau reload.

### `POST /chatbot/api/new/`
Tạo conversation mới, trả `conversation_id`.

**Tất cả**: `@require_POST` (trừ history), CSRF token từ cookie, giới hạn `message` ≤ 1000 ký tự.

---

## 10. CẤU HÌNH

`requirements.txt` — thêm:
```
google-genai>=1.0.0
```
> Dùng SDK mới `google-genai`, **không** dùng `google-generativeai` (đã deprecated).

`.env` / `.env.example` — thêm:
```
GEMINI_API_KEY=
GEMINI_MODEL=gemini-2.0-flash
CHATBOT_ENABLED=true
CHATBOT_RATE_LIMIT_PER_HOUR=20
CHATBOT_MAX_TOOL_ROUNDS=3
CHATBOT_HISTORY_LIMIT=10
CHATBOT_TIMEOUT_SECONDS=20
```

`techgear/settings.py`:
- `INSTALLED_APPS += ['chatbot']`
- Đọc các biến trên (dùng helper `_env_bool` có sẵn)
- Thêm `CACHES` nếu chưa có (locmem là đủ cho dev)

`techgear/urls.py`:
- `path('chatbot/', include('chatbot.urls'))`

`templates/base.html`:
- `{% include 'chatbot/widget.html' %}` trước `</body>`, bọc trong `{% if CHATBOT_ENABLED %}` (qua context processor hoặc template tag).

**BẢO MẬT**: `GEMINI_API_KEY` chỉ nằm trong `.env`. `.env` đã có trong `.gitignore` — kiểm tra lại trước commit đầu tiên. `.env.example` chỉ chứa key rỗng.

Lấy API key: https://aistudio.google.com/apikey (miễn phí, không cần thẻ).

---

## 11. LỘ TRÌNH THỰC THI

> Thực hiện **tuần tự**. Không nhảy giai đoạn. Giai đoạn 1–3 **không cần API key** → làm được ngay.

### Giai đoạn 1 — Nền tảng
- [ ] Tạo app `chatbot`, `apps.py`, thêm vào `INSTALLED_APPS`
- [ ] `models.py`: `Conversation`, `Message`, `ChatTurnLog`
- [ ] `makemigrations chatbot` + `migrate`
- [ ] `admin.py` đăng ký 3 model (`ChatTurnLog` readonly)
- [ ] `context.py`: dataclass `ChatContext`
- [ ] Thêm biến env + settings + `.env.example`
- [ ] `requirements.txt`: thêm `google-genai`

### Giai đoạn 2 — Serializer + tầng alias
- [ ] `serializers.py`: `strip_rich_text()`, `to_llm()`, `to_ui()`
- [ ] **Dump slug thực tế** từ DB `tg1` (management command hoặc shell) để làm cơ sở viết alias
- [ ] `intent/aliases.py`: `INTENT_ALIASES` theo slug thật
- [ ] `intent/resolver.py`: `resolve_aliases()` + `validate_filters_against_db()`
- [ ] `tests/test_serializers.py`, `tests/test_aliases.py` (≥ 30 case)

### Giai đoạn 3 — Tầng tool (quan trọng nhất)
- [x] `tools/catalog.py`: `get_catalog_overview`, `get_filter_options`
- [x] `tools/catalog.py`: `search_products` (kèm scoring keyword)
- [x] `tools/recovery.py`: thang nới lỏng 4 bước
- [x] `tools/catalog.py`: `get_product_detail`
- [x] `tools/compare.py`: `compare_products` (tách `rows_different` / `rows_same`)
- [x] `tools/registry.py`: `TOOL_REGISTRY`
- [x] `schemas.py`: JSON Schema 5 tool
- [x] Caching cho các tool
- [x] `tests/test_search.py`, `test_compare.py`, `test_recovery.py`
- [ ] **Kiểm tra số query** bằng `assertNumQueries` để chắc không N+1 *(defer nhỏ: sẽ siết ở vòng refactor Giai đoạn 5/6)*

### Giai đoạn 4 — Engine + provider
- [ ] `providers/base.py`: ABC `LLMProvider`, dataclass `LLMResult`
- [ ] `providers/exceptions.py`
- [ ] `providers/gemini.py`: `GeminiProvider` (map tool schema → Gemini format)
- [ ] `prompts.py`: `SYSTEM_PROMPT` tiếng Việt (gồm policy hỏi lại + no-result)
- [ ] `engine.py`: vòng lặp tool-calling ≤ 3 vòng, ghi `ChatTurnLog`
- [ ] `tests/test_engine.py` với mock provider

### Giai đoạn 5 — API + rate limit
- [ ] `throttling.py`
- [ ] `views.py`: `chat_api`, `history_api`, `new_conversation_api`
- [ ] `urls.py` + nối vào `techgear/urls.py`
- [ ] Fallback handling đầy đủ
- [ ] `tests/test_throttling.py`
- [ ] **Smoke test thật** với API key (lần đầu gọi Gemini)

### Giai đoạn 6 — UI
- [ ] `templates/chatbot/widget.html` + include vào `base.html`
- [ ] `static/css/chatbot.css`
- [ ] `static/js/chatbot.js`: gửi/nhận, render markdown cơ bản, restore history
- [ ] Render product card + nút "Thêm vào giỏ" (nối API cart sẵn có)
- [ ] Render compare table: mặc định chỉ `rows_different`, nút "Xem tất cả thông số"
- [ ] Quick prompts: *Tư vấn theo ngân sách* / *So sánh 2 sản phẩm* / *Sản phẩm bán chạy*
- [ ] Context-aware: trang chi tiết tự truyền `slug` vào `page_context`
- [ ] Trạng thái loading / typing indicator / error state

### Giai đoạn 7 — Kiểm thử & số liệu khoá luận
- [ ] Bộ **30 câu hỏi tiếng Việt** chuẩn (tư vấn, so sánh, lọc giá, mơ hồ, không có kết quả)
- [ ] Đo: độ chính xác tool chọn đúng, latency p50/p95, số vòng loop trung bình, tỷ lệ no-result recovery thành công
- [ ] Xuất số liệu từ `ChatTurnLog`
- [ ] Viết mục thực nghiệm

### Giai đoạn 8 — V2 (chỉ sau khi MVP xong & đã đo số liệu)
- [ ] `tools/orders.py`: `get_order_status` với bảo mật 2 yếu tố (mục 5.3)
- [ ] `providers/groq.py` + auto-fallback khi `QuotaExceeded`
- [ ] So sánh Gemini vs Groq từ `ChatTurnLog`
- [ ] Personalization (lịch sử mua, favorite, đã xem)
- [ ] SSE streaming
- [ ] MySQL FULLTEXT (`RunSQL` index + raw `MATCH...AGAINST`)
- [ ] Analytics dashboard admin

---

## 12. ĐỊNH NGHĨA HOÀN THÀNH (Definition of Done)

MVP được coi là xong khi **tất cả** điều kiện sau thoả:

1. Toàn bộ test trong `chatbot/tests/` pass.
2. Không query nào thiếu `is_active=True, deleted_at__isnull=True`.
3. `compare_products` với 3 sản phẩm chạy trong **≤ 5 query** (kiểm bằng `assertNumQueries`).
4. Chatbot **không bao giờ** nêu giá/tồn kho không khớp DB (kiểm thủ công 10 case).
5. Câu hỏi mơ hồ ("tư vấn chuột") → bot **hỏi lại**, không search ngay.
6. Truy vấn không có kết quả → bot **đề xuất phương án nới lỏng**, không trả lời cụt.
7. Vượt rate limit → trả 429 với message thân thiện, **không** gọi Gemini.
8. Mỗi lượt chat tạo đúng 1 `ChatTurnLog` với `tool_calls` đầy đủ.
9. `GEMINI_API_KEY` không xuất hiện trong bất kỳ file được commit.
10. Widget hoạt động ở cả trạng thái đăng nhập và guest.

---

## 13. TRẠNG THÁI TIẾN ĐỘ

| Giai đoạn | Trạng thái | Ghi chú |
|---|---|---|
| 1. Nền tảng | ✅ **Xong** | App `chatbot` + 3 model + migration `0001_initial` đã applied. `requirements.txt` đã tạo mới. |
| 2. Serializer + alias | ✅ **Xong** | `serializers.py`, `intent/aliases.py`, `intent/resolver.py` (+ `parse_price`), command `chatbot_check_aliases`. **82/82 test pass**, alias khớp 100% DB thật. |
| 3. Tầng tool | ✅ **Xong** | `tools/catalog.py`, `tools/recovery.py`, `tools/compare.py`, `tools/registry.py`, `schemas.py`. **104/104 test pass** toàn app `chatbot`. |
| 4. Engine + provider | ✅ **Xong** | `providers/base.py`, `exceptions.py`, `gemini.py`, `prompts.py`, `engine.py`, `tests/test_engine.py`. 7/7 test pass với mock provider. `google-genai` đã cài. Cần API key thật để smoke test. |
| 5. API + rate limit | ✅ **Xong** | `throttling.py`, `views.py` (chat/history/new), `urls.py`, fallback. 4/4 test pass. Smoke test API thật cần `GEMINI_API_KEY`. |
| 6. UI | ✅ **Xong** | `templates/chatbot/widget.html`, `static/css/chatbot.css`, `static/js/chatbot.js`, include vào `base.html`, context processor `CHATBOT_ENABLED`. |
| 7. Kiểm thử & số liệu | ⏳ Đang thực hiện | Bộ 30 câu hỏi chatbot/eval/questions.json, command chatbot_eval, chatbot_export_logs. Cần GEMINI_API_KEY để chạy đánh giá thật. |
| 8. V2 | ⬜ Chưa bắt đầu | Chỉ sau khi MVP đạt DoD |

**Việc cần người dùng làm**: lấy `GEMINI_API_KEY` tại https://aistudio.google.com/apikey và điền vào `.env` trước Giai đoạn 4.

---

## PHỤ LỤC A — DUMP SCHEMA THẬT (DB `tg1`, 2026-10-09)

> Nguồn chân lý cho mọi slug dùng trong `aliases.py` và test. **Không tự suy luận slug.**
> Lệnh dump lại khi dữ liệu đổi: xem cuối phụ lục.

### A.1 Môi trường thật

| Hạng mục | Giá trị |
|---|---|
| Python | **3.14** hệ thống (`py -0p`) — `venv/` **hỏng**, không dùng |
| Django | **6.0.6** (settings header ghi 5.2.13 — không chính xác) |
| DB | **MariaDB** (cảnh báo `mysql.W002`), schema `tg1` |
| DB driver | `mysqlclient==2.2.8` |
| `django_ckeditor_5` | **Chưa cài** → `CKEDITOR_AVAILABLE = False` |
| UI stack | Bootstrap 5.3.3 CDN + bootstrap-icons 1.11.3 + `static/css/style.css` |
| Test runner | `pytest 9.1.1` + `pytest-django 4.12.0` (có sẵn) |
| Sản phẩm active | **133** |

### A.2 Category (5, tất cả top-level, KHÔNG có cấp con)

`ban-phim` (Bàn phím) · `chuot` (Chuột) · `microphone` (Microphone) · `tai-nghe` (Tai nghe) · `tay-cam` (Tay cầm)

### A.3 Brand (21) — `Brand` không có slug, lọc theo `name`

```
ACER, AKKO, Aolion, Asus, ATK, AULA, BigBig Won, Corsair, DareU, E-Dra,
EasySMX, Elgato, Flydigi, HyperX, Keychron, Logitech, MSI, NZXT, Rapoo,
Razer, Sony
```

### A.4 AttributeGroup (29)

| slug | Tên | data_type | filter_type | order | Áp dụng cho category | Sạch? |
|---|---|---|---|---|---|---|
| `thoi-gian-bao-hanh` | Bảo hành | text | checkbox | 0 | chuot | ⚠️ |
| `cam-bien` | Cảm biến | text | checkbox | 0 | chuot | ⚠️ |
| `keycap` | Keycap | text | checkbox | 0 | ban-phim | ⚠️ |
| `kich-thuoc` | Kích thước | text | checkbox | 0 | chuot | ⚠️ |
| `polling-rate` | Polling Rate | text | checkbox | 0 | chuot | ⚠️ |
| `so-nut` | Số nút | text | checkbox | 0 | chuot | ⚠️ |
| `thoi-luong-pin` | Thời lượng pin | text | checkbox | 0 | chuot | ❌ bẩn |
| `tro-khang` | Trở kháng | text | checkbox | 0 | tai-nghe | ⚠️ |
| `trong-luong` | Trọng lượng | text | checkbox | 0 | chuot | ✅ |
| `den-led` | Đèn LED | text | checkbox | 0 | ban-phim | ✅ |
| `mau-sac` | Màu sắc | text | **color** | 10 | **tất cả 5** | ✅ |
| `ket-noi` | Kết nối | text | checkbox | 20 | **tất cả 5** | ✅ |
| `form-chuot` | Form chuột | text | checkbox | 30 | chuot | ✅ |
| `layout` | Layout | text | radio | 30 | ban-phim | ✅ |
| `loai-micro` | Loại microphone | text | checkbox | 30 | microphone | ✅ |
| `loai-tai-nghe` | Loại tai nghe | text | checkbox | 30 | tai-nghe | ✅ |
| `tuong-thich` | Tương thích | text | checkbox | 30 | chuot, tay-cam | ✅ |
| `chong-on` | Chống ồn | **boolean** | radio | 40 | tai-nghe | ❌ bẩn |
| `dpi` | DPI | **number** | range | 40 | chuot | ⚠️ |
| `huong-thu-am` | Hướng thu âm | text | checkbox | 40 | microphone, tai-nghe | ✅ |
| `loai-tay-cam` | Loại tay cầm | text | radio | 40 | **ban-phim**, tay-cam | ✅ (T14) |
| `switch` | Switch | text | checkbox | 40 | ban-phim | ✅ |
| `dai-tan` | Dải tần đáp ứng | text | range | 50 | microphone, tai-nghe | ⚠️ |
| `microphone` | Microphone | **boolean** | radio | 50 | tai-nghe | ❌ bẩn |
| `rung` | Rung / Haptic | **boolean** | radio | 50 | tay-cam | ✅ |
| `pin` | Pin / Nguồn | text | radio | 60 | ban-phim, tay-cam | ❌ bẩn |
| `do-nhay` | Độ nhạy | text | range | 60 | microphone, tai-nghe | ❌ bẩn |
| `snr` | SNR | text | range | 70 | microphone, tai-nghe | ❌ bẩn |
| `chan-de` | Chân đế kèm theo | **boolean** | radio | 80 | microphone | ✅ |

**Chú thích**: ✅ = dùng trong `CLEAN_GROUPS`; ⚠️ = value tự do nhưng còn dùng được; ❌ = chứa rác, **không** gợi ý cho LLM.

### A.5 AttributeValue của các group SẠCH (dùng trực tiếp trong alias)

```
ket-noi:        24ghz | 24ghz-wireless | 35mm | bluetooth | type-c | usb | wireless | xlr
layout:         2x-32mm-drivers | 65 | 75 | 96 | fullsize | tkl
switch:         50-trieu-lan-nhan | akko-frost-pink | akko-piano-pro | black | blue |
                brown | co-hoc | gateron-ks20 | gateron-ks20-30-10g | gl-low-profile-clicky |
                gl-low-profile-tactile | kailh | kailh-linear-40-8g | kailh-tactile-50-10g |
                linear | low-profile-mechanical-quieter-switch | nimbus-v3-switch |
                reaper-switch | red | red-switch | rog-nx | rog-nx-snow | rog-nx-storm |
                rog-nx-v2 | tactile
den-led:        1-khu-vuc | 6-zone-razer-chroma-rgb | battery | capslock | led-rgb | rgb |
                yes | yes-for-caps-lock-and-game-mode
mau-sac:        bac | cam | en(=Đen) | hong | o(=Đỏ) | tim | trang | vang | xam | xanh |
                xanh-duong | xanh-la
form-chuot:     ergonomic | oi-xung(=Đối xứng)
loai-tai-nghe:  gaming | in-ear | on-ear | over-ear
loai-micro:     condenser | dynamic | gaming | podcast | streaming | usb-microphone
loai-tay-cam:   arcade-stick | controller | gamepad | joystick | steering-wheel | usb-type-c
huong-thu-am:   bidirectional | cardioid | omnidirectional | stereo | unidirectional
rung:           co | khong
chan-de:        co | khong
microphone:     co | khong | 100hz7khz | 32-bit-arm | dual-mems-capsule | khu-on-enc |
                omni-directional-beamforming        <-- chỉ dùng 'co'/'khong'
chong-on:       co | khong | + 8 value rác (1.3mm±0.30mm, 32-ohm, 400mm, ...)
                                                    <-- chỉ dùng 'co'/'khong'
trong-luong:    3-g | 53-g | 54-g | 59-g | 65-g | 80-g | 91-g | 121-g | 173-g | 285-g |
                340-g | 397-g | 1200-g
tuong-thich:    android | ios | linux | linux-kernel-26 | macos | macos-105-tro-len |
                nintendo-switch | pc | ps4 | ps5 | switch | thiet-bi-di-ong | usb-20-port |
                windows | windows-10 | windows-11-or-later | windows-7 | xbox | 8 | 10-tro-len
```

**Bẫy slug đã xác nhận (T11)** — ký tự `Đ/đ` bị `slugify` xoá:

| Giá trị hiển thị | Slug thật |
|---|---|
| `Đen` | `en` |
| `Đỏ` | `o` |
| `Đối xứng` | `oi-xung` |
| `thiết bị di động` | `thiet-bi-di-ong` |
| `Lên đến 100 giờ` | `len-en-100-gio` |
| `Không bật đèn: 95h` | `khong-bat-en-95h` |

### A.6 Endpoint hiện có mà chatbot sẽ nối vào

| Mục đích | URL | Method | Payload | Response |
|---|---|---|---|---|
| Chi tiết sản phẩm | `products:product_detail` → `/products/<slug>/` | GET | – | HTML |
| Danh mục | `products:category_products` → `/danh-muc/<slug>/` | GET | – | HTML |
| **Thêm vào giỏ** | `cart:add_to_cart` → `/gio-hang/them/` | POST | form-encoded `product_id`, `quantity`, header `X-Requested-With: XMLHttpRequest` | `{success, message, cart_count}` |
| Giỏ hàng | `cart:cart_detail` → `/gio-hang/` | GET | – | HTML |

### A.7 Lệnh dump lại schema

```powershell
python manage.py shell -c "from products.models import AttributeGroup, AttributeValue, Category, Brand, Product; print('=== GROUPS ==='); [print(g.slug,'||',g.name,'||',g.data_type,'||',g.filter_type,'||ord=',g.display_order,'||cats=',','.join(g.categories.values_list('slug',flat=True)) or 'ALL') for g in AttributeGroup.objects.order_by('display_order','name')]; print('=== VALUES ==='); [print(v.group.slug,'->',v.slug,'|',v.value) for v in AttributeValue.objects.filter(is_active=True).select_related('group')]; print('=== CATEGORIES ==='); [print(c.slug,'|',c.name,'| parent=',c.parent.slug if c.parent else '-') for c in Category.objects.select_related('parent')]; print('=== BRANDS ==='); print([b.name for b in Brand.objects.all()]); print('products_active=', Product.objects.filter(is_active=True, deleted_at__isnull=True).count())"
```
