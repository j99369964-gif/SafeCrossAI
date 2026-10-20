"""Street names for intersections that data/sample/intersection_info.csv has no name for.

Without a name the app labels an intersection by its coordinates ("Intersection near 40.7681, -73.9819"), which
says nothing to a reader. The intersections people actually read about are the few that add the most to a route's
risk score, so only those are looked up here, on demand, and the answers are kept in memory.

Every node_id is an OpenStreetMap node, so the lookup asks OpenStreetMap's Overpass API which named roads pass
through that exact node and builds the label the same way scripts/build_intersection_info.py does ("Broadway &
West 42nd Street"). No API key is needed. If the lookup fails or finds nothing, the coordinates label stays.
"""

from __future__ import annotations

import threading
import time
from typing import Callable, Iterable

import pandas as pd
import requests

OVERPASS_ENDPOINT = "https://overpass-api.de/api/interpreter"
USER_AGENT = "SafeCrossAI/1.0 (intersection street names)"
TIMEOUT_S = 8.0
MAX_NODES_PER_REQUEST = 50
RETRY_AFTER_FAILURE_S = 60.0  # after a failed lookup, don't ask again for a minute
MAX_CACHE = 50_000
TOP_CONTRIBUTORS = 10  # per route: covers the "biggest contributors" summary and the top of the sorted list

# Same ranking as scripts/build_intersection_info.py: the bigger road is named first.
HIGHWAY_RANK = {
    "motorway": 7, "trunk": 6, "primary": 5, "secondary": 4, "tertiary": 3,
    "residential": 2, "unclassified": 1, "living_street": 1, "service": 0,
}
FALLBACK_PREFIX = "Intersection near "


def needs_name(label) -> bool:
    """True for a missing label or one that is only coordinates (see safecross_core.fallback_label)."""
    return label is None or (isinstance(label, float) and label != label) or not str(label).strip() or str(label).startswith(FALLBACK_PREFIX)


def label_from_ways(ways: Iterable[dict]) -> str:
    """'Main & Cross' from the OSM ways through one node, or '' when none of them is named."""
    names: dict[str, list] = {}  # name_lower -> [display, best_rank]
    for way in ways:
        tags = way.get("tags", {})
        highway = str(tags.get("highway", ""))
        rank = HIGHWAY_RANK.get(highway.replace("_link", ""), 0)
        for name in [n.strip() for n in str(tags.get("name") or tags.get("ref") or "").split(";")]:
            if name:
                entry = names.setdefault(name.lower(), [name, -1])
                entry[1] = max(entry[1], rank)
    streets = [entry[0] for entry in sorted(names.values(), key=lambda e: (-e[1], e[0]))]
    if len(streets) >= 2:
        return f"{streets[0]} & {streets[1]}"
    if len(streets) == 1:
        return f"{streets[0]} & unnamed road"
    return ""


class StreetNameLookup:
    """Thread-safe, in-memory cache of node_id -> street-name label ('' means OSM has no name for it)."""

    def __init__(self, http_post: Callable = requests.post, clock: Callable[[], float] = time.time, enabled: bool = True):
        self.http_post = http_post
        self.clock = clock
        self.enabled = enabled
        self._labels: dict[str, str] = {}
        self._lock = threading.Lock()
        self._paused_until = 0.0

    def cached(self, node_id) -> str | None:
        """The street-name label if one was found earlier, else None."""
        with self._lock:
            return self._labels.get(str(node_id)) or None

    def lookup(self, node_ids: Iterable) -> dict[str, str]:
        """Labels for these OSM node ids (only the ones that have a name). Never raises."""
        wanted = list(dict.fromkeys(str(n) for n in node_ids if str(n).isdigit()))
        with self._lock:
            missing = [n for n in wanted if n not in self._labels]
            paused = self.clock() < self._paused_until
        if missing and self.enabled and not paused:
            self._fetch(missing[:MAX_NODES_PER_REQUEST])
        with self._lock:
            return {n: self._labels[n] for n in wanted if self._labels.get(n)}

    def _fetch(self, node_ids: list[str]) -> None:
        query = f"[out:json][timeout:{int(TIMEOUT_S)}];node(id:{','.join(node_ids)});way(bn)[highway];out body;"
        try:
            response = self.http_post(OVERPASS_ENDPOINT, data={"data": query}, headers={"User-Agent": USER_AGENT}, timeout=TIMEOUT_S)
            response.raise_for_status()
            ways = response.json().get("elements", [])
        except (requests.RequestException, ValueError, AttributeError):
            with self._lock:
                self._paused_until = self.clock() + RETRY_AFTER_FAILURE_S
            return
        wanted = {int(n) for n in node_ids}
        by_node: dict[int, list[dict]] = {n: [] for n in wanted}
        for way in ways:
            if way.get("type") != "way":
                continue
            for node in set(way.get("nodes", [])) & wanted:
                by_node[node].append(way)
        with self._lock:
            if len(self._labels) > MAX_CACHE:
                self._labels.clear()
            for node, node_ways in by_node.items():
                self._labels[str(node)] = label_from_ways(node_ways)

    def fill(self, frame: pd.DataFrame, top_n: int = TOP_CONTRIBUTORS, order_by: str = "contribution") -> pd.DataFrame:
        """Replaces coordinate labels on the `top_n` rows with the largest `order_by` by street names, where a name is
        found. Returns a new frame (or `frame` itself when nothing changed)."""
        ids = top_unnamed(frame, top_n, order_by)
        found = self.lookup(ids) if ids else {}
        if not found:
            return frame
        frame = frame.copy()
        names = frame["node_id"].astype(str).map(found)
        frame["intersection_label"] = names.where(names.notna(), frame["intersection_label"])
        return frame

    def fill_routes(self, risks: list, top_n: int = TOP_CONTRIBUTORS) -> None:
        """Names the biggest contributors of every route (route_utils.RouteRisk), with one lookup for all of them."""
        ids = [node for risk in risks for node in top_unnamed(risk.passed, top_n)]
        if ids:
            self.lookup(ids)  # fill() below then reads the cache
        for risk in risks:
            risk.passed = self.fill(risk.passed, top_n)


def top_unnamed(frame: pd.DataFrame, top_n: int = TOP_CONTRIBUTORS, order_by: str = "contribution") -> list[str]:
    """node_ids among the `top_n` rows with the largest `order_by` that are labelled only by coordinates."""
    if frame.empty or not {"node_id", "intersection_label"}.issubset(frame.columns):
        return []
    top = frame.loc[frame[order_by].nlargest(top_n).index] if order_by in frame.columns else frame.head(top_n)
    return top.loc[top["intersection_label"].map(needs_name), "node_id"].astype(str).tolist()


# One shared cache per process (the Streamlit pages and the PWA server each use this).
default_lookup = StreetNameLookup()
