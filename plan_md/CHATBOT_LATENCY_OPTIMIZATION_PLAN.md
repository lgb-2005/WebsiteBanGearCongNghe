# KẾ HOẠCH TỐI ƯU LATENCY (THỜI GIAN PHẢN HỒI), GIẢM TOKEN & XỬ LÝ LỖI 503 CHO CHATBOT AI

## 1. PHÂN TÍCH SỐ LIỆU THỰC TẾ TỪ `ChatTurnLog`

Qua thống kê 9 lượt chat thực tế trong bảng `ChatTurnLog`:
- **Thời gian chạy Tool tại Backend Django + MySQL**: Chỉ mất **6ms – 35ms** (`search_products`: 12–35ms, `compare_products`: 15–16ms, `get_product_detail`: 6ms).
- **Tổng thời gian phản hồi (`latency_ms`)**: Trung bình **~12.257 ms (~12,3 giây)**, dao động từ **7.075 ms đến 34.499 ms**.
- **Số lượng `prompt_tokens`**: Lên tới **5.014 – 5.877 tokens** cho một lượt chat có gọi tool.

### 3 Nguyên nhân gốc rễ gây trễ (Latency cao) và tốn Token:
1. **Chế độ "Thinking" (suy nghĩ ngầm) đang bật mặc định trên dòng model Gemini Flash mới**:
   - Trong `chatbot/providers/gemini.py` (dòng 132–141), `GenerateContentConfig` chưa cấu hình `thinking_config`.
   - Với mỗi lượt chat có gọi tool (`rounds = 2`), Gemini phải chạy chuỗi suy nghĩ ngầm (`thinking`) 2 lần (Vòng 1: suy nghĩ chọn tool → Vòng 2: suy nghĩ viết câu trả lời). Riêng thời gian suy nghĩ ngầm này chiếm **4s – 25s** mỗi lượt.
   - Với bài toán tư vấn sản phẩm đã có sẵn tầng Alias deterministic (`resolver.py`) và dữ liệu JSON có cấu trúc từ Tool, việc tắt hoặc giới hạn `thinking_budget = 0` sẽ giúp model phản hồi ngay lập tức mà vẫn giữ nguyên độ chính xác.
2. **Đang gửi cả dữ liệu giao diện (`ui_results`, `ui_products`, `ui_product`, `ui_suggestions`) vào `tool_payload` cho Gemini**:
   - Trong `chatbot/engine.py` (dòng 223–232), toàn bộ `tool_result['result']` được truyền thẳng vào `LLMMessage(role='tool', tool_payload=tool_result['result'])`.
   - Dù `serializers.py` đã tách riêng bản gọn cho LLM (`results`/`products`) và bản giàu cho UI (`ui_results`/`ui_products` chứa đường dẫn ảnh, URL, thông tin giỏ hàng), cả hai đều nằm chung trong dict kết quả của tool. Việc gửi cả phần `ui_*` (và `rows_same` trùng lặp khi so sánh) lên Gemini khiến `prompt_tokens` bị phình to không cần thiết, làm chậm thời gian xử lý của LLM.
   - Ngoài ra, khi `search_products` không tìm thấy kết quả chính xác và kích hoạt `relaxation` (`recover_no_results`), các sản phẩm gợi ý nằm trong `result['relaxation']['ui_results']` hiện chưa được `_extract_products_and_comparison` lấy ra để hiển thị thẻ sản phẩm (Product Cards) trên giao diện.
3. **Chưa có cơ chế tự động Retry ngắn khi gặp lỗi `503 UNAVAILABLE (high demand)` từ máy chủ Google**:
   - Như ghi nhận tại log `ID=5`, máy chủ Gemini đôi lúc trả về lỗi tạm thời `503 UNAVAILABLE: This model is currently experiencing high demand`.
   - Hiện tại `gemini.py` mới chỉ xử lý retry cho mã `429 (Quota)`, còn lỗi `503` bị văng `ProviderError` ngay lập tức ở lần thử đầu tiên.

