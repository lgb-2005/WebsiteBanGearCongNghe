# KẾ HOẠCH TRIỂN KHAI CHI TIẾT & THEO DÕI TIẾN ĐỘ HUẤN LUYỆN MÔ HÌNH (`MODEL TRAINING EXECUTION PLAN`)

> **Tài liệu phối hợp cùng:** [`MODEL_TRAINING_GUIDELINES.md`](./MODEL_TRAINING_GUIDELINES.md)
>
> **Mục tiêu:** Quy định lộ trình triển khai từng bước (từ viết code, để **Người dùng tự nhấn chạy huấn luyện qua Google Colab Extension**, hiệu chỉnh xác suất, chấm điểm 1 lần trên tập Test Tháng 12 đến tích hợp vào Website Django TechGear) kèm bảng checklist tiến độ để đánh dấu `[x]` sau mỗi hạng mục hoàn thành.
>
> ---
> ### ⚠️ QUY TẮC BẮT BUỘC DÀNH CHO AI AGENT (`HUMAN-IN-THE-LOOP TRAINING RULE`)
> 1. **AI Agent KHÔNG ĐƯỢC tự ý chạy huấn luyện thật (`train.py`) hay chấm điểm tập Test thật (`evaluate.py`):**
>    - AI Agent **chỉ có nhiệm vụ viết code** các file `.py`, chuẩn bị sẵn file Notebook điều khiển `analytics/ml/colab_train_runner.ipynb` và chỉ được chạy `manage.py test analytics` (với dữ liệu giả lập nhỏ `< 500 dòng` trong RAM để kiểm tra logic code).
>    - AI Agent **TUYỆT ĐỐI KHÔNG** dùng terminal để chạy train trên file `session_features.csv` (`2.64 triệu` dòng) hay `session_test_features.csv` (`1.78 triệu` dòng).
> 2. **NGƯỜI DÙNG (User) là người duy nhất trực tiếp nhấn nút Train & Evaluate trên Google Colab Extension:**
>    - Ngay sau khi viết xong code và pass unit tests, AI Agent **PHẢI DỪNG LẠI** và hướng dẫn người dùng mở `analytics/ml/colab_train_runner.ipynb` (kết nối kernel Google Colab Extension) để **người dùng tự nhấn nút `[▶ Run]`** thực hiện quá trình train và xuất model.

---

## PHẦN I — BẢNG THEO DÕI TIẾN ĐỘ TỔNG THỂ (`PROGRESS TRACKER`)

*(Cập nhật trạng thái `[ ]` $\rightarrow$ `[x]` ngay sau khi hoàn thành và kiểm tra xong từng bước)*

### Giai đoạn 0: Chuẩn bị Cấu hình & Tương thích Google Colab Extension
- [x] **0.1.** Cập nhật `analytics/ml/config.py`: Bổ sung các hằng số đường dẫn model (`MODELS_DIR`, `BEST_MODEL_PATH`, `BEST_MODEL_META_PATH`, `MODEL_EVAL_REPORT_JSON_PATH`, `MODEL_EVAL_REPORT_MD_PATH`), tỷ giá `VND_TO_USD_RATE = 25_000.0`, ngưỡng cắt `MAX_SESSION_DURATION_SEC = 3600.0`.
- [x] **0.2.** Đảm bảo các file huấn luyện lõi (`transformers.py`, `train.py`, `evaluate.py`) **độc lập hoàn toàn với Django ORM (`Zero-Django Dependency`)** để chạy trực tiếp được trên kernel của Google Colab Extension mà không cần nạp `db.sqlite3` hay cấu hình Django.
- [x] **0.3.** Đồng bộ phiên bản `scikit-learn`, `numpy`, `pandas`, `joblib` giữa Google Colab Extension và môi trường `.venv` dưới máy local (ghi rõ `sklearn_version` vào `best_model_meta.json` để tránh lỗi lệch phiên bản khi `joblib.load()`).

