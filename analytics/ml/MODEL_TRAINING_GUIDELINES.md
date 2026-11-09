# HƯỚNG DẪN KỸ THUẬT & QUY TẮC HUẤN LUYỆN MÔ HÌNH DỰ ĐOÁN Ý ĐỊNH MUA HÀNG (`MODEL TRAINING & INFERENCE GUIDELINES`)

> **Mục đích tài liệu:** Tài liệu này cung cấp ngữ cảnh bắt buộc cho AI Agent và lập trình viên khi triển khai giai đoạn **Huấn luyện mô hình (`Model Training`)**, **Đánh giá (`Evaluation`)** và **Tích hợp suy luận thời gian thực trên Website TechGear (`Web Inference Adapter`)**.
>
> **Nguyên tắc bất khả xâm phạm (Zero-Regression Rule):**
> - **KHÔNG ĐƯỢC** sửa đổi hoặc làm hỏng cấu trúc 14 cột đặc trưng đầu ra (`SESSION_FEATURE_COLUMNS`) của Data Pipeline Tuần 3 trong `analytics/ml/config.py`, `analytics/ml/preprocess.py`, `analytics/ml/features.py` và 31 unit tests trong `analytics/tests.py`.
> - **KHÔNG CẦN** chạy lại quá trình lọc 23 GB CSV gốc. Mọi bước chuẩn hóa nâng cao, xử lý nhiễu ngoại lai (outliers), đặc trưng dẫn xuất (derived features) và tương thích miền dữ liệu (domain adaptation) phải được thực hiện bên trong **Model Pipeline (`train.py` / `transformers.py`)** và **Inference Adapter (`predictor.py`)**.

---

## 1. Bối cảnh Bài toán & Định nghĩa Khung thời gian Dự báo (Prediction Horizon)

### 1.1 Bản chất bài toán hiện tại: In-Session Purchase Intent Prediction
- **Đơn vị mẫu (`Unit of Analysis`):** Cấp độ phiên truy cập (`user_session`), không phải cấp độ tài khoản dài hạn (`user_id`).
- **Nhãn mục tiêu (`will_purchase` $\in \{0, 1\}$):** Dự đoán xác suất khách hàng sẽ thực hiện hành động thanh toán (`purchase` / `checkout`) **ngay trong phiên truy cập hiện tại** dựa trên các hành vi quan sát được trước thời điểm mua hàng đầu tiên (`event_time < first_purchase_time`).
- **Lý do kiến trúc này phù hợp với Website TechGear:**
  - Trên hệ thống thực tế (`analytics/models.py` & `analytics/services.py`), phần lớn lưu lượng truy cập là khách vãng lai chưa đăng nhập (`user=None`), nhưng luôn có định danh phiên `analytics_session_id`.
  - Dự báo ở cấp độ `user_session` cho phép kích hoạt hành động thời gian thực (Chatbot chủ động tư vấn, gợi ý sản phẩm, cảnh báo bỏ giỏ hàng) cho 100% người truy cập web.

### 1.2 Nguồn dữ liệu đầu vào đã kết xuất sẵn từ Data Pipeline
- **Tập Train (`2019-Oct.csv` + `2019-Nov.csv`):** `analytics/ml/artifacts/session_features.csv`
  - Tổng số phiên: `2,648,705` (`will_purchase = 1`: `126,473` phiên — `4.7749%`; `will_purchase = 0`: `2,522,232` phiên; tỷ lệ mất cân bằng `1 : 19.94`).
- **Tập Test độc lập theo thời gian (`Out-of-Time Test Set` — `2019-Dec.csv`):** `analytics/ml/artifacts/session_test_features.csv`
  - Tổng số phiên: `1,786,352` (`will_purchase = 1`: `55,760` phiên — `3.1214%`; `will_purchase = 0`: `1,730,592` phiên; tỷ lệ mất cân bằng `1 : 31.04`).
- **Schema 16 cột cố định (`OUTPUT_COLUMNS`):**
  ```text
  user_session, view_count, unique_products, unique_categories, cart_count,
  remove_cart_count, session_duration_sec, avg_price, max_price, min_price,
  repeat_view_ratio, cart_to_view_ratio, hour, day_of_week, is_weekend, will_purchase
  ```

---

## 2. Phân tích 6 Hệ lụy Tiềm ẩn trong Dữ liệu & Giải pháp Kỹ thuật Bắt buộc

Khi triển khai code huấn luyện và suy luận, AI Agent **bắt buộc** phải xử lý 6 vấn đề thực nghiệm được phát hiện từ báo cáo thống kê `rp_03_pipeline_stats.md` dưới đây:

---

### Vấn đề 1 & 5: Nhiễu ngoại lai cực đoan (`Extreme Outliers`) ở `session_duration_sec` và Thiên lệch độ dài phiên (`Right-Censoring / Cutoff Bias`)

#### Lý do chi tiết & Số liệu chứng minh
1. **Nhiễu ngoại lai do cookie phiên không tự đóng:**
   - Trong tập Train (`rp_03_pipeline_stats.md` dòng 88), `session_duration_sec` có trung vị `Median = 22.0 giây`, phân vị thứ 95 `P95 = 979.0 giây` (~16.3 phút), nhưng giá trị cực đại lên tới `Max = 4,920,199.0 giây` (**~57 ngày**) và độ lệch chuẩn `Std = 26,049.18 giây`.
   - Nguyên nhân: `user_session` trên Kaggle là chuỗi cookie trình duyệt; một số người dùng treo tab hoặc giữ cookie qua nhiều tuần khiến thời lượng phiên vọt lên hàng triệu giây.
