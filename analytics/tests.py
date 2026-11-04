"""Small offline fixtures; optional real integration awaits Bảo's modules."""

import importlib.util
import io
import json
import tempfile
import types
from contextlib import contextmanager
from pathlib import Path
from unittest import skipUnless
from unittest.mock import patch

import pandas as pd
from django.core.management import call_command
from django.core.management.base import CommandError
from django.test import TestCase

from analytics.ml.features import (
    COUNT_FIELDS, FEATURE_COLUMNS, FLOAT_COLUMNS, INPUT_COLUMNS, INTEGER_COLUMNS,
    OUTPUT_COLUMNS, extract_session_features_from_df, run_feature_extraction,
)


def event(time="2019-10-05 10:00:00 UTC", kind="view", product=1,
          price=100, session="s1", category="computers.peripherals.mouse"):
    return dict(zip(INPUT_COLUMNS, [
        time, kind, product, 2103807459595387724, category, None, price,
        541312140, session,
    ]))


def calculation_fixture():
    return pd.DataFrame([
        event(),
        event("2019-10-05 10:01:00 UTC"),
        event("2019-10-05 10:02:00 UTC", product=2, price=200, category="computers.notebook"),
        event("2019-10-05 10:03:00 UTC", "cart", product=2, price=200, category="computers.notebook"),
    ], columns=INPUT_COLUMNS)


HAS_PREPROCESS = importlib.util.find_spec("analytics.ml.preprocess") is not None
HAS_INTEGRATIONS = all(importlib.util.find_spec(name) is not None for name in (
    "analytics.ml.preprocess", "analytics.ml.report_stats",
))


