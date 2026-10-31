# KẾ HOẠCH CẢI THIỆN ĐỊNH DẠNG & HIỂN THỊ CÂU TRẢ LỜI CHATBOT AI

## 1. MỤC TIÊU & VẤN ĐỀ HIỆN TẠI

### 1.1 Vấn đề đang gặp phải
1. **Câu trả lời từ Gemini thường dính thành khối văn bản dài (wall of text)**:
   - `SYSTEM_PROMPT` trong `chatbot/prompts.py` mới chỉ hướng dẫn chung chung (*"Trả lời ngắn gọn, thân thiện, tối đa 3–4 câu khi có kết quả"*, *"Dùng Markdown cơ bản: in đậm tên sản phẩm, gạch đầu dòng nếu cần"*).
   - AI thường lặp lại toàn bộ tên, giá, đường dẫn raw `/products/slug/` và nhiều thông số trong cùng một đoạn văn, gây trùng lặp với phần **Product Cards** và **Compare Table** đã được render ngay bên dưới bubble chat.
2. **Bộ xử lý `renderMarkdown()` trong `static/js/chatbot.js` quá sơ sài**:
   - Chưa hỗ trợ cú pháp link Markdown `[Tên SP](/products/slug/)` (khiến chuỗi link bị in thô ra màn hình).
   - Chưa hỗ trợ danh sách đánh số (`1. `, `2. `) hoặc đầu dòng bằng ký tự `•`.
   - Lệnh `.replace(/\n/g, '<br>')` chạy đè lên cả khối `<ul>...</ul>`, sinh ra các thẻ `<br>` thừa nằm giữa các thẻ `<li>`, làm hỏng bố cục danh sách.
   - Chưa tách đoạn văn `<p>` rõ ràng giữa câu mở đầu, danh sách sản phẩm và câu gợi ý cuối.
3. **CSS của Bubble Chat & Bảng so sánh trong `static/css/chatbot.css` chưa tối ưu**:
   - Các mục `<li>` và đoạn văn trong `.chatbot-bubble` sát nhau, thiếu khoảng nghỉ thị giác (`margin-bottom`).
   - Điểm nhấn quan trọng (`<strong>`, giá tiền) chưa nổi bật so với chữ thường.
   - Bảng so sánh đang dùng rule `.chatbot-compare-table tbody:not(.show-all) tr:nth-child(n+2) { display: none; }` khiến toàn bộ các dòng thông số khác biệt (`rows_different`) bị ẩn mất, chỉ hiện đúng dòng Giá.

### 1.2 Mục tiêu sau khi nâng cấp
- Câu trả lời của AI ngắn gọn, có cấu trúc phân tầng rõ ràng theo từng tình huống (Tìm kiếm danh sách / Chi tiết 1 sản phẩm / So sánh sản phẩm / Không có kết quả).
- Không lặp lại thông tin thừa đã có trên thẻ sản phẩm hoặc bảng so sánh; không chèn đường dẫn raw URL gây rối mắt.
- Giao diện bubble chat hiển thị đẹp mắt các danh sách gạch đầu dòng, đoạn văn, link Markdown, tô nổi bật tên sản phẩm và giá tiền.
- Bảng so sánh hiển thị mặc định đầy đủ dòng **Giá** + các dòng **Thông số khác nhau (`rows_different`)**, chỉ thu gọn các dòng **Thông số giống nhau (`rows_same`)**.

---

## 2. CHI TIẾT TRIỂN KHAI THEO 3 HẠNG MỤC

### Hạng mục 1: Chuẩn hóa cấu trúc trả lời trong `chatbot/prompts.py`

**File tác động**: `chatbot/prompts.py`

Cập nhật phần `ĐỊNH DẠNG TRẢ LỜI` trong hằng số `SYSTEM_PROMPT` thành khuôn mẫu (template) cụ thể cho từng kịch bản:

