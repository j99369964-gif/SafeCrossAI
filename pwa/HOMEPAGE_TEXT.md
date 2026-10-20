# SafeCross AI: home page and route button text

This file holds all the wording on the home page (`pwa/web/js/homeview.js`), the
"Open Route A in Google Maps" button and the intersection popup on the route planner
(`pwa/web/js/routeview.js`), and the new street-fact wording (`app/safecross_core.py`).

**How to edit:** change any text you like, add or delete sentences, and leave notes in
`[[double brackets]]` if you want something changed that isn't just wording. Keep the headings
and the **bold labels** so each piece can be matched back to the page.

**Facts to check:** numbers marked † come from the project's data and model files. If you change
one, say where the new number comes from.

---

## 1. Hero (top of the page)

**Kicker:** New York City · Westchester County

**Title:** See the risky intersections *before* you get there.

**Intro:** SafeCross AI ranks every intersection by relative crash risk and shows how risky each
route option is, so you can pick a safer way to go and open it straight in Google Maps.

**Buttons:** Plan a safer route · Explore the risk map

**Jump links:** Why I created this · Why it matters · The data · The model · Risk levels

**Street sign (numbers fill in live):** [number] intersections ranked · [number] in the
highest-priority tier · Risk snapshot, week of [date]

---

## 2. The story

**Kicker:** Why I created this

**Heading:** It started on my daily commute.

**Paragraph 1:** Hi. I'm Joseph Wu-Oswald and I am currently a Junior. I live close enough to school to not ride the bus and far enough away to care about the route I walk. I notices that if I followed the auto-generated google maps route, I would have to go through this really nasty intersection. The cars always went way too fast, the visibility was way too low, and there wasn't even a sidewalk. I didn't want to take another route because I didn't know if the alternates would be any safer.

**Paragraph 2:** That was when I decided to do something about it. I decided I would put my coding experience to good use and design the app I wish I had. I wanted people to be able to see how risky the routes they were going to take were before leaving the house.

**Paragraph 3:** So I built SafeCross AI to put that information in front of people **before** they
set out, and to make choosing a safer route as easy as choosing a faster one.

---

## 3. Why it matters (social impact)

**Kicker:** Why it matters

**Heading:** Every number here was a person on their way somewhere.

**Panel intro:** SafeCross learns from data from July 2012 to May 2026:

**Stat 1:** 1,607† pedestrians killed (and 128,355† injured)

**Stat 2:** 260† cyclists killed (and 62,422† injured)

**Stat 3:** 3,167† people killed in all (and 677,199† injured)

**Stat 4:** 114† pedestrians killed in 2025 alone (and 9,046† injured)

**Panel footnote:** Source: NYC Open Data, Motor Vehicle Collisions – Crashes. Counts are reported
crashes only.

**Card: Protecting the people most exposed:** People on foot and on bikes have no car around them,
and they include the students, elderly and families who walk every day. SafeCross weighs fast
streets and recent injuries more heavily for them, so their routes are scored for the risks they
actually face.

**Card: Making public data usable:** New York publishes every reported crash, but two million rows
of spreadsheet don't help anyone cross the street. SafeCross turns that record into a map and a
route comparison anyone can read in seconds.

**Card: A starting point for safer streets:** The map shows where risk concentrates, neighborhood by
neighborhood. Residents, schools and community boards can use it to start conversations about
crossings, signals and speed, in the spirit of the city's Vision Zero goal of ending traffic
deaths.

**Card: Free, and private by design:** No account, no ads and no analytics. The addresses you type
are passed to Google only to find routes, and SafeCross never saves them.

---

## 4. What the app does

**Kicker:** What the app does

**Heading:** Three tools, one goal: fewer close calls.

**01 Ranks every intersection:** A machine-learning model trained on New York City's crash history,
road layout and recent crash activity gives each intersection a relative risk level, from lower
risk up to the highest-priority top 10%.

**02 Compares your routes:** Enter a start and a destination. Google Maps supplies the options, and
SafeCross shows the travel time and a risk score for each one, side by side. When you've picked
one, open it straight in Google Maps on your phone.