class SessionFeatureTests(TestCase):
    databases = set()

    def assert_counts(self, meta):
        self.assertEqual(meta["input_events"], meta["output_events"] + meta["leakage_events_removed"])
        self.assertEqual(meta["input_sessions"], meta["output_sessions"] + meta["dropped_no_history_sessions"])
        self.assertEqual(meta["output_sessions"], meta["positive_sessions"] + meta["negative_sessions"])

    def test_anti_data_leakage_cutoff(self):
        frame = pd.DataFrame([
            event("2019-10-05 10:00:00 UTC"),
            event("2019-10-05 10:02:00 UTC", "cart"),
            event("2019-10-05 10:05:00 UTC", "purchase", price=900),
            event("2019-10-05 10:08:00 UTC", price=800),
            event("2019-10-05 10:10:00 UTC", "cart", price=700),
        ])
        original = frame.copy(deep=True)
        result, meta = extract_session_features_from_df(frame)
        row = result.iloc[0]
        self.assertEqual(row.will_purchase, 1)
        self.assertEqual(row.view_count, 1)
        self.assertEqual(row.cart_count, 1)
        self.assertEqual(row.session_duration_sec, 120)
        self.assertEqual(row.max_price, 100)
        self.assertEqual(meta["leakage_events_removed"], 3)
        self.assert_counts(meta)
        pd.testing.assert_frame_equal(frame, original)

    def test_session_feature_calculations(self):
        result, meta = extract_session_features_from_df(calculation_fixture())
        expected = {
            "user_session": "s1", "view_count": 3, "unique_products": 2,
            "unique_categories": 2, "cart_count": 1, "remove_cart_count": 0,
            "session_duration_sec": 180, "avg_price": 150, "max_price": 200,
            "min_price": 100, "repeat_view_ratio": 1 / 3, "cart_to_view_ratio": 1 / 3,
            "hour": 10, "day_of_week": 5, "is_weekend": 1, "will_purchase": 0,
        }
        self.assertEqual(list(result.columns), OUTPUT_COLUMNS)
        self.assertEqual(len(FEATURE_COLUMNS), 14)
        for column, value in expected.items():
            with self.subTest(column=column):
                if column in FLOAT_COLUMNS:
                    self.assertAlmostEqual(result.iloc[0][column], value)
                else:
                    self.assertEqual(result.iloc[0][column], value)
        for column in INTEGER_COLUMNS:
            self.assertEqual(str(result[column].dtype), "int64")
        self.assert_counts(meta)

    def test_simultaneous_events_multiple_purchases_and_dropped_sessions(self):
        frame = pd.DataFrame([
            event("2019-10-05 10:00:00 UTC"),
            event("2019-10-05 10:01:00 UTC", "purchase"),
            event("2019-10-05 10:01:00 UTC", "view", product=2),
            event("2019-10-05 10:02:00 UTC", "purchase"),
            event(kind="purchase", session="only-purchase"),
            event(session="same-time-only"),
            event(kind="purchase", session="same-time-only"),
            event(session="negative"),
        ]).sample(frac=1, random_state=42).reset_index(drop=True)
        result, meta = extract_session_features_from_df(frame)
        self.assertEqual(set(result.user_session), {"s1", "negative"})
        self.assertEqual(result.set_index("user_session").loc["s1", "view_count"], 1)
        self.assertEqual(meta["dropped_no_history_sessions"], 2)
        self.assertEqual(meta["leakage_events_removed"], 6)
        self.assertEqual(meta["input_positive_sessions"], 3)
        self.assert_counts(meta)

    def test_cart_remove_only_and_ratio_above_one(self):
        result, _ = extract_session_features_from_df(pd.DataFrame([
            event(kind="cart"), event(kind="cart", product=2),
            event(kind="remove_from_cart", session="remove"),
            event("2019-10-05 10:01:00 UTC", "purchase", session="remove"),
        ]))
        row = result.set_index("user_session").loc["s1"]
        self.assertEqual(row.cart_to_view_ratio, 2)
        self.assertEqual(row.repeat_view_ratio, 0)
        self.assertEqual(row.unique_products, 2)
        self.assertEqual(row.session_duration_sec, 0)
        self.assertEqual(result.set_index("user_session").loc["remove", "remove_cart_count"], 1)

    def test_cart_only_product_does_not_change_unique_viewed_products(self):
        result, _ = extract_session_features_from_df(pd.DataFrame([
            event(), event(), event(kind="cart", product=2),
        ]))
        self.assertEqual(result.iloc[0].unique_products, 2)
        self.assertEqual(result.iloc[0].repeat_view_ratio, 0.5)

    def test_utc_weekend_and_midnight(self):
        frame = pd.DataFrame([
            event("2019-10-04T23:59:00Z", session="friday"),
            event("2019-10-05T00:01:00Z", session="friday"),
            event("2019-10-07T00:30:00+07:00", session="sunday"),
            event("2019-10-07T00:30:00Z", session="monday"),
        ])
        rows = extract_session_features_from_df(frame)[0].set_index("user_session")
        self.assertEqual(rows.loc["friday", "hour"], 23)
        self.assertEqual(rows.loc["friday", "day_of_week"], 4)
        self.assertEqual(rows.loc["friday", "session_duration_sec"], 120)
        self.assertEqual(rows.loc["friday", "is_weekend"], 0)
        self.assertEqual(rows.loc["sunday", "day_of_week"], 6)
        self.assertEqual(rows.loc["sunday", "hour"], 17)
        self.assertEqual(rows.loc["sunday", "is_weekend"], 1)
        self.assertEqual(rows.loc["monday", "is_weekend"], 0)

    def test_empty_input_and_all_purchase_input(self):
        for frame in (pd.DataFrame(columns=INPUT_COLUMNS), pd.DataFrame([event(kind="purchase")])):
            result, meta = extract_session_features_from_df(frame)
            self.assertTrue(result.empty)
            self.assertEqual(list(result.columns), OUTPUT_COLUMNS)
            self.assertTrue(all(str(result[col].dtype) == "int64" for col in INTEGER_COLUMNS))
            self.assert_counts(meta)

    def test_invalid_contract(self):
        for column, value in (
            ("price", 0), ("price", float("inf")), ("price", float("nan")),
            ("event_time", "invalid"), ("event_time", None), ("event_type", "checkout"),
            ("user_session", " "), ("user_session", None), ("category_code", None),
            ("product_id", 1.2), ("category_id", "9223372036854775808"),
        ):
            with self.subTest(column=column, value=value):
                frame = pd.DataFrame([event()])
                frame[column] = value
                with self.assertRaises(ValueError):
                    extract_session_features_from_df(frame)
        with self.assertRaisesRegex(ValueError, "Missing event columns"):
            extract_session_features_from_df(pd.DataFrame())

    def test_large_identifiers_remain_distinct(self):
        frame = pd.DataFrame([event(product=2103807459595387724), event(product=2103807459595387725)])
        self.assertEqual(extract_session_features_from_df(frame)[0].iloc[0].unique_products, 2)