```python
ĐỊNH DẠNG TRẢ LỜI (BẮT BUỘC TUÂN THỦ ĐỂ DỄ ĐỌC):
- Luôn chia câu trả lời thành các phần tách biệt bằng xuống dòng, tuyệt đối KHÔNG viết thành một đoạn văn dài liền mạch.
- Giá tiền luôn định dạng kiểu Việt Nam (VD: 1.200.000đ).
- KHÔNG chèn đường dẫn raw URL (như /products/slug/) vào văn bản vì giao diện bên dưới đã tự động hiển thị thẻ sản phẩm có sẵn nút bấm. Nếu thật sự cần gắn link thì bắt buộc dùng cú pháp Markdown [Tên sản phẩm](/products/slug/).

1. Khi tư vấn / tìm thấy danh sách sản phẩm (search_products):
   - Dòng mở đầu: 1 câu ngắn gọn xác nhận nhu cầu của khách.
   - Danh sách gợi ý (tối đa 3–4 sản phẩm tiêu biểu nhất), mỗi sản phẩm 1 dòng gạch đầu dòng theo đúng mẫu:
     - **Tên sản phẩm** (Giá bán): Điểm mạnh nổi bật nhất phù hợp với nhu cầu (VD: switch êm, pin lâu, siêu nhẹ 54g).
   - Dòng kết: 1 câu gợi ý hành động tiếp theo (VD: "Bạn có muốn mình so sánh chi tiết 2 mẫu nào trong số này không?").

2. Khi tư vấn chi tiết 1 sản phẩm (get_product_detail):
   - Trình bày thành các gạch đầu dòng rõ ràng:
     - **Giá bán & Tình trạng**: Giá hiện tại (kèm % giảm nếu có) và tình trạng còn hàng/hết hàng.
     - **Thông số nổi bật**: Tóm tắt 3–4 thông số quan trọng nhất từ key_specs.
     - **Đánh giá nhanh**: Ưu điểm chính và sản phẩm này phù hợp nhất với nhu cầu/đối tượng nào.

3. Khi so sánh sản phẩm (compare_products):
   - KHÔNG liệt kê lại toàn bộ thông số kỹ thuật (vì giao diện bên dưới đã hiển thị bảng so sánh chi tiết).
   - Chỉ tóm tắt ngắn gọn theo gạch đầu dòng mỗi mẫu phù hợp với ai:
     - Chọn **Mẫu A** (Giá) nếu bạn ưu tiên: ...
     - Chọn **Mẫu B** (Giá) nếu bạn thích: ...
   - Kết thúc bằng 1 câu chốt khuyến nghị theo nhu cầu của khách.
```

---

### Hạng mục 2: Nâng cấp bộ render Markdown & Bảng so sánh trong `static/js/chatbot.js`

**File tác động**: `static/js/chatbot.js`

#### 2.1 Viết lại hàm `renderMarkdown(text)`
Thay thế regex đơn lẻ hiện tại bằng hàm xử lý theo dòng/khối an toàn (escape HTML trước, sau đó parse inline & block):
1. **Escape HTML an toàn**: `&`, `<`, `>`, `"`.
2. **Xử lý Inline Markdown (`formatInline`)**:
   - Link Markdown: `[text](/path)` hoặc `[text](https://...)` → `<a href="..." target="_blank" rel="noopener noreferrer">text</a>`.
   - In đậm: `**text**` → `<strong>text</strong>`.
   - In nghiêng: `*text*` → `<em>text</em>`.
   - Code ngắn: `` `text` `` → `<code>text</code>`.
   - Highlight giá tiền tự nhiên (VD: `1.290.000đ`, `850.000đ`, `1,25 triệuđ`) → `<span class="chatbot-price-inline">...</span>`.
3. **Xử lý Block theo từng dòng**:
   - Dòng bắt đầu bằng `- `, `* `, `• ` → gom vào khối `<ul class="chatbot-list"><li>...</li></ul>`.
   - Dòng bắt đầu bằng `1. `, `2. ` → gom vào khối `<ol class="chatbot-list"><li>...</li></ol>`.
   - Tiêu đề ngắn `### ...` hoặc `## ...` → `<div class="chatbot-heading">...</div>`.
   - Các dòng văn bản thông thường → gom thành từng đoạn `<p class="chatbot-paragraph">...</p>` (tách đoạn khi gặp dòng trống, hoặc xuống dòng `<br>` nếu liền kề).
   - **Không** chạy `.replace(/\n/g, '<br>')` toàn cục sau khi đã đóng thẻ `<ul>/<ol>`, triệt tiêu hoàn toàn lỗi thừa khoảng trắng.

#### 2.2 Sửa logic ẩn/hiện dòng trong `renderCompareTable(comparison)`
- Trong `renderCompareTable`:
  - Gắn class `diff-row` cho dòng Giá và các dòng trong `comparison.rows_different`.
  - Gắn class `same-row` cho các dòng trong `comparison.rows_same` (và bỏ dòng `<tr class="same-rows d-none">` thừa ở dòng 165).
