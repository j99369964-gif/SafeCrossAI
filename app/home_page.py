"""SafeCross AI: Home page (the landing page of the multipage app).

Introduces the project, what it does, and why it was created. The other pages are linked
from here with st.page_link, so this file must be registered in streamlit_app.py's st.navigation.
"""

from __future__ import annotations

import streamlit as st
from streamlit.errors import StreamlitAPIException

try:
    st.set_page_config(page_title="SafeCross AI", page_icon="🚦", layout="wide")
except StreamlitAPIException:
    pass

st.markdown(
    """
<style>
.sc-hero { padding: 1.5rem 0 0.5rem 0; }
.sc-hero h1 { font-size: 3rem; line-height: 1.1; margin-bottom: 0.4rem; }
.sc-hero p.sc-tagline { font-size: 1.3rem; opacity: 0.85; max-width: 46rem; margin: 0; }
.sc-story { border-left: 5px solid #d7191c; padding: 0.4rem 0 0.4rem 1.2rem; font-size: 1.1rem; line-height: 1.6; }
</style>
<div class="sc-hero">
  <h1>🚦 SafeCross AI</h1>
  <p class="sc-tagline">Find a route that steers clear of the most dangerous intersections, and get where you're going safely.</p>
</div>
""",
    unsafe_allow_html=True,
)

st.write("")
cta_route, cta_explore, _spacer = st.columns([1, 1, 2])
with cta_route:
    st.page_link("route_page.py", label="Plan a safer route", icon=":material/alt_route:", use_container_width=True)
with cta_explore:
    st.page_link("streamlit_app_map.py", label="Explore the risk map", icon=":material/map:", use_container_width=True)

st.divider()

# --- Why I made it -------------------------------------------------------------------
st.header("Why I created this")
left, right = st.columns([3, 2], gap="large")
with left:
    st.markdown(
        """
<div class="sc-story">
On my walk to school, I kept passing intersections that felt dangerous: crossings where cars moved fast,
where it was hard to see traffic coming, or where I had to hurry to make it across.
I realized that most people never get to know which intersections are risky until they are standing in the middle of one.
<br><br>
I built SafeCross AI so that anyone can see which intersections are the riskiest <b>before</b> they set out,
and choose a route that avoids as many of them as possible. My goal is simple: help people avoid dangerous
intersections and stay safe.
</div>
""",
        unsafe_allow_html=True,
    )
with right:
    st.info(
        "**The idea in one line**\n\n"
        "If you can see the risky intersections on your route, you can choose a safer way to go."
    )

st.divider()

# --- What it does ----------------------------------------------------------------------
st.header("What it does")
card_one, card_two, card_three = st.columns(3, gap="medium")
with card_one:
    with st.container(border=True):
        st.markdown("### 🧠 Ranks intersections")
        st.write(
            "A machine-learning model trained on New York City's crash history, road layout, and recent crash "
            "activity gives every intersection a **relative risk tier**, from lower risk up to the "
            "highest-priority top 10%."
        )
with card_two:
    with st.container(border=True):
        st.markdown("### 🛣️ Compares your routes")
        st.write(
            "Enter a start and a destination. Google Maps supplies the route options, and SafeCross shows the "
            "**travel time** and **how many high-risk intersections** each one passes, side by side."
        )
with card_three:
    with st.container(border=True):
        st.markdown("### 🗺️ Shows the risk map")
        st.write(
            "Explore a map of the whole city. Zoom out for area-level risk, zoom in to see individual "
            "intersections, and click one to learn what is behind its ranking."
        )

st.divider()

# --- How it works ----------------------------------------------------------------------
st.header("How to use it")
st.markdown(
    """
1. **Open _Plan a safer route_** and type where you're starting and where you're going.
2. **Choose how you're travelling**: walking, cycling, or driving.
3. **Compare the options.** Badges mark the fastest route and the one with the fewest high-risk intersections.
4. **Check the map.** Red dots show the highest-priority intersections on each route, so you know what to expect.
"""
)

st.divider()

# --- Honest limits ---------------------------------------------------------------------
st.header("Good to know")
st.warning(
    "SafeCross AI shows **rankings, not predictions**. A flagged intersection looks like places that had crashes "
    "recently. It doesn't mean a crash will happen, and a route with fewer flagged intersections isn't guaranteed "
    "to be safe. It is not turn-by-turn navigation, so always follow traffic laws and use your own judgement. "
    "Coverage is New York City, with Westchester County as an unvalidated estimate."
)
st.caption(
    "Want the details? The *Explore the risk map* page has a Model tab and a full list of limitations. "
    "See *Terms & privacy* in the menu for how your data is handled."
)
