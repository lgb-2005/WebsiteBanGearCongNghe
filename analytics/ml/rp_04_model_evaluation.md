# BÁO CÁO KẾT QUẢ HUẤN LUYỆN, HIỆU CHỈNH XÁC SUẤT & ĐÁNH GIÁ MÔ HÌNH DỰ ĐOÁN Ý ĐỊNH MUA HÀNG

- **Thời điểm xuất báo cáo:** `2026-11-09 17:29:34 UTC`
- **Phiên bản `scikit-learn`:** `1.6.1`
- **Chế độ chạy dữ liệu:** `Toàn tập dữ liệu chính thức (Full Dataset Run)`
- **Mô hình Vô địch được chọn (`Champion Model`):** **`HistGradientBoosting (Gradient Boosted Trees)`** (`gradient_boosting`)
- **Tiêu chí chọn mô hình:** `PR-AUC` cao nhất trên tập `Val_Select` (tuyệt đối không dùng tập Test Tháng 12 để tinh chỉnh hay chọn model)
- **Ngưỡng quyết định tối ưu đã khóa (`Locked Optimal Threshold τ*`):** **`0.3100`**

---

## 1. Thống kê Phân chia Dữ liệu Thực nghiệm (`Train_Fit` / `Val_Calib` / `Val_Select` / `Out-of-Time Test`)

| Tập dữ liệu | Nguồn thời gian | Tổng số phiên (`Sessions`) | Số phiên mua (`will_purchase = 1`) | Số phiên không mua (`0`) | Tỷ lệ chuyển đổi (`%`) | Tỷ lệ mất cân bằng | Vai trò trong thực nghiệm |
| --- | --- | ---: | ---: | ---: | ---: | :---: | --- |
| **1. `Train_Fit` (70%)** | `2019-Oct + Nov` | `1,854,093` | `88,531` | `1,765,562` | `4.7749%` | `1 : 19.94` | Huấn luyện trọng số các mô hình gốc (`Base Models`) & `RobustScaler` |
| **2. `Val_Calib` (15%)** | `2019-Oct + Nov` | `397,306` | `18,971` | `378,335` | `4.7749%` | `1 : 19.94` | Khớp bộ Hiệu chỉnh xác suất (`Isotonic / Sigmoid Calibration`) |
| **3. `Val_Select` (15%)** | `2019-Oct + Nov` | `397,306` | `18,971` | `378,335` | `4.7749%` | `1 : 19.94` | Chọn mô hình tốt nhất theo `PR-AUC` & dò ngưỡng tối ưu `τ*` |
| **4. `Out-of-Time Test` (100%)** | **`2019-Dec` (Độc lập)** | `1,786,352` | `55,760` | `1,730,592` | `3.1214%` | `1 : 31.04` | **Chỉ chạy đánh giá đúng 1 lần duy nhất sau khi khóa mô hình & `τ*`** |

---

## 2. Bảng 1 — So sánh 3 Mô hình Nền trên Cùng Bộ 14 Đặc trưng (`Validation` vs. `Out-of-Time Test 2019-Dec`)

### 2.1 Kết quả trên Tập `Val_Select` (Dùng để chọn mô hình và khóa ngưỡng `τ*`)

| Mô hình (`Model`) | `PR-AUC` (Chính) | `ROC-AUC` | `Brier Score` | Ngưỡng `τ*` | `F1 (@τ*)` | `Precision (@τ*)` | `Recall (@τ*)` | `F1 (@0.50)` | Thời gian Train (s) |
| --- | ---: | ---: | ---: | ---: | ---: | ---: | ---: | ---: | ---: |
| **Logistic Regression (Linear Baseline)** | **`0.3441`** | `0.8348` | `0.0347` | `0.2238` | **`0.4741`** | `0.3857` | `0.6153` | `0.0000` | `6.73s` |
| **Random Forest (Bagging Tree Ensemble)** | **`0.4807`** | `0.8692` | `0.0314` | `0.2800` | **`0.5325`** | `0.5343` | `0.5308` | `0.4364` | `186.08s` |
| 🏆 **HistGradientBoosting (Gradient Boosted Trees)** | **`0.4942`** | `0.8765` | `0.0311` | `0.3100` | **`0.5384`** | `0.5553` | `0.5226` | `0.4757` | `44.11s` |
| **Early-Intent HistGB (View-Only Ablation, No Cart)** | **`0.3690`** | `0.8141` | `0.0359` | `0.2236` | **`0.4115`** | `0.5958` | `0.3143` | `0.3837` | `39.84s` |

