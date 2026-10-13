"""First-visit onboarding for SafeCross AI: a short guided tour in a dialog.

* Opens automatically once per browser session (skip it with ?tour=off in the URL).
* Can be reopened any time from the sidebar ("Take the tour").
* Ends with an optional one-click example route, so a new user sees real results immediately.

State used (all plain session_state keys, so they survive page switches):
    tour_requested  - set to True to open the dialog on the next run
    tour_step       - which step is showing (0-based)
    tour_close      - set by the buttons; the dialog closes itself on its next run
    pending_example - tells the route page to fill in and run the example trip
    goto_route      - tells the entrypoint to switch to the route page
    tour_opened     - the automatic tour has already been offered this session
"""

from __future__ import annotations

import streamlit as st

EXAMPLE_FROM = "Columbus Circle, New York, NY"
EXAMPLE_TO = "Barclays Center, Brooklyn, NY"
TOUR_STEPS = 4


def request_tour() -> None:
    """Button callback: reopen the tour from the beginning."""
    st.session_state.tour_step = 0
    st.session_state.tour_requested = True


def maybe_request_first_visit_tour() -> None:
    """Offer the tour once per session, unless the URL says ?tour=off."""
    if st.session_state.get("tour_opened"):
        return
    st.session_state.tour_opened = True
    if st.query_params.get("tour") == "off":
        return
    request_tour()


def _go(delta: int) -> None:
    step = st.session_state.get("tour_step", 0) + delta
    st.session_state.tour_step = min(max(step, 0), TOUR_STEPS - 1)


def _finish(try_example: bool) -> None:
    if try_example:
        st.session_state.pending_example = True
        st.session_state.goto_route = True
    st.session_state.tour_close = True


@st.dialog("Welcome to SafeCross AI", width="large")
def show_tour() -> None:
    # A button press runs its callback and then re-runs only this dialog. When a button has asked to
    # close the tour, re-run the whole app: the dialog is not called again, so it disappears.
    if st.session_state.pop("tour_close", False):
        st.rerun()

    step = st.session_state.get("tour_step", 0)
    st.progress((step + 1) / TOUR_STEPS, text=f"Step {step + 1} of {TOUR_STEPS}")

    if step == 0:
        st.subheader("Find a route that steers clear of the riskiest intersections")
        st.markdown(
            """
SafeCross AI compares ways to get from **A to B** in New York City and Westchester County.

- You enter a start and a destination.
- Google Maps supplies several route options.
- For every option you see the **travel time** *and* **how many high-risk intersections it passes**.

You stay in control. SafeCross compares your options; it never tells you where you have to go.
"""
        )
    elif step == 1:
        st.subheader("What does \"high-risk\" mean?")
        st.markdown(
            """
Every intersection in the city gets a **relative risk tier** from a model trained on New York City's crash
history, the layout of the roads, and recent crash activity nearby.

- 🔴 **Highest-priority (top 10%)**: among the riskiest tenth of intersections. These are the ones we count.
- 🟠 **Elevated**: the next tier down (roughly the top 25% overall).
- Everything else is moderate or lower relative risk.
"""
        )
        st.info(
            "These are **rankings, not forecasts**. \"High-risk\" means an intersection looks like places that "
            "had crashes recently. It does not mean a crash will happen to you, and a route with fewer flagged "
            "intersections is not guaranteed to be safe."
        )
    elif step == 2:
        st.subheader("How to plan a trip")
        st.markdown(
            """
1. **Type a start and a destination.** An address, a landmark, or coordinates like `40.7681, -73.9819` all work.
2. **Pick how you're travelling** (driving, cycling or walking) and press **Find routes**.
3. **Compare the route cards.** Each shows time, distance and the high-risk count. Badges mark the fastest route and the one with the fewest high-risk intersections.
4. **Look at the map.** Click a route (or its label in the corner of the map) to focus it. Red dots are the high-risk intersections it passes.
5. **Open "Show details"** on a card to list those intersections in order, then open the trip in Google Maps to navigate.

Want a risk map of the whole city instead? Use **Explore the risk map** in the menu on the left.
"""
        )
    else:
        st.subheader("Good to know")
        st.markdown(
            """
- **Counts are approximate.** An intersection counts as "passed" if it is within about 25 metres of the route. Big intersections can be drawn as more than one point, and routes over bridges or highways can pick up streets they cross above.
- **Risk is a recent snapshot,** not live conditions, and it covers New York City and Westchester County.
- **Westchester is an unvalidated estimate.** We have no Westchester crash history, so its intersections are ranked on road design alone and only against each other. Treat Westchester results as a rough guide.
- **Your addresses are sent to Google** to calculate the routes. SafeCross does not store them. See *Terms & privacy* in the menu.
- **This is not turn-by-turn navigation.** Follow traffic laws and use your own judgement on the road.
"""
        )

    st.divider()
    back_column, middle_column, next_column = st.columns(3)
    if step > 0:
        back_column.button("Back", on_click=_go, args=(-1,), key=f"tour_back_{step}")
    if step < TOUR_STEPS - 1:
        middle_column.button("Skip tour", on_click=_finish, args=(False,), key=f"tour_skip_{step}")
        next_column.button("Next", on_click=_go, args=(1,), type="primary", key=f"tour_next_{step}")
    else:
        middle_column.button("Start planning", on_click=_finish, args=(False,), key="tour_start")
        next_column.button("Try an example route", on_click=_finish, args=(True,), type="primary", key="tour_example")
