"""Observed crash history for the 3D map: monthly crash counts per H3 hexagon, summed over a chosen period.

The file is built by scripts/build_historical_density.py. It is OBSERVED history only and has nothing to do with the
model's predictions. Summing pre-aggregated monthly rows keeps every request small and fast: the browser gets one row
per hexagon (a few thousand), never the millions of crash records behind them.
"""

from __future__ import annotations

from pathlib import Path

import numpy as np
import pandas as pd

METRICS = {
    "all": "crash_count",
    "injury": "injury_crash_count",
    "pedestrian": "pedestrian_crash_count",
    "cyclist": "cyclist_crash_count",
}
CACHE_SIZE = 32


class HistoricalDensity:
    def __init__(self, monthly_path: Path, cells_path: Path | None = None):
        monthly = pd.read_parquet(monthly_path)
        monthly["month"] = pd.to_datetime(monthly["month"]).dt.to_period("M")
        self.cell_ids = np.array(sorted(monthly["h3_cell"].unique()))
        code = pd.Series(np.arange(len(self.cell_ids)), index=self.cell_ids)
        # Columnar copies: one month code and one cell code per row, so a period is a mask plus a bincount.
        self.month = monthly["month"].dt.year.to_numpy() * 12 + monthly["month"].dt.month.to_numpy() - 1
        self.cell = code.reindex(monthly["h3_cell"]).to_numpy()
        self.counts = {key: monthly[column].to_numpy(np.int64) for key, column in METRICS.items()}
        self.first, self.last = monthly["month"].min(), monthly["month"].max()

        boroughs = pd.Series("", index=self.cell_ids, dtype=object)
        if cells_path is not None and Path(cells_path).exists():
            names = pd.read_parquet(cells_path).set_index("h3_cell")["borough"]
            boroughs.update(names)
        self.borough_names = sorted(n for n in boroughs.unique() if n)
        lookup = {name: i for i, name in enumerate(self.borough_names)}
        self.borough_code = boroughs.map(lambda n: lookup.get(n, -1)).to_numpy(int)
        self._cache: dict[tuple[str, str], dict] = {}

    @classmethod
    def load(cls, repo_root: Path) -> "HistoricalDensity | None":
        processed = Path(repo_root) / "data" / "processed"
        monthly = processed / "historical_spatial_monthly.parquet"
        return cls(monthly, processed / "historical_cells.parquet") if monthly.exists() else None

    def meta(self) -> dict:
        # The last COMPLETE calendar year in the data, so "one year" is never a partial year.
        last_full = self.last.year if self.last.month == 12 else self.last.year - 1
        first = str(self.first)
        presets = [
            {"key": "year", "label": str(last_full), "from": f"{last_full}-01", "to": f"{last_full}-12"},
            {"key": "5y", "label": f"{last_full - 4}–{last_full}", "from": f"{last_full - 4}-01", "to": f"{last_full}-12"},
            {"key": "10y", "label": f"{last_full - 9}–{last_full}", "from": f"{last_full - 9}-01", "to": f"{last_full}-12"},
            {"key": "all", "label": "Full available history", "from": first, "to": str(self.last)},
        ]
        return {"first": first, "last": str(self.last), "presets": presets, "metrics": list(METRICS), "cells": len(self.cell_ids)}

    def parse_month(self, text: str) -> pd.Period:
        period = pd.Period(text, freq="M")  # raises ValueError on junk
        return min(max(period, self.first), self.last)

    def period(self, start: str, end: str) -> dict:
        """Counts per hexagon between two months (inclusive), only for hexagons with at least one crash."""
        first, last = self.parse_month(start), self.parse_month(end)
        if first > last:
            first, last = last, first
        key = (str(first), str(last))
        if key in self._cache:
            return self._cache[key]
        lo, hi = first.year * 12 + first.month - 1, last.year * 12 + last.month - 1
        mask = (self.month >= lo) & (self.month <= hi)
        cells = self.cell[mask]
        sums = {k: np.bincount(cells, weights=v[mask], minlength=len(self.cell_ids)).astype(np.int64) for k, v in self.counts.items()}
        keep = np.flatnonzero(sums["all"] > 0)
        result = {
            "from": str(first),
            "to": str(last),
            "months": int(hi - lo + 1),
            "boroughs": self.borough_names,
            "cells": self.cell_ids[keep].tolist(),
            "borough": self.borough_code[keep].tolist(),
            **{k: s[keep].tolist() for k, s in sums.items()},
            "totals": {k: int(s.sum()) for k, s in sums.items()},
        }
        if len(self._cache) >= CACHE_SIZE:
            self._cache.clear()
        self._cache[key] = result
        return result