### 2.2 Kết quả Chính thức (1 Lần Duy Nhất) trên Tập Test Độc lập Tháng 12 (`2019-Dec`)

| Mô hình (`Model`) | `PR-AUC` (Chính) | `ROC-AUC` | `Brier Score` | Ngưỡng khóa `τ*` | `F1 (@τ*)` | `Precision (@τ*)` | `Recall (@τ*)` | `F1 (@0.50)` | Ma trận nhầm lẫn (`TP / FP / TN / FN`) |
| --- | ---: | ---: | ---: | ---: | ---: | ---: | ---: | ---: | --- |
| **Logistic Regression (Linear Baseline)** | **`0.5735`** | `0.9803` | `0.0167` | `0.2238` | **`0.6303`** | `0.4787` | `0.9223` | `0.0000` | `TP=51,427, FP=55,993, TN=1,674,599, FN=4,333` |
| **Random Forest (Bagging Tree Ensemble)** | **`0.6742`** | `0.9838` | `0.0150` | `0.2800` | **`0.6679`** | `0.5932` | `0.7641` | `0.5583` | `TP=42,605, FP=29,213, TN=1,701,379, FN=13,155` |
| 🏆 **HistGradientBoosting (Gradient Boosted Trees)** | **`0.6695`** | `0.9832` | `0.0151` | `0.3100` | **`0.6631`** | `0.5953` | `0.7485` | `0.5914` | `TP=41,736, FP=28,377, TN=1,702,215, FN=14,024` |
| **Early-Intent HistGB (View-Only Ablation, No Cart)** | **`0.4409`** | `0.8789` | `0.0210` | `0.2236` | **`0.5410`** | `0.7072` | `0.4381` | `0.4861` | `TP=24,428, FP=10,116, TN=1,720,476, FN=31,332` |

---

## 3. Bảng 2 — Đánh giá Hiệu chỉnh Xác suất Dự đoán (`Probability Calibration: Uncalibrated vs. Calibrated`)

> **Ý nghĩa kỹ thuật:** Khi bật `class_weight='balanced'` để xử lý tỷ lệ mất cân bằng `1 : 19.94`, xác suất dự đoán thô (`Uncalibrated`) bị đẩy vọt lên cao gấp nhiều lần tỷ lệ mua thực tế. Hiệu chỉnh xác suất (`Isotonic` / `Sigmoid`) trên `Val_Calib` kéo xác suất dự đoán về đúng tỷ lệ chuyển đổi thực nghiệm, giúp `Brier Score`, `Log Loss` và `ECE` giảm mạnh mà vẫn bảo toàn `PR-AUC`.

| Mô hình (`Model`) | Phương pháp chọn | `Brier (Uncal)` $\rightarrow$ **`Brier (Cal)`** | `LogLoss (Uncal)` $\rightarrow$ **`LogLoss (Cal)`** | `ECE (Uncal)` $\rightarrow$ **`ECE (Cal)`** | Xác suất TB `Uncal` $\rightarrow$ **`Cal`** *(Thực tế Test: `3.12%`)* |
| --- | :---: | :---: | :---: | :---: | :---: |
| **Logistic Regression (Linear Baseline)** | `isotonic` | `0.1021` $\rightarrow$ **`0.0167`** | `0.3929` $\rightarrow$ **`0.0640`** | `0.2844` $\rightarrow$ **`0.0233`** | `31.56%` $\rightarrow$ **`4.14%`** |
| **Random Forest (Bagging Tree Ensemble)** | `isotonic` | `0.0876` $\rightarrow$ **`0.0150`** | `0.3431` $\rightarrow$ **`0.0588`** | `0.2532` $\rightarrow$ **`0.0185`** | `28.44%` $\rightarrow$ **`4.18%`** |
| **HistGradientBoosting (Gradient Boosted Trees)** | `sigmoid` | `0.0862` $\rightarrow$ **`0.0151`** | `0.3352` $\rightarrow$ **`0.0586`** | `0.2417` $\rightarrow$ **`0.0170`** | `27.29%` $\rightarrow$ **`4.23%`** |
| **Early-Intent HistGB (View-Only Ablation, No Cart)** | `sigmoid` | `0.1252` $\rightarrow$ **`0.0210`** | `0.4195` $\rightarrow$ **`0.0927`** | `0.2940` $\rightarrow$ **`0.0110`** | `32.53%` $\rightarrow$ **`3.95%`** |