- Trong phần `<style>` cuối file (hoặc chuyển hẳn sang `static/css/chatbot.css`):
  - Thay `.chatbot-compare-table tbody:not(.show-all) tr:nth-child(n+2) { display: none; }`
  - Bằng `.chatbot-compare-table tbody:not(.show-all) tr.same-row { display: none; }`
  - Nhờ đó, người dùng luôn thấy ngay **Giá** và **các điểm khác biệt chính** mà không cần bấm mở rộng; nút *"Xem tất cả thông số"* chỉ dùng để mở thêm các thông số giống nhau.

---

### Hạng mục 3: Tinh chỉnh Typography & Layout trong `static/css/chatbot.css`

**File tác động**: `static/css/chatbot.css`

Bổ sung và tinh chỉnh các rule CSS cho nội dung bên trong `.chatbot-bubble`:
1. **Đoạn văn & Danh sách**:
   - `.chatbot-bubble p, .chatbot-paragraph`: `margin: 0 0 8px 0;` (`:last-child { margin-bottom: 0; }`).
   - `.chatbot-bubble ul, .chatbot-bubble ol`: `margin: 6px 0 8px 0; padding-left: 1.25rem;`.
   - `.chatbot-bubble li`: `margin-bottom: 6px; line-height: 1.5;` (`:last-child { margin-bottom: 0; }`).
   - Điểm nhấn đầu dòng (marker) của `ul li::marker`: đổi sang màu cam thương hiệu `var(--cb-orange-2)` để dễ định vị mắt khi đọc danh sách sản phẩm.
2. **Điểm nhấn văn bản (`strong`, giá tiền, heading)**:
   - `.chatbot-bubble strong`: `color: #0f172a; font-weight: 700;`.
   - `.chatbot-price-inline`: `color: var(--cb-orange-2); font-weight: 700; white-space: nowrap;`.
   - `.chatbot-heading`: `font-weight: 700; font-size: 0.96rem; margin: 8px 0 4px 0; color: var(--cb-dark);`.
3. **Bảng so sánh**:
   - Đưa rule `.chatbot-compare-table tbody:not(.show-all) tr.same-row { display: none; }` vào thẳng `chatbot.css` (và xóa đoạn inject `<style>` bằng JS ở cuối `chatbot.js`).

---

## 3. DANH SÁCH FILE SẼ THAY ĐỔI

| STT | File | Nội dung thay đổi |
|---|---|---|
| 1 | `chatbot/prompts.py` | Cập nhật `SYSTEM_PROMPT` với template định dạng câu trả lời chi tiết cho 3 kịch bản (`search_products`, `get_product_detail`, `compare_products`) và quy tắc không chèn raw URL. |
| 2 | `static/js/chatbot.js` | Viết lại `renderMarkdown()` hỗ trợ `<p>`, `<ul>`, `<ol>`, link `[text](url)`, highlight giá tiền; sửa class `same-row` trong `renderCompareTable()`. |
| 3 | `static/css/chatbot.css` | Thêm style cho `.chatbot-paragraph`, `.chatbot-bubble li`, `li::marker`, `.chatbot-price-inline`, `.chatbot-heading` và rule ẩn/hiện `.same-row` của bảng so sánh. |

---

## 4. KIỂM THỬ & NGHIỆM THU (VERIFICATION)

1. **Chạy bộ unit test hiện có của app `chatbot`**:
   ```bash
   python -m pytest chatbot/tests/
   ```
   Đảm bảo toàn bộ 104/104 test hiện tại vẫn pass 100% (không làm gãy logic `build_system_prompt` hay `ChatEngine`).
2. **Kiểm tra hiển thị thực tế trên giao diện Widget**:
   - **Test case 1 (Tìm kiếm danh sách)**: Bấm quick prompt *"Tư vấn chuột gaming dưới 1 triệu"* → Câu trả lời có 1 câu mở đầu, danh sách bullet 3–4 mẫu với **Tên sản phẩm** in đậm + giá tô cam + điểm mạnh ngắn gọn, 1 câu hỏi gợi ý cuối, bên dưới là danh sách Product Cards.
   - **Test case 2 (Chi tiết sản phẩm)**: Hỏi chi tiết 1 mẫu cụ thể → Hiển thị rõ 3 gạch đầu dòng: Giá & Tình trạng, Thông số nổi bật, Đánh giá nhanh.
   - **Test case 3 (So sánh 2 sản phẩm)**: Yêu cầu so sánh 2 mẫu → AI tóm tắt ngắn gọn *"Chọn Mẫu A nếu..., Chọn Mẫu B nếu..."*, bảng so sánh bên dưới hiển thị sẵn dòng Giá và các dòng thông số khác nhau (`rows_different`).
