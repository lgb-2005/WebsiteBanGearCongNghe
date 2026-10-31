# KẾ HOẠCH TỐI ƯU LOGIC, NGỮ CẢNH MULTI-TURN & GIAO DIỆN CHATBOT AI

## 1. TỔNG QUAN 5 HẠNG MỤC TỐI ƯU

| # | Hạng mục | File tác động | Mức độ ưu tiên |
|---|---|---|---|
| 1 | Khắc phục lỗi gửi lặp 2 lần tin nhắn User lên Gemini ở mỗi lượt chat | `chatbot/engine.py` | Cao (Bug logic & tốn token) |
| 2 | Bổ sung ngữ cảnh `slug` sản phẩm vào lịch sử hội thoại (Multi-turn context) | `chatbot/engine.py` | Cao (Giúp AI nhớ SP ở lượt trước) |
| 3 | Thêm nút "Hội thoại mới / Làm mới" trên Header của Widget | `templates/chatbot/widget.html`, `static/js/chatbot.js` | Trung bình - Cao (UX) |
| 4 | Cộng dồn chính xác `prompt_tokens` và `completion_tokens` qua các vòng gọi tool | `chatbot/engine.py` | Trung bình (Chính xác số liệu khóa luận) |
| 5 | Xử lý từ khóa phủ định ở tầng Alias (`không cần led`, `không thích màu hồng`, ...) | `chatbot/intent/resolver.py` | Trung bình (Tăng độ chính xác tầng 1) |

---

## 2. CHI TIẾT KỸ THUẬT TỪNG HẠNG MỤC

### Hạng mục 1: Khắc phục lỗi gửi lặp 2 lần tin nhắn User lên Gemini

- **Vị trí**: `chatbot/engine.py` (dòng 54–63 và 151–186)
- **Nguyên nhân**:
  1. Dòng 152 gọi `Message.objects.create(conversation=conversation, role=Message.ROLE_USER, content=raw_message)` lưu tin nhắn hiện tại vào DB.
  2. Dòng 179 gọi `history = self._load_history(conversation)` truy vấn `conversation.messages.filter(...)[:HISTORY_LIMIT]` — kết quả trả về **đã bao gồm** tin nhắn vừa tạo ở dòng 152.
  3. Dòng 180 tạo thêm `current_messages = [LLMMessage(role='user', content=user_content)]` rồi nối `provider_messages = history + current_messages` ở dòng 185.
  4. Hệ quả: Cuối danh sách message gửi lên Gemini luôn có 2 message `role='user'` liên tiếp chứa cùng nội dung câu hỏi.
- **Giải pháp chuẩn**:
  - Cập nhật `_load_history(conversation, exclude_message_id=None)`: nếu có `exclude_message_id` thì `.exclude(pk=exclude_message_id)` trước khi cắt `[:HISTORY_LIMIT]`.
  - Hoặc gọi `history = self._load_history(conversation)` **trước khi** `Message.objects.create(...)` cho tin nhắn mới (đồng thời vẫn truyền `exclude_message_id=user_msg.pk` như một lớp bảo vệ kép).

```python
@staticmethod
def _load_history(conversation: Conversation, exclude_message_id: int = None):
    qs = conversation.messages.filter(role__in=[Message.ROLE_USER, Message.ROLE_ASSISTANT])
    if exclude_message_id is not None:
        qs = qs.exclude(pk=exclude_message_id)
    messages = qs.order_by('-created_at', '-id')[:HISTORY_LIMIT]
    ...
```

---

### Hạng mục 2: Giữ ngữ cảnh `slug` sản phẩm giữa các lượt hội thoại (Multi-turn Context)

- **Vị trí**: `chatbot/engine.py` — hàm `_load_history` (dòng 54–63)
- **Nguyên nhân**:
  - Khi khách hỏi ở Lượt 1 (*"Tư vấn chuột gaming dưới 1 triệu"*), `Message` của `assistant` lưu văn bản trả lời vào `content` và danh sách sản phẩm (chứa `name`, `slug`, `final_price`) vào JSONField `products`.
  - Ở Lượt 2, khách hỏi *"So sánh giúp mình 2 mẫu đầu tiên"* hoặc *"Chi tiết mẫu G102"*. Vì `_load_history` chỉ đọc `message.content` (không có `slug`), Gemini không biết `slug` thực tế trong DB để truyền vào `compare_products(slugs=[...])` hoặc `get_product_detail(slug=...)`.