---

## 2. CHI TIẾT GIẢI PHÁP KỸ THUẬT (3 HẠNG MỤC)

### Hạng mục 1: Tắt / Tối ưu `thinking_config` và Retry lỗi tạm thời `503` trong `chatbot/providers/gemini.py`

**File tác động**: `techgear/settings.py`, `chatbot/providers/gemini.py`

1. **Thêm cấu hình `CHATBOT_THINKING_BUDGET` trong `techgear/settings.py`**:
   ```python
   CHATBOT_THINKING_BUDGET = _env_int('CHATBOT_THINKING_BUDGET', 0)
   ```
   - Mặc định bằng `0` (tắt suy nghĩ ngầm để ưu tiên tốc độ phản hồi nhanh 2s–4s). Nếu đặt `< 0` (ví dụ `-1`) thì giữ mặc định của model.
2. **Cập nhật `_call_api` trong `chatbot/providers/gemini.py`**:
   - Khởi tạo `types.ThinkingConfig(thinking_budget=thinking_budget)` khi `thinking_budget is not None and thinking_budget >= 0`.
   - Có cơ chế fallback an toàn: nếu model không hỗ trợ `thinking_config` (trả lỗi `400`), tự động gọi lại không kèm `thinking_config`.
3. **Bổ sung tự động Retry ngắn cho lỗi tạm thời `503 UNAVAILABLE` / `500` / `504` trong `GeminiProvider.generate()`**:
   - Thêm tham số `max_transient_retries=2` (mặc định bật).
   - Khi gặp `APIError` có `code in (500, 503, 504)` hoặc chuỗi `'unavailable'`, `'high demand'`, `'overloaded'` trong thông báo lỗi:
     - Tự động chờ ngắn (`1.5s` ở lần 1, `3.0s` ở lần 2) rồi thử lại trước khi báo lỗi.

```python
config_kwargs = {
    'system_instruction': system_prompt,
    'tools': _convert_tools(tools),
}
if self.thinking_budget is not None and self.thinking_budget >= 0:
    config_kwargs['thinking_config'] = types.ThinkingConfig(
        thinking_budget=self.thinking_budget,
    )
config = types.GenerateContentConfig(**config_kwargs)
```

---

### Hạng mục 2: Lọc bỏ dữ liệu UI (`_strip_ui_fields`) trước khi gửi `tool_payload` cho Gemini trong `chatbot/engine.py`

**File tác động**: `chatbot/engine.py`

1. **Viết hàm static `_strip_ui_fields(tool_result: dict) -> dict` trong `ChatEngine`**:
   - Tạo bản sao gọn của `tool_result` dành riêng cho LLM (`llm_payload`), loại bỏ hoàn toàn các trường chỉ phục vụ giao diện:
     - `ui_results`
     - `ui_product`
     - `ui_products`
     - `ui_suggestions`
   - Nếu trong `tool_result` có nhánh `relaxation` (là `dict`), cũng loại bỏ `relaxation['ui_results']` trong bản gửi cho LLM (chỉ giữ `relaxation['results']`, `applied`, `dropped_filters`, `strategy`).
   - Với `compare_products`, loại bỏ thêm `rows_same` trong `llm_payload` (vì `products` đã có `key_specs` và bảng UI đã giữ `rows_same`; LLM chỉ cần `products`, `price_row` và `rows_different` để nhận xét điểm khác nhau).
   - Trong `get_product_detail`, loại bỏ `specs` và `recent_reviews` bị trùng ở cấp ngoài cùng (vì bên trong `product` do `to_llm(..., include_all_specs=True, include_reviews=True)` tạo ra đã chứa sẵn toàn bộ `key_specs`, `review_count` và `recent_reviews`).
