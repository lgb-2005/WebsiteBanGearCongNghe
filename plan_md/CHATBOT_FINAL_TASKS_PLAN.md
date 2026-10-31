# KẾ HOẠCH HOÀN THIỆN 4 HẠNG MỤC CUỐI TRONG BẢNG PHÂN CÔNG CHATBOT AI

## 1. MỤC TIÊU TỔNG QUAN

Hoàn tất 100% các đầu việc còn lại trong bảng phân công của **Nguyễn Hùng Khương** và **Lê Gia Bảo**:

| # | Hạng mục | Người phụ trách | File tác động |
|---|---|---|---|
| 1 | Nâng cấp `parse_price()` hỗ trợ `"1tr5"`, `"1m5"`, `"1 triệu rưỡi"`, `"tầm 2 củ"`, `"không quá 800k"` | Lê Gia Bảo | `chatbot/intent/resolver.py`, `chatbot/tests/test_intent.py` |
| 2 | Bổ sung **Fast-path Rule-based (Pre-search)** giúp giảm từ 2 vòng gọi Gemini xuống **1 vòng duy nhất** cho câu hỏi tư vấn đã rõ ý | Nguyễn Hùng Khương | `chatbot/engine.py`, `chatbot/prompts.py`, `chatbot/tests/test_engine.py` |
| 3 | Kiểm tra N+1 query bằng `assertNumQueries` (compare ≤ 5 query) & sửa cảnh báo `chatbot_check_aliases` | Nguyễn Hùng Khương | `chatbot/intent/aliases.py`, `chatbot/management/commands/chatbot_check_aliases.py`, `chatbot/tools/compare.py`, `chatbot/tests/test_search.py`, `chatbot/tests/test_compare.py` |
| 4 | Bổ sung thống kê `p50 / p95 latency`, số vòng loop trung bình và token usage vào `chatbot_export_logs` | Nguyễn Hùng Khương | `chatbot/management/commands/chatbot_export_logs.py` |

---

## 2. CHI TIẾT KỸ THUẬT TỪNG HẠNG MỤC

### Hạng mục 1: Nâng cấp bộ phân tích giá tiếng Việt `parse_price()` (`chatbot/intent/resolver.py`)

**Vấn đề hiện tại**:
- Regex `_AMOUNT` hiện chỉ bắt dạng `<số> <đơn_vị>` (VD: `1 triệu`, `500k`, `1,5 triệu`).
- Chưa bắt được cách viết tắt rất phổ biến của người Việt:
  - Dạng ghép số lẻ sau đơn vị: **`1tr5`**, **`1m5`**, **`2tr2`**, **`1 triệu 5`**, **`1 củ 5`** (= `1.500.000đ`, `2.200.000đ`).
  - Dạng có chữ **`rưỡi`**: **`1 triệu rưỡi`**, **`1 củ rưỡi`**, **`1tr rưỡi`** (= `1.500.000đ`).
  - Các đơn vị khẩu ngữ: **`củ`** (`cu`), **`m`** (= `1.000.000`), **`lít`** (`lit` = `100.000`).

**Giải pháp chuẩn**:
1. Thêm bước tiền xử lý chuỗi số tiền tiếng Việt `_normalize_shorthand_prices(normalized_text)` trong `resolver.py` trước khi đưa vào các regex `_RANGE_RE`, `_MAX_RE`, `_MIN_RE`, `_AROUND_RE`:
   - Chuyển đổi các dạng ghép sau về dạng thập phân chuẩn `<số>.<lẻ> trieu`:
     - `(\d+)\s*(?:trieu|tr|cu|m)\s*ruoi\b` → `\1.5 trieu` (VD: `"1 củ rưỡi"` → `"1.5 trieu"`).
     - `(\d+)\s*(?:trieu|tr|cu|m)\s*(\d{1,2})\b` (khi theo sau không phải đơn vị khác) → `\1.\2 trieu` (VD: `"1tr5"` → `"1.5 trieu"`, `"2tr25"` → `"2.25 trieu"`, `"1 triệu 5"` → `"1.5 trieu"`).
     - `(\d+(?:[.,]\d+)?)\s*(?:cu|m)\b` → `\1 trieu` (VD: `"tầm 2 củ"` → `"tam 2 trieu"`).