2. **Thiên lệch cắt ngưỡng (`Cutoff Bias`) giữa lớp `0` và lớp `1`:**
   - Với phiên mua hàng (`will_purchase = 1`), cơ chế chống rò rỉ dữ liệu (`Anti-Leakage Cutoff`) đã cắt bỏ toàn bộ sự kiện từ thời điểm `first_purchase_time` trở về sau.
   - Ngược lại, với phiên không mua (`will_purchase = 0`), toàn bộ sự kiện được giữ nguyên đến tận lúc kết thúc phiên.
   - Hệ quả trên số liệu thực tế: Nhóm không mua (`0`) có `session_duration_sec` trung bình (`907.69s`) **cao gấp 3.75 lần** nhóm có mua (`241.88s`), và số sản phẩm xem duy nhất `unique_products` trung bình của nhóm không mua (`2.4031`) cũng **cao hơn** nhóm có mua (`2.0837`).
   - Nếu đưa dữ liệu thô vào mô hình (đặc biệt là Logistic Regression, SVM, MLP hoặc `StandardScaler`), bộ chuẩn hóa sẽ bị méo hoàn toàn bởi các phiên 57 ngày, và mô hình sẽ học định kiến sai lầm: *"Thời gian ở lại trang càng lâu hoặc xem càng nhiều sản phẩm thì xác suất mua càng giảm"*.

#### Giải pháp bắt buộc khi Train & Inference
Đặt một bước biến đổi tiền xử lý (`FeatureClipAndLogTransformer`) ở đầu `scikit-learn Pipeline`:
1. **Cắt trần thời lượng phiên (`Winsorizing / Clipping`):**
   - Giới hạn `session_duration_sec` trong đoạn `[0.0, 3600.0]` (tối đa 1 giờ = 3600 giây) hoặc phân vị `P99` của tập Train:
     ```python
     session_duration_sec = np.clip(session_duration_sec, 0.0, 3600.0)
     ```
   - Việc cắt trần ở `3600s` loại bỏ hoàn toàn các phiên treo tab nhiều ngày ở nhóm `0`, đưa trung bình của nhóm `0` về sát thực tế và cân bằng với cửa sổ quan sát của nhóm `1`.
2. **Biến đổi Logarit (`np.log1p`) cho các đặc trưng đếm và thời lượng lệch phải (`Right-Skewed`):**
   - Áp dụng `np.log1p(x)` cho: `view_count`, `unique_products`, `unique_categories`, `cart_count`, `session_duration_sec`, `cart_to_view_ratio`.
   - Giảm độ nhạy của mô hình với độ dài tuyệt đối của phiên, giúp mô hình dự đoán ổn định ngay cả khi phiên truy cập trên web đang diễn ra nửa chừng (real-time prefix session).
3. **Sử dụng `RobustScaler` thay vì `StandardScaler`:**
   - Đối với các mô hình tuyến tính (như Logistic Regression), bắt buộc dùng `RobustScaler()` (chuẩn hóa theo `Median` và `IQR`) để miễn nhiễm với ngoại lai.

---

### Vấn đề 2: Sự thống trị tuyệt đối của `cart_count` (Nguy cơ suy biến thành luật `if cart_count > 0`)

#### Lý do chi tiết & Số liệu chứng minh
- Trong `rp_03_pipeline_stats.md` (Bảng 4 của cả Tập Train và Tập Test):
  - Các đặc trưng duyệt (`view_count`, `unique_products`, `unique_categories`, `hour`, `day_of_week`) có phân phối giữa lớp `0` và lớp `1` rất gần nhau (`view_count` Median đều bằng `2.0`, Mean `3.706` vs `3.745`).
  - Trong khi đó, `cart_count` và `cart_to_view_ratio` phân tách cực mạnh: ở tập Train, nhóm `0` có `cart_count` Mean = `0.0837` (Median = `0.0`), còn nhóm `1` có Mean = `0.9431` (Median = `1.0`). Ở tập Test tháng 12, hơn 95% phiên không mua có `cart_count = 0` (`P95 = 0.0`).
- **Hệ lụy:** Nếu huấn luyện mô hình cây quyết định mặc định và chỉ báo cáo một con số tổng thể, `cart_count` và `cart_to_view_ratio` sẽ chiếm trên 85–90% Feature Importance. Mô hình thực chất suy biến thành câu lệnh `if cart_count >= 1: return 1`, làm giảm giá trị học máy và không trả lời được câu hỏi: *"Trong số những người đã thêm vào giỏ hàng, ai sẽ mua thật và ai sẽ bỏ giỏ hàng?"* hoặc *"Khi khách mới chỉ đang xem sản phẩm (`cart_count == 0`), ai có tiềm năng mua cao?"*.

#### Giải pháp bắt buộc khi Train & Đánh giá (`Evaluation Protocol`)
1. **Cấu hình siêu tham số chống phụ thuộc đơn biến cho mô hình cây (Random Forest / XGBoost / LightGBM):**
   - Bắt buộc thiết lập lấy mẫu cột ngẫu nhiên ở mỗi cây/nhánh: `colsample_bytree = 0.7` (XGBoost/LightGBM) hoặc `max_features = "sqrt"` (Random Forest).
   - Khi 30%–50% số nhánh không được phép nhìn thấy `cart_count` và `cart_to_view_ratio`, các cây con buộc phải học ranh giới quyết định từ `repeat_view_ratio`, `session_duration_sec`, `avg_price` và `hour`.
