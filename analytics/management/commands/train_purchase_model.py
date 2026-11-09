"""Django management command for training, calibrating, and evaluating purchase-intent models."""

from __future__ import annotations

from pathlib import Path

from django.core.management.base import BaseCommand, CommandError

from analytics.ml.config import (
    DEFAULT_RANDOM_STATE,
    MODEL_EVAL_REPORT_JSON_PATH,
    MODEL_EVAL_REPORT_MD_PATH,
    MODELS_DIR,
    SESSION_FEATURES_PATH,
    SESSION_TEST_FEATURES_PATH,
)
from analytics.ml.evaluate import run_final_test_evaluation
from analytics.ml.train import run_training_pipeline


class Command(BaseCommand):
    help = (
        "Train >=3 baseline purchase-intent models with 70/15/15 split, probability calibration, "
        "threshold tuning, and optional single-shot evaluation on 2019-Dec Out-of-Time Test set."
    )
    requires_system_checks = []

    def add_arguments(self, parser) -> None:
        parser.add_argument(
            "--train-csv",
            type=Path,
            default=SESSION_FEATURES_PATH,
            help="Path to training session_features.csv (2019-Oct + 2019-Nov).",
        )
        parser.add_argument(
            "--test-csv",
            type=Path,
            default=SESSION_TEST_FEATURES_PATH,
            help="Path to independent Out-of-Time test session_test_features.csv (2019-Dec).",
        )
        parser.add_argument(
            "--models-dir",
            type=Path,
            default=MODELS_DIR,
            help="Output directory for trained .joblib models and metadata.",
        )
        parser.add_argument(
            "--report-json",
            type=Path,
            default=MODEL_EVAL_REPORT_JSON_PATH,
            help="Output path for model_evaluation_report.json.",
        )
        parser.add_argument(
            "--report-md",
            type=Path,
            default=MODEL_EVAL_REPORT_MD_PATH,
            help="Output path for rp_04_model_evaluation.md.",
        )
        parser.add_argument(
            "--sample-size",
            type=int,
            default=None,
            help="Optional stratified sample size for fast smoke testing.",
        )
        parser.add_argument(
            "--random-state",
            type=int,
            default=DEFAULT_RANDOM_STATE,
            help="Random state for reproducible splitting and training.",
        )
        parser.add_argument(
            "--train-only",
            action="store_true",
            help="Run only Stage 1 & Stage 2 (Train + Calibration + Validation Selection) without touching Test CSV.",
        )
        parser.add_argument(
            "--evaluate-only",
            action="store_true",
            help="Run only Stage 3 single-shot evaluation using already frozen models in --models-dir.",
        )

    def handle(self, *args, **options):
        if options["train_only"] and options["evaluate_only"]:
            raise CommandError("Cannot specify both --train-only and --evaluate-only")

        try:
            if not options["evaluate_only"]:
                self.stdout.write("[Stage 1 & 2] Running training, calibration, and threshold tuning...")
                train_summary = run_training_pipeline(
                    train_csv_path=options["train_csv"],
                    models_dir=options["models_dir"],
                    sample_size=options["sample_size"],
                    random_state=options["random_state"],
                )
                self.stdout.write(
                    self.style.SUCCESS(
                        f"Training complete. Champion: {train_summary['champion_model_name']} "
                        f"saved to {train_summary['best_model_path']}"
                    )
                )

            if not options["train_only"]:
                self.stdout.write("[Stage 3] Running single-shot evaluation on Out-of-Time Test set...")
                report = run_final_test_evaluation(
                    test_csv_path=options["test_csv"],
                    models_dir=options["models_dir"],
                    output_json_path=options["report_json"],
                    output_md_path=options["report_md"],
                    sample_size=options["sample_size"],
                    random_state=options["random_state"],
                )
                self.stdout.write(
                    self.style.SUCCESS(
                        f"Evaluation complete. Reports saved to {options['report_json']} "
                        f"and {options['report_md']} (Champion Test PR-AUC: "
                        f"{report['models'][report['champion_model_name']]['test_metrics_all_sessions_calibrated']['pr_auc']:.4f})"
                    )
                )
        except Exception as exc:
            raise CommandError(f"Model training/evaluation pipeline failed: {exc}") from exc
