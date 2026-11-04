"""Coordinate the three offline stages; preprocessing/reporting belong to Bảo."""

import hashlib
import importlib
import json
import tempfile
from pathlib import Path
from time import perf_counter

import pandas as pd
from django.conf import settings
from django.core.management.base import BaseCommand, CommandError

from analytics.ml.features import (
    INPUT_COLUMNS, OUTPUT_COLUMNS, SCHEMA_VERSION, run_feature_extraction,
)


ARTIFACTS = (
    "filtered_events.csv", "preprocess_meta.json", "session_features.csv",
    "feature_meta.json", "pipeline_stats_report.json",
)


def _positive_int(value):
    import argparse

    try:
        number = int(value)
    except (TypeError, ValueError) as exc:
        raise argparse.ArgumentTypeError("Expected a positive integer") from exc
    if number <= 0:
        raise argparse.ArgumentTypeError("Expected a positive integer")
    return number


def _json(path, value):
    Path(path).write_text(json.dumps(value, indent=2, ensure_ascii=False, allow_nan=False) + "\n",
                          encoding="utf-8")


def _fingerprint(path):
    stat = path.stat()
    return {"path": str(path.resolve()), "size": stat.st_size, "mtime_ns": stat.st_mtime_ns}


def _integration(module_name, function_name):
    try:
        module = importlib.import_module(module_name)
    except ModuleNotFoundError as exc:
        if exc.name == module_name:
            raise CommandError(
                f"Chờ module của Bảo: {module_name}.{function_name}. "
                "Xem analytics/ml/README.md để biết giao diện tích hợp."
            ) from exc
        raise
    function = getattr(module, function_name, None)
    if not callable(function):
        raise CommandError(f"{module_name} must provide {function_name}")
    return module, function