2. Bổ sung `'cu'` và `'m'` vào `_UNIT_MULTIPLIERS` (`1_000_000`).
3. Thêm đầy đủ các test case vào `ParsePriceTests` trong `chatbot/tests/test_intent.py`:
   - `parse_price('chuột tầm 1tr5')` → `(1_200_000, 1_800_000)`
   - `parse_price('bàn phím dưới 1 củ rưỡi')` → `(None, 1_500_000)`
   - `parse_price('tai nghe tầm 2 củ')` → `(1_600_000, 2_400_000)`
   - `parse_price('từ 500k đến 1tr5')` → `(500_000, 1_500_000)`
   - `parse_price('không quá 800k')` → `(None, 800_000)`

---

### Hạng mục 2: Bổ sung Fast-path Rule-based (Pre-search) trong `chatbot/engine.py`

**Vấn đề hiện tại**:
- Khi khách hỏi câu rất rõ ràng như *"Tư vấn chuột gaming không dây dưới 1 triệu"* hoặc *"Bàn phím cơ khoảng 2 triệu"*, tầng 1 (`resolve_aliases`) đã trích xuất chính xác `category_slug`, `price_min/max`, `attributes`, `keywords`.
- Tuy nhiên, `ChatEngine.process()` vẫn phải gọi Gemini **Vòng 1** chỉ để Gemini trả về `function_call: search_products(...)`, sau đó chạy tool rồi mới gọi Gemini **Vòng 2** để sinh câu trả lời. Việc này làm tốn **gấp đôi số request quota** và **gấp đôi thời gian chờ (latency)**.

**Giải pháp chuẩn**:
1. Tạo phương thức `_can_fast_path_search(raw_message: str, resolved_aliases: dict) -> bool` trong `ChatEngine`:
   - Điều kiện kích hoạt Fast-path:
     - Đã nhận diện được `category_slug` trong `resolved_aliases`.
     - Có ít nhất 1 tiêu chí lọc đi kèm: `price_min is not None` hoặc `price_max is not None` hoặc `bool(attributes)` hoặc `bool(keywords)` hoặc `bool(sort_by)`.
     - Câu hỏi **không** mang ý định so sánh hoặc hỏi chi tiết 1 mã cụ thể (không chứa từ khóa `'so sanh'`, `'vs'`, `'chi tiet'`, `'danh gia'`, `'review'`).
2. Khi `_can_fast_path_search` trả về `True` (và `provider` là `GeminiProvider` hoặc bật `enable_fast_path=True`):
   - Tự động gọi tool `search_products` ngay ở tầng Python với các tham số đã resolve (`category_slug`, `keyword`, `price_min`, `price_max`, `attributes`, `sort_by`).
   - Ghi nhận kết quả vào `tool_log_entries` (với flag `'fast_path': True`) để lưu log và trích xuất `products` cho UI.
   - Đính kèm kết quả `llm_payload` (đã qua `_strip_ui_fields`) vào `user_content` gửi cho Gemini kèm chỉ dẫn:
     `[Hệ thống đã tìm kiếm sẵn danh sách sản phẩm khớp nhu cầu từ DB dưới đây. Hãy tư vấn ngay dựa trên dữ liệu này mà KHÔNG cần gọi lại tool search_products:]`
   - Nhờ đó, Gemini trả lời văn bản ngay ở **Vòng 1 (`loop_rounds = 1`)**, giảm **50% latency** và **50% số request API**!
3. Khử trùng lặp sản phẩm trong `_extract_products_and_comparison()` theo `slug` để đảm bảo an toàn tuyệt đối nếu model vẫn gọi thêm tool.

---

### Hạng mục 3: Kiểm tra N+1 Query (`assertNumQueries`) & Sửa `chatbot_check_aliases`