### Bảng Đường cong Độ tin cậy 10 Khoảng (`10-Bin Reliability Diagram`) — Mô hình Vô địch `HistGradientBoosting (Gradient Boosted Trees)` trên Tập Test Tháng 12

| Khoảng xác suất dự đoán (`Bin`) | Số lượng phiên (`Count`) | Xác suất dự đoán TB (`Mean Predicted`) | Tỷ lệ mua thực tế (`Empirical Positive`) | Độ lệch tuyệt đối (`|Gap|`) |
| :---: | ---: | ---: | ---: | ---: |
| `[0.0, 0.1)` | `1,669,209` | `0.0161` | `0.0011` | `0.0150` |
| `[0.1, 0.2)` | `22,215` | `0.1504` | `0.2131` | `0.0627` |
| `[0.2, 0.3)` | `23,024` | `0.2480` | `0.2993` | `0.0513` |
| `[0.3, 0.4)` | `17,521` | `0.3500` | `0.3931` | `0.0431` |
| `[0.4, 0.5)` | `13,871` | `0.4482` | `0.5039` | `0.0557` |
| `[0.5, 0.6)` | `10,104` | `0.5481` | `0.6108` | `0.0628` |
| `[0.6, 0.7)` | `11,247` | `0.6526` | `0.6859` | `0.0333` |
| `[0.7, 0.8)` | `18,348` | `0.7511` | `0.7602` | `0.0092` |
| `[0.8, 0.9)` | `813` | `0.8076` | `0.7798` | `0.0277` |
| `[0.9, 1.0]` | `0` | `0.0000` | `0.0000` | `0.0000` |

---

## 4. Bảng 3 — Đánh giá theo 3 Lát cắt Thực tế (`Multi-Slice & Cart-Abandonment Evaluation` trên Tập Test Tháng 12)

### 4.1 Lát cắt B (`Cart-Active Subset`: Các phiên đã có `cart_count >= 1` — Phân biệt Chốt đơn thật vs. Bỏ quên giỏ hàng)

> **Chứng minh mô hình không suy biến thành luật `if cart_count >= 1`:** Trên tập con các khách hàng đã thêm sản phẩm vào giỏ (`cart_count >= 1`), luật đơn giản `if cart_count >= 1` sẽ dự đoán 100% là mua hàng (`Recall = 1.0` nhưng không phân biệt được ai bỏ giỏ hàng, `ROC-AUC = 0.5000`). Trong khi đó, các mô hình ML sử dụng `repeat_view_ratio`, `session_duration_sec`, `cart_to_view_ratio`, `avg_price` để phân tách chính xác người mua thật và người bỏ quên giỏ hàng.

| Mô hình / Luật so sánh trên tập `cart_count >= 1` | Tổng phiên có giỏ | `PR-AUC` | `ROC-AUC` | `F1-Score (@τ*)` | `Precision (@τ*)` | `Recall (@τ*)` | Ma trận nhầm lẫn (`TP / FP / TN / FN`) |
| --- | ---: | ---: | ---: | ---: | ---: | ---: | --- |
| **Rule Baseline (`if cart_count >= 1: return 1`)** | `119,782` | `0.4594` | `0.5000` | `0.6295` | `0.4594` | `1.0000` | `TP=55,023, FP=64,759, TN=0, FN=0` |
| **Logistic Regression (Linear Baseline)** | `119,782` | **`0.5803`** | **`0.6549`** | **`0.6332`** | `0.4788` | `0.9346` | `TP=51,427, FP=55,978, TN=8,781, FN=3,596` |
| **Random Forest (Bagging Tree Ensemble)** | `119,782` | **`0.6822`** | **`0.7319`** | **`0.6718`** | `0.5932` | `0.7743` | `TP=42,605, FP=29,213, TN=35,546, FN=12,418` |
| **HistGradientBoosting (Gradient Boosted Trees)** | `119,782` | **`0.6782`** | **`0.7237`** | **`0.6671`** | `0.5953` | `0.7585` | `TP=41,736, FP=28,377, TN=36,382, FN=13,287` |

### 4.2 Lát cắt C (`Early-Intent Ablation`: Dự báo sớm khi loại bỏ hoàn toàn các biến giỏ hàng)

