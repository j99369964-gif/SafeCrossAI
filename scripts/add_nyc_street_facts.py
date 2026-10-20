"""Adds New York City's official street data to data/sample/intersection_info.csv, replacing the OpenStreetMap
facts for NYC intersections (Westchester keeps its OpenStreetMap facts):

  * Speed limit   NYC DOT, VZV Speed Limits (https://data.cityofnewyork.us/d/7n5j-865y, table 5mad-ntua).
                  The highest posted limit on a street that meets at the intersection.
  * Sidewalk      NYC Planimetric Database: Sidewalk (https://data.cityofnewyork.us/d/vfx9-tbb6, table 52n9-sdep).
                  How many sides of the connecting streets have a sidewalk next to the intersection.
  * Bike lane     NYC DOT, New York City Bike Routes (https://data.cityofnewyork.us/d/9e2b-mctv, table mzxg-pwib).
                  The best current bike facility on a street that meets at the intersection, or an off-street
                  path (a greenway) within OFFSTREET_RADIUS_M of it.

Nothing here trains or changes a model: none of these columns are model inputs. The app reads the CSV this writes.

Run from the REPOSITORY ROOT, AFTER scripts/build_intersection_info.py (which rewrites the CSV from scratch):

    python scripts/add_nyc_street_facts.py

The three datasets are downloaded once into cache/nyc_open_data/ (git-ignored). Pass --refresh to download them again.

How a street segment is matched to an intersection
---------------------------------------------------
NYC's data is drawn on the city's own street centrelines (LION), not on OpenStreetMap, so the two never line up
exactly. A segment belongs to an intersection when it passes within MATCH_RADIUS_M of it AND either shares a street
name with it or ends within MATCH_RADIUS_M of it. The second test keeps out highways that pass overhead.

How sidewalks are measured
--------------------------
For each street leaving the intersection (from the OpenStreetMap drive network), a short line is drawn straight out
to the left and to the right, SIDEWALK_PROBE_ALONG_M along the street. A side "has a sidewalk" when that line crosses
one of the city's sidewalk outlines within SIDEWALK_PROBE_MIN_M to SIDEWALK_PROBE_MAX_M of the centreline.
Motorways and their ramps are skipped (people may not walk there).
"""

from __future__ import annotations

import argparse
import json
import math
import re
import sys
import urllib.request
from pathlib import Path

import numpy as np
import pandas as pd
import shapely
from scipy.spatial import cKDTree

REPO_ROOT = Path(__file__).resolve().parent.parent
SAMPLE_DIR = REPO_ROOT / "data" / "sample"
INFO_PATH = SAMPLE_DIR / "intersection_info.csv"
NYC_DEMO = SAMPLE_DIR / "safecross_app_demo.csv"
NYC_GRAPH = REPO_ROOT / "data" / "raw" / "osm_drive_nyc_all.graphml"
CACHE_DIR = REPO_ROOT / "cache" / "nyc_open_data"

SOURCES = {
    "speed": ("vzv_speed_limits.geojson", "https://data.cityofnewyork.us/resource/5mad-ntua.geojson?$limit=500000"),
    "bike": ("bike_routes.geojson", "https://data.cityofnewyork.us/resource/mzxg-pwib.geojson?$limit=500000&$where=status='Current'"),
    "sidewalk": ("planimetric_sidewalk.geojson", "https://data.cityofnewyork.us/resource/52n9-sdep.geojson?$limit=500000"),
}

MATCH_RADIUS_M = 20.0
OFFSTREET_RADIUS_M = 30.0  # greenways often run beside the road, a little way from the street centreline
SIDEWALK_PROBE_ALONG_M = (8.0, 30.0)  # probe at half the street's length, kept within this range
SIDEWALK_PROBE_MIN_M = 3.0
SIDEWALK_PROBE_MAX_M = 36.0
SIDEWALK_YES_SHARE = 0.75  # at least this share of street sides with a sidewalk counts as "yes"
SKIP_FOR_SIDEWALK = {"motorway", "motorway_link"}
# Limited-access roads, ramps, bridges and tunnels in NYC DOT's street names.
HIGHWAY_WORDS = re.compile(r"\b(EXPRESSWAY|EXPWY|EXPY|EP|HIGHWAY|HWY|PARKWAY|PKWY|THRUWAY|TURNPIKE|FDR|DRIVE|BRIDGE|TUNNEL|"
                           r"TNNL|VIADUCT|APPROACH|RAMP|EXIT|ENTRANCE|ET|EN|EB|WB|NB|SB)\b")

