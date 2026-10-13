"""Builds data/sample/intersection_info.csv: what the app shows about each intersection that is NOT a model input.

For every intersection it writes
  * the names of the streets that meet there (so the app can say "Broadway & West 42nd Street"
    instead of "OSM node 123456"),
  * sidewalk, bike-lane, street-lighting, bridge/tunnel, roundabout and traffic-control facts, taken from
    OpenStreetMap tags on the connecting streets and on the intersection point itself.

Nothing here trains or changes a model. The app only reads the CSV this script writes.

Run from the REPOSITORY ROOT:

    python scripts/build_intersection_info.py

It reads the street-network files Notebook 1 already saved (data/raw/osm_drive_*.graphml). Street names, bridge,
tunnel, roundabout and traffic-control facts are in those files already. SIDEWALK, BIKE-LANE and LIGHTING tags are
NOT: OSMnx leaves them out of its default download. Without them the app says "not mapped in OpenStreetMap" for those
facts rather than guessing. To add them, run once with --refresh-tags (it downloads the street network again with those
tags, which takes a while, and needs an internet connection):

    python scripts/build_intersection_info.py --refresh-tags

Useful options:
    --raw-dir PATH      folder holding the .graphml files (default: data/raw)
    --graph FILE        use this .graphml file (repeat for several) instead of every osm_drive_*.graphml in --raw-dir
    --all-nodes         write every intersection in the graph, not only the ones in the app's demo CSVs
"""

from __future__ import annotations

import argparse
import ast
import re
import sys
from collections import defaultdict
from pathlib import Path

import pandas as pd

REPO_ROOT = Path(__file__).resolve().parent.parent
RAW_DIR = REPO_ROOT / "data" / "raw"
SAMPLE_DIR = REPO_ROOT / "data" / "sample"
OUTPUT_PATH = SAMPLE_DIR / "intersection_info.csv"
DEMO_FILES = ["safecross_app_demo.csv", "safecross_app_demo_westchester.csv"]

# Places Notebook 1 downloads for scope "ALL" plus the Westchester transfer area. Only used by --refresh-tags.
REFRESH_PLACES = {
    "osm_drive_ALL_tags.graphml": [
        "Manhattan, New York, USA", "Brooklyn, New York, USA", "Queens, New York, USA",
        "Bronx, New York, USA", "Staten Island, New York, USA",
    ],
    "osm_drive_westchester_tags.graphml": ["Westchester County, New York, USA"],
}
# OSMnx's default tag list plus the tags that describe sidewalks, bike lanes and lighting.
EXTRA_WAY_TAGS = [
    "bridge", "tunnel", "oneway", "lanes", "ref", "name", "highway", "maxspeed", "service", "access", "area",
    "landuse", "width", "est_width", "junction",
    "sidewalk", "sidewalk:left", "sidewalk:right", "sidewalk:both",
    "cycleway", "cycleway:left", "cycleway:right", "cycleway:both", "bicycle", "lit",
]

HIGHWAY_RANK = {
    "motorway": 7, "trunk": 6, "primary": 5, "secondary": 4, "tertiary": 3,
    "residential": 2, "unclassified": 1, "living_street": 1, "service": 0,
}
NO_VALUES = {"no", "none"}
MAX_STREETS_LISTED = 6


# --------------------------------------------------------------------------- tag helpers
def as_list(value) -> list[str]:
    """OSM tags can be a single value, a list (several merged segments), or a list that was saved as text."""
    if value is None:
        return []
    if isinstance(value, float) and value != value:  # NaN
        return []
    if isinstance(value, (list, tuple, set)):
        out: list[str] = []
        for item in value:
            out.extend(as_list(item))
        return out
    text = str(value).strip()
    if not text:
        return []
    if text.startswith("[") and text.endswith("]"):
        try:
            return as_list(ast.literal_eval(text))
        except (ValueError, SyntaxError):
            pass
    return [text]


def highway_rank(value) -> int:
    best = -1
    for item in as_list(value):
        best = max(best, HIGHWAY_RANK.get(item.replace("_link", ""), 0))
    return best


def clean_name(name: str) -> str:
    return re.sub(r"\s+", " ", name).strip()


