"""Loads the SafeCross model and scored intersections for the PWA's API server.

Everything is computed ONCE at start-up (the scoring is the same code the Streamlit app uses:
app/safecross_core.py), then kept in memory. Nothing here talks to Google, and nothing in this
file is Google content, so it may be cached freely.
"""

from __future__ import annotations

import json
import sys
from pathlib import Path

import joblib
import numpy as np
import pandas as pd

# Share the Streamlit app's Streamlit-free modules.
REPO_ROOT_DEFAULT = Path(__file__).resolve().parent.parent.parent
sys.path.insert(0, str(REPO_ROOT_DEFAULT / "app"))

import safecross_core as core  # noqa: E402
from route_utils import IntersectionIndex  # noqa: E402

TIER_ORDER = [
    "Highest-priority (top 10%)",
    "Elevated relative risk",
    "Moderate relative risk",
    "Lower relative risk",
]
MAX_POINTS = 1500
GRID_BINS = 30


def pretty_feature(name: str) -> str:
    return core.feature_display_name(name)


class SafeCrossData:
    def __init__(self, repo_root: Path | str = REPO_ROOT_DEFAULT):
        self.repo_root = Path(repo_root)
        models = self.repo_root / "models"
        bundle_path = models / "safecross_model_bundle.joblib"
        metadata_path = models / "safecross_model_metadata.json"
        for path in (bundle_path, metadata_path):
            if not path.exists():
                raise FileNotFoundError(f"Missing {path}. Run scripts/make_model_bundle.py first.")

        self.bundle = joblib.load(bundle_path)
        core.force_cpu_for_deployment(self.bundle["model"])
        with open(metadata_path, "r", encoding="utf-8") as file:
            self.metadata = json.load(file)

        # ---- score each area (tiers are computed WITHIN each area) ----
        demo_dir = self.repo_root / "data" / "sample"
        sources = {"nyc": demo_dir / "safecross_app_demo.csv", "westchester": demo_dir / "safecross_app_demo_westchester.csv"}
        if not sources["nyc"].exists():
            raise FileNotFoundError(f"Missing {sources['nyc']}. Run scripts/export_streamlit_assets.py first.")
        parts = [core.score_region(self.bundle, pd.read_csv(path), key) for key, path in sources.items() if path.exists()]
        frame = core.add_intersection_labels(pd.concat(parts, ignore_index=True))
        if "week_start" in frame.columns:
            frame = frame.loc[frame["week_start"] == frame["week_start"].max()]
        # Sorted once: highest within-area percentile first. Raw probabilities from different areas are not on one scale.
        self.frame = frame.sort_values(["risk_percentile", "predicted_probability"], ascending=False).reset_index(drop=True)
        self.index = IntersectionIndex.from_scored(self.frame)

        # ---- columnar copies for fast viewport queries ----
        self.lat = self.frame["latitude"].to_numpy(float)
        self.lng = self.frame["longitude"].to_numpy(float)
        self.tier_code = self.frame["risk_tier"].map({t: i for i, t in enumerate(TIER_ORDER)}).fillna(3).astype(int).to_numpy()
        self.pct = self.frame["risk_percentile"].round(0).astype(int).to_numpy()
        self.unvalidated = (~self.frame["validated"].astype(bool)).to_numpy()
        self.area_keys = list(dict.fromkeys(self.frame["region"].tolist()))
        self.area_code = self.frame["region"].map({k: i for i, k in enumerate(self.area_keys)}).to_numpy(int)
        self.node_ids = self.frame["node_id"].astype(str).to_numpy()
        self.id_to_row = {node_id: i for i, node_id in enumerate(self.node_ids)}
        self.areas = [
            {
                "key": key,
                "label": core.REGION_META[key]["label"],
                "validated": bool(core.REGION_META[key]["validated"]),
                "count": int((self.area_code == i).sum()),
            }
            for i, key in enumerate(self.area_keys)
        ]

        self.signal_features = self._rank_signal_features()
        metrics_path = self.repo_root / "reports" / "metrics" / "selected_model_test_metrics.json"
        self.test_metrics = json.load(open(metrics_path, encoding="utf-8")) if metrics_path.exists() else None
        self._grid_cache: dict[tuple, dict] = {}

    # ------------------------------------------------------------------ helpers
    @property
    def snapshot_week(self) -> str | None:
        return self.index.snapshot_week

    @property
    def bounds(self) -> dict:
        south, north, west, east = self.index.bounds
        return {"south": south, "north": north, "west": west, "east": east}

    def _rank_signal_features(self) -> list[str]:
        numeric = list(self.bundle["numeric_features"])
        importance_path = self.repo_root / "reports" / "notebook_02_03" / "permutation_importance.csv"
        if importance_path.exists():
            ranked = [f for f in pd.read_csv(importance_path)["feature"].tolist() if f in numeric and core.is_intersection_signal(f)]
            if ranked:
                return ranked[:8]
        return [f for f in core.FALLBACK_SIGNAL_FEATURES if f in numeric and core.is_intersection_signal(f)]

    def _masks(self, areas: list[str] | None, tiers: list[int] | None) -> np.ndarray:
        mask = np.ones(len(self.frame), dtype=bool)
        if areas is not None:
            allowed = [i for i, k in enumerate(self.area_keys) if k in areas]
            mask &= np.isin(self.area_code, allowed)
        if tiers is not None:
            mask &= np.isin(self.tier_code, tiers)
        return mask

    # ------------------------------------------------------------------ explore
    def summary(self) -> dict:
        return {
            "snapshotWeek": self.snapshot_week,
            "total": int(len(self.frame)),
            "areas": self.areas,
            "tiers": [
                {"code": i, "name": name, "count": int((self.tier_code == i).sum())} for i, name in enumerate(TIER_ORDER)
            ],
            "bounds": self.bounds,
        }

    def points(self, south, north, west, east, areas=None, tiers=None, limit=MAX_POINTS) -> dict:
        """Intersections inside the viewport, highest within-area risk first, capped."""
        limit = int(max(1, min(limit, MAX_POINTS)))
        mask = self._masks(areas, tiers) & (self.lat >= south) & (self.lat <= north) & (self.lng >= west) & (self.lng <= east)
        rows = np.flatnonzero(mask)  # already in risk order because the frame is sorted
        total = int(len(rows))
        rows = rows[:limit]
        return {
            "total": total,
            "shown": int(len(rows)),
            "capped": total > len(rows),
            "id": self.node_ids[rows].tolist(),
            "lat": np.round(self.lat[rows], 5).tolist(),
            "lng": np.round(self.lng[rows], 5).tolist(),
            "tier": self.tier_code[rows].tolist(),
            "pct": self.pct[rows].tolist(),
            "unvalidated": self.unvalidated[rows].astype(int).tolist(),
            "area": self.area_code[rows].tolist(),
        }

    def grid(self, areas=None, tiers=None) -> dict:
        """Area-level overview as GeoJSON, colored by the average WITHIN-AREA percentile (0-1)."""
        key = (tuple(sorted(areas)) if areas is not None else None, tuple(sorted(tiers)) if tiers is not None else None)
        if key in self._grid_cache:
            return self._grid_cache[key]
        rows = self.frame.loc[self._masks(areas, tiers)]
        grid_input = rows[["latitude", "longitude", "risk_tier"]].assign(predicted_probability=rows["risk_percentile"] / 100.0)
        result = core.build_risk_grid(grid_input, target_bins=GRID_BINS)
        if len(self._grid_cache) > 64:
            self._grid_cache.clear()
        self._grid_cache[key] = result
        return result

    def intersection(self, node_id: str) -> dict | None:
        position = self.id_to_row.get(str(node_id))
        if position is None:
            return None
        row = self.frame.iloc[position]
        reference = core.same_region_rows(self.frame, row)
        signals = [
            {"feature": pretty_feature(f), "value": round(v, 4), "percentile": None if p is None else int(p * 100)}
            for f, v, p in core.top_signals_for_row(row, self.signal_features, reference=reference)
        ]
        validated = bool(row["validated"])
        crashes = row.get("crashes_last_4w")
        return {
            "id": str(row["node_id"]),
            "label": str(row["intersection_label"]),
            "lat": round(float(row["latitude"]), 5),
            "lng": round(float(row["longitude"]), 5),
            "area": row["region_label"],
            "validated": validated,
            "tier": str(row["risk_tier"]),
            "tierCode": int(self.tier_code[position]),
            "percentile": int(self.pct[position]),
            "connectedStreets": None if pd.isna(row.get("street_count")) else int(row["street_count"]),
            # An area with no crash history must show "not available", never a fake 0.
            "crashesLast4Weeks": int(crashes) if validated and pd.notna(crashes) else None,
            "signals": signals,
            "measures": core.candidate_measures_for_row(row),
            "note": None if validated else core.unvalidated_note([row["region_label"]]),
        }

    def model_info(self) -> dict:
        return {
            "selectedModel": self.metadata.get("selected_model"),
            "testMetrics": self.test_metrics,
            "snapshotWeek": self.snapshot_week,
            "areas": self.areas,
        }
