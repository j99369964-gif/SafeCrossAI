"""Shared utilities for the SafeCross AI Streamlit map app."""

from __future__ import annotations

from pathlib import Path
import joblib
import numpy as np
import pandas as pd
import streamlit as st

# --- Project paths ----------------------------------------------------
REPO_ROOT = Path(__file__).resolve().parent.parent
MODEL_BUNDLE_PATH = REPO_ROOT / "models" / "safecross_model_bundle.joblib"
DEMO_DATA_PATH = REPO_ROOT / "data" / "sample" / "safecross_app_demo.csv"

# --- Cached loaders ------------------------------------------------------
@st.cache_resource(show_spinner="Loading model...")
def load_model_bundle() -> dict:
    if not MODEL_BUNDLE_PATH.exists():
        raise FileNotFoundError(f"Missing {MODEL_BUNDLE_PATH}.")
    bundle = joblib.load(MODEL_BUNDLE_PATH)
    force_cpu_for_deployment(bundle["model"])
    return bundle


def force_cpu_for_deployment(model) -> None:
    if hasattr(model, "set_params"):
        try: model.set_params(device="cpu")
        except (ValueError, TypeError): pass

    if hasattr(model, "get_booster"):
        try: model.get_booster().set_param({"device": "cpu"})
        except Exception: pass


@st.cache_data(show_spinner="Loading demo data...")
def load_demo_data() -> pd.DataFrame:
    if not DEMO_DATA_PATH.exists():
        raise FileNotFoundError(f"Missing {DEMO_DATA_PATH}.")
    return pd.read_csv(DEMO_DATA_PATH)


# --- Prediction and presentation -----------------------------------------
def predict_risk(bundle: dict, rows: pd.DataFrame) -> np.ndarray:
    raw_features = bundle["raw_features"]
    transformed = bundle["preprocessor"].transform(rows[raw_features])
    return bundle["model"].predict_proba(transformed)[:, 1]


def assign_risk_tier(probability: pd.Series) -> pd.Series:
    percentile = probability.rank(pct=True) * 100
    conditions = [percentile >= 90, percentile >= 75, percentile >= 50]
    labels = ["Highest-priority (top 10%)", "Elevated relative risk", "Moderate relative risk"]
    return pd.Series(np.select(conditions, labels, default="Lower relative risk"), index=probability.index)


def build_risk_grid(rows: pd.DataFrame, target_bins: int = 18) -> dict:
    if rows.empty or not {"latitude", "longitude", "predicted_probability"}.issubset(rows.columns):
        return {"type": "FeatureCollection", "features": []}

    lat_span = max(rows["latitude"].max() - rows["latitude"].min(), 1e-6)
    lon_span = max(rows["longitude"].max() - rows["longitude"].min(), 1e-6)
    cell_size = max(lat_span, lon_span) / target_bins

    grid_rows = rows.copy()
    grid_rows["cell_lat"] = (grid_rows["latitude"] // cell_size) * cell_size
    grid_rows["cell_lon"] = (grid_rows["longitude"] // cell_size) * cell_size

    cell_groups = grid_rows.groupby(["cell_lat", "cell_lon"])
    features = []
    
    for (cell_lat, cell_lon), cell_points in cell_groups:
        mean_probability = float(cell_points["predicted_probability"].mean())
        dominant_tier = cell_points["risk_tier"].mode().iat[0] if "risk_tier" in cell_points else None
        polygon = [[[cell_lon, cell_lat], [cell_lon + cell_size, cell_lat], [cell_lon + cell_size, cell_lat + cell_size], [cell_lon, cell_lat + cell_size], [cell_lon, cell_lat]]]
        
        features.append({
            "type": "Feature",
            "geometry": {"type": "Polygon", "coordinates": polygon},
            "properties": {"mean_probability": mean_probability, "dominant_tier": dominant_tier, "point_count": int(len(cell_points))},
        })

    return {"type": "FeatureCollection", "features": features}


def format_intersection_label(row: pd.Series) -> str:
    if "intersection_label" in row and pd.notna(row["intersection_label"]):
        return str(row["intersection_label"])
    return f"OSM node {row['node_id']} | {row['latitude']:.4f}, {row['longitude']:.4f}"