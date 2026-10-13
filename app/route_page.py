"""SafeCross AI: Plan a safer route (the main page).

Flow: the visitor enters two places -> Google's Routes API returns route options (server side) ->
each route is matched against the scored intersections -> the options are compared by travel
time and by how many high-risk intersections they pass -> the routes are drawn on a Google Map.

Google Maps Platform policy (see route_utils.py / route_map.py): route results are kept only in the
visitor's own session (never in st.cache_*, which is shared between visitors, and never on disk) and
are shown on a Google Map.
"""

from __future__ import annotations

import inspect
import os
import sys
from pathlib import Path

import numpy as np
import pandas as pd
import streamlit as st
from streamlit.errors import StreamlitAPIException

sys.path.insert(0, str(Path(__file__).resolve().parent))

# When this file is a page of the multipage app, streamlit_app.py has already configured the page.
try:
    st.set_page_config(page_title="SafeCross AI", page_icon="🚦", layout="wide")
except StreamlitAPIException:
    pass

from app_utils import load_scored_demo_data  # noqa: E402
from onboarding import EXAMPLE_FROM, EXAMPLE_TO  # noqa: E402
from route_map import render_route_map  # noqa: E402
from route_utils import (  # noqa: E402
    PASS_RADIUS_M,
    TIER_ELEVATED,
    TIER_HIGH,
    TRAVEL_MODES,
    IntersectionIndex,
    RoutingError,
    analyze_route,
    build_map_payload,
    compare_routes,
    fetch_routes,
    format_distance,
    format_duration,
    format_minutes_delta,
    google_maps_directions_url,
)

# A public app lets anyone spend your Google quota. This is a simple per-visitor limit; also set
# quotas and a budget alert in Google Cloud Console.
MAX_SEARCHES_PER_SESSION = 20
ROUTE_DOTS = ["🔵", "🟠", "🟢", "🟣"]
ROUTE_COLORS = ["#1a73e8", "#e8710a", "#188038", "#9334e6"]
ROUTES_KEY_NAME = "GOOGLE_ROUTES_API_KEY"
MAPS_JS_KEY_NAME = "GOOGLE_MAPS_JS_API_KEY"


# --- small helpers ---------------------------------------------------------
def stretch(function) -> dict:
    """Full-width keyword that works on both older and newer Streamlit versions."""
    try:
        return {"width": "stretch"} if "width" in inspect.signature(function).parameters else {"use_container_width": True}
    except (TypeError, ValueError):
        return {"use_container_width": True}


def get_key(name: str) -> str | None:
    """Look for a key in Streamlit secrets, then environment variables, then this session's dev entry."""
    try:
        value = st.secrets.get(name)
    except Exception:  # no secrets file configured
        value = None
    return value or os.environ.get(name) or st.session_state.get(f"_dev_{name}")


@st.cache_resource(show_spinner="Preparing the intersection index...")
def get_intersection_index() -> IntersectionIndex:
    return IntersectionIndex.from_scored(load_scored_demo_data())


def set_detail(position: int) -> None:
    st.session_state.detail_route = position


def load_example() -> None:
    st.session_state.pending_example = True


# --- header ------------------------------------------------------------------
st.title("Plan a safer route")
st.write(
    "Compare route options by **travel time** and by **how many high-risk intersections** each one passes. "
    "Route options come from Google Maps; risk rankings come from the SafeCross AI model."
)

# --- keys ------------------------------------------------------------------------
routes_key = get_key(ROUTES_KEY_NAME)
js_key = get_key(MAPS_JS_KEY_NAME)

if not (routes_key and js_key):
    st.warning(
        "Route planning needs two Google Maps keys, which haven't been set up for this app yet "
        f"(missing: {', '.join(name for name, value in ((ROUTES_KEY_NAME, routes_key), (MAPS_JS_KEY_NAME, js_key)) if not value)})."
    )
    with st.expander("How to set them up", expanded=True):
        st.markdown(
            f"""
Add both keys to Streamlit secrets (`.streamlit/secrets.toml` locally, or *Settings → Secrets* on Streamlit Community Cloud):

```toml
{ROUTES_KEY_NAME} = "..."      # server-side key: restrict it to the Routes API
{MAPS_JS_KEY_NAME} = "..."     # browser key: restrict it to the Maps JavaScript API and to your app's web addresses
```

They are two different keys on purpose. The map key is visible in the visitor's browser, so it must be locked down.
See `ROUTE_FINDER_SETUP.md` for the steps.

**Just trying it locally?** Paste the keys below. They are kept only for this browser session.
"""
        )
        entered_routes = st.text_input(ROUTES_KEY_NAME, type="password", key="dev_routes_input")
        entered_js = st.text_input(MAPS_JS_KEY_NAME, type="password", key="dev_js_input")
        if st.button("Use these keys for this session"):
            if entered_routes:
                st.session_state[f"_dev_{ROUTES_KEY_NAME}"] = entered_routes.strip()
            if entered_js:
                st.session_state[f"_dev_{MAPS_JS_KEY_NAME}"] = entered_js.strip()
            st.rerun()
    st.stop()