def edge_street_names(data: dict) -> list[str]:
    """Street names on one edge, falling back to the route number (for example "I 495") when there is no name."""
    names = [clean_name(n) for n in as_list(data.get("name"))]
    if not names:
        names = [clean_name(n) for n in as_list(data.get("ref"))]
    return [n for n in names if n]


def edge_edge_length(data: dict) -> float:
    try:
        return float(as_list(data.get("length"))[0])
    except (IndexError, ValueError):
        return 0.0


def sidewalk_sides(data: dict) -> str | None:
    """'both', 'one', 'none', or None when the edge carries no sidewalk tag at all."""
    values = {key: {v.lower() for v in as_list(data.get(key))} for key in ("sidewalk", "sidewalk:both", "sidewalk:left", "sidewalk:right")}
    if not any(values.values()):
        return None
    both = values["sidewalk"] | values["sidewalk:both"]
    left, right = values["sidewalk:left"], values["sidewalk:right"]
    present = {"yes", "both", "separate", "left", "right", "lane"}
    if both & {"both", "yes", "separate"} or ((left & present) and (right & present)):
        return "both"
    if (both & {"left", "right"}) or (left & present) or (right & present):
        return "one"
    if (both & NO_VALUES) or (left & NO_VALUES) or (right & NO_VALUES):
        return "none"
    return None


def bike_facility(data: dict) -> str | None:
    values: set[str] = set()
    for key in ("cycleway", "cycleway:left", "cycleway:right", "cycleway:both"):
        values |= {v.lower() for v in as_list(data.get(key))}
    values |= {v.lower() for v in as_list(data.get("bicycle")) if v.lower() == "designated"}
    if not values:
        return None
    if values - NO_VALUES:
        return "yes"
    return "no"


def lighting(data: dict) -> str | None:
    values = {v.lower() for v in as_list(data.get("lit"))}
    if "yes" in values or "24/7" in values or "automatic" in values:
        return "yes"
    if values & NO_VALUES:
        return "no"
    return None


NODE_CONTROL_LABELS = {
    "traffic_signals": "traffic signal", "stop": "stop sign", "give_way": "yield sign",
    "mini_roundabout": "mini roundabout", "crossing": "marked crossing",
}


# --------------------------------------------------------------------------- the core computation
def summarize_graph(graph) -> pd.DataFrame:
    """One row per node: street names, label, and OSM-tag facts. `graph` is a networkx MultiDiGraph as OSMnx loads it."""
    names: dict = defaultdict(dict)  # node -> {name_lower: [display, best_rank, total_length]}
    sidewalk: dict = defaultdict(list)
    bike: dict = defaultdict(list)
    lit: dict = defaultdict(list)
    structure: dict = defaultdict(bool)
    roundabout: dict = defaultdict(bool)

    for u, v, data in graph.edges(data=True):
        rank = highway_rank(data.get("highway"))
        length = edge_edge_length(data)
        edge_names = edge_street_names(data)
        sides = sidewalk_sides(data)
        facility = bike_facility(data)
        light = lighting(data)
        is_structure = any(x.lower() not in NO_VALUES for x in as_list(data.get("bridge")) + as_list(data.get("tunnel")))
        is_roundabout = any(x.lower() in {"roundabout", "circular"} for x in as_list(data.get("junction")))
        for node in (u, v):
            for name in edge_names:
                entry = names[node].setdefault(name.lower(), [name, -1, 0.0])
                entry[1] = max(entry[1], rank)
                entry[2] += length
            if sides:
                sidewalk[node].append(sides)
            if facility:
                bike[node].append(facility)
            if light:
                lit[node].append(light)
            structure[node] = structure[node] or is_structure
            roundabout[node] = roundabout[node] or is_roundabout

    rows = []
    for node, node_data in graph.nodes(data=True):
        ranked = sorted(names.get(node, {}).values(), key=lambda e: (-e[1], -e[2], e[0]))
        streets = [e[0] for e in ranked][:MAX_STREETS_LISTED]
        if len(streets) >= 2:
            label = f"{streets[0]} & {streets[1]}"
        elif len(streets) == 1:
            label = f"{streets[0]} & unnamed road"
        else:
            label = ""
        sides = sidewalk.get(node, [])
        sidewalk_summary = "unknown"
        if sides:
            if "both" in sides:
                sidewalk_summary = "yes"
            elif "one" in sides:
                sidewalk_summary = "partial"
            else:
                sidewalk_summary = "no"
        bikes = bike.get(node, [])
        lights = lit.get(node, [])
        control = ""
        for item in as_list(node_data.get("highway")):
            if item in NODE_CONTROL_LABELS:
                control = control or item
        rows.append(
            {
                "node_id": str(node),
                "label": label,
                "streets": " | ".join(streets),
                "sidewalk": sidewalk_summary,
                "bike_lane": "yes" if "yes" in bikes else ("no" if bikes else "unknown"),
                "lit": "yes" if "yes" in lights else ("no" if "no" in lights else "unknown"),
                "bridge_or_tunnel": int(bool(structure.get(node))),
                "roundabout": int(bool(roundabout.get(node))),
                "node_control": control,
            }
        )
    return pd.DataFrame(rows)


