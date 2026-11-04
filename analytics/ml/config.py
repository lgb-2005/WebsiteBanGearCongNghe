from pathlib import Path

BASE_DIR = Path(__file__).resolve().parent.parent.parent

DATASET_DIR = BASE_DIR / "dataset_example_trainModel"
ARTIFACTS_DIR = Path(__file__).resolve().parent / "artifacts"

TRAIN_CSV_FILES = [
    "2019-Oct.csv",
    "2019-Nov.csv",
]

TEST_CSV_FILES = [
    "2019-Dec.csv",
]

FILTERED_TRAIN_EVENTS_PATH = ARTIFACTS_DIR / "filtered_events.csv"
FILTERED_TEST_EVENTS_PATH = ARTIFACTS_DIR / "filtered_test_events.csv"
PREPROCESS_META_PATH = ARTIFACTS_DIR / "preprocess_meta.json"
PREPROCESS_TEST_META_PATH = ARTIFACTS_DIR / "preprocess_test_meta.json"
SESSION_FEATURES_PATH = ARTIFACTS_DIR / "session_features.csv"
SESSION_TEST_FEATURES_PATH = ARTIFACTS_DIR / "session_test_features.csv"
FEATURE_META_PATH = ARTIFACTS_DIR / "feature_meta.json"
PIPELINE_STATS_REPORT_PATH = Path(__file__).resolve().parent / "pipeline_stats_report.json"
MARKDOWN_REPORT_PATH = BASE_DIR / "del" / "rp_03_pipeline_stats.md"

KAGGLE_CSV_COLUMNS = [
    "event_time",
    "event_type",
    "product_id",
    "category_id",
    "category_code",
    "brand",
    "price",
    "user_id",
    "user_session",
]

VALID_KAGGLE_EVENT_TYPES = (
    "view",
    "cart",
    "remove_from_cart",
    "purchase",
)

KAGGLE_TO_TECHGEAR_EVENT_MAP = {
    "view": "view_product",
    "cart": "add_to_cart",
    "remove_from_cart": "remove_from_cart",
    "purchase": "checkout",
}

TARGET_CATEGORY_PREFIXES = (
    "computers.",
    "electronics.audio.",
)

TARGET_CATEGORY_CODES = (
    "computers.peripherals.mouse",
    "computers.peripherals.keyboard",
    "computers.peripherals.monitor",
    "computers.peripherals.camera",
    "computers.peripherals.printer",
    "computers.notebook",
    "computers.desktop",
    "computers.components.videocards",
    "computers.components.cpu",
    "computers.components.motherboard",
    "computers.components.memory",
    "computers.components.hdd",
    "computers.components.power_supply",
    "computers.components.cooler",
    "electronics.audio.headphone",
    "electronics.audio.microphone",
    "electronics.audio.acoustic",
    "electronics.audio.subwoofer",
)

SESSION_FEATURE_COLUMNS = [
    "view_count",
    "unique_products",
    "unique_categories",
    "cart_count",
    "remove_cart_count",
    "session_duration_sec",
    "avg_price",
    "max_price",
    "min_price",
    "repeat_view_ratio",
    "cart_to_view_ratio",
    "hour",
    "day_of_week",
    "is_weekend",
]

TARGET_LABEL_COLUMN = "will_purchase"

DEFAULT_CHUNK_SIZE = 500_000