- **Giải pháp chuẩn**:
  - Trong `_load_history`, khi duyệt qua từng `message`: nếu `message.role == Message.ROLE_ASSISTANT` và `message.products` có dữ liệu, tự động nối thêm dòng tóm tắt ngữ cảnh sản phẩm (kèm thứ tự `#1`, `#2`, tên và `slug`) vào cuối `content` của `LLMMessage` gửi cho model (chỉ nối trong bộ nhớ khi gửi cho LLM, **không** sửa `message.content` lưu trong DB nên giao diện người dùng không bị ảnh hưởng):

```python
@staticmethod
def _format_history_content(message: Message) -> str:
    content = message.content or ''
    if message.role == Message.ROLE_ASSISTANT and message.products:
        items = []
        for idx, prod in enumerate(message.products, start=1):
            if isinstance(prod, dict) and prod.get('slug'):
                name = prod.get('name') or prod['slug']
                items.append(f"#{idx} {name} (slug: {prod['slug']})")
        if items:
            note = '[Ngữ cảnh hệ thống - Sản phẩm đã gợi ý ở lượt này: ' + '; '.join(items) + ']'
            content = f'{content}\n{note}' if content else note
    return content
```

---

### Hạng mục 3: Thêm nút "Hội thoại mới / Làm mới" trên Header của Widget

- **Vị trí**:
  - `templates/chatbot/widget.html` (dòng 20–27)
  - `static/js/chatbot.js` (dòng 7–15, 260–332)
- **Nguyên nhân**:
  - Đã có endpoint `POST /chatbot/api/new/` và hàm `createConversation()` trong JS, nhưng thiếu nút bấm trên UI và thiếu hàm reset giao diện khung chat về trạng thái chào mừng ban đầu.
- **Giải pháp chuẩn**:
  1. Trong `templates/chatbot/widget.html`:
     Thêm nút `#chatbot-reset` ngay trước nút `#chatbot-fullscreen` trong `.chatbot-header-actions`:
     ```html
     <button id="chatbot-reset" class="chatbot-header-btn" aria-label="Hội thoại mới" title="Hội thoại mới">
         <i class="bi bi-arrow-clockwise"></i>
     </button>
     ```
  2. Trong `static/js/chatbot.js`:
     - Khai báo `const RESET = document.getElementById('chatbot-reset');` và lưu lại HTML chào mừng ban đầu `const INITIAL_WELCOME_HTML = MESSAGES.innerHTML;`.
     - Viết hàm `resetConversation()`:
       - Xóa `chatbot_conversation_id` cũ trong `localStorage`, đặt `conversationId = null`.
       - Khôi phục `MESSAGES.innerHTML = INITIAL_WELCOME_HTML`, ẩn thông báo lỗi (`setError('')`), ẩn typing (`setTyping(false)`).
       - Gọi `await createConversation()` để lấy `conversation_id` mới từ server.
     - Ngoài ra, tối ưu `openPanel()` bằng biến cờ `historyLoaded` để chỉ gọi API `loadHistory()` đúng 1 lần khi mở widget lần đầu (không gọi lại mỗi khi đóng/mở panel).

---

### Hạng mục 4: Cộng dồn chính xác `prompt_tokens` và `completion_tokens` trong `ChatTurnLog`

- **Vị trí**: `chatbot/engine.py` (dòng 137–138, 189–192, 218–220)
- **Nguyên nhân**:
  - Hiện tại `prompt_tokens` và `completion_tokens` bị gán đè (`=`) ở mỗi vòng lặp, và ở lượt gọi `final_round` (dòng 218 khi chạm trần `MAX_LOOP_ROUNDS`) hoàn toàn chưa lấy `prompt_tokens` / `completion_tokens`.
- **Giải pháp chuẩn**:
  - Viết hàm helper hoặc cộng dồn an toàn qua mọi lần gọi `provider.generate(...)`:
    ```python
    if result.prompt_tokens is not None:
        prompt_tokens = (prompt_tokens or 0) + result.prompt_tokens
    if result.completion_tokens is not None:
        completion_tokens = (completion_tokens or 0) + result.completion_tokens
    ```
  - Bổ sung cộng dồn tương tự cho `final_round` ở dòng 218–220.

---

### Hạng mục 5: Xử lý từ khóa phủ định ở tầng Alias (`chatbot/intent/resolver.py`)

- **Vị trí**: `chatbot/intent/resolver.py` (dòng 51–61 và 177–191)
- **Nguyên nhân**:
  - Khi người dùng nhập câu có ý phủ định như *"bàn phím cơ không cần led"*, *"chuột không thích màu hồng"*, *"tai nghe không dây"* (trong đó chữ `dây` là keyword của `wired`), hàm `_find()` hiện chỉ tìm sự xuất hiện của từ khóa nên vẫn bắt nhầm `rgb` (`led`), `pink` (`màu hồng`), hoặc bắt cả `wired` (`dây`).