# NYC DOT bike facility classes: I = protected lane or off-street path, II = painted lane, III = shared lane or
# signed route, L = a short link between facilities.
BIKE_CLASS = {"I": "protected", "II": "lane", "III": "shared", "L": "shared"}
BIKE_RANK = {"protected": 3, "lane": 2, "shared": 1, "none": 0}

ABBREVIATIONS = {
    "ST": "STREET", "AVE": "AVENUE", "AV": "AVENUE", "BLVD": "BOULEVARD", "BL": "BOULEVARD", "PKWY": "PARKWAY",
    "PKY": "PARKWAY", "EXPWY": "EXPRESSWAY", "EXPY": "EXPRESSWAY", "EXWY": "EXPRESSWAY", "HWY": "HIGHWAY", "RD": "ROAD",
    "DR": "DRIVE", "PL": "PLACE", "LN": "LANE", "CT": "COURT", "TER": "TERRACE", "TERR": "TERRACE", "SQ": "SQUARE",
    "TPKE": "TURNPIKE", "CRES": "CRESCENT", "E": "EAST", "W": "WEST", "N": "NORTH", "S": "SOUTH", "BR": "BRIDGE",
    "BRG": "BRIDGE", "HTS": "HEIGHTS", "FT": "FORT", "MT": "MOUNT",
}
NUMBER_WORDS = {
    "FIRST": "1", "SECOND": "2", "THIRD": "3", "FOURTH": "4", "FIFTH": "5", "SIXTH": "6", "SEVENTH": "7",
    "EIGHTH": "8", "NINTH": "9", "TENTH": "10", "ELEVENTH": "11", "TWELFTH": "12",
}


# --------------------------------------------------------------------------- helpers
def normalize_street(name: str) -> str:
    """'West 106th Street' and 'WEST  106 STREET' both become 'WEST 106 STREET'."""
    text = re.sub(r"\b(MC|MAC|O) (?=[A-Z])", r"\1", re.sub(r"[^A-Z0-9 ]", " ", str(name).upper()))  # MC KENNY -> MCKENNY
    tokens = text.split()
    out = []
    for position, token in enumerate(tokens):
        ordinal = re.fullmatch(r"(\d+)(ST|ND|RD|TH)", token)
        if ordinal:
            token = ordinal.group(1)
        elif token == "ST" and position == 0 and len(tokens) > 1:
            token = "SAINT"
        else:
            token = NUMBER_WORDS.get(token, ABBREVIATIONS.get(token, token))
        out.append(token)
    return " ".join(out)


def names_match(a: str, b: str) -> bool:
    """`a` is a city segment's name and `b` the intersection's street. A ramp such as 'GOWANUS EXPWY EB EN 3 AVE'
    never matches a plain street ('3 AVENUE')."""
    if not a or not b:
        return False
    if a == b:
        return True
    if HIGHWAY_WORDS.search(a) and not HIGHWAY_WORDS.search(b):
        return False
    ta, tb = set(a.split()), set(b.split())
    return min(len(ta), len(tb)) >= 2 and (ta <= tb or tb <= ta)


class Projection:
    """Local equirectangular projection to metres (as route_utils.IntersectionIndex uses)."""

    def __init__(self, lat0: float, lon0: float):
        self.lat0, self.lon0 = lat0, lon0
        self.kx = 6_371_008.8 * math.radians(1) * math.cos(math.radians(lat0))
        self.ky = 6_371_008.8 * math.radians(1)

    def xy(self, lon, lat) -> np.ndarray:
        return np.column_stack([(np.asarray(lon) - self.lon0) * self.kx, (np.asarray(lat) - self.lat0) * self.ky])

    def geometry(self, geom):
        return shapely.transform(geom, lambda c: np.column_stack([(c[:, 0] - self.lon0) * self.kx, (c[:, 1] - self.lat0) * self.ky]))


