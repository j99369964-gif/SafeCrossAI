"""Terms of use and privacy notice.

Google's Routes API policy requires apps that use it to provide publicly accessible Terms of Use
and a Privacy Policy that reference Google's Terms of Service and Privacy Policy.

THIS IS A DRAFT TEMPLATE, NOT LEGAL ADVICE. Replace the contact details, adjust it to how you
actually run and host the app, and have it reviewed (for example by your school or organisation)
before relying on it.
"""

from __future__ import annotations

import sys
from pathlib import Path

import streamlit as st
from streamlit.errors import StreamlitAPIException

sys.path.insert(0, str(Path(__file__).resolve().parent))

try:
    st.set_page_config(page_title="SafeCross AI", page_icon="🚦", layout="wide")
except StreamlitAPIException:
    pass

CONTACT_EMAIL = "j99369964@gmail.com" 

st.title("Terms of use and privacy")

st.markdown(
    f"""
## About this app

SafeCross AI is a student research project. It ranks New York City and Westchester County intersections by *relative* crash risk
and compares route options by how many high-risk intersections they pass. It is provided for information
only, **as is**, with no warranty. It is **not** a navigation system or a safety guarantee, and it is not
for emergencies. Follow traffic laws and use your own judgement.

## Terms of use

- Use the app lawfully and do not try to overload, scrape, or misuse it.
- Route options, travel times and route maps come from **Google Maps Platform**. By using route planning you
  also agree to the [Google Maps Platform Terms of Service](https://cloud.google.com/maps-platform/terms)
  and the [Google Maps/Google Earth Additional Terms of Service](https://maps.google.com/help/terms_maps/).
- Risk rankings come from a statistical model and have known limits (see *Limitations* on the Explore page).
  Do not rely on them as the only basis for any safety decision.
- **Westchester County rankings are unvalidated estimates.** The model was trained on New York City crashes and applied to
  Westchester's road layout without any Westchester crash data. Do not treat them as measured or verified risk.

## Privacy

- **What you enter.** The start and destination you type (and the travel mode) are sent to Google to calculate
  routes. Google's handling of that data is described in the
  [Google Privacy Policy](https://policies.google.com/privacy).
- **What this app keeps.** The route results are held only in your browser session, in the app's memory, for as long
  as the session lasts. The app does not save addresses or routes to a database or file, and it does not use
  advertising or analytics cookies of its own.
- **Hosting.** The app is hosted on a third-party platform, which may keep standard technical logs (for example IP
  addresses and request times) under its own policies.
- **Maps in your browser.** The route map is a Google Map, so Google Maps scripts load in your browser and Google may
  set cookies or collect usage data as described in its privacy policy.

## Contact

Questions or concerns: {CONTACT_EMAIL}
"""
)