2. **Đánh giá mô hình theo 3 lát cắt thực nghiệm (Multi-Slice & Ablation Evaluation) trong báo cáo kết quả:**
   - **Slice A — Toàn bộ tập Test (`All Test Sessions` - 1,786,352 phiên):** Đánh giá hiệu năng tổng thể của hệ thống.
   - **Slice B — Tập con Đã có giỏ hàng (`Cart-Active Subset`: lọc `cart_count >= 1` trên tập Test):** Đo khả năng phân biệt giữa **Chốt đơn (`Purchase`)** và **Bỏ quên giỏ hàng (`Cart Abandonment`)**. Trên tập con này, một luật ngây thơ `if cart_count >= 1` sẽ đoán toàn bộ là `1` (Precision thấp, False Positive rất cao), qua đó chứng minh giá trị thực sự của mô hình ML.
   - **Slice C / Ablation — Mô hình Dự báo sớm không dùng biến giỏ hàng (`Early-Intent / View-Only Features`):** Huấn luyện hoặc đánh giá một biến thể loại bỏ `cart_count`, `remove_cart_count`, `cart_to_view_ratio` (chỉ dùng hành vi xem và giá) để chứng minh khả năng phát hiện ý định mua sớm trước khi khách bấm nút "Thêm vào giỏ".

---

### Vấn đề 3: Đặc trưng "Chết" (`Dead Feature`) — `remove_cart_count = 0` trên toàn tập Kaggle

#### Lý do chi tiết & Số liệu chứng minh
- Trong cả tập Train (`10,446,279` sự kiện) và tập Test (`5,538,408` sự kiện), số lượng sự kiện `remove_from_cart` bằng **`0` tuyệt đối** (`Mean = 0.0, Std = 0.0, Max = 0.0`).
- **Hệ lụy:**
  1. Với các mô hình tuyến tính hoặc có ma trận hiệp phương sai, một cột hằng số bằng `0` không mang thông tin (zero variance) và có thể gây suy biến nếu không xử lý chia cho 0 khi chuẩn hóa.
  2. Quan trọng hơn: Trên website Django TechGear thực tế (`analytics/models.py`), hệ thống **có** ghi nhận sự kiện `remove_from_cart`. Vì mô hình học từ Kaggle gán trọng số bằng `0` cho cột `remove_cart_count`, nếu trên web khách hàng thêm 2 món vào giỏ rồi xóa cả 2 món đi (`add_to_cart = 2`, `remove_from_cart = 2`), mô hình vẫn chỉ nhìn thấy `cart_count = 2` và dự đoán nhầm rằng khách sắp mua hàng với xác suất rất cao!

#### Giải pháp bắt buộc khi Train & Tích hợp Web Inference
1. **Trong Pipeline Huấn luyện (`train.py`):**
   - Vẫn giữ `remove_cart_count` trong danh sách 14 cột đầu vào của Pipeline để đảm bảo tương thích 100% với `SESSION_FEATURE_COLUMNS`.
   - Đảm bảo bộ Scaler xử lý an toàn cột có phương sai bằng `0` (trong `scikit-learn`, `StandardScaler` và `RobustScaler` mặc định giữ nguyên hệ số chia `scale_ = 1.0` khi phương sai/IQR bằng 0, không sinh `NaN`).
2. **Trong Tầng Suy luận trên Website (`Web Inference Adapter` — khi đọc từ bảng `analytics.Event` của Django):**
   - Khi chuyển đổi sự kiện của một phiên trên website TechGear thành vector 14 đặc trưng để truyền vào mô hình, bắt buộc quy đổi `cart_count` thành **Số lượng thêm giỏ hàng ròng (`Effective Net Cart Count`)**:
     ```python
     raw_add_cart = count(event_type == "add_to_cart")
     raw_remove_cart = count(event_type == "remove_from_cart")
     effective_cart_count = max(0, raw_add_cart - raw_remove_cart)
     effective_cart_to_view_ratio = effective_cart_count / max(view_count, 1)
     ```
   - Truyền `effective_cart_count` vào vị trí cột `cart_count` và `effective_cart_to_view_ratio` vào vị trí `cart_to_view_ratio`. Nhờ đó, khi khách hàng trên web xóa sản phẩm khỏi giỏ, xác suất mua dự đoán sẽ giảm xuống ngay lập tức đúng với thực tế.

---

### Vấn đề 4: Lệch miền đơn vị tiền tệ (`Price Domain Shift`: USD vs. VNĐ) và Nghịch lý giá

#### Lý do chi tiết & Số liệu chứng minh
1. **Lệch thang đo tiền tệ giữa Kaggle và Website TechGear:**
   - Dữ liệu Kaggle có `avg_price`, `max_price`, `min_price` tính bằng **USD** (trung vị `~162 - 199 USD`, tối đa `2574.07 USD`).
   - Dữ liệu sản phẩm trên website TechGear (`products.Product.price` / `analytics.Event.event_value`) tính bằng **VNĐ** (ví dụ: `500,000 VNĐ` đến `45,000,000 VNĐ`).
   - Nếu truyền trực tiếp giá VNĐ vào mô hình đã train trên USD, mọi phiên trên website đều vượt gấp hàng nghìn lần ngưỡng `max_price = 2574` của tập Train.