2. **Cập nhật `_extract_products_and_comparison` trong `ChatEngine`**:
   - Khi `search_products` trả về `ui_results` rỗng nhưng có `relaxation.ui_results`, tự động lấy `relaxation['ui_results']` đưa vào `products` để giao diện vẫn hiển thị Product Cards cho các sản phẩm gợi ý thay thế.
   - Tương tự, khi `get_product_detail` không tìm thấy đúng slug nhưng có `ui_suggestions`, lấy `ui_suggestions` hiển thị lên Product Cards.

```python
_UI_ONLY_KEYS = {'ui_results', 'ui_product', 'ui_products', 'ui_suggestions'}

@classmethod
def _strip_ui_fields(cls, tool_name: str, payload):
    if not isinstance(payload, dict):
        return payload
    cleaned = {
        key: value
        for key, value in payload.items()
        if key not in cls._UI_ONLY_KEYS
    }
    if isinstance(cleaned.get('relaxation'), dict):
        cleaned['relaxation'] = {
            k: v for k, v in cleaned['relaxation'].items()
            if k not in cls._UI_ONLY_KEYS
        }
    if tool_name == 'compare_products':
        cleaned.pop('rows_same', None)
    elif tool_name == 'get_product_detail' and isinstance(cleaned.get('product'), dict):
        cleaned.pop('specs', None)
        cleaned.pop('recent_reviews', None)
    return cleaned
```

---

### Hạng mục 3: Bổ sung Unit Tests kiểm chứng

**File tác động**: `chatbot/tests/test_engine.py`

Thêm các bài test tự động:
1. `test_engine_strips_ui_fields_from_llm_tool_payload`: Kiểm tra `LLMMessage(role='tool')` gửi sang `provider.generate` ở vòng 2 **không** chứa `ui_results`, `ui_products`, `ui_product`, trong khi `response['products']` trả về cho frontend vẫn có đầy đủ dữ liệu UI card.
2. `test_engine_extracts_relaxation_ui_results_when_no_exact_match`: Kiểm tra khi `search_products` rơi vào nhánh `relaxation`, frontend vẫn nhận được danh sách `products` gợi ý từ `relaxation['ui_results']`.
3. `test_gemini_provider_retries_on_503_unavailable`: Kiểm tra `GeminiProvider` tự động retry khi gặp lỗi tạm thời `503 UNAVAILABLE` và trả về kết quả thành công ở lần gọi kế tiếp.

---

## 3. TỔNG HỢP FILE THAY ĐỔI & KỲ VỌNG KẾT QUẢ

| STT | File | Nội dung thay đổi |
|---|---|---|
| 1 | `techgear/settings.py` | Thêm cấu hình `CHATBOT_THINKING_BUDGET = _env_int('CHATBOT_THINKING_BUDGET', 0)`. |
| 2 | `chatbot/providers/gemini.py` | Áp dụng `ThinkingConfig(thinking_budget=...)` trong `_call_api` và thêm retry tự động cho lỗi `503/500/504`. |
| 3 | `chatbot/engine.py` | Thêm `_strip_ui_fields()` lọc sạch dữ liệu UI trước khi gửi lên Gemini; cập nhật `_extract_products_and_comparison` lấy cả `relaxation.ui_results`. |
| 4 | `chatbot/tests/test_engine.py` | Bổ sung 3 unit test kiểm tra lọc `tool_payload`, hiển thị card `relaxation`, và retry lỗi `503`. |

### Kỳ vọng cải thiện sau khi triển khai:
- **Giảm `prompt_tokens` ở vòng 2 (sau khi gọi tool)**: Giảm khoảng **35% – 50%** lượng dữ liệu JSON gửi lên Gemini.
- **Giảm `latency_ms` trung bình**: Từ mức **9s – 34s** xuống còn khoảng **2,5s – 5s** cho các câu hỏi gọi tool 2 vòng.
- **Tăng độ ổn định**: Không còn bị đứt quãng ngay lập tức khi server Gemini báo `503 High Demand` thoáng qua.