def load_layer(key: str, refresh: bool) -> list[dict]:
    filename, url = SOURCES[key]
    path = CACHE_DIR / filename
    if refresh or not path.exists():
        CACHE_DIR.mkdir(parents=True, exist_ok=True)
        print(f"Downloading {url} ...")
        with urllib.request.urlopen(url, timeout=600) as response:
            path.write_bytes(response.read())
    features = json.loads(path.read_text(encoding="utf-8")).get("features", [])
    if not features:
        sys.exit(f"{path} has no features. Delete it and run again with --refresh.")
    print(f"  {key}: {len(features):,} features")
    return [f for f in features if f.get("geometry")]


def segment_table(features: list[dict], projection: Projection) -> tuple[np.ndarray, list[dict]]:
    geoms = projection.geometry(np.array([shapely.geometry.shape(f["geometry"]) for f in features], dtype=object))
    return geoms, [f.get("properties", {}) for f in features]


def endpoint_index(geoms: np.ndarray) -> tuple[cKDTree, np.ndarray]:
    """Both ends of every part of every (multi)line, and which segment each end belongs to."""
    points, owners = [], []
    for i, geom in enumerate(geoms):
        for part in getattr(geom, "geoms", [geom]):
            coords = np.asarray(part.coords)
            if len(coords):
                points.extend([coords[0, :2], coords[-1, :2]])
                owners.extend([i, i])
    return cKDTree(np.array(points)), np.array(owners)


def matched_segments(node_xy: np.ndarray, node_names: list[set[str]], has_unnamed: np.ndarray, geoms: np.ndarray, names: list[str]) -> list[set[int]]:
    """For each node, the segments that meet it (see the module notes)."""
    tree = shapely.STRtree(geoms)
    node_index, seg_index = tree.query(shapely.points(node_xy), predicate="dwithin", distance=MATCH_RADIUS_M)
    ends_tree, owners = endpoint_index(geoms)
    near_ends = ends_tree.query_ball_point(node_xy, r=MATCH_RADIUS_M)
    candidates: list[list[int]] = [[] for _ in range(len(node_xy))]
    for node, seg in zip(node_index.tolist(), seg_index.tolist()):
        candidates[node].append(seg)

    result: list[set[int]] = []
    for node, segs in enumerate(candidates):
        own = node_names[node]
        by_name = {seg for seg in segs if any(names_match(names[seg], street) for street in own)}
        explained = {street for street in own if any(names_match(names[seg], street) for seg in by_name)}
        # Fall back to "ends here" only for a street whose name found no match, and never for a highway: the city
        # splits highway segments where they pass over or under a street, so their ends sit right above it.
        if len(explained) < len(own) or has_unnamed[node]:
            ends_here = set(owners[near_ends[node]].tolist())
            by_name |= {seg for seg in segs if seg in ends_here and not HIGHWAY_WORDS.search(names[seg])}
        result.append(by_name)
    return result


# --------------------------------------------------------------------------- the three facts
def speed_limits(node_xy, node_names, has_unnamed, features, projection) -> np.ndarray:
    geoms, props = segment_table(features, projection)
    names = [normalize_street(p.get("street", "")) for p in props]
    limits = np.array([pd.to_numeric(p.get("postvz_sl"), errors="coerce") for p in props], dtype=float)
    limits[limits <= 0] = np.nan  # 0 marks ramps and other segments with no posted limit
    out = np.full(len(node_xy), np.nan)
    for node, segs in enumerate(matched_segments(node_xy, node_names, has_unnamed, geoms, names)):
        values = limits[list(segs)] if segs else np.array([])
        values = values[~np.isnan(values)]
        if len(values):
            out[node] = values.max()
    return out