2. **Hiện tượng giá trung bình phiên không mua cao hơn phiên mua:**
   - Trong tập Train (`rp_03_pipeline_stats.md` dòng 89–91), nhóm không mua có `avg_price = 349.26 USD` (`P95 = 1286.78 USD`), cao hơn nhóm có mua `avg_price = 249.59 USD` (`P95 = 823.68 USD`). Người dùng thường thích bấm xem tham khảo các dàn PC/Laptop đắt tiền nhưng tỷ lệ chốt đơn thực tế lại rơi nhiều vào nhóm linh kiện/phụ kiện vừa túi tiền.

#### Giải pháp bắt buộc khi Train & Tích hợp Web Inference
1. **Quy đổi tỷ giá chuẩn hóa tại `Web Inference Adapter`:**
   - Khai báo hằng số tỷ giá quy đổi `VND_TO_USD_RATE = 25_000.0` (hoặc cấu hình trong `config.py`).
   - Khi trích xuất `avg_price`, `max_price`, `min_price` từ database Django (VNĐ) để đưa vào mô hình, bắt buộc chia cho `VND_TO_USD_RATE` (và chỉ tính trung bình trên các sự kiện có `price > 0`).
2. **Bổ sung đặc trưng tỷ lệ biên độ giá không thứ nguyên (`Dimensionless Price Ratios`) trong `FeaturePreprocessor`:**
   - Bên trong transformer của mô hình, tính thêm tỷ lệ độ lệch giá nội bộ trong phiên:
     ```python
     price_range_ratio = (max_price - min_price) / np.clip(avg_price, 1e-3, None)
     ```
   - Đại lượng `(max_price - min_price) / avg_price` hoàn toàn **bất biến với đơn vị tiền tệ** (dù tính bằng USD hay VNĐ thì kết quả vẫn bằng nhau), phản ánh mức độ tập trung của khách hàng vào một phân khúc giá cụ thể.
   - Áp dụng `np.log1p` cho `avg_price`, `max_price`, `min_price` để nén biên độ giá trước khi đưa vào mô hình.

---

### Vấn đề 6: Mất cân bằng nhãn nghiêm trọng (`Class Imbalance 1 : 19.94`) & Dịch chuyển phân phối theo thời gian (`Temporal Drift`)

#### Lý do chi tiết & Số liệu chứng minh
- Tỷ lệ lớp dương tính (`will_purchase = 1`) trên tập Train (Tháng 10 + 11) chỉ là **`4.7749%`** (`126,473` phiên mua trên `2,522,232` phiên không mua $\rightarrow$ tỷ lệ mất cân bằng đúng bằng **`1 : 19.94`**, tức xấp xỉ **1 phiên mua cho 20 phiên không mua**). Sang tập Test độc lập (Tháng 12), tỷ lệ này giảm xuống còn **`3.1214%`** (`1 : 31.04`).
- **Tại sao `Accuracy` hoàn toàn vô nghĩa trên tập dữ liệu này?**
  - Một mô hình "rỗng" dự đoán 100% khách hàng đều không mua (`will_purchase = 0`) sẽ đạt `Accuracy = 95.23%` trên tập Train và `Accuracy = 96.88%` trên tập Test, nhưng `Recall = 0%` và không phát hiện được bất kỳ khách hàng tiềm năng nào.
  - Ngay cả `ROC-AUC` đôi khi vẫn cho điểm cao giả tạo (optimistic) khi số lượng mẫu âm (`True Negatives - TN`) quá khổng lồ (`2.52 triệu` phiên âm làm mẫu số `FPR = FP / (FP + TN)` rất nhỏ).
  - Do đó, **PR-AUC (`Precision-Recall AUC` / `Average Precision`)** là thước đo chính xác và khắt khe nhất vì nó tập trung trực tiếp vào mối quan hệ đánh đổi giữa `Precision` và `Recall` trên lớp thiểu số (`will_purchase = 1`) mà không bị làm loãng bởi `TN`.

#### Giải pháp bắt buộc khi Train & Đánh giá
1. **Phương án xử lý mất cân bằng lớp (`Imbalance Handling Strategy`):**
   - **Cân bằng trọng số hàm mục tiêu (`Cost-Sensitive Learning` — Bắt buộc làm phương án chuẩn):**
     - Với `LogisticRegression` và `RandomForestClassifier`: cấu hình `class_weight="balanced"`.
     - Với `HistGradientBoostingClassifier` / `LightGBM` / `XGBoost`: cấu hình `class_weight="balanced"` hoặc `scale_pos_weight = negative_sessions / positive_sessions` ($\approx 19.94$ tính từ tập Train).
   - **Lý do ưu tiên Cost-Sensitive Learning thay vì SMOTE trên 2.64 triệu dòng:**
     - Tập Train đã có sẵn `126,473` phiên mua hàng thực tế — số lượng mẫu dương tính đủ lớn để học ranh giới phức tạp mà không cần nội suy nhân tạo (SMOTE trên 2.64 triệu dòng sẽ làm phình dữ liệu lên ~5 triệu dòng, tốn bộ nhớ và dễ làm nhòe ranh giới ở vùng mật độ chồng lấn). Tuy nhiên, có thể so sánh thực nghiệm giữa `Unweighted`, `Class-Weighted (Cost-Sensitive)` và `Random Undersampling` trên tập Validation để chứng minh hiệu quả trong báo cáo.
