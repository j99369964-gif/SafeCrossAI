"""Builds the two model files the Streamlit app loads, from what Notebook 2 saved.

Notebook 2 saves ONE fitted scikit-learn pipeline plus a metadata file:

    models/safecross_baseline_pipeline.joblib
    models/safecross_baseline_metadata.json

The app instead loads a "bundle" (preprocessor, model, and feature lists kept
together) and an app-facing metadata file:

    models/safecross_model_bundle.joblib
    models/safecross_model_metadata.json

This script converts one into the other. It does not retrain anything. RE-RUN IT
every time Notebook 2 is re-run, otherwise the app keeps using an older model.

Run from the REPOSITORY ROOT:

    python scripts/make_model_bundle.py
"""

from __future__ import annotations

import json
import sys
from pathlib import Path

import joblib

REPO_ROOT = Path(__file__).resolve().parent.parent

PIPELINE_PATH = REPO_ROOT / "models" / "safecross_baseline_pipeline.joblib"
BASELINE_METADATA_PATH = REPO_ROOT / "models" / "safecross_baseline_metadata.json"
BUNDLE_PATH = REPO_ROOT / "models" / "safecross_model_bundle.joblib"
APP_METADATA_PATH = REPO_ROOT / "models" / "safecross_model_metadata.json"

# GitHub rejects files over 100 MB, and Streamlit Community Cloud deploys from GitHub.
GITHUB_FILE_LIMIT_MB = 100


def main() -> None:
    for path in (PIPELINE_PATH, BASELINE_METADATA_PATH):
        if not path.exists():
            sys.exit(f"Missing {path}.\nRun Notebook 2 completely first (its model-saving step).")

    pipeline = joblib.load(PIPELINE_PATH)
    with open(BASELINE_METADATA_PATH, "r", encoding="utf-8") as file:
        metadata = json.load(file)

    steps = getattr(pipeline, "named_steps", {})
    if "preprocess" not in steps or "model" not in steps:
        sys.exit(f"Unexpected pipeline layout. Found steps: {list(steps)}; expected 'preprocess' and 'model'.")

    numeric_features = list(metadata["numeric_features"])
    categorical_features = list(metadata["categorical_features"])
    raw_features = numeric_features + categorical_features

    # The preprocessor must have been fitted on exactly these columns, in this order.
    fitted_columns = list(getattr(steps["preprocess"], "feature_names_in_", raw_features))
    if fitted_columns != raw_features:
        sys.exit(
            "The pipeline's fitted columns do not match the metadata's feature lists.\n"
            f"Pipeline: {fitted_columns}\nMetadata: {raw_features}\n"
            "These files came from different Notebook 2 runs. Re-run Notebook 2."
        )

    bundle = {
        "preprocessor": steps["preprocess"],
        "model": steps["model"],
        "raw_features": raw_features,
        "numeric_features": numeric_features,
        "categorical_features": categorical_features,
    }
    joblib.dump(bundle, BUNDLE_PATH, compress=3)

    app_metadata = dict(metadata)
    app_metadata["prediction_horizon_weeks"] = 1  # Notebook 2: "week t features predict week t+1"
    app_metadata["xgboost_training_device"] = "cpu" if metadata.get("selected_model") == "xgboost" else "n/a"
    with open(APP_METADATA_PATH, "w", encoding="utf-8") as file:
        json.dump(app_metadata, file, indent=2)

    size_mb = BUNDLE_PATH.stat().st_size / 1e6
    print(f"Selected model: {metadata.get('selected_model')}")
    print(f"Saved: {BUNDLE_PATH.relative_to(REPO_ROOT)} ({size_mb:.1f} MB)")
    print(f"Saved: {APP_METADATA_PATH.relative_to(REPO_ROOT)}")
    if size_mb > GITHUB_FILE_LIMIT_MB * 0.9:
        print(
            f"WARNING: the bundle is {size_mb:.0f} MB, close to or over GitHub's {GITHUB_FILE_LIMIT_MB} MB "
            "file limit. This usually means a random forest was the selected model (its size grows with "
            "the training rows). Options: deploy a gradient-boosting model instead, retrain the forest with "
            "fewer/shallower trees, or use Git LFS."
        )


if __name__ == "__main__":
    main()