try:
    index = get_intersection_index()
except FileNotFoundError as error:
    st.error(f"The risk data isn't available yet: {error}")
    st.stop()

# --- search form ---------------------------------------------------------------------------
# An example (from the onboarding tour or the button below) fills the form and searches straight away.
auto_search = bool(st.session_state.pop("pending_example", False))
if auto_search:
    st.session_state.route_from = EXAMPLE_FROM
    st.session_state.route_to = EXAMPLE_TO
    st.session_state.route_mode = "Driving"

last_query = st.session_state.get("route_query") or {}
st.session_state.setdefault("route_from", last_query.get("from", ""))
st.session_state.setdefault("route_to", last_query.get("to", ""))
st.session_state.setdefault("route_mode", last_query.get("mode_label", "Driving"))
st.session_state.setdefault("search_count", 0)

with st.form("route_form"):
    from_column, to_column = st.columns(2)
    origin = from_column.text_input("From", key="route_from", placeholder="e.g. Columbus Circle, or 40.7681, -73.9819")
    destination = to_column.text_input("To", key="route_to", placeholder="e.g. Barclays Center, Brooklyn")
    mode_label = st.radio("Travel mode", list(TRAVEL_MODES), horizontal=True, key="route_mode")
    submitted = st.form_submit_button("Find routes", type="primary")
st.button("Try an example trip", on_click=load_example, help="Columbus Circle to Barclays Center")
st.caption("Places are assumed to be in New York (the city or Westchester County) unless you include another place name.")

if submitted or auto_search:
    st.session_state.route_error = None
    if st.session_state.search_count >= MAX_SEARCHES_PER_SESSION:
        st.session_state.route_error = (
            f"You've reached the limit of {MAX_SEARCHES_PER_SESSION} searches for this session. "
            "Reload the page to start a new session."
        )
    elif not origin.strip() or not destination.strip():
        st.session_state.route_error = "Enter both a starting point and a destination."
    else:
        st.session_state.search_count += 1
        try:
            with st.spinner("Finding route options..."):
                routes, notices = fetch_routes(routes_key, origin, destination, TRAVEL_MODES[mode_label])
            risks = [analyze_route(route, index, mode=TRAVEL_MODES[mode_label]) for route in routes]
            st.session_state.route_results = {
                "routes": routes,
                "risks": risks,
                "notices": notices,
                "comparison": compare_routes(routes, risks),
                "origin": origin,
                "destination": destination,
                "mode": TRAVEL_MODES[mode_label],
                "start_inside": index.contains(float(routes[0].points[0, 0]), float(routes[0].points[0, 1])),
                "end_inside": index.contains(float(routes[0].points[-1, 0]), float(routes[0].points[-1, 1])),
            }
            st.session_state.route_query = {"from": origin, "to": destination, "mode_label": mode_label}
            st.session_state.detail_route = None
        except RoutingError as error:
            st.session_state.route_results = None
            st.session_state.route_error = str(error)

if st.session_state.get("route_error"):
    st.error(st.session_state.route_error)

results = st.session_state.get("route_results")

# --- empty state: tell a first-time visitor what to do --------------------------------------
if not results and not st.session_state.get("route_error"):
    st.info(
        "**How it works:** 1) enter where you're starting and where you're going, "
        "2) press **Find routes**, 3) compare the options by time and by high-risk intersections passed. "
        "New here? Press **Try an example trip**, or reopen the tour from the sidebar."
    )
    st.stop()
if not results:
    st.stop()

# --- results ---------------------------------------------------------------------------------
routes, risks, comparison = results["routes"], results["risks"], results["comparison"]

for notice in results["notices"]:
    st.info(notice)

lowest_coverage = min(risk.coverage for risk in risks)
if not (results["start_inside"] and results["end_inside"]) or lowest_coverage < 0.5:
    st.warning(
        "Much of this trip is **outside the areas SafeCross covers (New York City and Westchester County)**, so the intersection counts "
        "below are incomplete and should not be used to compare these routes."
    )
elif lowest_coverage < 0.8:
    st.warning(f"Only about {lowest_coverage:.0%} of the least-covered route is inside SafeCross's areas, so its count may be low.")

snapshot = index.snapshot_week
st.subheader("Route options")
st.info(comparison.headline)

if any(risk.n_unvalidated for risk in risks):
    st.warning(
        "Part of this trip is in **Westchester County, where rankings are unvalidated estimates**. There is no crash "
        "history there, so Westchester intersections are ranked on road design alone, against each other rather than "
        "against New York City. Treat Westchester counts as a rough guide only."
    )