### Chặng 1: Phân chia Dữ liệu `session_features.csv` (Tháng 10 + 11) thành 3 Tập Nội bộ (`70% / 15% / 15%`)
- [x] **1.1.** Viết hàm nạp và kiểm tra tính toàn vẹn của `session_features.csv` (`2,648,705` phiên, đủ 14 cột `SESSION_FEATURE_COLUMNS` + nhãn `will_purchase`).
- [x] **1.2.** Triển khai hàm chia phân tầng 3 phần (`Stratified 3-Way Split` với `random_state=42`):
  - `Train_Fit` (`70%` $\approx 1,854,093$ phiên | tỷ lệ mua `~4.7749%`)
  - `Val_Calib` (`15%` $\approx 397,306$ phiên | tỷ lệ mua `~4.7749%`)
  - `Val_Select` (`15%` $\approx 397,306$ phiên | tỷ lệ mua `~4.7749%`)
- [x] **1.3.** Kiểm tra tự động (assertion) đảm bảo 3 tập `Train_Fit`, `Val_Calib`, `Val_Select` rời nhau tuyệt đối (không trùng `user_session` / index) và chưa hề chạm tới file `session_test_features.csv` (Tháng 12).

### Chặng 2: Huấn luyện $\ge 3$ Mô hình Nền + Hiệu chỉnh Xác suất + Chọn Nhà Vô Địch (Trên Tháng 10 + 11)
- [x] **2.1.** Xây dựng `analytics/ml/transformers.py` chứa `SessionFeatureTransformer`:
  - Cắt trần `session_duration_sec` trong đoạn `[0.0, 3600.0]`.
  - Tạo đặc trưng tỷ lệ giá không thứ nguyên `price_range_ratio = (max_price - min_price) / clip(avg_price, 1e-3, None)`.
  - Biến đổi `np.log1p` cho các cột lệch phải (`view_count`, `unique_products`, `unique_categories`, `cart_count`, `session_duration_sec`, `avg_price`, `max_price`, `min_price`, `cart_to_view_ratio`).
  - Kết hợp với `RobustScaler()`.
- [x] **2.2.** Xây dựng `analytics/ml/train.py` huấn luyện 3 mô hình nền có xử lý mất cân bằng (`1 : 19.94`) trên `X_train_fit, y_train_fit`:
  - Model 1: `LogisticRegression(class_weight="balanced", ...)`
  - Model 2: `RandomForestClassifier(class_weight="balanced_subsample", max_features="sqrt", ...)`
  - Model 3: `HistGradientBoostingClassifier(class_weight="balanced", ...)` (hoặc `LightGBM`)
  - Model Phụ (Ablation): Mô hình dự báo sớm `Early-Intent` (loại bỏ nhóm biến giỏ hàng `cart_count`, `remove_cart_count`, `cart_to_view_ratio`).
- [x] **2.3.** Thực hiện **Hiệu chỉnh xác suất dự đoán (`Probability Calibration`)** trên tập `X_val_calib, y_val_calib` (sử dụng `Isotonic Regression` và đối chứng với `Platt Scaling / Sigmoid`).
- [x] **2.4.** Đánh giá trên `X_val_select, y_val_select`:
  - Đo `Brier Score`, `Log Loss`, `ECE` (trước và sau khi hiệu chỉnh).
  - Đo `PR-AUC` (`Average Precision`) và `ROC-AUC`.
  - Quét 99 mốc ngưỡng trên xác suất đã hiệu chỉnh của `Val_Select` để tìm ngưỡng tối ưu $\tau^*$ đạt `F1-Score` cao nhất cho từng mô hình.
  - Chọn mô hình có **`PR-AUC` cao nhất trên `Val_Select`** để xuất ra `best_purchase_model.joblib` và `best_model_meta.json`.
- [x] **2.5.** **[AI AGENT CHUẨN BỊ NOTEBOOK ĐIỀU KHIỂN]** Tạo file `analytics/ml/colab_train_runner.ipynb` (chỉ gồm các ô gọi hàm từ `analytics.ml.train` và `analytics.ml.evaluate`, không khai báo class trực tiếp trong cell) để bạn mở bằng **Google Colab Extension** trên IDE và tự nhấn nút `[▶ Run]`.
- [x] **2.6.** **[NGƯỜI DÙNG TỰ NHẤN NÚT CHẠY TRÊN COLAB EXTENSION]** Bạn tự bấm nút `[▶ Run]` Cell Huấn luyện trong `colab_train_runner.ipynb` để train toàn tập `2,648,705` phiên và xuất bộ model `.joblib` vào `analytics/ml/artifacts/models/`.