class FeatureFileTests(TestCase):
    databases = set()

    def test_cross_chunk_and_file_sessions_match_dataframe(self):
        # Concatenation simulates the filtered output of two raw month files.
        first_month = pd.DataFrame([event(), event(session="negative")])
        second_month = pd.DataFrame([
            event("2019-10-05 10:02:00 UTC", "cart"),
            event("2019-10-05 10:05:00 UTC", "purchase"),
            event("2019-10-05 10:07:00 UTC", "view", price=999),
        ])
        frame = pd.concat([first_month, second_month], ignore_index=True)
        expected, expected_meta = extract_session_features_from_df(frame)
        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary)
            source = root / "events.csv"
            frame.to_csv(source, index=False)
            for chunk_size, partitions in ((1, 1), (2, 4), (100, 32)):
                with self.subTest(chunk_size=chunk_size, partitions=partitions):
                    meta = run_feature_extraction(source, root / "features.csv", root / "meta.json",
                                                  chunk_size=chunk_size, partitions=partitions)
                    actual = pd.read_csv(root / "features.csv").sort_values("user_session").reset_index(drop=True)
                    pd.testing.assert_frame_equal(actual, expected, check_dtype=False)
                    self.assertEqual({key: meta[key] for key in COUNT_FIELDS},
                                     {key: expected_meta[key] for key in COUNT_FIELDS})
                    self.assertEqual(json.loads((root / "meta.json").read_text())["output_sessions"], 2)
                    self.assertFalse(list(root.glob("features-*")))

    def test_repartitioning_preserves_complete_sessions(self):
        frame = pd.DataFrame([event(session=f"session-{n}") for n in range(20)])
        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary)
            frame.to_csv(root / "events.csv", index=False)
            meta = run_feature_extraction(root / "events.csv", root / "features.csv",
                                          partitions=1, chunk_size=5, max_partition_bytes=1000)
            self.assertEqual(meta["output_sessions"], 20)
            actual = pd.read_csv(root / "features.csv").sort_values("user_session").reset_index(drop=True)
            pd.testing.assert_frame_equal(actual, extract_session_features_from_df(frame)[0], check_dtype=False)

    def test_oversized_single_session_fails_without_overwriting(self):
        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary)
            calculation_fixture().to_csv(root / "events.csv", index=False)
            output = root / "features.csv"
            output.write_text("original", encoding="utf-8")
            with self.assertRaisesRegex(ValueError, "exceeds the memory budget"):
                run_feature_extraction(root / "events.csv", output, partitions=1, max_partition_bytes=100)
            self.assertEqual(output.read_text(), "original")
            self.assertFalse(list(root.glob("features-*")))

    def test_empty_file_output_and_path_validation(self):
        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary)
            source = root / "empty.csv"
            pd.DataFrame(columns=INPUT_COLUMNS).to_csv(source, index=False)
            meta = run_feature_extraction(source, root / "output.csv")
            self.assertEqual(meta["input_events"], 0)
            self.assertEqual(list(pd.read_csv(root / "output.csv").columns), OUTPUT_COLUMNS)
            with self.assertRaisesRegex(ValueError, "different"):
                run_feature_extraction(source, source)
            with self.assertRaisesRegex(ValueError, "Only CSV"):
                run_feature_extraction(source, root / "features.parquet")
            with self.assertRaisesRegex(ValueError, "positive integer"):
                run_feature_extraction(source, root / "output.csv", chunk_size=0)
            with self.assertRaises(FileNotFoundError):
                run_feature_extraction(root / "missing.csv", root / "output.csv")