2. **Thước đo đánh giá bắt buộc (`Mandatory Evaluation Metrics`):**
   - **PR-AUC (`Average Precision`):** Thước đo chính (`Primary Metric`) để chọn mô hình tốt nhất và tinh chỉnh siêu tham số.
   - **ROC-AUC:** Thước đo xếp hạng bổ trợ.
   - **F1-Score, Precision, Recall** của lớp dương tính (`will_purchase = 1`).
   - **Brier Score (`brier_score_loss`) & Log Loss:** Thước đo đánh giá chất lượng hiệu chỉnh xác suất (`Probability Calibration`).
   - **Confusion Matrix (`TP, FP, TN, FN`):** Minh bạch hóa số phiên mua bắt trúng và số phiên báo động nhầm.
   - *(Lưu ý: Chỉ liệt kê `Accuracy` như một chỉ số tham khảo phụ kèm cảnh báo mất cân bằng, tuyệt đối không dùng `Accuracy` để xếp hạng mô hình).*

---

## 3. Quy chuẩn Thực nghiệm Bắt buộc theo Yêu cầu Giảng viên Hướng dẫn (`Academic & Experimental Requirements`)

Phần này quy định chi tiết quy trình thực nghiệm chuẩn mực học thuật mà AI Agent **bắt buộc** phải cài đặt đầy đủ trong code huấn luyện và báo cáo:

---

### 3.1 Quy tắc Tách `Train / Validation / Out-of-Time Test` (Chống Rò rỉ Tập Test Tháng 12)

> **Quy tắc nghiêm ngặt:** Tập Test độc lập Tháng 12 (`session_test_features.csv` — `1,786,352` phiên) **CHỈ ĐƯỢC SỬ DỤNG ĐÚNG 1 LẦN Ở BƯỚC ĐÁNH GIÁ CUỐI CÙNG (`Final Evaluation`)**. Tuyệt đối **KHÔNG ĐƯỢC** dùng tập Test Tháng 12 để:
> 1. Tinh chỉnh siêu tham số (`Hyperparameter Tuning`).
> 2. Dừng sớm khi huấn luyện (`Early Stopping`).
> 3. Khớp bộ hiệu chỉnh xác suất (`Probability Calibration Fitting`).
> 4. Dò ngưỡng cắt quyết định (`Decision Threshold Tuning`).
> 5. Chọn mô hình tốt nhất (`Model Selection`).

#### Sơ đồ phân chia dữ liệu bắt buộc trong `train.py`
Toàn bộ quá trình huấn luyện, tinh chỉnh siêu tham số, hiệu chỉnh xác suất và dò ngưỡng phải diễn ra hoàn toàn bên trong dữ liệu Tháng 10 + Tháng 11 (`session_features.csv` — `2,648,705` phiên) bằng cách chia **Stratified Split** (giữ nguyên tỷ lệ `4.7749%` phiên mua hàng ở mọi tập con):

```text
[File 1] session_features.csv (Tháng 10 + 11: 2,648,705 phiên | Tỷ lệ 1 : 19.94)
   │
   ├──► (80%) TẬP TRAIN (~2,118,964 phiên | ~101,178 phiên mua)
   │      └── Dùng để fit FeaturePreprocessor, RobustScaler và huấn luyện các Base Models.
   │
   └──► (20%) TẬP VALIDATION (~529,741 phiên | ~25,295 phiên mua)
          └── Dùng cho 4 nhiệm vụ nội bộ trước khi mở khóa tập Test:
              (a) Tinh chỉnh siêu tham số (Hyperparameter Tuning) & Early Stopping
              (b) Fit bộ hiệu chỉnh xác suất (Probability Calibration - CalibratedClassifierCV)
              (c) Dò ngưỡng xác suất tối ưu (Optimal Threshold τ* tối đa hóa F1-Score)
              (d) Chọn mô hình vô địch (Model Selection theo PR-AUC cao nhất trên Validation)

=====================================================================================

[File 2] session_test_features.csv (Tháng 12: 1,786,352 phiên | Tỷ lệ 1 : 31.04)
   │
   └──► (100%) TẬP TEST ĐỘC LẬP THEO THỜI GIAN (Out-of-Time Test Set)
          └── Chỉ gọi .predict_proba() một lần sau khi đã khóa cứng mô hình và ngưỡng τ*
              từ Tập Validation để xuất bảng số liệu báo cáo cuối cùng.
```

*(Ghi chú kỹ thuật: Nếu tách riêng việc chọn siêu tham số/Early Stopping và việc fit bộ Calibration trên tập Validation, có thể chia tập Validation 20% thành 2 nửa Stratified `10% Validation_Tune` (~264k phiên) và `10% Validation_Calib` (~264k phiên), hoặc dùng `CalibratedClassifierCV(..., cv=3)` ngay trên tập Validation để tránh thiên lệch khi vừa calibrate vừa dò ngưỡng).*

---

### 3.2 Yêu cầu Nâng cao 1: So sánh Ít nhất 3 Mô hình Nền (`>= 3 Baseline Models`) trên Cùng Bộ Đặc trưng

AI Agent bắt buộc phải huấn luyện và đặt lên bàn cân so sánh **ít nhất 3 họ mô hình nền tảng khác nhau về bản chất toán học** trên **cùng một tập 14 đặc trưng đầu vào (`SESSION_FEATURE_COLUMNS`)** và cùng một quy trình đánh giá:

| Thứ tự | Họ mô hình (`Model Family`) | Class triển khai chuẩn | Bản chất & Lý do đưa vào so sánh | Cấu hình bắt buộc (Tham khảo) |
| :---: | :--- | :--- | :--- | :--- |
| **Model 1** | **Mô hình Tuyến tính (`Linear Baseline`)** | `sklearn.linear_model.LogisticRegression` | Làm mốc cơ sở tuyến tính (interpretable baseline), kiểm tra mức độ tách biệt tuyến tính của các đặc trưng sau khi đã biến đổi `log1p` + `RobustScaler`. | `class_weight="balanced"`, `C=1.0`, `max_iter=500`, `random_state=42` |
| **Model 2** | **Mô hình Tổ hợp Song song (`Bagging Tree Ensemble`)** | `sklearn.ensemble.RandomForestClassifier` | Đại diện họ cây quyết định lấy mẫu túi (Bagging), giảm phương sai, bắt tương tác phi tuyến nhưng xác suất thô thường bị co về trung tâm. | `n_estimators=200`, `max_depth=12`, `min_samples_leaf=50`, `max_features="sqrt"`, `class_weight="balanced_subsample"`, `n_jobs=-1`, `random_state=42` |
| **Model 3** | **Mô hình Tăng cường Gradient (`Gradient Boosted Decision Trees`)** | `HistGradientBoostingClassifier` (hoặc `LightGBM` / `XGBoost`) | Đại diện họ Boosting tuần tự tối ưu hàm mất mát đạo hàm bậc hai trên dữ liệu bảng quy mô hàng triệu dòng; tốc độ nhanh và hiệu năng `PR-AUC` cao nhất. | `max_iter=300`, `learning_rate=0.05`, `max_leaf_nodes=63`, `min_samples_leaf=100`, `l2_regularization=1.0`, `class_weight="balanced"`, `early_stopping=True`, `random_state=42` |

*(Khuyến khích: Có thể bổ sung thêm **Model 4 — `MLPClassifier` (Neural Network nhiều tầng)** hoặc **Mô hình Không cân bằng trọng số (`Unweighted Baseline`)** để bảng so sánh trong Khóa luận càng phong phú và thuyết phục).*

**Yêu cầu công bằng khi so sánh (`Fair Comparison Contract`):**
- Cả 3 mô hình đều phải nhận đầu vào từ cùng một tập `X_train` (cùng 14 cột `SESSION_FEATURE_COLUMNS`, đi qua cùng bộ xử lý cắt trần `session_duration_sec <= 3600s` và biến đổi đặc trưng).
- Bảng kết quả báo cáo phải hiển thị song song điểm số của cả 3 mô hình trên **Tập Validation** và **Tập Test độc lập Tháng 12** kèm thời gian huấn luyện (`train_time_sec`) và thời gian suy luận (`inference_time_ms`).

---

### 3.3 Yêu cầu Nâng cao 2: Hiệu chỉnh Xác suất Dự đoán (`Probability Calibration`)

#### Tại sao bắt buộc phải làm Hiệu chỉnh xác suất (`Probability Calibration`) trong bài toán này?
1. **Sự biến dạng xác suất do `class_weight="balanced"` (`Prior Shift Distortion`):**
   - Khi bật `class_weight="balanced"` trên tập Train có tỷ lệ `1 : 19.94` (`4.77%` mua hàng), thuật toán nhân trọng số lớp dương tính lên ~20 lần, tương đương với việc ép mô hình học trong một thế giới giả định có tỷ lệ mua hàng là **50% - 50%**.
   - Hậu quả: Xác suất thô (`raw predict_proba`) do mô hình trả về bị **phóng đại lên rất cao** (ví dụ: một phiên thực tế chỉ có `8%` cơ hội mua hàng nhưng mô hình `class_weight="balanced"` sẽ trả về xác suất `0.65` hay `65%`).
2. **Sự biến dạng nội tại của các mô hình cây (`Tree Ensemble Probability Distortion`):**
   - `RandomForest` lấy trung bình của nhiều cây con nên rất hiếm khi dự đoán xác suất gần `0.0` hoặc `1.0` (xác suất bị dồn về khoảng giữa). Ngược lại, `Gradient Boosting` lại có xu hướng đẩy xác suất ra hai cực.
3. **Ý nghĩa sống còn khi tích hợp vào Website TechGear & Chatbot:**
   - Trên trang quản trị Analytics hoặc trong logic kích hoạt Chatbot/Voucher, nếu hệ thống hiển thị *"Khách hàng đang có xác suất mua hàng là $p = 75\%$ expected conversion"*, con số $75\%$ đó phải phản ánh **xác suất thực nghiệm đúng ngoài đời thực** (tức là trong 100 phiên được dự báo $75\%$, thực sự có khoảng 75 phiên chốt đơn), chứ không phải một điểm số bị thổi phồng do `class_weight="balanced"`.

#### Quy trình kỹ thuật thực hiện `Probability Calibration` bắt buộc trong code
1. **Phương pháp hiệu chỉnh (`Calibration Methods`):**
   - Sử dụng `sklearn.calibration.CalibratedClassifierCV` với hai phương pháp chuẩn học thuật:
     - **`method="isotonic"` (Isotonic Regression — Hồi quy đơn điệu phi tham số):** Rất mạnh và linh hoạt khi tập dữ liệu hiệu chỉnh lớn (`> 10,000` mẫu; tập Validation của dự án có tới `529,741` mẫu nên cực kỳ lý tưởng cho Isotonic Calibration, không lo bị overfit).
     - **`method="sigmoid"` (Platt Scaling — Hàm Logistic Sigmoid):** Phù hợp làm đối chứng tham số.