1. **Sửa `chatbot/intent/aliases.py` và `chatbot/management/commands/chatbot_check_aliases.py`**:
   - Trong `aliases.py` (dòng 39): Bỏ slug `'24ghz'` không tồn tại trong DB khỏi `'wireless'` (giữ `['wireless', '24ghz-wireless', 'bluetooth']` khớp 100% với DB thật).
   - Trong `chatbot_check_aliases.py`: Thêm `sys.stdout.reconfigure(encoding='utf-8')` ở đầu `handle()` để chạy trên PowerShell Windows không bị lỗi `UnicodeEncodeError`, đồng thời đảm bảo kết quả in ra: **`Toàn bộ alias khớp với DB`**.
2. **Tối ưu & bổ sung test `assertNumQueries`**:
   - Kiểm tra số lượng query của `compare_products(['a', 'b', 'c'])` (so sánh 3 sản phẩm):
     - Nhờ `with_related_data()` (`select_related('brand', 'category')` + `prefetch_related('images', 'reviews__user', 'attributes__attribute_value__group')`), toàn bộ `compare_products` chỉ tốn đúng **4 queries** (1 query `Product` + 3 query prefetch `images`, `reviews`, `attributes`) — đạt chuẩn **≤ 5 queries**!
   - Thêm hàm缓存 (cache) ngắn cho `compare_products` trong `chatbot/tools/compare.py` để tối ưu thêm tốc độ khi so sánh lại.
   - Thêm test `test_compare_three_products_num_queries_at_most_five` dùng `self.assertNumQueries(4)` vào `chatbot/tests/test_compare.py`.
   - Thêm test `test_search_and_detail_no_n_plus_one_queries` dùng `self.assertNumQueries` vào `chatbot/tests/test_search.py`.

---

### Hạng mục 4: Bổ sung thống kê `p50 / p95 latency`, `avg_rounds`, `token usage` vào `chatbot_export_logs.py`

**File tác động**: `chatbot/management/commands/chatbot_export_logs.py`

- Mở rộng command `python manage.py chatbot_export_logs` để ngoài việc xuất file CSV/JSON, lệnh sẽ tự động tính toán và in ra màn hình bảng thống kê tổng hợp (Metrics Summary) từ `ChatTurnLog`:
  - Tổng số lượt chat & tỉ lệ thành công (`status = ok`).
  - **Latency (ms)**: Trung bình (`avg`), Trung vị **`p50`**, Phân vị **`p95`**, Min, Max.
  - **Tool-calling**: Số vòng lặp trung bình (`avg_loop_rounds`), tỉ lệ lượt chat chỉ tốn 1 vòng.
  - **Token usage**: Trung bình và tổng `prompt_tokens`, `completion_tokens`, tổng token tiêu thụ.

---

## 3. DANH SÁCH FILE SẼ THAY ĐỔI

| STT | File | Nội dung thay đổi |
|---|---|---|
| 1 | `chatbot/intent/resolver.py` | Nâng cấp `parse_price()` hỗ trợ `1tr5`, `1m5`, `1 triệu 5`, `1 củ rưỡi`, đơn vị `củ`, `m`. |
| 2 | `chatbot/intent/aliases.py` | Xóa slug chết `'24ghz'` trong alias `'wireless'`. |
| 3 | `chatbot/management/commands/chatbot_check_aliases.py` | Cấu hình UTF-8 cho stdout để không lỗi font trên Windows terminal. |
| 4 | `chatbot/engine.py` | Thêm cơ chế Fast-path Pre-search (`_can_fast_path_search`) và khử trùng lặp `products` theo `slug`. |
| 5 | `chatbot/tools/compare.py` | Bổ sung cache cho `compare_products`. |
| 6 | `chatbot/management/commands/chatbot_export_logs.py` | Tính toán và in báo cáo `p50`, `p95` latency, `avg_rounds`, `avg_tokens`. |
| 7 | `chatbot/tests/test_intent.py`, `test_search.py`, `test_compare.py`, `test_engine.py` | Bổ sung unit test cho `parse_price` mới, `assertNumQueries` (≤ 5 queries), và Fast-path. |