@skipUnless(HAS_PREPROCESS, "Chờ preprocess.py của Bảo")
class PreprocessFeatureIntegrationTests(TestCase):
    databases = set()

    def test_real_preprocess_features_cross_file_and_chunk(self):
        from analytics.ml.preprocess import run_preprocessing

        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary)
            first = root / "first.csv"
            second = root / "second.csv"
            calculation_fixture().to_csv(first, index=False)
            pd.DataFrame([
                event("2019-10-05 10:05:00 UTC", "purchase"),
                event("2019-10-05 10:06:00 UTC", price=999),
                event(session="unrelated", category="apparel.shoes"),
            ]).to_csv(second, index=False)
            pre_meta = run_preprocessing([first, second], root / "filtered.csv",
                                         root / "pre_meta.json", chunk_size=1)
            feature_meta = run_feature_extraction(root / "filtered.csv", root / "features.csv",
                                                   root / "feature_meta.json", chunk_size=1)
            actual = pd.read_csv(root / "features.csv")
            self.assertEqual(pre_meta["total_raw_rows"], 7)
            self.assertEqual(pre_meta["valid_filtered_rows"], feature_meta["input_events"])
            self.assertEqual(list(actual.columns), OUTPUT_COLUMNS)
            self.assertEqual(len(actual), 1)
            self.assertEqual(actual.iloc[0].will_purchase, 1)
            self.assertEqual(actual.iloc[0].view_count, 3)
            self.assertEqual(actual.iloc[0].cart_count, 1)
            self.assertEqual(actual.iloc[0].avg_price, 150)
            self.assertEqual(feature_meta["leakage_events_removed"], 2)

    def test_real_preprocess_global_chunk_budget(self):
        from analytics.ml.preprocess import run_preprocessing

        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary)
            for name in ("first.csv", "second.csv"):
                calculation_fixture().to_csv(root / name, index=False)
            meta = run_preprocessing([root / "first.csv", root / "second.csv"], root / "filtered.csv",
                                     root / "meta.json", chunk_size=2, max_chunks=1)
            self.assertEqual(meta["chunks_processed"], 1)
            self.assertEqual(meta["total_raw_rows"], 2)
            self.assertEqual(len(meta["per_file_stats"]), 1)
            self.assertEqual(len(pd.read_csv(root / "filtered.csv")), 2)

    def test_cleaned_identifiers_and_prices_satisfy_feature_contract(self):
        from analytics.ml.preprocess import run_preprocessing

        good = event()
        good.update(product_id="2103807459595387724", category_id="2103807459595387724", user_id="1")
        other = {**good, "product_id": "2103807459595387725", "category_id": "2103807459595387725"}
        rows = [good, other, {**good, "category_id": None}, {**good, "product_id": "1.5"},
                {**good, "user_id": "-1"}, {**good, "category_id": "9223372036854775808"},
                {**good, "price": "inf"}, {**good, "event_time": "invalid"}]
        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary)
            pd.DataFrame(rows).to_csv(root / "raw.csv", index=False)
            meta = run_preprocessing(root / "raw.csv", root / "filtered.csv", root / "meta.json", chunk_size=8)
            actual = pd.read_csv(root / "filtered.csv", dtype="string")
            self.assertEqual(meta["valid_filtered_rows"], 2)
            self.assertEqual(meta["dropped_invalid_rows"], 6)
            self.assertEqual(set(actual.product_id), {good["product_id"], other["product_id"]})
            self.assertEqual(set(actual.category_id), {good["category_id"], other["category_id"]})
            features, _ = extract_session_features_from_df(actual)
            self.assertEqual(features.iloc[0].unique_products, 2)

    def test_preprocess_preserves_subsecond_cutoff(self):
        from analytics.ml.preprocess import run_preprocessing

        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary)
            pd.DataFrame([
                event("2019-10-05T10:00:00.100000001Z"),
                event("2019-10-05T10:00:00.900000001Z", "purchase"),
            ]).to_csv(root / "raw.csv", index=False)
            run_preprocessing(root / "raw.csv", root / "filtered.csv", root / "meta.json", chunk_size=1)
            run_feature_extraction(root / "filtered.csv", root / "features.csv", chunk_size=1)
            actual = pd.read_csv(root / "features.csv")
            self.assertEqual(len(actual), 1)
            self.assertEqual(actual.iloc[0].view_count, 1)
            self.assertEqual(actual.iloc[0].will_purchase, 1)

    def test_preprocess_input_validation_does_not_overwrite_source(self):
        from analytics.ml.preprocess import run_preprocessing

        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary)
            source = root / "raw.csv"
            calculation_fixture().to_csv(source, index=False)
            before = source.read_bytes()
            with self.assertRaisesRegex(ValueError, "different"):
                run_preprocessing(source, source, root / "meta.json")
            with self.assertRaisesRegex(ValueError, "positive integer"):
                run_preprocessing(source, root / "filtered.csv", root / "meta.json", max_chunks=0)
            with self.assertRaisesRegex(ValueError, "positive integer"):
                run_preprocessing(source, root / "filtered.csv", root / "meta.json", chunk_size=None)
            self.assertEqual(source.read_bytes(), before)

    def test_preprocess_empty_output_is_feature_compatible(self):
        from analytics.ml.preprocess import run_preprocessing

        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary)
            pd.DataFrame([event(category="apparel.shoes")]).to_csv(root / "raw.csv", index=False)
            pre = run_preprocessing(root / "raw.csv", root / "filtered.csv", root / "meta.json", chunk_size=1)
            features = run_feature_extraction(root / "filtered.csv", root / "features.csv")
            self.assertEqual(pre["valid_filtered_rows"], 0)
            self.assertEqual(features["output_sessions"], 0)
            self.assertEqual(list(pd.read_csv(root / "features.csv").columns), OUTPUT_COLUMNS)


