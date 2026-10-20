// Home: what SafeCross AI does, why it exists, where its data comes from, how the model and the risk levels work,
// and why it matters. The numbers in the hero sign come from the live risk snapshot, so they always match the map.
// All of the wording on this page is also kept in pwa/HOMEPAGE_TEXT.md for editing.
import { h, icon, reducedMotion } from "./dom.js";
import * as api from "./api.js";
import { TIER_COLORS } from "./detail.js";

/** Counts a number up from zero once, unless the user prefers reduced motion. */
function countUp(el, target, duration = 1100) {
  const format = (value) => Math.round(value).toLocaleString();
  if (reducedMotion()) { el.textContent = format(target); return; }
  const started = performance.now();
  const step = (now) => {
    const t = Math.min(1, (now - started) / duration);
    el.textContent = format(target * (1 - Math.pow(1 - t, 3)));
    if (t < 1) requestAnimationFrame(step);
  };
  requestAnimationFrame(step);
}

function formatWeek(iso) {
  const date = new Date(`${iso}T12:00:00`);
  return Number.isNaN(date.getTime()) ? iso : date.toLocaleDateString(undefined, { month: "long", day: "numeric", year: "numeric" });
}

const stripes = (className, count) => h("div", { class: className, "aria-hidden": "true" }, Array.from({ length: count }, () => h("span", {})));

/** A home-page section with a kicker, a focusable heading (for the jump links) and its content. */
function section(id, kicker, title, ...content) {
  const heading = h("h2", { id, tabindex: "-1" }, title);
  const element = h("section", { class: "home-section", "aria-labelledby": id }, h("p", { class: "kicker" }, kicker), heading, ...content);
  return { element, heading };
}

/** A big number with a short explanation underneath. */
const stat = (value, label, note) => h("div", { class: "stat" },
  h("span", { class: "stat-value" }, value), h("span", { class: "stat-label" }, label), note ? h("span", { class: "stat-note" }, note) : null);

