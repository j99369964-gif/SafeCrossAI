"""Street and intersection search for the Explore map.

Built once at start-up from the scored intersections. A street is every intersection whose street names include it
(from data/sample/intersection_info.csv, or from the "Main & Cross" label when that file is missing). One name can be
several unrelated streets (there is a Broadway in Manhattan, Brooklyn, Queens and Yonkers), so each street is split
into pieces: intersections more than LINK_M apart with nothing in between belong to different pieces.

    "broadway"              -> streets named like it, one result per piece
    "broadway & w 42nd st"  -> the intersections where the two meet ("and", "at", "/" and "@" also work)
    "40.7581, -73.9855"     -> the nearest intersection
"""

from __future__ import annotations

import re
from collections import Counter, defaultdict

import numpy as np
import pandas as pd
from scipy.sparse import coo_matrix
from scipy.sparse.csgraph import connected_components, minimum_spanning_tree
from scipy.spatial import cKDTree

LINK_M = 400.0  # intersections of one street further apart than this (with nothing between) are separate pieces
MAX_RESULTS = 8
MAX_STREETS_PER_PART = 40
MAX_PIECES_PER_NAME = 3
NEAREST_MAX_M = 300.0

ABBREVIATIONS = {
    "st": "street", "str": "street", "av": "avenue", "ave": "avenue", "avn": "avenue", "blvd": "boulevard",
    "bl": "boulevard", "pkwy": "parkway", "pky": "parkway", "rd": "road", "dr": "drive", "pl": "place", "ln": "lane",
    "ct": "court", "ter": "terrace", "terr": "terrace", "hwy": "highway", "expy": "expressway", "expwy": "expressway",
    "tpke": "turnpike", "tpk": "turnpike", "sq": "square", "cir": "circle", "plz": "plaza", "br": "bridge",
    "w": "west", "e": "east", "n": "north", "s": "south", "ft": "fort", "mt": "mount",
}
_ORDINAL = re.compile(r"^(\d+)(?:st|nd|rd|th)$")
_SPLIT = re.compile(r"\s*(?:&|@|/|\+|\band\b|\bat\b|\bx\b)\s*", re.IGNORECASE)
_COORDINATES = re.compile(r"^\s*(-?\d{1,2}(?:\.\d+)?)\s*,\s*(-?\d{1,3}(?:\.\d+)?)\s*$")
FALLBACK_PREFIX = "Intersection near "


def tokens(text: str) -> list[str]:
    """Lower-case words with abbreviations spelled out and ordinals reduced to numbers ("W 42nd St" -> west 42 street)."""
    words = re.sub(r"[^0-9a-z]+", " ", str(text).lower().replace("'", "").replace(".", "")).split()
    out = []
    for position, word in enumerate(words):
        ordinal = _ORDINAL.match(word)
        if ordinal:
            out.append(ordinal.group(1))
        elif word == "st" and position == 0 and len(words) > 1:
            out.append("saint")  # "St Nicholas Ave"
        else:
            out.append(ABBREVIATIONS.get(word, word))
    return out


def normalize(text: str) -> str:
    return " ".join(tokens(text))


def match_quality(query: list[str], name: list[str]) -> int | None:
    """None if `name` doesn't match. Otherwise lower is better: 0 exact, 1 starts the same way, 2 all words found.
    Numbers must match whole ("4" is not "42"); other words may be typed partly ("broad" finds Broadway)."""
    if not query:
        return None
    used = set()
    for word in query:
        found = None
        for i, candidate in enumerate(name):
            if i in used:
                continue
            if (candidate == word) if word.isdigit() else candidate.startswith(word):
                found = i
                break
        if found is None:
            return None
        used.add(found)
    if query == name:
        return 0
    if name[: len(query) - 1] == query[:-1] and name[len(query) - 1].startswith(query[-1]):
        return 1
    return 2


def streets_of(row) -> list[str]:
    """The street names at one intersection."""
    value = row.get("streets")
    if isinstance(value, str) and value.strip():
        return [s.strip() for s in value.split(" | ") if s.strip()]
    label = str(row.get("intersection_label", ""))
    if not label or label.startswith(FALLBACK_PREFIX):
        return []
    return [s.strip() for s in label.split(" & ") if s.strip() and s.strip() != "unnamed road"]