selected = st.session_state.get("detail_route")
if selected is None or selected >= len(routes):
    selected = comparison.recommended_idx
fastest = routes[comparison.fastest_idx]
fastest_risk = risks[comparison.fastest_idx]

columns = st.columns(len(routes))
for position, (column, route, risk) in enumerate(zip(columns, routes, risks)):
    with column:
        with st.container(border=True):
            st.markdown(f"#### {ROUTE_DOTS[position % len(ROUTE_DOTS)]} {route.label}")
            if comparison.badges[position]:
                st.markdown(" ".join(f":green[**{badge}**]" for badge in comparison.badges[position]))
            time_column, risk_column = st.columns(2)
            time_delta = None if position == comparison.fastest_idx else format_minutes_delta(route.duration_s - fastest.duration_s)
            time_column.metric("Travel time", format_duration(route.duration_s), delta=time_delta, delta_color="inverse")
            score_delta = None if position == comparison.fastest_idx or fastest_risk.score <= 0 else f"{(risk.score - fastest_risk.score) / fastest_risk.score * 100:+.0f}%"
            risk_column.metric("Risk score", f"{risk.score:.1f}", delta=score_delta, delta_color="inverse",
                               help="Adds up the relative risk of every intersection the route passes (1 point = one average intersection). Lower is safer.")
            card_caption = f"{format_distance(route.distance_m)} · {risk.n_intersections} intersections passed · {risk.n_high} high-risk · {risk.n_elevated} elevated"
            if risk.n_unvalidated:
                card_caption += f" · {risk.n_unvalidated} in an unvalidated area"
            st.caption(card_caption)
            st.button(
                "Showing details" if position == selected else "Show details",
                key=f"detail_button_{position}",
                on_click=set_detail,
                args=(position,),
                type="primary" if position == selected else "secondary",
                **stretch(st.button),
            )
st.caption("Changes in the cards are compared with the fastest route.")

# --- Google Map ---------------------------------------------------------------------------------
render_route_map(js_key, build_map_payload(routes, risks, ROUTE_COLORS), height=560)

# --- details for the selected route -----------------------------------------------------------
route, risk = routes[selected], risks[selected]
st.subheader(f"{route.label}: intersections along the way")
show_elevated = st.toggle("Include elevated-risk intersections", value=False)

tiers = [TIER_HIGH] + ([TIER_ELEVATED] if show_elevated else [])
flagged = risk.passed.loc[risk.passed["risk_tier"].isin(tiers)]
if flagged.empty:
    st.success("This route passes no highest-priority (top 10%) intersections.")
else:
    label_column = "intersection_label" if "intersection_label" in flagged.columns else "node_id"
    if "region_label" in flagged.columns:
        area = np.where(flagged["validated"].astype(bool), flagged["region_label"], flagged["region_label"] + " (unvalidated)")
    else:
        area = None
    table = pd.DataFrame(
        {
            "Intersection": flagged[label_column].astype(str).to_numpy(),
            "Area": area,
            "Relative risk": flagged["risk_tier"].to_numpy(),
            "Percentile": flagged["risk_percentile"].round(0).astype(int).to_numpy() if "risk_percentile" in flagged.columns else None,
            "Miles into route": (flagged["distance_along_route_m"] / 1609.344).round(2).to_numpy(),
        }
    )
    table.insert(0, "#", range(1, len(table) + 1))
    if table["Area"].isna().all():
        table = table.drop(columns=["Area"])
    st.dataframe(table, hide_index=True, **stretch(st.dataframe))

st.link_button(
    "Open this trip in Google Maps",
    google_maps_directions_url(results["origin"], results["destination"], results["mode"]),
    help="Opens Google Maps. Choose the route there that matches the one you picked here.",
)

with st.expander("How are these counts worked out?"):
    st.markdown(
        f"""
- Google's route line is matched against every scored intersection. An intersection counts as **passed** if it is within about
  **{PASS_RADIUS_M:.0f} metres** of the line.
- **High-risk** means the intersection is in the top 10% for relative risk this week; **elevated** is the next tier
  (the top 25% overall). Both are *rankings against other intersections*, not chances of a crash.
- Large intersections can be mapped as several points and counted more than once. Routes on bridges or highways can pick up
  streets they cross over or under. Treat the counts as a comparison between options, not exact figures.
- Risk uses a recent weekly snapshot{f" (week of {snapshot})" if snapshot else ""}, not live traffic or conditions.
- **Westchester County is an unvalidated estimate.** The model was trained on New York City crashes. For Westchester it is applied to the road layout
  only, because no Westchester crash history is available. Its tiers compare Westchester intersections with each other, not with New York City.
"""
    )

st.caption(
    "Route options, travel times and the map are provided by Google Maps Platform. Risk rankings are from the SafeCross AI model. "
    "See *Terms & privacy* in the menu."
)
