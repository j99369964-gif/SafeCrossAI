"""Builds the Westchester County intersection file the Streamlit app uses.

IMPORTANT: this is a TRANSFER, not a trained model. We have no crash records with coordinates for
Westchester (the public DMV crash file has no locations), so the NYC-trained model is applied to
Westchester intersections as it is. That means:

* The static road features (street count, signals, crossings, road class, lanes, speed limit, one-way)
  are built from OpenStreetMap with exactly the same logic as Notebook 2.
* There is no crash history, so the crash-history features are left blank. When the app scores these
  rows it also blanks latitude/longitude (Westchester is north of everywhere the model trained). The
  model's own imputer then treats them as "typical", so the ranking comes from road design alone.
* Weather and season are copied from the NYC snapshot week (same week, same values).
* The result is an UNVALIDATED relative ranking. The app labels it that way everywhere.

When real geocoded Westchester crashes are obtained (FOIL request), retrain with them and stop using this
script.

Run from the REPOSITORY ROOT, after scripts/export_streamlit_assets.py has produced the NYC demo file:

    python scripts/build_westchester_assets.py

Needs osmnx (already installed for Notebook 1/2) and an internet connection the first time (the street
network is cached afterwards).
"""

from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path

import numpy as np
import pandas as pd

REPO_ROOT = Path(__file__).resolve().parent.parent

NYC_DEMO_PATH = REPO_ROOT / "data" / "sample" / "safecross_app_demo.csv"
MODEL_METADATA_PATH = REPO_ROOT / "models" / "safecross_model_metadata.json"
RAW_DIR = REPO_ROOT / "data" / "raw"

REGIONS = {
    "westchester": {
        "label": "Westchester County",
        "place": "Westchester County, New York, USA",
        "graph_path": RAW_DIR / "osm_drive_westchester.graphml",
        "output_path": REPO_ROOT / "data" / "sample" / "safecross_app_demo_westchester.csv",
        "diagnostics_path": REPO_ROOT / "data" / "sample" / "westchester_transfer_diagnostics.json",
    }
}

# Same threshold Notebook 2 uses for "is this node an intersection" (CANDIDATE_MIN_STREET_COUNT).
CANDIDATE_MIN_STREET_COUNT = 3
MAX_ROWS = 60_000

# Features that are copied (not computed) because they are the same for every intersection in a given
# week: weather and season.
COPIED_FEATURE_PREFIXES = ("current_week_", "week_of_year")

_ROAD_CLASS_RANK = {"motorway": 6, "trunk": 5, "primary": 4, "secondary": 3, "tertiary": 2, "residential": 1, "unclassified": 0, "service": 0}