### Chặng 3: Đánh giá Chính thức ĐÚNG 1 LẦN trên Tập Test Độc lập Tháng 12 (`session_test_features.csv`)
- [x] **3.1.** **[AI AGENT VIẾT CODE]** Xây dựng `analytics/ml/evaluate.py` nạp các model đã đóng băng từ Chặng 2 cùng ngưỡng $\tau^*$ cố định.
- [x] **3.2.** **[NGƯỜI DÙNG TỰ NHẤN NÚT CHẠY 1 LẦN TRÊN COLAB EXTENSION]** Sau khi Chặng 2 hoàn tất, bạn tự bấm nút `[▶ Run]` Cell Đánh giá Test một lượt duy nhất trên `session_test_features.csv` (`1,786,352` phiên của Tháng 12) để xuất ra `analytics/ml/model_evaluation_report.json` + `analytics/ml/rp_04_model_evaluation.md` gồm đủ 4 bảng thực nghiệm.

### Chặng 4: Đóng gói `predictor.py` cho Website TechGear & Kiểm thử Tự động (`Unit Tests`)
- [x] **4.1.** Xây dựng `analytics/ml/predictor.py` nhận `Session` / `Event` từ Django ORM, tự động đổi giá `VNĐ -> USD` (`/ 25000.0`), tính giỏ hàng ròng `effective_cart_count = max(0, add_to_cart - remove_from_cart)` và trả về xác suất mua đã hiệu chỉnh + nhãn dự đoán.
- [x] **4.2.** Xây dựng Django Management Command `analytics/management/commands/train_purchase_model.py`.
- [x] **4.3.** Bổ sung bộ Unit Tests trong `analytics/tests.py` kiểm tra toàn bộ `SessionFeatureTransformer`, quy trình `train/calibrate/evaluate` trên dữ liệu giả lập và `predictor.py` (đảm bảo 31 tests cũ + các tests mới đều PASS 100%).

---

## PHẦN II — THIẾT KẾ ĐẶC BIỆT ĐỂ BẠN CHẠY TRAIN BẰNG GOOGLE COLAB EXTENSION

Vì bạn sẽ tự chạy quá trình train thông qua **Google Colab Extension** ngay trong IDE (VS Code / Windsurf), kiến trúc code phải tuân thủ **4 quy tắc kỹ thuật bắt buộc** sau để không gặp lỗi khi chuyển model từ Colab về chạy trên Website Django local:

### 1. Không định nghĩa Class/Hàm của Pipeline trực tiếp trong ô Notebook (`No __main__ Pickle Trap`)
- **Rủi ro:** Nếu bạn chạy một ô trong `.ipynb` có chứa `class SessionFeatureTransformer:` rồi gọi `joblib.dump()`, file `.joblib` sẽ lưu đường dẫn class là `__main__.SessionFeatureTransformer`. Khi Django web server gọi `joblib.load()`, nó sẽ báo lỗi `AttributeError: Can't get attribute 'SessionFeatureTransformer' on <module '__main__'>`.
- **Cách thiết kế chuẩn trong dự án này:**
  - Mọi class biến đổi (`SessionFeatureTransformer`, wrapper hiệu chỉnh xác suất) đều được viết trong file `.py` độc lập (`analytics/ml/transformers.py`).
  - File runner dùng cho Colab Extension (dù bạn mở bằng file `.py` hay một file notebook điều khiển nhẹ `colab_train_runner.ipynb`) chỉ thực hiện **import module** (`from analytics.ml.train import run_training_pipeline`) chứ tuyệt đối không khai báo class trực tiếp trong cell.