@contextmanager
def stub_integrations(*, fail_report=False):
    """Orchestration doubles only: these do not establish real E2E acceptance."""
    preprocessor = types.ModuleType("analytics.ml.preprocess")
    reporter = types.ModuleType("analytics.ml.report_stats")

    def preprocess(*, input_paths, output_csv_path, meta_json_path, chunk_size, max_chunks):
        frames = [pd.read_csv(path) for path in input_paths]
        pd.concat(frames, ignore_index=True)[INPUT_COLUMNS].to_csv(output_csv_path, index=False)
        return {"input_events": sum(map(len, frames)), "stub": True}

    def report(*, features_path, preprocess_meta, feature_meta, output_json_path, output_md_path):
        if fail_report:
            raise ValueError("Simulated report failure")
        data = {"stub": True, "partial_run": preprocess_meta["partial_run"],
                "sessions": len(pd.read_csv(features_path))}
        Path(output_json_path).write_text(json.dumps(data), encoding="utf-8")
        Path(output_md_path).write_text("# Test double report\n", encoding="utf-8")
        return data

    preprocessor.run_preprocessing = preprocess
    reporter.run_report_stats = report
    with patch.dict("sys.modules", {preprocessor.__name__: preprocessor, reporter.__name__: reporter}):
        yield


