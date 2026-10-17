// Home: what SafeCross AI does, why it exists, and the two ways in (plan a route, explore the map).
// The numbers in the hero sign come from the live risk snapshot, so they always match the map.
import { h, icon, reducedMotion } from "./dom.js";
import * as api from "./api.js";

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

export function mountHomeView(root) {
  const heading = h("h1", { tabindex: "-1", class: "home-title" }, "See the risky intersections ", h("em", {}, "before"), " you get there.");

  // The "sign": live counts from the risk snapshot, styled like a street sign.
  const total = h("span", { class: "sign-number" }, "—");
  const top = h("span", { class: "sign-number" }, "—");
  const week = h("span", { class: "sign-foot" }, "Weekly risk snapshot");
  const sign = h("aside", { class: "home-sign", "aria-label": "The risk snapshot in numbers" },
    h("div", { class: "sign-stripes", "aria-hidden": "true" }, h("span", {}), h("span", {}), h("span", {}), h("span", {}), h("span", {})),
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

  // The story is the reason the app exists, so it sits right under the hero as a full-width feature panel.
  const storyHeading = h("h2", { id: "home-story-title", tabindex: "-1" }, "It started on my walk to school.");
  const story = h("section", { class: "home-story", "aria-labelledby": "home-story-title" },
    h("div", { class: "story-stripes", "aria-hidden": "true" }, h("span", {}), h("span", {}), h("span", {}), h("span", {}), h("span", {}), h("span", {}), h("span", {})),
    h("p", { class: "kicker story-kicker" }, "Why I created this"),
    storyHeading,
    h("div", { class: "story-text" },
      h("p", { class: "story-first" }, "Every day I passed intersections that felt dangerous: crossings where cars moved fast, where it was hard to see traffic coming, or where I had to hurry to make it across before the light changed."),
      h("p", {}, "I realized most people never find out which intersections are risky until they're standing in the middle of one. The crash records exist, but they're buried in spreadsheets nobody reads on the way out the door."),
      h("p", {}, "So I built SafeCross AI to put that information in front of people ", h("strong", {}, "before"), " they set out, and to make choosing a safer route as easy as choosing a faster one.")));

  // The router owns the hash, so the story link scrolls with a button instead of an #anchor.
  const storyLink = h("button", { type: "button", class: "story-link", onclick: () => {
    story.scrollIntoView({ behavior: reducedMotion() ? "auto" : "smooth", block: "start" });
    storyHeading.focus({ preventScroll: true });
  } }, "Why I built this", icon("arrow", 16));

  const hero = h("header", { class: "home-hero" },
    h("div", { class: "home-hero-text" },
      h("p", { class: "kicker" }, "New York City · Westchester County"),
      heading,
      h("p", { class: "lede" }, "SafeCross AI ranks every intersection by relative crash risk and shows how many of the riskiest ones each route passes, so you can pick a safer way to go."),
      h("div", { class: "btn-row" },
        h("a", { class: "btn", href: "#/route" }, icon("route", 18), "Plan a safer route"),
        h("a", { class: "btn btn-ghost", href: "#/explore" }, icon("map", 18), "Explore the risk map")),
      storyLink),
    sign);

  const feature = (iconName, number, title, text) => h("article", { class: "feature" },
    h("div", { class: "feature-top" }, h("span", { class: "feature-icon" }, icon(iconName, 22)), h("span", { class: "feature-number" }, number)),
    h("h3", {}, title), h("p", {}, text));
  const features = h("section", { class: "home-section" },
    h("p", { class: "kicker" }, "What it does"),
    h("h2", {}, "Three tools, one goal: fewer close calls."),
    h("div", { class: "feature-grid" },
      feature("info", "01", "Ranks every intersection",
        "A machine-learning model trained on New York City's crash history, road layout and recent crash activity gives each intersection a relative risk tier, from lower risk up to the highest-priority top 10%."),
      feature("route", "02", "Compares your routes",
        "Enter a start and a destination. Google Maps supplies the options, and SafeCross shows the travel time and how many high-risk intersections each one passes, side by side."),
      feature("map", "03", "Maps the risk",
        "Zoom out to see how risk varies across neighborhoods. Zoom in to see individual intersections, and tap one to learn what's behind its ranking.")));

  const step = (title, text) => h("li", {}, h("strong", {}, title), h("span", {}, text));
  const steps = h("section", { class: "home-section" },
    h("p", { class: "kicker" }, "How to use it"),
    h("h2", {}, "From A to B in four steps."),
    h("ol", { class: "steps" },
      step("Say where you're going", "Type a start and a destination, or use your current location."),
      step("Pick how you travel", "Walking, cycling or driving."),
      step("Compare the options", "Badges mark the fastest route and the one with the lowest risk score."),
      step("Check the map", "Red dots show the highest-priority intersections, so you know what's ahead.")));

  const limits = h("section", { class: "home-section" },
    h("div", { class: "banner banner-warn" },
      h("strong", {}, "Rankings, not predictions. "),
      "A flagged intersection looks like places that had crashes recently. It doesn't mean a crash will happen, and a route with fewer flagged intersections isn't guaranteed to be safe. SafeCross isn't turn-by-turn navigation, so follow traffic laws and use your own judgement. Westchester County is an unvalidated estimate. ",
      h("a", { href: "#/about" }, "Read about the method and its limits.")));

  const cta = h("section", { class: "home-cta" },
    h("h2", {}, "Where are you headed?"),
    h("p", {}, "Compare your routes in seconds."),
    h("a", { class: "btn btn-amber", href: "#/route" }, "Plan a safer route", icon("arrow", 18)));

  root.append(h("section", { class: "page home" }, hero, story, features, steps, limits, cta));
  return { heading, destroy() {} };
}