# =============================================================================
# Static features: a faithful port of Notebook 2's sections 8 and 8b, on plain pandas tables
# =============================================================================
def build_static_features(nodes_gdf: pd.DataFrame, edges_gdf: pd.DataFrame, min_street_count: int = CANDIDATE_MIN_STREET_COUNT) -> pd.DataFrame:
    """Return one row per eligible intersection with the same static columns Notebook 2 builds.

    `nodes_gdf` / `edges_gdf` are what osmnx.convert.graph_to_gdfs returns (nodes indexed by osmid,
    with a street_count column; edges indexed by (u, v, key)). Unlike Notebook 2, every edge-based
    feature is computed whether or not its tag clears the 50% completeness audit in THIS region, because
    the trained model expects those columns. The fill rates are reported by diagnose() instead.
    """
    nodes = nodes_gdf.reset_index().copy()
    node_id_column = "osmid" if "osmid" in nodes.columns else nodes.columns[0]
    nodes = nodes.rename(columns={node_id_column: "node_id"})
    nodes["node_id"] = nodes["node_id"].astype("string")
    nodes["street_count"] = pd.to_numeric(nodes["street_count"], errors="coerce")
    nodes["longitude"] = pd.to_numeric(nodes["x"], errors="coerce")
    nodes["latitude"] = pd.to_numeric(nodes["y"], errors="coerce")

    if "highway" not in nodes.columns:
        nodes["highway"] = pd.NA
    if "crossing" not in nodes.columns:
        nodes["crossing"] = pd.NA

    nodes["node_highway"] = nodes["highway"].astype("string").fillna("missing")
    nodes["is_traffic_signal"] = nodes["node_highway"].str.contains("traffic_signals", case=False, na=False).astype("int8")
    nodes["is_crossing_tagged"] = nodes["crossing"].notna().astype("int8")

    candidate_nodes = (
        nodes.loc[
            nodes["street_count"] >= min_street_count,
            ["node_id", "latitude", "longitude", "street_count", "node_highway", "is_traffic_signal", "is_crossing_tagged"],
        ]
        .dropna(subset=["node_id", "latitude", "longitude"])
        .drop_duplicates(subset=["node_id"])
        .copy()
    )
    if candidate_nodes.empty:
        raise ValueError("No eligible intersection nodes were found.")

    edges = edges_gdf.reset_index()
    road_design = pd.DataFrame({"node_id": nodes["node_id"]})

    def endpoints(value_column: str, new_name: str) -> pd.DataFrame:
        both = pd.concat(
            [
                edges[["u", value_column]].rename(columns={"u": "node_id"}),
                edges[["v", value_column]].rename(columns={"v": "node_id"}),
            ]
        )
        both["node_id"] = both["node_id"].astype("string")
        return both.rename(columns={value_column: new_name})

    if "highway" in edges.columns:
        def road_class_rank(value):
            if isinstance(value, list):
                value = value[0] if value else None
            return _ROAD_CLASS_RANK.get(value, -1)

        edges["road_class_rank"] = edges["highway"].apply(road_class_rank)
        per_endpoint = pd.concat(
            [
                edges[["u", "highway", "road_class_rank"]].rename(columns={"u": "node_id"}),
                edges[["v", "highway", "road_class_rank"]].rename(columns={"v": "node_id"}),
            ]
        )
        per_endpoint["node_id"] = per_endpoint["node_id"].astype("string")
        best = per_endpoint.sort_values("road_class_rank", ascending=False).drop_duplicates(subset="node_id")
        road_design = road_design.merge(best[["node_id", "highway"]].rename(columns={"highway": "road_class"}), on="node_id", how="left")

    if "lanes" in edges.columns:
        def parse_lanes(value):
            if isinstance(value, list):
                value = value[0] if value else None
            return pd.to_numeric(value, errors="coerce")

        edges["lanes_numeric"] = edges["lanes"].apply(parse_lanes)
        grouped = endpoints("lanes_numeric", "lanes_numeric").groupby("node_id", as_index=False)["lanes_numeric"].max()
        road_design = road_design.merge(grouped.rename(columns={"lanes_numeric": "max_connecting_lanes"}), on="node_id", how="left")

    if "maxspeed" in edges.columns:
        def parse_speed(value):
            if isinstance(value, list):
                value = value[0] if value else None
            if isinstance(value, str):
                value = "".join(character for character in value if character.isdigit())
            return pd.to_numeric(value, errors="coerce")

        edges["maxspeed_numeric"] = edges["maxspeed"].apply(parse_speed)
        grouped = endpoints("maxspeed_numeric", "maxspeed_numeric").groupby("node_id", as_index=False)["maxspeed_numeric"].max()
        road_design = road_design.merge(grouped.rename(columns={"maxspeed_numeric": "max_connecting_speed_limit"}), on="node_id", how="left")

    if "oneway" in edges.columns:
        edges["is_oneway_numeric"] = edges["oneway"].astype("string").str.lower().eq("true").astype("int8")
        grouped = endpoints("is_oneway_numeric", "is_oneway_numeric").groupby("node_id", as_index=False)["is_oneway_numeric"].max()
        road_design = road_design.merge(grouped.rename(columns={"is_oneway_numeric": "touches_oneway_street"}), on="node_id", how="left")

    return candidate_nodes.merge(road_design, on="node_id", how="left")


def join_list_values(frame: pd.DataFrame) -> pd.DataFrame:
    """OSM tags can be lists when road segments were merged. Join them to text ("a|b") exactly as the
    training table does, so the model's one-hot encoder sees the same kind of category."""
    frame = frame.copy()
    for column in frame.columns:
        if frame[column].dtype == "object":
            frame[column] = frame[column].map(lambda value: "|".join(map(str, value)) if isinstance(value, (list, tuple)) else value)
    return frame


# =============================================================================
# Assemble the app file
# =============================================================================
def build_region_frame(
    static_features: pd.DataFrame,
    nyc_demo: pd.DataFrame,
    metadata: dict,
    region_key: str,
) -> pd.DataFrame:
    """Static features + the weather/season values from the NYC snapshot week + region columns."""
    required = list(metadata["numeric_features"]) + list(metadata["categorical_features"])
    frame = join_list_values(static_features)

    copied = [column for column in required if column.startswith(COPIED_FEATURE_PREFIXES)]
    for column in copied:
        if column not in nyc_demo.columns:
            raise ValueError(f"The NYC demo file is missing '{column}', so it can't be copied to the new area.")
        frame[column] = float(nyc_demo[column].iloc[0])

    if "week_start" in nyc_demo.columns:
        frame.insert(1, "week_start", nyc_demo["week_start"].iloc[0])
    frame["region"] = region_key

    # Anything the model needs that is neither computed here nor copied is crash history (or location):
    # leave it out. The app blanks those for transfer areas.
    keep = ["node_id", "week_start", "latitude", "longitude"] + [c for c in required if c in frame.columns and c not in ("latitude", "longitude")] + ["region"]
    keep = [column for column in dict.fromkeys(keep) if column in frame.columns]
    return frame[keep]