export function mountHomeView(root) {
  const heading = h("h1", { tabindex: "-1", class: "home-title" }, "See the risky intersections ", h("em", {}, "before"), " you get there.");

  // The "sign": live counts from the risk snapshot, styled like a street sign.
  const total = h("span", { class: "sign-number" }, "—");
  const top = h("span", { class: "sign-number" }, "—");
  const week = h("span", { class: "sign-foot" }, "Weekly risk snapshot");
  const sign = h("aside", { class: "home-sign", "aria-label": "The risk snapshot in numbers" },
    stripes("sign-stripes", 5),
    h("div", { class: "sign-row" }, total, h("span", { class: "sign-label" }, "intersections ranked")),
    h("div", { class: "sign-row" }, top, h("span", { class: "sign-label" }, "in the highest-priority tier")),
    week);
  api.exploreSummary().then((summary) => {
    const totalCount = summary.areas.reduce((sum, area) => sum + (area.count || 0), 0);
    const topTier = (summary.tiers || []).find((tier) => tier.code === 0);
    if (totalCount) countUp(total, totalCount);
    if (topTier) countUp(top, topTier.count);
    if (summary.snapshotWeek) week.textContent = `Risk snapshot, week of ${formatWeek(summary.snapshotWeek)}`;
  }).catch(() => { sign.hidden = true; });

  // ---------------------------------------------------------------- the story
  const storyHeading = h("h2", { id: "home-story-title", tabindex: "-1" }, "It started on my walk to school.");
  const story = h("section", { class: "home-story", "aria-labelledby": "home-story-title" },
    stripes("story-stripes", 7),
    h("p", { class: "kicker story-kicker" }, "Why I created this"),
    storyHeading,
    h("div", { class: "story-text" },
      h("p", { class: "story-first" }, "Every day I passed intersections that felt dangerous: crossings where cars moved fast, where it was hard to see traffic coming, or where I had to hurry to make it across before the light changed."),
      h("p", {}, "I realized most people never find out which intersections are risky until they're standing in the middle of one. The crash records exist, but they're buried in spreadsheets nobody reads on the way out the door."),
      h("p", {}, "So I built SafeCross AI to put that information in front of people ", h("strong", {}, "before"), " they set out, and to make choosing a safer route as easy as choosing a faster one.")));

  // ---------------------------------------------------------------- why it matters (social impact)
  const impactCard = (iconName, title, text) => h("article", { class: "feature" },
    h("div", { class: "feature-top" }, h("span", { class: "feature-icon" }, icon(iconName, 22))),
    h("h3", {}, title), h("p", {}, text));
  const impact = section("home-impact", "Why it matters", "Every number here was a person on their way somewhere.",
    h("div", { class: "impact-plate" },
      stripes("story-stripes", 7),
      h("p", { class: "impact-lede" }, "In the New York City crash reports SafeCross learns from (July 2012 to May 2026):"),
      h("div", { class: "stat-grid stat-grid-dark" },
        stat("1,607", "pedestrians killed", "and 128,355 injured"),
        stat("260", "cyclists killed", "and 62,422 injured"),
        stat("3,167", "people killed in all", "and 677,199 injured"),
        stat("114", "pedestrians killed in 2025 alone", "and 9,046 injured")),
      h("p", { class: "impact-foot" }, "Source: NYC Open Data, Motor Vehicle Collisions – Crashes. Counts are reported crashes only.")),
    h("div", { class: "feature-grid" },
      impactCard("walk", "Protecting the people most exposed",
        "People on foot and on bikes have no car around them, and they include the students, older adults and families who walk every day. SafeCross weighs fast streets and recent injuries more heavily for them, so their routes are scored for the risks they actually face."),
      impactCard("database", "Making public data usable",
        "New York publishes every reported crash, but two million rows of spreadsheet don't help anyone cross the street. SafeCross turns that record into a map and a route comparison anyone can read in seconds."),
      impactCard("flag", "A starting point for safer streets",
        "The map shows where risk concentrates, neighborhood by neighborhood. Residents, schools and community boards can use it to start conversations about crossings, signals and speed, in the spirit of the city's Vision Zero goal of ending traffic deaths."),
      impactCard("lock", "Free, and private by design",
        "No account, no ads and no analytics. The addresses you type are passed to Google only to find routes, and SafeCross never saves them.")));

  // ---------------------------------------------------------------- what it does
  const feature = (iconName, number, title, text) => h("article", { class: "feature" },
    h("div", { class: "feature-top" }, h("span", { class: "feature-icon" }, icon(iconName, 22)), h("span", { class: "feature-number" }, number)),
    h("h3", {}, title), h("p", {}, text));
  const features = section("home-app", "What the app does", "Three tools, one goal: fewer close calls.",
    h("div", { class: "feature-grid" },
      feature("info", "01", "Ranks every intersection",
        "A machine-learning model trained on New York City's crash history, road layout and recent crash activity gives each intersection a relative risk level, from lower risk up to the highest-priority top 10%."),
      feature("route", "02", "Compares your routes",
        "Enter a start and a destination. Google Maps supplies the options, and SafeCross shows the travel time and a risk score for each one, side by side. When you've picked one, open it straight in Google Maps on your phone."),
      feature("map", "03", "Maps the risk",
        "Zoom out to see how risk varies across neighborhoods. Zoom in to see individual intersections, and tap one to learn what's behind its ranking.")));

  const step = (title, text) => h("li", {}, h("strong", {}, title), h("span", {}, text));
  const steps = section("home-steps", "How to use it", "From A to B in four steps.",
    h("ol", { class: "steps" },
      step("Say where you're going", "Type a start and a destination, or use your current location, then pick walking, cycling or driving."),
      step("Compare the options", "Badges mark the fastest route and the one with the lowest risk score. Red dots on the map are the highest-priority intersections."),
      step("Pick your route", "Tap a route's card or its line to select it. Tap any dot on the map to see that intersection's speed limit, sidewalks, bike lanes and crash history."),
      step("Open it in Google Maps", "Tap “Open Route A in Google Maps” (it names the route you picked) to follow that exact route on your phone.")));

  // ---------------------------------------------------------------- data sources
  const source = (iconName, name, figure, figureLabel, text, ...links) => h("article", { class: "feature source" },
    h("div", { class: "feature-top" }, h("span", { class: "feature-icon" }, icon(iconName, 22))),
    h("h3", {}, name),
    h("p", { class: "source-figure" }, h("span", { class: "stat-value" }, figure), h("span", { class: "stat-label" }, figureLabel)),
    h("p", {}, text),
    links.length ? h("div", { class: "source-links" }, links.map((link) =>
      h("a", { class: "source-link", href: link.href, target: "_blank", rel: "noopener noreferrer" }, link.text, icon("external", 14)))) : null);
  const data = section("home-data", "Where the data comes from", "Public records, open maps, and nothing about you.",
    h("div", { class: "feature-grid" },
      source("database", "NYC crash reports", "2,021,565", "crashes, July 2012 to May 2026",
        "Every police-reported motor vehicle crash in New York City: when and where it happened, and how many pedestrians, cyclists and motorists were hurt or killed. Each crash is matched to the nearest intersection.",
        { href: "https://data.cityofnewyork.us/Public-Safety/Motor-Vehicle-Collisions-Crashes/h9gi-nx95", text: "NYC Open Data" }),
      source("map", "OpenStreetMap", "73,563", "intersections (51,281 in NYC, 22,282 in Westchester)",
        "The street network, drawn by volunteers: where the intersections are, how many streets meet, traffic signals, marked crosswalks, one-way streets and street lighting.",
        { href: "https://www.openstreetmap.org/copyright", text: "© OpenStreetMap contributors" }),
      source("walk", "NYC street data", "3", "official city datasets",
        "What you'll meet at each New York City intersection: NYC DOT's posted speed limits, NYC DOT's bike lanes and routes, and every sidewalk in the city's planimetric map. Each is matched to the intersection by location and street name.",
        { href: "https://data.cityofnewyork.us/Transportation/VZV-Speed-Limits/7n5j-865y", text: "Speed limits" },
        { href: "https://data.cityofnewyork.us/City-Government/NYC-Planimetric-Database-Sidewalk/vfx9-tbb6", text: "Sidewalks" },
        { href: "https://data.cityofnewyork.us/dataset/New-York-City-Bike-Routes-Map-/9e2b-mctv", text: "Bike routes" }),
      source("route", "Google Maps Platform", "Live", "route options and travel times",
        "When you plan a trip, Google supplies the route options, travel times and the map. Google's data is used only to draw and compare your routes, never to train the model."),
      source("cloud", "Hourly weather", "Tested", "and left out",
        "Weather was collected and tried in the model, but it didn't improve the results: one citywide reading is the same for every intersection in a given week, so it can't tell them apart.")));

  // ---------------------------------------------------------------- the model
  const group = (title, text) => h("li", {}, h("strong", {}, title), h("span", {}, text));
  const model = section("home-model", "The model", "One question, asked of every intersection, every week.",
    h("p", { class: "section-lede" }, "Will at least one crash be reported here next week? The model answers with a probability. SafeCross doesn't show that number as a forecast; it uses it to rank intersections against their neighbors (see Risk levels below)."),
    h("div", { class: "model-grid" },
      h("div", { class: "card model-card" },
        h("h3", {}, "What it looks at: 41 signals in 7 groups"),
        h("ul", { class: "group-list" },
          group("Recent crashes here", "in the last 1, 4 and 8 weeks, including injuries and pedestrian and cyclist casualties"),
          group("Long-run history here", "up to three years back, plus the all-time crash rate and fatal crashes"),
          group("Crashes nearby", "within 150 and 400 metres, because danger rarely stops at one corner"),
          group("Road layout", "streets meeting, signals, crosswalks, one-way streets and how dense the intersections are"),
          group("Road type", "from residential streets up to major arterials"),
          group("Citywide trend and season", "how many crashes the whole city had lately, and the time of year"),
          group("Location", "where the intersection is"))),
      h("div", { class: "card model-card" },
        h("h3", {}, "How it was built and tested"),
        h("ol", { class: "timeline" },
          h("li", {}, h("strong", {}, "Train"), h("span", {}, "July 2012 to February 2022")),
          h("li", {}, h("strong", {}, "Tune"), h("span", {}, "March 2022 to March 2024")),
          h("li", {}, h("strong", {}, "Test"), h("span", {}, "April 2024 to April 2026: 5.6 million intersection-weeks the model never saw"))),
        h("p", {}, "Five kinds of model were compared (XGBoost, LightGBM, a neural network, a random forest and logistic regression) against a simple rule of thumb: “flag places that had a crash in the last four weeks.” XGBoost, a gradient-boosted decision-tree model, did best and is the one SafeCross uses."))),
    h("div", { class: "stat-grid" },
      stat("0.80", "ROC AUC on the test years", "Shown one intersection that had a crash and one that didn't, it ranks the crash site higher 80% of the time."),
      stat("43%", "of next week's crash sites caught", "while flagging only about 11% of intersections each week."),
      stat("4.7×", "better than random picks", "at finding next week's crash sites (average precision)."),
      stat("3×", "better than the rule of thumb", "on the same measure, during tuning.")));

  // ---------------------------------------------------------------- risk criteria
  const tier = (code, name, range, text) => h("li", { style: `--tier:${TIER_COLORS[code]}` },
    h("span", { class: "tier-bar", "aria-hidden": "true" }),
    h("span", { class: "tier-text" }, h("strong", {}, name), h("span", { class: "tier-range" }, range), h("span", {}, text)));
  const rule = (title, text) => h("li", {}, h("strong", {}, title), " ", text);
  const criteria = section("home-risk", "Risk levels", "How an intersection earns its color.",
    h("p", { class: "section-lede" }, "Each intersection is compared with the 200 intersections nearest to it, about a kilometre around it. A busy Midtown corner is measured against Midtown, and a quiet Staten Island corner against its own neighborhood, so every part of the city has its own top 10%."),
    h("ol", { class: "tier-ladder" },
      tier(0, "Highest-priority", "Top 10%", "The riskiest tenth of its neighborhood. These are the “high-risk” intersections counted on your routes."),
      tier(1, "Elevated", "Top 10–25%", "Noticeably riskier than most intersections around it."),
      tier(2, "Moderate", "Top 25–50%", "Around or a little above typical for its neighborhood."),
      tier(3, "Lower", "Bottom half", "Less risky than most intersections nearby.")),
    h("div", { class: "card rules-card" },
      h("h3", {}, "How a route is scored"),
      h("ul", {},
        rule("Relative risk.", "Each intersection's prediction is divided by its neighborhood's average, so 1.0 is typical and 3.0 is three times typical. An intersection at 3× or more is a hot spot."),
        rule("Every intersection counts.", "The score adds up the relative risk of every intersection within about 25 metres of the route, weighted by how squarely the route runs through it. Lower is safer."),
        rule("Walking and cycling.", "Intersections count 15% more where a street's posted speed limit is above the city's 25 mph default (35% more at 35 mph and up), and 25% more for each crash that hurt a pedestrian or cyclist there in the last eight weeks (up to three)."),
        rule("Westchester County.", "There are no crash records for Westchester in this project, so its intersections are ranked on road design alone. Treat them as a rough, unvalidated guide.")),
      h("a", { class: "source-link", href: "#/about" }, "More on the method and its limits", icon("arrow", 14))));

  // ---------------------------------------------------------------- limits and call to action
  const limits = h("section", { class: "home-section" },
    h("div", { class: "banner banner-warn" },
      h("strong", {}, "Rankings, not predictions. "),
      "A flagged intersection looks like places that had crashes recently. It doesn't mean a crash will happen, and a route with fewer flagged intersections isn't guaranteed to be safe. Follow traffic laws and use your own judgement. ",
      h("a", { href: "#/about" }, "Read about the method and its limits.")));

  const cta = h("section", { class: "home-cta" },
    h("h2", {}, "Where are you headed?"),
    h("p", {}, "Compare your routes in seconds, then take the safer one with you."),
    h("a", { class: "btn btn-amber", href: "#/route" }, "Plan a safer route", icon("arrow", 18)));

  // The router owns the hash, so the jump links scroll with buttons instead of #anchors.
  const jump = (label, target, targetHeading) => h("button", { type: "button", class: "story-link", onclick: () => {
    target.scrollIntoView({ behavior: reducedMotion() ? "auto" : "smooth", block: "start" });
    targetHeading.focus({ preventScroll: true });
  } }, label, icon("arrow", 16));
  const jumps = h("nav", { class: "jump-row", "aria-label": "On this page" },
    jump("Why I built this", story, storyHeading),
    jump("Why it matters", impact.element, impact.heading),
    jump("The data", data.element, data.heading),
    jump("The model", model.element, model.heading),
    jump("Risk levels", criteria.element, criteria.heading));

  const hero = h("header", { class: "home-hero" },
    h("div", { class: "home-hero-text" },
      h("p", { class: "kicker" }, "New York City · Westchester County"),
      heading,
      h("p", { class: "lede" }, "SafeCross AI ranks every intersection by relative crash risk and shows how risky each route option is, so you can pick a safer way to go and open it straight in Google Maps."),
      h("div", { class: "btn-row" },
        h("a", { class: "btn", href: "#/route" }, icon("route", 18), "Plan a safer route"),
        h("a", { class: "btn btn-ghost", href: "#/explore" }, icon("map", 18), "Explore the risk map")),
      jumps),
    sign);

  root.append(h("section", { class: "page home" }, hero, story, impact.element, features.element, steps.element,
    data.element, model.element, criteria.element, limits, cta));
  return { heading, destroy() {} };
}