- **Giải pháp chuẩn**:
  - Định nghĩa danh sách tiền tố phủ định đã chuẩn hóa (không dấu):
    ```python
    _NEGATION_PREFIX_RE = re.compile(
        r'(?:khong|ko|chua|chang|chan|ghét|ghet|tranh|tru|bo|dung)\s+'
        r'(?:can|thich|muon|co|dung|lay|chon|ua|xai)?\s*$'
    )
    ```
  - Tạo hàm `_is_negated(normalized_text, match_start, normalized_keyword)`:
    - Nếu bản thân `normalized_keyword` đã bắt đầu bằng từ mang nghĩa phủ định/đối lập (như `'khong day'`, `'khong on'`) thì **không** coi là bị phủ định bởi chữ `'khong'` bên trong chính nó.
    - Kiểm tra đoạn văn bản ngay trước `match_start` (khoảng 25 ký tự cuối của `normalized_text[:match_start]`): nếu khớp với `_NEGATION_PREFIX_RE` thì trả về `True` (bị phủ định).
  - Trong `_find(normalized_text, keyword, ignore_negated=False)`:
    - Dùng `finditer` duyệt qua các vị trí khớp ranh giới từ; nếu `ignore_negated=True` và vị trí đó bị `_is_negated(...)` thì bỏ qua, tìm vị trí khớp hợp lệ tiếp theo.
  - Áp dụng `ignore_negated=True` cho `_match_attribute_aliases()` và `_match_keywords()`.
    - Ví dụ 1: `"ban phim co khong can led"` → từ khóa `led` có tiền tố `khong can ` đứng trước → bị bỏ qua, không gợi ý `den-led = rgb`.
    - Ví dụ 2: `"chuot khong day"` →
      - Alias `wireless` có keyword `'khong day'` → tiền tố trước `'khong day'` là `'chuot '` → **hợp lệ (match)**.
      - Alias `wired` có keyword `'day'` → tiền tố trước `'day'` là `'chuot khong '` (khớp `_NEGATION_PREFIX_RE`) → **bị loại bỏ ngay tức khắc**, không cần chờ tới `_resolve_conflicts`.

---

## 3. DANH SÁCH FILE SẼ THAY ĐỔI & BỔ SUNG TEST

| STT | File | Nội dung thay đổi |
|---|---|---|
| 1 | `chatbot/engine.py` | Sửa `_load_history()` (tránh lặp message user + đính kèm ngữ cảnh `slug` sản phẩm từ `message.products`); cộng dồn `prompt_tokens` & `completion_tokens` qua mọi vòng gọi tool. |
| 2 | `chatbot/intent/resolver.py` | Bổ sung kiểm tra phủ định (`_NEGATION_PREFIX_RE`, `_is_negated`) vào `_find()` khi khớp attribute alias và keyword alias. |
| 3 | `templates/chatbot/widget.html` | Thêm nút `#chatbot-reset` ("Hội thoại mới") trên thanh header của widget. |
| 4 | `static/js/chatbot.js` | Xử lý sự kiện click `#chatbot-reset` (reset khung chat về trạng thái welcome + tạo conversation mới) và tránh gọi `loadHistory()` lặp lại không cần thiết khi đóng/mở panel. |
| 5 | `chatbot/tests/test_engine.py` | Thêm unit test kiểm tra: (a) không gửi lặp user message trong `provider_messages`, (b) lịch sử lượt sau có chứa `slug` sản phẩm của lượt trước, (c) cộng dồn `prompt_tokens` / `completion_tokens` qua 2 vòng gọi. |
| 6 | `chatbot/tests/test_intent.py` | Thêm unit test kiểm tra phủ định: `"bàn phím cơ không cần led"`, `"chuột không thích màu hồng"`, `"chuột không dây"`. |

---

## 4. CÁC BƯỚC KIỂM THỬ & NGHIỆM THU

1. Chạy toàn bộ bộ test tự động bằng lệnh:
   ```bash
   .\venv\Scripts\python.exe -m pytest chatbot/tests/
   ```
   Đảm bảo 100% test cũ và các test mới cho 5 hạng mục đều **PASS**.
2. Kiểm tra lệnh đối chiếu alias với DB thật:
   ```bash
   .\venv\Scripts\python.exe manage.py chatbot_check_aliases
   ```
3. Kiểm tra thực tế trên giao diện:
   - Hỏi *"Tư vấn chuột gaming dưới 1 triệu"* → Sau khi có kết quả, hỏi tiếp *"So sánh 2 mẫu đầu tiên"* → AI lấy đúng `slug` của 2 mẫu vừa hiển thị để gọi `compare_products`.
   - Bấm nút **Hội thoại mới** (`↻`) trên header widget → Khung chat xóa lịch sử cũ, hiện lại lời chào và tạo `conversation_id` mới.