**03 Maps the risk:** Zoom out to see how risk varies across neighborhoods. Zoom in to see
individual intersections, and tap one to learn what's behind its ranking.

---

## 5. How to use it

**Kicker:** How to use it

**Heading:** From A to B in four steps.

**Step 1, Say where you're going:** Type a start and a destination, or use your current location,
then pick walking, cycling or driving.

**Step 2, Compare the options:** Badges mark the fastest route and the one with the lowest risk
score. Red dots on the map are the highest-priority intersections.

**Step 3, Pick your route:** Tap a route's card or its line to select it. Tap any dot on the map
to see that intersection's speed limit, sidewalks, bike lanes and crash history.

**Step 4, Open it in Google Maps:** Tap "Open Route A in Google Maps" (it names the route you picked)
to follow that exact route on your phone.

---

## 6. Where the data comes from

**Kicker:** Where the data comes from

**Heading:** Public records, open maps, and nothing about you.

**Card: NYC crash reports.** Figure: 2,021,565† crashes, July 2012 to May 2026.
Text: Every police-reported motor vehicle crash in New York City: when and where it happened, and
how many pedestrians, cyclists and motorists were hurt or killed. Each crash is matched to the
nearest intersection.
Link: NYC Open Data

**Card: OpenStreetMap.** Figure: 73,563† intersections (51,281 in NYC, 22,282 in Westchester).
Text: The street network, drawn by volunteers: where the intersections are, how many streets meet,
traffic signals, marked crosswalks, one-way streets and street lighting.
Link: © OpenStreetMap contributors

**Card: NYC street data.** Figure: 3 official city datasets.
Text: What you'll meet at each New York City intersection: NYC DOT's posted speed limits, NYC DOT's
bike lanes and routes, and every sidewalk in the city's planimetric map. Each is matched to the
intersection by location and street name.
Links: Speed limits · Sidewalks · Bike routes

**Card: Google Maps Platform.** Figure: Live, route options and travel times.
Text: When you plan a trip, Google supplies the route options, travel times and the map. Google's
data is used only to draw and compare your routes, never to train the model.

**Card: Hourly weather.** Figure: Tested, and left out.
Text: Weather was collected and tried in the model, but it didn't improve the results: one
citywide reading is the same for every intersection in a given week, so it can't tell them apart.

---

## 7. The model

**Kicker:** The model

**Heading:** One question, asked of every intersection, every week.

**Intro:** Will at least one crash be reported here next week? The model answers with a
probability. SafeCross doesn't show that number as a forecast; it uses it to rank intersections
against their neighbors (see Risk levels below).

**Card heading:** What it looks at: 41† signals in 7 groups

- **Recent crashes here:** in the last 1, 4 and 8 weeks, including injuries and pedestrian and
  cyclist casualties
- **Long-run history here:** up to three years back, plus the all-time crash rate and fatal crashes
- **Crashes nearby:** within 150 and 400 metres, because danger rarely stops at one corner
- **Road layout:** streets meeting, signals, crosswalks, one-way streets and how dense the
  intersections are
- **Road type:** from residential streets up to major arterials
- **Citywide trend and season:** how many crashes the whole city had lately, and the time of year
- **Location:** where the intersection is

**Card heading:** How it was built and tested

- **Train:** July 2012 to February 2022
- **Tune:** March 2022 to March 2024
- **Test:** April 2024 to April 2026: 5.6† million intersection-weeks the model never saw

**Card text:** Five kinds of model were compared (XGBoost, LightGBM, a neural network, a random
forest and logistic regression) against a simple rule of thumb: "flag places that had a crash in
the last four weeks." XGBoost, a gradient-boosted decision-tree model, did best and is the one
SafeCross uses.

**Stat 1:** 0.80† ROC AUC on the test years. Shown one intersection that had a crash and one that
didn't, it ranks the crash site higher 80% of the time.

**Stat 2:** 43%† of next week's crash sites caught, while flagging only about 11%† of
intersections each week.