class PipelineCommandTests(TestCase):
    databases = set()

    def setUp(self):
        temporary = tempfile.TemporaryDirectory()
        self.addCleanup(temporary.cleanup)
        self.root = Path(temporary.name)
        self.source = self.root / "source.csv"
        calculation_fixture().to_csv(self.source, index=False)
        self.output = self.root / "results"
        self.report = self.root / "report.md"

    def run_command(self, **options):
        output = io.StringIO()
        call_command("run_data_pipeline", inputs=[str(self.source)], output_dir=self.output,
                     report_md=self.report, stdout=output, **options)
        return output.getvalue()

    def test_orchestration_cache_force_and_invalidation_with_stubs(self):
        with stub_integrations():
            log = self.run_command()
            self.assertIn("Pipeline complete", log)
            self.assertIn("Cache valid", self.run_command())
            self.assertNotIn("Cache valid", self.run_command(force=True))
            self.assertNotIn("Cache valid", self.run_command(chunk_size=2))
            # Output tampering, changed source and missing artifacts invalidate reuse.
            self.report.write_text("changed", encoding="utf-8")
            self.assertNotIn("Cache valid", self.run_command(chunk_size=2))
            pd.concat([calculation_fixture(), pd.DataFrame([event(session="second")])]).to_csv(self.source, index=False)
            self.assertNotIn("Cache valid", self.run_command(chunk_size=2))
            (self.output / "feature_meta.json").unlink()
            self.assertNotIn("Cache valid", self.run_command(chunk_size=2))
        manifest = json.loads((self.output / "manifest.json").read_text())
        self.assertEqual(manifest["status"], "complete")
        self.assertEqual(len(pd.read_csv(self.output / "session_features.csv")), 2)
        meta = json.loads((self.output / "feature_meta.json").read_text())
        self.assertEqual(meta["output_features_path"], str(self.output / "session_features.csv"))

    def test_report_failure_does_not_publish_or_leave_cache(self):
        with stub_integrations():
            self.run_command()
        before = (self.output / "session_features.csv").read_bytes()
        with stub_integrations(fail_report=True):
            with self.assertRaisesRegex(CommandError, "Simulated report failure"):
                self.run_command(force=True)
        self.assertFalse((self.output / "manifest.json").exists())
        self.assertFalse((self.output / ".pipeline.lock").exists())
        self.assertEqual((self.output / "session_features.csv").read_bytes(), before)
        self.assertFalse(list(self.output.glob("pipeline-*")))

    def test_smoke_metadata_and_separation_from_full(self):
        with stub_integrations():
            self.assertIn("PARTIAL RUN", self.run_command(max_chunks=1))
            self.assertTrue(json.loads((self.output / "feature_meta.json").read_text())["partial_run"])
            with self.assertRaisesRegex(CommandError, "separate output directories"):
                self.run_command(force=True)

    def test_defaults_require_both_training_months(self):
        with self.settings(BASE_DIR=self.root):
            dataset = self.root / "dataset_trainmodel"
            dataset.mkdir()
            calculation_fixture().to_csv(dataset / "2019-Oct.csv", index=False)
            with self.assertRaisesRegex(CommandError, "2019-Nov.csv"):
                call_command("run_data_pipeline", stdout=io.StringIO())

    def test_validation_rejects_overwrite_and_invalid_chunk(self):
        with self.assertRaisesRegex(CommandError, "distinct"):
            call_command("run_data_pipeline", inputs=[str(self.source)], output_dir=self.root,
                         report_md=self.source, stdout=io.StringIO())
        with self.assertRaisesRegex(CommandError, "positive integer"):
            self.run_command(chunk_size=0)

    def test_missing_integration_explains_dependency(self):
        with patch("analytics.management.commands.run_data_pipeline.importlib.import_module",
                   side_effect=ModuleNotFoundError("Missing Bảo module", name="analytics.ml.preprocess")):
            with self.assertRaisesRegex(CommandError, "Chờ module của Bảo"):
                self.run_command()
        self.assertFalse(self.output.exists())

    def test_concurrent_run_lock_is_preserved(self):
        self.output.mkdir()
        lock = self.output / ".pipeline.lock"
        lock.write_text("existing owner", encoding="utf-8")
        with stub_integrations():
            with self.assertRaisesRegex(CommandError, "Another run owns"):
                self.run_command()
        self.assertEqual(lock.read_text(), "existing owner")

    def test_corrupt_manifest_is_recomputed(self):
        self.output.mkdir()
        for invalid in ("not json", '{"config": []}', "[]"):
            with self.subTest(manifest=invalid), stub_integrations():
                (self.output / "manifest.json").write_text(invalid, encoding="utf-8")
                self.assertNotIn("Cache valid", self.run_command())
                self.assertEqual(json.loads((self.output / "manifest.json").read_text())["status"], "complete")

    def test_source_mutation_aborts_before_publishing(self):
        from analytics.management.commands.run_data_pipeline import _integration

        with stub_integrations():
            module, original_report = _integration("analytics.ml.report_stats", "run_report_stats")

            def mutate_source(**kwargs):
                result = original_report(**kwargs)
                self.source.write_text("changed source\n", encoding="utf-8")
                return result

            module.run_report_stats = mutate_source
            with self.assertRaisesRegex(CommandError, "Source files changed"):
                self.run_command()
        self.assertFalse((self.output / "manifest.json").exists())
        self.assertFalse((self.output / "session_features.csv").exists())
        self.assertFalse((self.output / ".pipeline.lock").exists())

    @skipUnless(HAS_PREPROCESS, "Chờ preprocess.py của Bảo")
    def test_command_uses_real_preprocess_and_stages_its_metadata(self):
        real_preprocess = importlib.import_module("analytics.ml.preprocess")
        with stub_integrations(), patch.dict("sys.modules", {"analytics.ml.preprocess": real_preprocess}):
            with patch.object(real_preprocess, "run_preprocessing", wraps=real_preprocess.run_preprocessing) as spy:
                self.run_command(chunk_size=1)
                metadata_path = spy.call_args.kwargs["meta_json_path"]
                self.assertEqual(metadata_path.name, "preprocess_meta.json")
                self.assertEqual(metadata_path.parent.parent, self.output)
                self.assertFalse(metadata_path.exists())  # staging cleaned after publication
        meta = json.loads((self.output / "preprocess_meta.json").read_text())
        self.assertEqual(meta["total_raw_rows"], 4)
        self.assertEqual(meta["valid_filtered_rows"], 4)
        self.assertEqual(meta["output_csv_path"], str(self.output / "filtered_events.csv"))
        self.assertFalse(meta["partial_run"])