class Command(BaseCommand):
    help = "Preprocess CSV, extract anti-leakage session features and generate statistics."
    # This command handles offline files, not database models.
    requires_system_checks = []

    def add_arguments(self, parser):
        parser.add_argument("--input", nargs="+", dest="inputs", help="One or more raw CSV paths")
        parser.add_argument("--chunk-size", type=_positive_int, default=500_000)
        parser.add_argument("--max-chunks", type=_positive_int)
        parser.add_argument("--force", action="store_true")
        parser.add_argument("--output-dir", type=Path)
        parser.add_argument("--report-md", type=Path)

    def handle(self, *args, **options):
        try:
            return self._run(options)
        except CommandError:
            raise
        except (OSError, ValueError, TypeError, ImportError, KeyError) as exc:
            raise CommandError(f"Data pipeline failed: {exc}") from exc

    def _run(self, options):
        started = perf_counter()
        base = Path(settings.BASE_DIR)
        sources = [Path(path).resolve() for path in (
            options["inputs"] or [base / "dataset_trainmodel" / f"2019-{month}.csv"
                                  for month in ("Oct", "Nov")]
        )]
        if len(set(sources)) != len(sources):
            raise CommandError("Input CSV paths must be distinct")
        for key in ("chunk_size", "max_chunks"):
            value = options[key]
            if value is not None and (isinstance(value, bool) or not isinstance(value, int) or value <= 0):
                raise CommandError(f"{key} must be a positive integer")
        for source in sources:
            if not source.is_file():
                raise CommandError(f"Input CSV not found: {source}")
            missing = set(INPUT_COLUMNS) - set(pd.read_csv(source, nrows=0).columns)
            if missing:
                raise CommandError(f"{source}: missing columns {', '.join(sorted(missing))}")
        partial = options["max_chunks"] is not None
        output = (options["output_dir"] or base / "dataset_trainmodel" / "pipeline_output" /
                  ("smoke" if partial else "train")).resolve()
        report = (options["report_md"] or (
            output / "rp_03_pipeline_stats.md" if partial else base / "del" / "rp_03_pipeline_stats.md"
        )).resolve()
        manifest_path = output / "manifest.json"
        destinations = [output / name for name in ARTIFACTS] + [report, manifest_path]
        if len(set(destinations)) != len(destinations) or set(destinations).intersection(sources):
            raise CommandError("All input/output paths must be distinct")
        if report in (output, output / ".pipeline.lock") or output / ".pipeline.lock" in sources:
            raise CommandError("Report/input paths must not collide with the output directory or run lock")
        if any(path.is_dir() for path in destinations):
            raise CommandError("An output file path points to a directory")
        if partial and report == (base / "del" / "rp_03_pipeline_stats.md").resolve():
            raise CommandError("A partial run must use a separate Markdown report")
        previous = None
        if manifest_path.is_file():
            try:
                previous = json.loads(manifest_path.read_text(encoding="utf-8"))
            except (ValueError, OSError):
                pass
        old_config = previous.get("config") if isinstance(previous, dict) else None
        if isinstance(old_config, dict) and isinstance(old_config.get("partial_run"), bool) and old_config["partial_run"] != partial:
            raise CommandError("Use separate output directories for partial and full runs")

        preprocess_module, preprocess = _integration("analytics.ml.preprocess", "run_preprocessing")
        report_module, report_stats = _integration("analytics.ml.report_stats", "run_report_stats")
        from analytics.ml import config as ml_config, features

        code_paths = [Path(__file__), Path(features.__file__), Path(ml_config.__file__)]
        for module in (preprocess_module, report_module):
            if getattr(module, "__file__", None):
                code_paths.append(Path(module.__file__))
        config = {
            "sources": [_fingerprint(source) for source in sources],
            "chunk_size": options["chunk_size"], "max_chunks": options["max_chunks"],
            "partial_run": partial, "schema_version": SCHEMA_VERSION,
            "output_dir": str(output), "report_md": str(report),
            "code": {str(path.resolve()): hashlib.sha256(path.read_bytes()).hexdigest()
                     for path in code_paths},
        }
        if not options["force"] and self._cached(previous, config, destinations[:-1]):
            self.stdout.write(self.style.SUCCESS(f"Cache valid; reuse results in {output}"))
            return

        output.mkdir(parents=True, exist_ok=True)
        report.parent.mkdir(parents=True, exist_ok=True)
        # A lock avoids interleaved writers and one process invalidating another's manifest.
        lock = output / ".pipeline.lock"
        try:
            handle = lock.open("x", encoding="utf-8")
        except FileExistsError as exc:
            raise CommandError(f"Another run owns {lock}; inspect it before retrying") from exc
        try:
            with handle:
                handle.write("run_data_pipeline\n")
            manifest_path.unlink(missing_ok=True)
            with tempfile.TemporaryDirectory(prefix="pipeline-", dir=output) as temporary:
                work = Path(temporary)
                filtered = work / "filtered_events.csv"
                feature_csv = work / "session_features.csv"
                meta_path = work / "feature_meta.json"
                staged_report = work / "report.md"
                step = perf_counter()
                self.stdout.write("[1/3] Preprocessing raw events...")
                preprocess_meta = preprocess(
                    input_paths=sources, output_csv_path=filtered,
                    meta_json_path=work / "preprocess_meta.json",
                    chunk_size=options["chunk_size"], max_chunks=options["max_chunks"],
                )
                if not isinstance(preprocess_meta, dict):
                    raise ValueError("run_preprocessing must return a metadata dict")
                preprocess_meta["partial_run"] = partial
                preprocess_meta["output_csv_path"] = str(output / "filtered_events.csv")
                _json(work / "preprocess_meta.json", preprocess_meta)
                self.stdout.write(f"[1/3] Complete in {perf_counter() - step:.3f}s")

                step = perf_counter()
                self.stdout.write("[2/3] Extracting pre-purchase session features...")
                feature_meta = run_feature_extraction(
                    filtered, feature_csv, meta_path, chunk_size=options["chunk_size"],
                )
                feature_meta.update({"partial_run": partial,
                                     "input_csv_path": str(output / "filtered_events.csv"),
                                     "output_features_path": str(output / "session_features.csv")})
                _json(meta_path, feature_meta)
                self.stdout.write(
                    f"[2/3] {feature_meta['output_sessions']} sessions; "
                    f"{feature_meta['leakage_events_removed']} events removed; "
                    f"{perf_counter() - step:.3f}s"
                )
                step = perf_counter()
                self.stdout.write("[3/3] Generating statistics reports...")
                report_meta = report_stats(
                    features_path=feature_csv, preprocess_meta=preprocess_meta,
                    feature_meta=feature_meta, output_json_path=work / "pipeline_stats_report.json",
                    output_md_path=staged_report,
                )
                if not isinstance(report_meta, dict):
                    raise ValueError("run_report_stats must return a metadata dict")
                self._validate_outputs(work, staged_report)
                if [_fingerprint(source) for source in sources] != config["sources"]:
                    raise ValueError("Source files changed during the run; retry with stable inputs")
                for name in ARTIFACTS:
                    (work / name).replace(output / name)
                # Markdown can be on a different volume: stage next to its destination.
                with tempfile.NamedTemporaryFile(dir=report.parent, delete=False) as report_handle:
                    report_temp = Path(report_handle.name)
                try:
                    report_temp.write_bytes(staged_report.read_bytes())
                    report_temp.replace(report)
                finally:
                    report_temp.unlink(missing_ok=True)
                manifest = {"status": "complete", "config": config,
                            "outputs": [_fingerprint(path) for path in destinations[:-1]],
                            "duration_seconds": perf_counter() - started}
                staged_manifest = work / "manifest.json"
                _json(staged_manifest, manifest)
                staged_manifest.replace(manifest_path)
                self.stdout.write(f"[3/3] Complete in {perf_counter() - step:.3f}s")
        finally:
            lock.unlink(missing_ok=True)
        self.stdout.write(self.style.SUCCESS(f"Pipeline complete in {perf_counter() - started:.3f}s: {output}"))
        if partial:
            self.stdout.write(self.style.WARNING("PARTIAL RUN: sessions/labels may be incomplete; smoke test only."))

    @staticmethod
    def _cached(previous, config, outputs):
        if not isinstance(previous, dict) or previous.get("status") != "complete" or previous.get("config") != config:
            return False
        try:
            return previous.get("outputs") == [_fingerprint(path) for path in outputs]
        except OSError:
            return False

    @staticmethod
    def _validate_outputs(work, report):
        for name in ARTIFACTS:
            if not (work / name).is_file():
                raise ValueError(f"Stage did not produce {name}")
        if list(pd.read_csv(work / "filtered_events.csv", nrows=0).columns) != INPUT_COLUMNS:
            raise ValueError("Filtered CSV must follow the documented nine-column schema")
        if list(pd.read_csv(work / "session_features.csv", nrows=0).columns) != OUTPUT_COLUMNS:
            raise ValueError("Invalid feature CSV schema")
        for name in ("preprocess_meta.json", "feature_meta.json", "pipeline_stats_report.json"):
            if not isinstance(json.loads((work / name).read_text(encoding="utf-8")), dict):
                raise ValueError(f"{name} must be a JSON object")
        if not report.is_file() or not report.read_text(encoding="utf-8").strip():
            raise ValueError("Statistics stage must produce a non-empty Markdown report")