2. **Cách khớp (`Fit`) bộ hiệu chỉnh mà không làm rò rỉ dữ liệu:**
   - Sau khi huấn luyện mô hình cơ sở (`base_pipeline`) trên tập `X_train, y_train`, khớp bộ hiệu chỉnh xác suất trên tập `Validation` (hoặc dùng `CalibratedClassifierCV(base_pipeline, method="isotonic", cv=3)`).
   - **Tuyệt đối KHÔNG** fit bộ hiệu chỉnh trên tập Test Tháng 12.
3. **Đánh giá hiệu quả trước và sau khi Calibration (`Before vs. After Calibration Metrics`):**
   - Trong file báo cáo `model_evaluation_report.json` và `rp_04_model_evaluation.md`, bắt buộc phải có bảng đối chiếu **Trước hiệu chỉnh (`Uncalibrated`)** và **Sau hiệu chỉnh (`Calibrated`)** cho các mô hình theo các chỉ số:
     1. **`Brier Score Loss` (`sklearn.metrics.brier_score_loss` — càng nhỏ càng tốt):** Đo sai số bình phương trung bình giữa xác suất dự đoán $\hat{p}_i$ và nhãn thực tế $y_i \in \{0, 1\}$:
        $$\text{Brier Score} = \frac{1}{N} \sum_{i=1}^{N} (\hat{p}_i - y_i)^2$$
        Khi chưa hiệu chỉnh (`class_weight="balanced"`), `Brier Score` thường rất xấu (cao) do xác suất bị thổi phồng; sau khi `Isotonic / Sigmoid Calibration`, `Brier Score` và `Log Loss` sẽ giảm mạnh rõ rệt.
     2. **`Log Loss` (`sklearn.metrics.log_loss` — càng nhỏ càng tốt).**
     3. **`ECE` (`Expected Calibration Error` — Sai số hiệu chỉnh kỳ vọng across 10 bins) & Dữ liệu đường cong hiệu chỉnh (`Calibration Curve / Reliability Diagram` từ `sklearn.calibration.calibration_curve`):** Thống kê theo từng bin xác suất dự đoán (ví dụ `[0.0-0.1], [0.1-0.2], ..., [0.9-1.0]`) để so sánh `mean_predicted_probability` với `empirical_fraction_of_positives`.
     4. **`PR-AUC` và `ROC-AUC`:** Chứng minh rằng phép biến đổi đơn điệu của Calibration giúp xác suất chuẩn xác thực tế mà vẫn bảo toàn năng lực xếp hạng (`PR-AUC`, `ROC-AUC`).
4. **Dò ngưỡng quyết định ($\tau^*$) SAU bước Calibration:**
   - Vì xác suất đã được hiệu chỉnh về đúng tỷ lệ thực tế (quanh mốc base rate `4.77%` đến `100%`), ngưỡng tối ưu $\tau^*$ cho `F1-Score` phải được quét trên **xác suất đã hiệu chỉnh (`calibrated_proba`)** của tập Validation, sau đó lưu vào `best_model_meta.json`.

---

## 4. Cấu trúc Cây Thư mục Chuẩn khi Triển khai Code Huấn luyện & Xuất Mô hình

Để quản lý code sạch sẽ, không làm hỏng file Tuần 3 và tận dụng `.gitignore` hiện có (`analytics/ml/artifacts/`), AI Agent cần tổ chức các file trong `analytics/` theo đúng cây thư mục sau:

```text
Website_GearCN_TLCN/
└── analytics/
    ├── management/
    │   └── commands/
    │       ├── run_data_pipeline.py             # [ĐÃ CÓ - Tuần 3] CLI chạy Data Pipeline
    │       └── train_purchase_model.py          # [MỚI - Tuần 4] CLI huấn luyện, hiệu chỉnh, đánh giá & xuất model
    │
    └── ml/
        ├── __init__.py                          # [ĐÃ CÓ]
        ├── config.py                            # [ĐÃ CÓ - Bổ sung hằng số đường dẫn model & tỷ giá VND_TO_USD_RATE]
        │
        ├── # --- PHẦN 1: DATA PIPELINE (TUẦN 3 - GIỮ NGUYÊN 100%) ---
        ├── preprocess.py                        # [ĐÃ CÓ]
        ├── features.py                          # [ĐÃ CÓ]
        ├── report_stats.py                      # [ĐÃ CÓ]
        │
        ├── # --- PHẦN 2: MODEL TRAINING, CALIBRATION & INFERENCE (TUẦN 4 - MỚI) ---
        ├── transformers.py                      # [MỚI] SessionFeatureTransformer (Clip 3600s, log1p, price_range_ratio)
        ├── train.py                             # [MỚI] Chia Stratified Train/Val, train >= 3 models, Probability Calibration, Threshold Tuning
        ├── evaluate.py                          # [MỚI] Đánh giá 1 lần trên Test Tháng 12 (3 lát cắt + Calibration metrics + Feature Importance)
        ├── predictor.py                         # [MỚI] Web Inference Adapter (Nhận Session/Event Django -> Đổi VNĐ/USD -> Net Cart -> Predict)
        │
        ├── # --- PHẦN 3: BÁO CÁO & TÀI LIỆU (TRACKED TRÊN GIT) ---
        ├── README.md                            # [ĐÃ CÓ]
        ├── MODEL_TRAINING_GUIDELINES.md         # [FILE NÀY] Quy tắc kỹ thuật & yêu cầu thực nghiệm
        ├── pipeline_stats_report.json           # [ĐÃ CÓ]
        ├── rp_03_pipeline_stats.md              # [ĐÃ CÓ]
        ├── rp_03fn.md                           # [ĐÃ CÓ]
        ├── model_evaluation_report.json         # [MỚI] Toàn bộ kết quả JSON (Validation & Test, Uncalibrated vs Calibrated, 3 slices)
        ├── rp_04_model_evaluation.md            # [MỚI] Báo cáo bảng biểu Markdown chi tiết cho Khóa luận
        │
        └── # --- PHẦN 4: DỮ LIỆU & MODEL ARTIFACTS (TRONG .gitignore) ---
            artifacts/
            ├── session_features.csv             # [ĐÃ CÓ] Tập Train + Validation (Tháng 10-11: 2,648,705 phiên)
            ├── session_test_features.csv        # [ĐÃ CÓ] Tập Test độc lập (Tháng 12: 1,786,352 phiên)
            └── models/                          # [MỚI] Thư mục xuất mô hình đã train (.joblib)
                ├── best_purchase_model.joblib   # Mô hình tốt nhất đã Calibrate (đóng gói trọn bộ Pipeline) dùng cho Web
                ├── best_model_meta.json         # Lưu tên model, optimal_threshold, calibration_method, vnd_to_usd_rate, metrics
                ├── logistic_regression.joblib   # Model 1 (Calibrated Pipeline)
                ├── random_forest.joblib         # Model 2 (Calibrated Pipeline)
                ├── gradient_boosting.joblib     # Model 3 (Calibrated Pipeline)
                └── early_intent_no_cart.joblib  # Model Ablation (Không dùng biến giỏ hàng)
```

---

## 5. Tóm tắt Checklist Kiến trúc Code cho AI Agent khi Triển khai Mô hình

Khi viết code huấn luyện và dự đoán trong `analytics/ml/`, AI Agent cần kiểm tra đủ 6 tiêu chí nghiệm thu sau:

1. **Đầu vào & Chống rò rỉ Tập Test (`Zero Test Leakage`):**
   - Đọc `SESSION_FEATURES_PATH` (`session_features.csv`) và chia Stratified `Train / Validation`.
   - Mọi bước chọn siêu tham số, dừng sớm (`Early Stopping`), khớp bộ hiệu chỉnh xác suất (`Probability Calibration`) và tìm ngưỡng cắt tối ưu ($\tau^*$) chỉ được dùng `Train` và `Validation`.
   - File `SESSION_TEST_FEATURES_PATH` (`session_test_features.csv` — Tháng 12) chỉ được nạp ở pha đánh giá cuối cùng (`evaluate.py`) để chạy suy luận một lần duy nhất.
2. **Xử lý mất cân bằng `1 : 19.94` & Đánh giá bằng `PR-AUC`:**
   - Áp dụng `class_weight="balanced"` (hoặc `scale_pos_weight`) cho các mô hình nền.
   - Sử dụng **`PR-AUC` (`average_precision_score`)** làm thước đo chính để xếp hạng và chọn `best_purchase_model.joblib`, tuyệt đối không chọn model theo `Accuracy`.
3. **So sánh tối thiểu 3 mô hình nền trên cùng bộ 14 đặc trưng:**
   - Huấn luyện đầy đủ ít nhất 3 mô hình (`Logistic Regression`, `Random Forest`, `HistGradientBoosting / LightGBM / XGBoost`) trên cùng tập 14 cột `SESSION_FEATURE_COLUMNS`.
4. **Hiệu chỉnh xác suất dự đoán (`Probability Calibration`):**
   - Thực hiện hiệu chỉnh xác suất (`CalibratedClassifierCV` với `Isotonic` / `Sigmoid`), báo cáo bảng so sánh **Trước và Sau khi hiệu chỉnh** bằng `Brier Score`, `Log Loss`, `ECE`, `Calibration Curve (10 bins)` cùng `PR-AUC` và `ROC-AUC`.
5. **Giải quyết triệt để 5 rủi ro đặc trưng thực nghiệm:**
   - `SessionFeatureTransformer` cắt trần `session_duration_sec <= 3600s`, biến đổi `np.log1p` cho các biến đếm/thời lượng/giá lệch phải, bổ sung tỷ lệ biên độ giá không thứ nguyên `price_range_ratio = (max_price - min_price) / clip(avg_price, 1e-3, None)` và chuẩn hóa bằng `RobustScaler`.
   - Xuất kết quả đánh giá trên cả **3 lát cắt** (Toàn tập Test, Tập con `cart_count >= 1`, và Ablation không dùng biến giỏ hàng).
6. **Tầng `Web Inference Adapter` (`predictor.py`):**
   - Nhận `Session` hoặc danh sách `Event` từ Django ORM, tự động quy đổi giá VNĐ $\rightarrow$ USD (`price / 25000.0`), tính giỏ hàng ròng `effective_cart_count = max(0, add_to_cart - remove_from_cart)`, dựng đúng DataFrame 14 cột theo `SESSION_FEATURE_COLUMNS` và trả về xác suất mua hàng đã hiệu chỉnh (`calibrated_probability`) cùng nhãn dự đoán theo `optimal_threshold`.