### 2. Kiến trúc `Zero-Django Dependency` cho `transformers.py`, `train.py`, `evaluate.py`
- Trên máy ảo của Google Colab Extension, bạn chỉ cần cung cấp file CSV đặc trưng (`session_features.csv`, `session_test_features.csv`) và thư mục `analytics/ml/`, không cần cài đặt hay cấu hình toàn bộ các app `accounts`, `products`, `orders`, `chatbot` của Django.
- Do đó, `config.py`, `transformers.py`, `train.py` và `evaluate.py` chỉ dùng thư viện chuẩn của Python (`pathlib`, `json`, `math`, `time`) cùng bộ tứ khoa học dữ liệu (`numpy`, `pandas`, `scikit-learn`, `joblib`).

### 3. Hỗ trợ tham số đường dẫn linh hoạt (`Configurable Paths`)
- Các hàm `run_training_pipeline(...)` và `run_final_test_evaluation(...)` phải nhận đường dẫn đầu vào/đầu ra qua tham số (mặc định trỏ về `analytics/ml/artifacts/`, nhưng có thể truyền đường dẫn trên Google Drive / Colab workspace nếu file CSV đặt ở thư mục khác).
- Có sẵn tham số `sample_size: int | None = None`:
  - Khi kiểm tra thử trên Colab lần đầu: truyền `sample_size=50_000` (chạy xong trong **5 giây**) để kiểm tra đường dẫn và luồng xuất file.
  - Khi chạy thật: để `sample_size=None` để train toàn bộ `2,648,705` dòng.

### 4. Kiểm tra đồng bộ phiên bản `scikit-learn` giữa Colab và Local `.venv`
- Trước khi train trên Colab Extension, in ra `sklearn.__version__` và đảm bảo phiên bản `scikit-learn` trong `.venv` dưới máy tính Windows của bạn trùng khớp (hoặc tương thích cùng minor version) để khi tải `best_purchase_model.joblib` về máy local chạy web không gặp lỗi đọc Cython object.

---

## PHẦN III — NỘI DUNG CHI TIẾT TỪNG CHẶNG TRIỂN KHAI

---

### CHẶNG 1: Chia nhỏ `session_features.csv` (Tháng 10 + 11) thành 3 phần nội bộ (`70% / 15% / 15%`)

Thay vì chỉ chia 2 phần (`Train / Val`), cách thông minh và tiết kiệm thời gian tính toán nhất khi có bước **Hiệu chỉnh xác suất (`Probability Calibration`)** trên tập dữ liệu lớn `2,648,705` phiên là chia Stratified `session_features.csv` thành **3 phần độc lập**:

```text
session_features.csv (Tháng 10 + 11: 2,648,705 phiên | 4.7749% mua hàng)
 ├── 1. TẬP TRAIN_FIT  (70% ≈ 1,854,093 phiên | ~88,531 phiên mua): Dạy các mô hình gốc (Base Models)
 ├── 2. TẬP VAL_CALIB  (15% ≈   397,306 phiên | ~18,971 phiên mua): Khớp bộ Hiệu chỉnh xác suất (Calibration)
 └── 3. TẬP VAL_SELECT (15% ≈   397,306 phiên | ~18,971 phiên mua): Chấm PR-AUC chọn model & dò ngưỡng tối ưu τ*
```

#### Lý do thiết kế chia `70% Train_Fit – 15% Val_Calib – 15% Val_Select`:
1. **Đủ mẫu cho Calibration hội tụ tuyệt đối:** Mỗi tập `15%` vẫn chứa gần `400,000` phiên (với `~19,000` phiên mua hàng) — vượt xa ngưỡng tối thiểu (`10,000` mẫu) để bộ hiệu chỉnh phi tham số `Isotonic Regression` hội tụ chính xác mà không sợ overfitting.
2. **Tối ưu tốc độ chạy trên Colab:** Bạn chỉ cần fit mỗi mô hình gốc (`LogisticRegression`, `RandomForest`, `HistGradientBoosting`) **đúng 1 lần** trên `Train_Fit`, sau đó khớp bộ hiệu chỉnh trực tiếp trên `Val_Calib` (không phải huấn luyện lặp lại gấp 3–5 lần như K-Fold Cross-Validation), giúp rút ngắn thời gian train trên Colab xuống chỉ còn vài phút.
3. **Chống rò rỉ nội bộ (`Zero Selection Bias`):** Tập `Val_Select` chưa từng được nhìn thấy bởi cả mô hình gốc lẫn bộ hiệu chỉnh xác suất. Do đó, việc dùng `Val_Select` để chọn ra mô hình vô địch theo `PR-AUC` và quét tìm ngưỡng $\tau^*$ là hoàn toàn khách quan.