**Stat 3:** 4.7׆ better than random picks at finding next week's crash sites (average precision).

**Stat 4:** 3׆ better than the rule of thumb on the same measure, during tuning.

---

## 8. Risk levels (risk criteria)

**Kicker:** Risk levels

**Heading:** How an intersection earns its color.

**Intro:** Each intersection is compared with the 200 intersections nearest to it, about a
kilometre around it. A busy Midtown corner is measured against Midtown, and a quiet Staten Island
corner against its own neighborhood, so every part of the city has its own top 10%.

**Highest-priority (Top 10%):** The riskiest tenth of its neighborhood. These are the "high-risk"
intersections counted on your routes.

**Elevated (Top 10–25%):** Noticeably riskier than most intersections around it.

**Moderate (Top 25–50%):** Around or a little above typical for its neighborhood.

**Lower (Bottom half):** Less risky than most intersections nearby.

**Card heading:** How a route is scored

- **Relative risk.** Each intersection's prediction is divided by its neighborhood's average, so
  1.0 is typical and 3.0 is three times typical. An intersection at 3× or more is a hot spot.
- **Every intersection counts.** The score adds up the relative risk of every intersection within
  about 25 metres of the route, weighted by how squarely the route runs through it. Lower is safer.
- **Walking and cycling.** Intersections count 15% more where a street's posted speed limit is
  above the city's 25 mph default (35% more at 35 mph and up), and 25% more for each crash that
  hurt a pedestrian or cyclist there in the last eight weeks (up to three).
- **Westchester County.** There are no crash records for Westchester in this project, so its
  intersections are ranked on road design alone. Treat them as a rough, unvalidated guide.

**Link:** More on the method and its limits

---

## 9. Limits banner

**Rankings, not predictions.** A flagged intersection looks like places that had crashes recently.
It doesn't mean a crash will happen, and a route with fewer flagged intersections isn't guaranteed
to be safe. Follow traffic laws and use your own judgement. Read about the method and its limits.

---

## 10. Closing call to action

**Heading:** Where are you headed?

**Text:** Compare your routes in seconds, then take the safer one with you.

**Button:** Plan a safer route

---

## 11. Route planner: Google Maps button

**Button (names the selected route):** Open Route A in Google Maps

**Note under the button:** Opens Route A as it's drawn on the map. To keep Google on this route, the
link adds a few stops along the way; just drive (or ride, or walk) through them. Tap another card
to switch routes.

**Note for very short trips (no stops added):** Opens Route A in Google Maps. Google may suggest a
slightly different way on short trips.

**Map legend hint:** Tap a dot for that intersection's details, or a route line or card to select
the route.

**Intersection popup on the map:** [street names] · [risk level] · [Nth] percentile nearby ·
[how it compares with the neighborhood average] · [8]% of Route A's risk score · mile [2.3] ·
Speed limit · Control · Crosswalk · Sidewalk · Bike lane · Crashes, past year · button: All details

---

## 12. Intersection facts (details panel and popup)

These come from the data, so only the wording around the values can change.

- **Speed limit (fastest street here):** "30 mph (above the city's 25 mph default)" · source line
  "NYC DOT" · if missing: "Not listed by NYC DOT"
- **Sidewalk:** "On 6 of 8 street sides" · "None on any of the 4 street sides" · "None (only
  highways meet here)" · source line "NYC planimetric map"
- **Bike lane (best on a street here):** "Protected lane or off-street path" · "Painted bike lane" ·
  "Shared lane or signed bike route" · "None" · source line "NYC DOT bike routes"
- **Route list chips:** Sidewalk · Sidewalk on some sides · No sidewalk · Sidewalk not mapped ·
  (cycling trips) Protected bike lane · Bike lane · Shared bike route · No bike lane

**About page, new limitation:** Street facts are matched, not surveyed. In New York City, speed
limits and bike lanes come from NYC DOT and sidewalks from the city's planimetric map, each matched
to the intersection by location and street name. A few matches can be off, especially under
elevated highways. Elsewhere these facts come from OpenStreetMap.