def diagnose(region_frame: pd.DataFrame, nyc_demo: pd.DataFrame, numeric_columns: list[str]) -> pd.DataFrame:
    """Fill rate and median of each static feature in the new area vs. NYC. A feature that is mostly
    missing in the new area is filled with NYC's typical value by the model, so it adds no information."""
    rows = []
    for column in numeric_columns:
        if column not in region_frame.columns or column not in nyc_demo.columns:
            continue
        rows.append(
            {
                "feature": column,
                "region_filled_pct": round(100 * float(region_frame[column].notna().mean()), 1),
                "nyc_filled_pct": round(100 * float(nyc_demo[column].notna().mean()), 1),
                "region_median": None if region_frame[column].dropna().empty else float(region_frame[column].median()),
                "nyc_median": None if nyc_demo[column].dropna().empty else float(nyc_demo[column].median()),
            }
        )
    return pd.DataFrame(rows)


# =============================================================================
# OpenStreetMap (the only part that needs osmnx / the internet)
# =============================================================================
def load_region_tables(place: str, graph_path: Path, refresh: bool) -> tuple[pd.DataFrame, pd.DataFrame]:
    import networkx as nx
    import osmnx as ox

    if graph_path.exists() and not refresh:
        print(f"Loading cached street network: {graph_path}")
        graph = ox.io.load_graphml(graph_path)
    else:
        print(f"Downloading the street network for '{place}' (this can take several minutes)...")
        # retain_all=True keeps every connected piece, as in the citywide Notebook 1 run.
        graph = ox.graph.graph_from_place(place, network_type="drive", simplify=True, retain_all=True)
        graph_path.parent.mkdir(parents=True, exist_ok=True)
        ox.io.save_graphml(graph, graph_path)
        print(f"Saved: {graph_path}")

    # Same calls as Notebook 2, section 8.
    street_count_by_node = ox.stats.count_streets_per_node(graph)
    nx.set_node_attributes(graph, street_count_by_node, "street_count")
    nodes_gdf, edges_gdf = ox.convert.graph_to_gdfs(graph, nodes=True, edges=True)
    return nodes_gdf, edges_gdf


def main() -> None:
    parser = argparse.ArgumentParser(description="Build the Westchester transfer-region file for the app.")
    parser.add_argument("--region", choices=sorted(REGIONS), default="westchester")
    parser.add_argument("--refresh", action="store_true", help="download the street network again")
    parser.add_argument("--max-rows", type=int, default=MAX_ROWS)
    args = parser.parse_args()
    region = REGIONS[args.region]

    for path in (NYC_DEMO_PATH, MODEL_METADATA_PATH):
        if not path.exists():
            sys.exit(f"Missing {path}.\nRun scripts/make_model_bundle.py and scripts/export_streamlit_assets.py first.")

    with open(MODEL_METADATA_PATH, "r", encoding="utf-8") as file:
        metadata = json.load(file)
    nyc_demo = pd.read_csv(NYC_DEMO_PATH)

    nodes_gdf, edges_gdf = load_region_tables(region["place"], region["graph_path"], args.refresh)
    static = build_static_features(nodes_gdf, edges_gdf)
    frame = build_region_frame(static, nyc_demo, metadata, args.region)
    print(f"Eligible intersections in {region['label']}: {len(frame):,}")

    south, north = frame["latitude"].min(), frame["latitude"].max()
    if not (40.8 < south < 41.6 and 40.8 < north < 41.6):
        print(f"WARNING: latitudes {south:.2f}..{north:.2f} don't look like Westchester County. Check the place query.")

    diagnostics = diagnose(frame, nyc_demo, [c for c in metadata["numeric_features"] if c in ("street_count", "is_traffic_signal", "is_crossing_tagged", "max_connecting_lanes", "max_connecting_speed_limit", "touches_oneway_street")])
    print("\nHow complete the road-design features are here, compared with NYC:")
    print(diagnostics.to_string(index=False))
    sparse = diagnostics.loc[diagnostics["region_filled_pct"] < 50, "feature"].tolist()
    if sparse:
        print(
            f"\nWARNING: these features are under 50% filled in {region['label']}: {sparse}. For those the model falls "
            "back to NYC's typical value, so they will add little to the ranking."
        )

    if len(frame) > args.max_rows:
        print(f"WARNING: {len(frame):,} rows exceeds --max-rows ({args.max_rows:,}); sampling at random.")
        frame = frame.sample(n=args.max_rows, random_state=42)

    for column in frame.columns:
        if pd.api.types.is_float_dtype(frame[column]):
            frame[column] = frame[column].astype("float64").round(6)

    region["output_path"].parent.mkdir(parents=True, exist_ok=True)
    frame.sort_values("node_id").to_csv(region["output_path"], index=False)
    size_mb = region["output_path"].stat().st_size / 1e6
    print(f"\nSaved: {region['output_path'].relative_to(REPO_ROOT)} ({size_mb:.1f} MB, {len(frame):,} rows)")

    with open(region["diagnostics_path"], "w", encoding="utf-8") as file:
        json.dump(
            {
                "region": args.region,
                "mode": "transfer (NYC-trained model, road design only, unvalidated)",
                "rows": int(len(frame)),
                "feature_completeness": diagnostics.to_dict(orient="records"),
            },
            file,
            indent=2,
        )


if __name__ == "__main__":
    main()