#### Cách chia trong code (`train.py`):
```python
# Bước 1: Tách 70% Train_Fit và 30% Temp_Val (Stratified theo y)
X_train_fit, X_temp, y_train_fit, y_temp = train_test_split(
    X_all, y_all, test_size=0.30, stratify=y_all, random_state=42
)

# Bước 2: Chia đôi 30% Temp_Val thành 15% Val_Calib và 15% Val_Select (Stratified theo y_temp)
X_val_calib, X_val_select, y_val_calib, y_val_select = train_test_split(
    X_temp, y_temp, test_size=0.50, stratify=y_temp, random_state=42
)
```

---

### CHẶNG 2: Huấn luyện 3 Mô hình nền + Hiệu chỉnh xác suất + Chọn nhà vô địch (Chỉ diễn ra trên Tháng 10-11)

Module `analytics/ml/train.py` sẽ tự động thực hiện tuần tự 4 bước sau cho tất cả các mô hình:

#### Bước 2.1 — Tiền xử lý chống hệ lụy (`SessionFeatureTransformer` + `RobustScaler` trong `transformers.py`)
- Nhận vào DataFrame 14 cột chuẩn `SESSION_FEATURE_COLUMNS`.
- Thực hiện biến đổi an toàn (không làm thay đổi DataFrame gốc của người gọi):
  1. **Cắt trần ngoại lai thời lượng phiên:** `session_duration_sec = np.clip(session_duration_sec, 0.0, 3600.0)` để loại bỏ các phiên treo cookie 57 ngày ở nhóm không mua và xóa bỏ thiên lệch độ dài phiên (`Cutoff Bias`).
  2. **Thêm đặc trưng tỷ lệ giá không thứ nguyên (`Dimensionless Price Spread`):**
     `price_range_ratio = (max_price - min_price) / np.clip(avg_price, 1e-3, None)`
     (bất biến với đơn vị tiền tệ USD hay VNĐ).
  3. **Biến đổi Logarit (`np.log1p`):** Áp dụng cho các cột đếm, thời lượng và giá bị lệch phải (`view_count`, `unique_products`, `unique_categories`, `cart_count`, `session_duration_sec`, `avg_price`, `max_price`, `min_price`, `cart_to_view_ratio`).
  4. **Chuẩn hóa bền vững với ngoại lai:** Đưa qua `RobustScaler()` (fit duy nhất trên `X_train_fit`).

#### Bước 2.2 — Huấn luyện 3 Mô hình nền có cân bằng trọng số (`1 : 19.94`) + 1 Mô hình Ablation
1. **Model 1 — `logistic_regression` (Baseline Tuyến tính):**
   - `LogisticRegression(class_weight="balanced", C=1.0, max_iter=500, random_state=42)`
2. **Model 2 — `random_forest` (Tổ hợp cây song song Bagging):**
   - `RandomForestClassifier(n_estimators=200, max_depth=12, min_samples_leaf=50, max_features="sqrt", class_weight="balanced_subsample", n_jobs=-1, random_state=42)`
   - Tham số `max_features="sqrt"` ép các nhánh cây con phải học từ `repeat_view_ratio`, `session_duration_sec`, `avg_price` thay vì chỉ nhìn vào `cart_count`.
3. **Model 3 — `gradient_boosting` (Tăng cường Gradient tuần tự — Chủ lực):**
   - `HistGradientBoostingClassifier(max_iter=300, learning_rate=0.05, max_leaf_nodes=63, min_samples_leaf=100, l2_regularization=1.0, max_features=0.7, class_weight="balanced", early_stopping=True, random_state=42)`
   - Tham số `max_features=0.7` (tương đương `colsample_bytree=0.7`) lấy mẫu 70% đặc trưng ở mỗi lần chia nhánh để chống suy biến thành luật đơn biến `if cart_count > 0`.