- **Mô hình `Early-Intent HistGB (View-Only Ablation, No Cart)`** (chỉ học từ hành vi xem `view_count`, `repeat_view_ratio`, `session_duration_sec`, `avg_price`, `price_range_ratio`, `hour`, `day_of_week`, `is_weekend`):
  - Đạt **`ROC-AUC = 0.8789`** và **`PR-AUC = 0.4409`** trên Tập Test Tháng 12 (cao hơn nhiều lần so với tỷ lệ ngẫu nhiên `0.0312`), chứng minh các đặc trưng duyệt sản phẩm và thời lượng phiên đã được cắt trần `3600s` mang tín hiệu dự báo sớm thực sự.

---

## 5. Bảng 4 — Xếp hạng Mức độ Quan trọng của các Đặc trưng (`Feature Importance`)

### 5.1 Độ quan trọng đặc trưng trên Mô hình Vô địch (`HistGradientBoosting (Gradient Boosted Trees)`)

| Hạng (`Rank`) | Tên đặc trưng (`Feature`) | Tỷ trọng đóng góp (`Importance %`) | Giá trị thô (`Raw Score`) | Phương pháp đo |
| :---: | --- | ---: | ---: | --- |
| `1` | `cart_count` | **`51.37%`** | `0.372179` | `permutation_pr_auc_importance` |
| `2` | `cart_to_view_ratio` | **`29.22%`** | `0.211733` | `permutation_pr_auc_importance` |
| `3` | `repeat_view_ratio` | **`8.25%`** | `0.059804` | `permutation_pr_auc_importance` |
| `4` | `session_duration_sec` | **`4.86%`** | `0.035191` | `permutation_pr_auc_importance` |
| `5` | `min_price` | **`3.38%`** | `0.024484` | `permutation_pr_auc_importance` |
| `6` | `avg_price` | **`2.12%`** | `0.015378` | `permutation_pr_auc_importance` |
| `7` | `is_weekend` | **`0.38%`** | `0.002762` | `permutation_pr_auc_importance` |
| `8` | `unique_categories` | **`0.21%`** | `0.001524` | `permutation_pr_auc_importance` |
| `9` | `view_count` | **`0.16%`** | `0.001189` | `permutation_pr_auc_importance` |
| `10` | `unique_products` | **`0.04%`** | `0.000317` | `permutation_pr_auc_importance` |
| `11` | `remove_cart_count` | **`0.00%`** | `0.000000` | `permutation_pr_auc_importance` |
| `12` | `max_price` | **`0.00%`** | `0.000000` | `permutation_pr_auc_importance` |
| `13` | `hour` | **`0.00%`** | `0.000000` | `permutation_pr_auc_importance` |
| `14` | `day_of_week` | **`0.00%`** | `0.000000` | `permutation_pr_auc_importance` |
| `15` | `price_range_ratio` | **`0.00%`** | `0.000000` | `permutation_pr_auc_importance` |

### 5.2 Độ quan trọng đặc trưng trên Mô hình Dự báo sớm (`Early-Intent HistGB (View-Only Ablation, No Cart)` — Không có biến giỏ hàng)

| Hạng (`Rank`) | Tên đặc trưng (`Feature`) | Tỷ trọng đóng góp (`Importance %`) | Giá trị thô (`Raw Score`) | Phương pháp đo |
| :---: | --- | ---: | ---: | --- |
| `1` | `session_duration_sec` | **`52.31%`** | `0.385227` | `permutation_pr_auc_importance` |
| `2` | `view_count` | **`40.95%`** | `0.301563` | `permutation_pr_auc_importance` |
| `3` | `price_range_ratio` | **`2.18%`** | `0.016080` | `permutation_pr_auc_importance` |
| `4` | `min_price` | **`1.57%`** | `0.011572` | `permutation_pr_auc_importance` |
| `5` | `repeat_view_ratio` | **`1.42%`** | `0.010456` | `permutation_pr_auc_importance` |
| `6` | `avg_price` | **`1.15%`** | `0.008472` | `permutation_pr_auc_importance` |
| `7` | `max_price` | **`0.38%`** | `0.002832` | `permutation_pr_auc_importance` |
| `8` | `is_weekend` | **`0.03%`** | `0.000246` | `permutation_pr_auc_importance` |
| `9` | `unique_products` | **`0.00%`** | `0.000000` | `permutation_pr_auc_importance` |
| `10` | `unique_categories` | **`0.00%`** | `0.000000` | `permutation_pr_auc_importance` |
| `11` | `hour` | **`0.00%`** | `0.000000` | `permutation_pr_auc_importance` |
| `12` | `day_of_week` | **`0.00%`** | `0.000000` | `permutation_pr_auc_importance` |
