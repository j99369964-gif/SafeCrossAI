"""SafeCross AI: entrypoint for the multipage app.

Run from the REPOSITORY ROOT (not from inside app/):

    streamlit run app/streamlit_app.py

Pages
-----
* Plan a safer route    - the main page (route_page.py)
* Explore the risk map  - the citywide map, model and limitations (streamlit_app_map.py)
* Terms & privacy       - required when using Google's Routes API (legal_page.py)

Requires Streamlit 1.37 or newer (st.navigation, st.dialog).
"""

import streamlit as st

# set_page_config must be the FIRST Streamlit command, so it comes before any other import that
# might use Streamlit (the page scripts do, via cache decorators).
st.set_page_config(page_title="SafeCross AI", page_icon="🚦", layout="wide")

from onboarding import maybe_request_first_visit_tour, request_tour, show_tour  # noqa: E402

route_page = st.Page("route_page.py", title="Plan a safer route", icon=":material/alt_route:", url_path="route", default=True)
explore_page = st.Page("streamlit_app_map.py", title="Explore the risk map", icon=":material/map:", url_path="explore")
legal_page = st.Page("legal_page.py", title="Terms & privacy", icon=":material/gavel:", url_path="terms")

page = st.navigation([route_page, explore_page, legal_page])

with st.sidebar:
    st.button("Take the tour", icon=":material/help:", on_click=request_tour, key="sidebar_tour_button")

# First-time visitors get the tour once per session; the sidebar button reopens it.
maybe_request_first_visit_tour()

# The tour's "Try an example route" button asks for the route page: switch there before running a page.
if st.session_state.pop("goto_route", False) and page.url_path != route_page.url_path:
    st.switch_page(route_page)

if st.session_state.pop("tour_requested", False):
    show_tour()

page.run()