4. **Model Phụ (Ablation) — `early_intent_no_cart` (Dự báo sớm khi chưa có giỏ hàng):**
   - Dùng kiến trúc Gradient Boosting nhưng loại bỏ 3 cột giỏ hàng (`cart_count`, `remove_cart_count`, `cart_to_view_ratio`), chỉ học trên 11 đặc trưng hành vi xem, thời lượng, giá và thời gian để đánh giá khả năng bắt ý định mua sớm.

#### Bước 2.3 — Hiệu chỉnh xác suất (`Probability Calibration` trên `X_val_calib, y_val_calib`)
- Do `class_weight="balanced"` nhân trọng số lớp dương tính lên ~20 lần, xác suất dự đoán thô `raw_proba = base_model.predict_proba(X)[:, 1]` bị đẩy vọt về quanh mốc `0.50` (thổi phồng gấp ~10 lần so với tỷ lệ mua thực tế `4.77%`).
- Sử dụng tập `X_val_calib, y_val_calib` để khớp bộ hiệu chỉnh xác suất (bọc trong một class `CalibratedModelWrapper` nằm ở `transformers.py` để tương thích với mọi phiên bản `scikit-learn` mà không phụ thuộc vào `cv='prefit'` bị deprecated ở các bản sklearn mới):
  - **Phương pháp chính (`isotonic`):** `IsotonicRegression(y_min=0.0, y_max=1.0, out_of_bounds="clip")` khớp ánh xạ đơn điệu từ `raw_proba_val_calib` $\rightarrow$ `y_val_calib`.
  - **Phương pháp đối chứng (`sigmoid` / Platt Scaling):** `LogisticRegression()` khớp trên `logit(raw_proba_val_calib)` $\rightarrow$ `y_val_calib`.
  - Tự động chọn phương pháp hiệu chỉnh (`isotonic` vs `sigmoid`) có **`Brier Score` tốt hơn (thấp hơn)** và giữ nguyên `PR-AUC` cao trên `Val_Select`.

#### Bước 2.4 — Đánh giá trên `X_val_select` & Dò ngưỡng quyết định tối ưu $\tau^*$
- Trên tập `X_val_select, y_val_select` (hoàn toàn độc lập):
  1. Tính bộ chỉ số **Trước hiệu chỉnh (`Uncalibrated`)** và **Sau hiệu chỉnh (`Calibrated`)**:
     - `Brier Score Loss`, `Log Loss`, `ECE (Expected Calibration Error - 10 bins)`.
     - `PR-AUC (Average Precision)` và `ROC-AUC`.
  2. **Quét tìm ngưỡng tối ưu $\tau^*$ (`Threshold Tuning`):**
     - Duyệt 99 mốc ngưỡng $\tau \in [0.01, 0.99]$ (cùng các điểm phân vị từ `precision_recall_curve`) trên xác suất đã hiệu chỉnh của `Val_Select`.
     - Chọn ngưỡng $\tau^*$ mang lại **`F1-Score` cao nhất trên `Val_Select`**.
  3. **Chọn Nhà Vô Địch (`Model Selection`):**
     - Xếp hạng 3 mô hình nền theo **`PR-AUC` trên `Val_Select`**.
     - Mô hình đứng đầu được lưu thành `analytics/ml/artifacts/models/best_purchase_model.joblib` kèm `best_model_meta.json` (lưu rõ tên mô hình, `optimal_threshold`, `calibration_method`, `vnd_to_usd_rate`, `schema_version`, `sklearn_version` và bảng điểm Validation).

---

### CHẶNG 3: Đánh giá chính thức ĐÚNG 1 LẦN trên Tập Test độc lập Tháng 12 (`session_test_features.csv`)

Sau khi Chặng 2 đã khóa sổ hoàn toàn các file `.joblib` và ngưỡng $\tau^*$ trong `artifacts/models/`:

1. Module `analytics/ml/evaluate.py` nạp file `session_test_features.csv` (`1,786,352` phiên của Tháng 12, tỷ lệ mua `3.1214%`, mất cân bằng `1 : 31.04`).
2. Chạy `.predict_proba()` **một lượt duy nhất** cho các mô hình đã đóng băng, áp dụng đúng ngưỡng $\tau^*$ đã khóa từ tập Validation (tuyệt đối không dò lại ngưỡng trên tập Test).
3. Tự động xuất báo cáo hoàn chỉnh ra 2 file được theo dõi trên Git:
   - `analytics/ml/model_evaluation_report.json`
   - `analytics/ml/rp_04_model_evaluation.md`
4. **Cấu trúc 4 Bảng Thực nghiệm bắt buộc trong báo cáo `rp_04_model_evaluation.md`:**
   - **Bảng 1 — Bảng so sánh 3 Mô hình nền trên Tập Validation (`Val_Select`) và Tập Test Độc lập (`2019-Dec`):**
     - Các cột: `Model`, `PR-AUC (Primary)`, `ROC-AUC`, `Optimal Threshold (τ*)`, `F1-Score (@τ*)`, `Precision (@τ*)`, `Recall (@τ*)`, `F1-Score (@0.50)`, `TP / FP / TN / FN`, `Train Time (s)`.
   - **Bảng 2 — Bảng đánh giá Hiệu chỉnh xác suất (`Probability Calibration: Uncalibrated vs. Calibrated`):**
     - So sánh `Brier Score Loss`, `Log Loss`, `ECE (10 bins)` và `Mean Predicted Probability vs. Empirical Base Rate` trước và sau khi hiệu chỉnh; kèm bảng `Reliability Diagram (10 probability bins)`.
   - **Bảng 3 — Bảng đánh giá theo 3 Lát cắt Thực tế (`Multi-Slice & Ablation Evaluation`):**
     - *Lát cắt 1 (`All Test Sessions` - 1,786,352 phiên):* Hiệu năng tổng thể toàn hệ thống.
     - *Lát cắt 2 (`Cart-Active Subset: cart_count >= 1`):* Đánh giá khả năng phân biệt **Chốt đơn thật** vs. **Bỏ quên giỏ hàng (`Cart Abandonment`)**, so sánh trực diện mô hình ML với luật ngây thơ `Rule: if cart_count >= 1`.
     - *Lát cắt 3 (`Early-Intent Ablation: View-Only Features`):* Hiệu năng dự báo sớm khi không sử dụng các biến giỏ hàng.
   - **Bảng 4 — Bảng xếp hạng Mức độ quan trọng của Đặc trưng (`Feature Importance`):**
     - Trích xuất độ quan trọng của các đặc trưng (từ cả mô hình toàn cục và mô hình `Early-Intent`) để giải thích hành vi khách hàng mua Gear/PC/Audio.

---

### CHẶNG 4: Đóng gói `predictor.py` cho Website TechGear & Chạy Unit Tests

1. **Xây dựng `analytics/ml/predictor.py` (`Web Inference Adapter`):**
   - Nạp và cache trên bộ nhớ (`singleton / lru_cache`) cặp file `best_purchase_model.joblib` và `best_model_meta.json`.
   - Cung cấp hàm `extract_live_session_features(session_or_events)` và `predict_session_purchase_intent(session_or_events)`:
     - Đọc danh sách sự kiện từ bảng `analytics.Event` của Django ORM (chỉ lấy các sự kiện trước sự kiện `checkout` đầu tiên nếu có).
     - **Chuyển đổi đơn vị tiền tệ:** Chia `event_value` (hoặc `product.price`) từ VNĐ sang USD theo `VND_TO_USD_RATE = 25_000.0`.
     - **Tính giỏ hàng ròng (`Effective Net Cart Count`):**
       `effective_cart_count = max(0, add_to_cart_count - remove_from_cart_count)`
       và gán vào cột `cart_count` để xử lý triệt để hành vi xóa giỏ hàng trên website thực tế.
     - Trả về dictionary chuẩn:
       ```python
       {
           "user_session": str(session_id),
           "purchase_probability": float,      # Xác suất đã hiệu chỉnh (0.0 -> 1.0)
           "will_purchase": bool,              # purchase_probability >= optimal_threshold
           "intent_level": str,                # "high" | "medium" | "low"
           "optimal_threshold": float,
           "features": dict,                   # 14 đặc trưng đã trích xuất
       }
       ```