def bike_lanes(node_xy, node_names, has_unnamed, features, projection) -> tuple[list[str], list[str]]:
    geoms, props = segment_table(features, projection)
    names = [normalize_street(p.get("street", "")) for p in props]
    kinds = [BIKE_CLASS.get(str(p.get("facilitycl", "")).strip().upper(), "shared") for p in props]
    types = [str(p.get("ft_facilit") or p.get("tf_facilit") or "").strip() for p in props]
    matched = matched_segments(node_xy, node_names, has_unnamed, geoms, names)
    # An off-street path (a greenway) beside the intersection counts too, unless it is on a bridge passing overhead.
    off_street = np.array([str(p.get("onoffst", "")).upper() == "OFF" and not HIGHWAY_WORDS.search(names[i]) for i, p in enumerate(props)])
    node_index, seg_index = shapely.STRtree(geoms).query(shapely.points(node_xy), predicate="dwithin", distance=OFFSTREET_RADIUS_M)
    for node, seg in zip(node_index.tolist(), seg_index.tolist()):
        if off_street[seg]:
            matched[node].add(seg)
    best_kind, best_type = [], []
    for segs in matched:
        ranked = sorted(segs, key=lambda s: -BIKE_RANK[kinds[s]])
        best_kind.append(kinds[ranked[0]] if ranked else "none")
        best_type.append(types[ranked[0]] if ranked else "")
    return best_kind, best_type


def sidewalk_sides(node_ids, node_xy, features, projection) -> tuple[np.ndarray, np.ndarray, np.ndarray]:
    """(sides with a sidewalk, sides checked, only on motorways) for each node."""
    import osmnx as ox

    polygons = projection.geometry(np.array([shapely.geometry.shape(f["geometry"]) for f in features], dtype=object))
    tree = shapely.STRtree(polygons)
    print(f"Reading {NYC_GRAPH.relative_to(REPO_ROOT)} (about a minute) ...")
    graph = ox.io.load_graphml(NYC_GRAPH)
    position = {node: i for i, node in enumerate(node_ids)}

    rays, ray_node = [], []
    seen: set[tuple] = set()
    on_motorway = np.zeros(len(node_ids), dtype=bool)
    for u, v, data in graph.edges(data=True):
        if u == v:
            continue
        highway = data.get("highway")
        kinds = set(highway if isinstance(highway, list) else [highway])
        if kinds <= SKIP_FOR_SIDEWALK:
            for node in (str(u), str(v)):
                if node in position:
                    on_motorway[position[node]] = True
            continue
        geom = data.get("geometry")
        if geom is None:
            geom = shapely.LineString([(graph.nodes[u]["x"], graph.nodes[u]["y"]), (graph.nodes[v]["x"], graph.nodes[v]["y"])])
        line = projection.geometry(geom)
        for node, oriented in ((str(u), line), (str(v), line.reverse())):
            if node not in position:
                continue
            key = (node, round(oriented.length), tuple(np.round(oriented.coords[-1], 0)))
            if key in seen:  # a two-way street appears once per direction
                continue
            seen.add(key)
            along = float(np.clip(oriented.length / 2, *SIDEWALK_PROBE_ALONG_M))
            a, b = oriented.interpolate(max(along - 2, 0)), oriented.interpolate(min(along + 2, oriented.length))
            dx, dy = b.x - a.x, b.y - a.y
            norm = math.hypot(dx, dy)
            if norm == 0:
                continue
            nx, ny = -dy / norm, dx / norm
            centre = oriented.interpolate(along)
            for sign in (1, -1):
                rays.append(shapely.LineString([
                    (centre.x + sign * nx * SIDEWALK_PROBE_MIN_M, centre.y + sign * ny * SIDEWALK_PROBE_MIN_M),
                    (centre.x + sign * nx * SIDEWALK_PROBE_MAX_M, centre.y + sign * ny * SIDEWALK_PROBE_MAX_M),
                ]))
                ray_node.append(position[node])

    ray_node = np.array(ray_node)
    hit_rays, _ = tree.query(np.array(rays, dtype=object), predicate="intersects")
    has_sidewalk = np.zeros(len(rays), dtype=bool)
    has_sidewalk[np.unique(hit_rays)] = True
    sides_total = np.bincount(ray_node, minlength=len(node_ids))
    sides_with = np.bincount(ray_node, weights=has_sidewalk, minlength=len(node_ids)).astype(int)
    return sides_with, sides_total, on_motorway & (sides_total == 0)