class SearchIndex:
    def __init__(self, frame: pd.DataFrame, tier_code: np.ndarray, unvalidated: np.ndarray, project):
        """`frame` is SafeCrossData.frame (row positions are shared with it), `project(lat, lng)` gives metres."""
        self.frame = frame
        self.project = project
        self.tier_code = np.asarray(tier_code)
        self.unvalidated = np.asarray(unvalidated, dtype=bool)
        self.lat = frame["latitude"].to_numpy(float)
        self.lng = frame["longitude"].to_numpy(float)
        self.xy = project(self.lat, self.lng)
        self.tree = cKDTree(self.xy)
        self.ids = frame["node_id"].astype(str).to_numpy()
        self.labels = frame["intersection_label"].astype(str).to_numpy()
        self.area = frame["region_label"].astype(str).to_numpy() if "region_label" in frame.columns else np.full(len(frame), "")
        self.pct = frame["risk_percentile"].round(0).astype(int).to_numpy() if "risk_percentile" in frame.columns else np.zeros(len(frame), int)

        rows: dict[str, list[int]] = defaultdict(list)
        spellings: dict[str, Counter] = defaultdict(Counter)
        self.row_streets: list[list[str]] = []
        for position, row in enumerate(frame[[c for c in ("streets", "intersection_label") if c in frame.columns]].itertuples(index=False)):
            names = streets_of(row._asdict())
            keys = []
            for name in names:
                key = normalize(name)
                if key and key not in keys:
                    keys.append(key)
                    rows[key].append(position)
                    spellings[key][name] += 1
            self.row_streets.append(keys)
        self.street_rows = {key: np.array(value, dtype=int) for key, value in rows.items()}
        self.street_name = {key: counter.most_common(1)[0][0] for key, counter in spellings.items()}
        self.street_tokens = {key: key.split() for key in self.street_rows}
        self._pieces: dict[str, list[np.ndarray]] = {}

    # ------------------------------------------------------------------ helpers
    def matching_streets(self, text: str, limit: int = MAX_STREETS_PER_PART) -> list[tuple[int, str]]:
        """(quality, street key) pairs, best first: better match, then more intersections, then shorter name."""
        query = tokens(text)
        found = []
        for key, name_tokens in self.street_tokens.items():
            quality = match_quality(query, name_tokens)
            if quality is not None:
                found.append((quality, -len(self.street_rows[key]), len(key), key))
        found.sort()
        return [(quality, key) for quality, _, _, key in found[:limit]]

    def pieces(self, key: str) -> list[np.ndarray]:
        """The street's row positions split into connected pieces, biggest first."""
        if key not in self._pieces:
            rows = self.street_rows.get(key, np.zeros(0, int))
            if len(rows) <= 1:
                result = [rows]
            else:
                pairs = cKDTree(self.xy[rows]).query_pairs(LINK_M, output_type="ndarray")
                graph = coo_matrix((np.ones(len(pairs)), (pairs[:, 0], pairs[:, 1])), shape=(len(rows), len(rows)))
                count, labels = connected_components(graph, directed=False)
                result = sorted((rows[labels == k] for k in range(count)), key=len, reverse=True)
            if len(self._pieces) > 2000:
                self._pieces.clear()
            self._pieces[key] = result
        return self._pieces[key]

    def _ends(self, key: str, rows: np.ndarray) -> tuple[str | None, str | None]:
        """Cross streets at the two ends of a street piece (along its main direction)."""
        if len(rows) < 2:
            return None, None
        xy = self.xy[rows] - self.xy[rows].mean(axis=0)
        direction = np.linalg.svd(xy, full_matrices=False)[2][0]
        if direction[1] + 0.5 * direction[0] < 0:  # read south to north (west to east for cross-town streets)
            direction = -direction
        along = xy @ direction

        def cross(position: int) -> str | None:
            others = [k for k in self.row_streets[position] if k != key]
            return self.street_name[others[0]] if others else None

        order = np.argsort(along)
        first = next((cross(rows[i]) for i in order if cross(rows[i])), None)
        last = next((cross(rows[i]) for i in order[::-1] if cross(rows[i])), None)
        return first, last

    def _intersection_result(self, position: int, label: str | None = None) -> dict:
        own = self.labels[position]
        return {
            "type": "intersection",
            "id": self.ids[position],
            "label": own if not own.startswith(FALLBACK_PREFIX) or not label else label,
            "area": self.area[position],
            "tier": int(self.tier_code[position]),
            "unvalidated": bool(self.unvalidated[position]),
            "pct": int(self.pct[position]),
            "lat": round(float(self.lat[position]), 5),
            "lng": round(float(self.lng[position]), 5),
        }

    def _most_common_area(self, rows: np.ndarray) -> str:
        return Counter(self.area[rows].tolist()).most_common(1)[0][0] if len(rows) else ""

    # ------------------------------------------------------------------ search
    def search(self, text: str, limit: int = MAX_RESULTS) -> list[dict]:
        text = (text or "").strip()[:120]
        if len(text) < 2:
            return []
        coordinates = _COORDINATES.match(text)
        if coordinates:
            return self._nearest(float(coordinates.group(1)), float(coordinates.group(2)))
        parts = [part for part in _SPLIT.split(text) if part.strip()]
        if len(parts) >= 2:
            return self._crossing(parts[0], parts[1], limit)
        return self._streets(parts[0] if parts else text, limit)

    def _nearest(self, latitude: float, longitude: float) -> list[dict]:
        distance, position = self.tree.query(self.project(np.array([latitude]), np.array([longitude]))[0])
        if not np.isfinite(distance) or distance > NEAREST_MAX_M:
            return []
        return [self._intersection_result(int(position))]

    def nearby(self, latitude: float, longitude: float, radius_m: float = 400.0, limit: int = 10) -> list[dict]:
        """Intersections within `radius_m`, nearest first (for "report one near me")."""
        here = self.project(np.array([latitude]), np.array([longitude]))[0]
        distances, positions = self.tree.query(here, k=min(limit, len(self.ids)), distance_upper_bound=radius_m)
        results = []
        for distance, position in zip(np.atleast_1d(distances), np.atleast_1d(positions)):
            if np.isfinite(distance):
                results.append({**self._intersection_result(int(position)), "meters": int(round(float(distance)))})
        return results

    def _streets(self, text: str, limit: int) -> list[dict]:
        results = []
        for quality, key in self.matching_streets(text):
            for part, rows in enumerate(self.pieces(key)[:MAX_PIECES_PER_NAME]):
                first, last = self._ends(key, rows)
                results.append({
                    "type": "street",
                    "key": key,
                    "part": part,
                    "name": self.street_name[key],
                    "area": self._most_common_area(rows),
                    "count": int(len(rows)),
                    "from": first,
                    "to": last if last != first else None,
                    "quality": quality,
                })
                if len(results) >= limit:
                    return [{k: v for k, v in r.items() if k != "quality"} for r in results]
        return [{k: v for k, v in r.items() if k != "quality"} for r in results]

    def _crossing(self, first: str, second: str, limit: int) -> list[dict]:
        a = self.matching_streets(first)
        b = self.matching_streets(second)
        if not a or not b:
            return []
        best_a = {key: quality for quality, key in a}
        best_b = {key: quality for quality, key in b}
        rows_a = np.unique(np.concatenate([self.street_rows[key] for key in best_a]))
        rows_b = np.unique(np.concatenate([self.street_rows[key] for key in best_b]))
        common = np.intersect1d(rows_a, rows_b)
        scored = []
        for position in common:
            streets = self.row_streets[position]
            qa = [(best_a[k], k) for k in streets if k in best_a]
            qb = [(best_b[k], k) for k in streets if k in best_b and k not in {key for _, key in qa[:1]}]
            if not qa or not qb:
                continue
            (quality_a, key_a), (quality_b, key_b) = min(qa), min(qb)
            label = f"{self.street_name[key_a]} & {self.street_name[key_b]}"
            # Better text match first, then the riskier intersection (it is the one people most likely mean to check).
            scored.append((quality_a + quality_b, int(self.tier_code[position]), -int(self.pct[position]), int(position), label))
        scored.sort()
        results, kept = [], []
        for _, _, _, position, label in scored:
            # A divided avenue meets a cross street at two or more nodes a few metres apart: show it once.
            if any(np.hypot(*(self.xy[position] - self.xy[other])) < 60 for other in kept):
                continue
            kept.append(position)
            results.append(self._intersection_result(position, label))
            if len(results) >= limit:
                break
        return results

    # ------------------------------------------------------------------ one street, for highlighting
    def street(self, key: str, part: int = 0) -> dict | None:
        key = normalize(key)
        pieces = self.pieces(key) if key in self.street_rows else []
        if not 0 <= part < len(pieces):
            return None
        rows = pieces[part]
        segments = []
        if len(rows) > 1:
            distances = cKDTree(self.xy[rows]).sparse_distance_matrix(cKDTree(self.xy[rows]), LINK_M, output_type="coo_matrix")
            tree = minimum_spanning_tree(distances.tocsr()).tocoo()
            segments = [
                [[round(float(self.lat[rows[i]]), 5), round(float(self.lng[rows[i]]), 5)],
                 [round(float(self.lat[rows[j]]), 5), round(float(self.lng[rows[j]]), 5)]]
                for i, j in zip(tree.row, tree.col)
            ]
        order = sorted(rows.tolist(), key=lambda p: (int(self.tier_code[p]), -int(self.pct[p])))
        first, last = self._ends(key, rows)
        return {
            "key": key,
            "part": part,
            "name": self.street_name[key],
            "area": self._most_common_area(rows),
            "from": first,
            "to": last if last != first else None,
            "count": int(len(rows)),
            "tierCounts": [int((self.tier_code[rows] == code).sum()) for code in range(4)],
            "bounds": {
                "south": float(self.lat[rows].min()), "north": float(self.lat[rows].max()),
                "west": float(self.lng[rows].min()), "east": float(self.lng[rows].max()),
            },
            "points": [
                {"id": self.ids[p], "lat": round(float(self.lat[p]), 5), "lng": round(float(self.lng[p]), 5),
                 "tier": int(self.tier_code[p]), "unvalidated": int(self.unvalidated[p])}
                for p in rows.tolist()
            ],
            "segments": segments,
            "riskiest": [self._intersection_result(p) for p in order[:5]],
        }