2. **Viết bộ kiểm thử tự động trong `analytics/tests.py`:**
   - Kiểm tra `SessionFeatureTransformer` cắt đúng ngưỡng `3600s`, tính đúng `price_range_ratio`, không làm biến đổi DataFrame đầu vào.
   - Kiểm tra luồng `train` $\rightarrow$ `calibrate` $\rightarrow$ `evaluate` trên tập dữ liệu giả lập nhỏ (`synthetic dataset`) đảm bảo:
     - Chia đúng tỷ lệ `70 / 15 / 15`.
     - `Brier Score` sau khi hiệu chỉnh giảm xuống so với trước khi hiệu chỉnh.
     - Tạo đủ file `.joblib`, `best_model_meta.json`, `model_evaluation_report.json` và `rp_04_model_evaluation.md`.
   - Kiểm tra `predictor.py` với `Session` và `Event` của Django ORM (kiểm tra quy đổi VNĐ $\rightarrow$ USD và hiệu ứng giảm xác suất khi có sự kiện `remove_from_cart`).

---

## PHẦN IV — QUY TRÌNH BÀN GIAO ĐỂ BẠN TỰ NHẤN NÚT TRAIN TRÊN GOOGLE COLAB EXTENSION

Để đảm bảo **100% bạn là người trực tiếp nhấn nút chạy quá trình Train và Test**, quy trình phối hợp giữa AI Agent và Bạn được khóa chặt như sau:

1. **Những gì AI Agent sẽ làm rồi DỪNG LẠI:**
   - Viết hoàn chỉnh các module `.py`: `config.py`, `transformers.py`, `train.py`, `evaluate.py`, `predictor.py`, `train_purchase_model.py`.
   - Tạo sẵn file Notebook điều khiển `analytics/ml/colab_train_runner.ipynb` có chia sẵn từng ô (Cell) rõ ràng.
   - Chạy `python manage.py test analytics` (chỉ kiểm tra logic code bằng dữ liệu giả lập nhỏ `< 500 dòng` trong RAM, mất ~2 giây).
   - **AI Agent dừng lại hoàn toàn và bàn giao cho bạn.**

2. **Những gì BẠN sẽ trực tiếp thao tác trên Google Colab Extension:**
   - Mở file `analytics/ml/colab_train_runner.ipynb` ngay trong VS Code / Windsurf IDE và chọn Kernel của **Google Colab Extension**.
   - **Nhấn nút `[▶ Run]` ở Cell 1 (Kiểm tra môi trường & Smoke Run 50,000 dòng ~ 5 giây):** Kiểm tra kết nối file `session_features.csv` và phiên bản `scikit-learn`.
   - **Nhấn nút `[▶ Run]` ở Cell 2 (Huấn luyện & Hiệu chỉnh xác suất chính thức trên Toàn tập Tháng 10 + 11 — `2,648,705` phiên):** Gọi `run_training_pipeline()` để train 3 mô hình nền + 1 mô hình Ablation, hiệu chỉnh xác suất và lưu `.joblib` vào `analytics/ml/artifacts/models/`.
   - **Nhấn nút `[▶ Run]` ở Cell 3 (Đánh giá ĐÚNG 1 LẦN trên Tập Test độc lập Tháng 12 — `1,786,352` phiên):** Gọi `run_final_test_evaluation()` để chấm điểm một lần duy nhất trên `session_test_features.csv` và xuất báo cáo `model_evaluation_report.json` + `rp_04_model_evaluation.md`.
   *(Ngoài ra, nếu muốn chạy bằng lệnh Terminal trên Colab/Local, bạn cũng có thể tự gõ `python -m analytics.ml.train` và `python -m analytics.ml.evaluate`).*