# --------------------------------------------------------------------------- main
def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    parser.add_argument("--refresh", action="store_true", help="download the three NYC datasets again")
    args = parser.parse_args()

    for path in (INFO_PATH, NYC_DEMO, NYC_GRAPH):
        if not path.exists():
            sys.exit(f"Missing {path}. Run scripts/build_intersection_info.py (and Notebook 1) first.")
    info = pd.read_csv(INFO_PATH, dtype={"node_id": str})
    nodes = pd.read_csv(NYC_DEMO, usecols=["node_id", "latitude", "longitude"], dtype={"node_id": str}).drop_duplicates("node_id")
    nodes = nodes.merge(info[["node_id", "streets"]], on="node_id", how="left")
    projection = Projection(float(nodes["latitude"].median()), float(nodes["longitude"].median()))
    node_xy = projection.xy(nodes["longitude"], nodes["latitude"])
    nodes = nodes.merge(info[["node_id", "label"]], on="node_id", how="left")
    node_names = [{normalize_street(s) for s in str(text).split(" | ") if s.strip()} if pd.notna(text) else set() for text in nodes["streets"]]
    has_unnamed = nodes["label"].fillna("").str.contains("unnamed road").to_numpy() | nodes["streets"].isna().to_numpy()
    print(f"{len(nodes):,} NYC intersections")

    layers = {key: load_layer(key, args.refresh) for key in SOURCES}

    print("Matching speed limits ...")
    nodes["max_connecting_speed_limit"] = speed_limits(node_xy, node_names, has_unnamed, layers["speed"], projection)
    print("Matching bike routes ...")
    nodes["bike_lane"], nodes["bike_lane_type"] = bike_lanes(node_xy, node_names, has_unnamed, layers["bike"], projection)
    print("Checking sidewalks ...")
    with_sidewalk, checked, motorway_only = sidewalk_sides(nodes["node_id"].tolist(), node_xy, layers["sidewalk"], projection)
    share = np.divide(with_sidewalk, checked, out=np.zeros(len(checked)), where=checked > 0)
    # Only motorways meet here: nobody walks there, so "no sidewalk" (shown as a highway, see intersection_facts).
    nodes["sidewalk"] = np.select([motorway_only, checked == 0, share >= SIDEWALK_YES_SHARE, share > 0], ["no", "unknown", "yes", "partial"], "no")
    nodes["sidewalk_sides"] = with_sidewalk
    nodes["sidewalk_sides_total"] = checked

    # Write: NYC rows take the city's facts; every other row keeps its OpenStreetMap facts.
    nyc = nodes.set_index("node_id")
    is_nyc = info["node_id"].isin(nyc.index)
    for column in ("max_connecting_speed_limit", "sidewalk_sides", "sidewalk_sides_total", "bike_lane_type"):
        info[column] = info["node_id"].map(nyc[column]) if column in nyc else np.nan
    for column in ("sidewalk", "bike_lane"):
        info[column] = info["node_id"].map(nyc[column]).where(is_nyc, info[column])
    info["speed_limit_source"] = np.where(is_nyc & info["max_connecting_speed_limit"].notna(), "nyc_dot", "")
    info["sidewalk_source"] = np.where(is_nyc & (info["sidewalk"] != "unknown"), "nyc_planimetric", np.where(info["sidewalk"] != "unknown", "osm", ""))
    info["bike_lane_source"] = np.where(is_nyc, "nyc_dot", np.where(info["bike_lane"] != "unknown", "osm", ""))
    info["sidewalk_sides"] = info["sidewalk_sides"].astype("Int64")
    info["sidewalk_sides_total"] = info["sidewalk_sides_total"].astype("Int64")
    info.to_csv(INFO_PATH, index=False)

    covered = nodes["max_connecting_speed_limit"].notna().mean()
    print(f"Saved: {INFO_PATH.relative_to(REPO_ROOT)}")
    print(f"  speed limit found for {covered:.1%} of NYC intersections; "
          f"limits: {nodes['max_connecting_speed_limit'].value_counts().sort_index().to_dict()}")
    print(f"  sidewalk: {nodes['sidewalk'].value_counts().to_dict()}")
    print(f"  bike lane: {nodes['bike_lane'].value_counts().to_dict()}")


if __name__ == "__main__":
    main()