def graph_has_tag(graph, tag: str) -> bool:
    return any(tag in data for _, _, data in graph.edges(data=True))


# --------------------------------------------------------------------------- IO
def load_graph(path: Path):
    try:
        import osmnx as ox

        return ox.io.load_graphml(path)
    except ImportError:  # still works without OSMnx, but list-valued tags arrive as text (as_list handles that)
        import networkx as nx

        return nx.read_graphml(path)


def refresh_with_tags(raw_dir: Path) -> list[Path]:
    import osmnx as ox

    ox.settings.useful_tags_way = EXTRA_WAY_TAGS
    ox.settings.use_cache = True
    written = []
    for filename, places in REFRESH_PLACES.items():
        target = raw_dir / filename
        print(f"Downloading {places} (this can take a long while for a whole city)...")
        graph = ox.graph.graph_from_place(places, network_type="drive", simplify=True, retain_all=True)
        raw_dir.mkdir(parents=True, exist_ok=True)
        ox.io.save_graphml(graph, target)
        print(f"Saved: {target}")
        written.append(target)
    return written


def demo_node_ids() -> set[str] | None:
    ids: set[str] = set()
    found = False
    for filename in DEMO_FILES:
        path = SAMPLE_DIR / filename
        if path.exists():
            found = True
            ids |= set(pd.read_csv(path, usecols=["node_id"], dtype={"node_id": str})["node_id"].astype(str))
    return ids if found else None


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    parser.add_argument("--raw-dir", type=Path, default=RAW_DIR)
    parser.add_argument("--graph", type=Path, action="append", default=None)
    parser.add_argument("--refresh-tags", action="store_true")
    parser.add_argument("--all-nodes", action="store_true")
    args = parser.parse_args()

    if args.refresh_tags:
        graphs = refresh_with_tags(args.raw_dir)
    elif args.graph:
        graphs = list(args.graph)
    else:
        tagged = sorted(args.raw_dir.glob("osm_drive_*_tags.graphml"))
        graphs = tagged or sorted(args.raw_dir.glob("osm_drive_*.graphml"))
    if not graphs:
        sys.exit(f"No street-network files found in {args.raw_dir}. Run Notebook 1 first, or pass --graph FILE.")

    keep = None if args.all_nodes else demo_node_ids()
    parts = []
    for path in graphs:
        print(f"Reading {path} ...")
        graph = load_graph(path)
        for tag in ("sidewalk", "cycleway", "lit"):
            if not graph_has_tag(graph, tag) and not any(graph_has_tag(graph, f"{tag}:{s}") for s in ("both", "left", "right")):
                print(f"  note: this file has no '{tag}' tags, so that fact will show as 'not mapped'. (Use --refresh-tags to add them.)")
        table = summarize_graph(graph)
        if keep is not None:
            table = table.loc[table["node_id"].isin(keep)]
        parts.append(table)
        print(f"  {len(table):,} intersections")

    result = pd.concat(parts, ignore_index=True).drop_duplicates(subset="node_id", keep="first")
    SAMPLE_DIR.mkdir(parents=True, exist_ok=True)
    result.to_csv(OUTPUT_PATH, index=False)
    named = int((result["label"] != "").sum())
    print(f"Saved: {OUTPUT_PATH.relative_to(REPO_ROOT)}  ({len(result):,} rows, {named:,} with street names)")
    if keep is not None:
        missing = len(keep - set(result["node_id"]))
        if missing:
            print(f"  {missing:,} intersections in the demo CSVs were not found in these graphs; they will show coordinates instead of street names.")


if __name__ == "__main__":
    main()