class RealPipelineIntegrationTests(TestCase):
    databases = set()

    @skipUnless(HAS_PREPROCESS, "Chờ preprocess.py của Bảo")
    def test_category_filter_and_cleaning(self):
        from analytics.ml.preprocess import run_preprocessing

        frame = pd.DataFrame([
            event(), event(category="computers.notebook", session="notebook"),
            event(category="electronics.audio.headphone", session="audio"),
            event(category="apparel.shoes"), event(category="appliances.kitchen.washer"),
            event(price=0), event(price=-1), event(session=None), event(session=""),
        ])
        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary)
            frame.to_csv(root / "raw.csv", index=False)
            metadata = run_preprocessing(input_paths=[root / "raw.csv"], output_csv_path=root / "filtered.csv",
                                         meta_json_path=root / "preprocess_meta.json", chunk_size=2, max_chunks=None)
            actual = pd.read_csv(root / "filtered.csv")
            self.assertEqual(len(actual), 3)
            self.assertEqual(set(actual.user_session), {"s1", "notebook", "audio"})
            self.assertIsInstance(metadata, dict)
            self.assertEqual(metadata["total_raw_rows"], 9)
            self.assertEqual(metadata["dropped_non_target_category"], 2)
            self.assertEqual(metadata["dropped_invalid_rows"], 4)
            self.assertEqual(metadata["valid_filtered_rows"], 3)

    @skipUnless(HAS_INTEGRATIONS, "Chờ report_stats.py của Bảo; không thay E2E bằng mock")
    def test_end_to_end_pipeline_command(self):
        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary)
            frame = pd.concat([calculation_fixture(), pd.DataFrame([
                event("2019-10-05 10:05:00 UTC", "purchase"),
                event("2019-10-05 10:06:00 UTC", price=999),
            ])], ignore_index=True)
            frame.to_csv(root / "raw.csv", index=False)
            call_command("run_data_pipeline", inputs=[str(root / "raw.csv")], output_dir=root / "out",
                         report_md=root / "report.md", chunk_size=1, stdout=io.StringIO())
            actual = pd.read_csv(root / "out" / "session_features.csv")
            self.assertEqual(list(actual.columns), OUTPUT_COLUMNS)
            self.assertEqual(actual.iloc[0].will_purchase, 1)
            self.assertEqual(actual.iloc[0].view_count, 3)
            self.assertEqual(actual.iloc[0].avg_price, 150)
            meta = json.loads((root / "out" / "feature_meta.json").read_text())
            self.assertEqual(meta["leakage_events_removed"], 2)
            self.assertTrue((root / "out" / "pipeline_stats_report.json").is_file())
            self.assertTrue((root / "report.md").read_text(encoding="utf-8").strip())
