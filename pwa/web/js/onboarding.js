// First-run tour: four short steps in an accessible dialog. "Seen" is remembered on this device (localStorage),
// so a returning visitor isn't shown it again. ?tour=off skips it; the Help button reopens it at any time.
import { h, icon, leave } from "./dom.js";
import { getItem, setItem } from "./storage.js";

export const TOUR_KEY = "safecross.onboarded.v1";

export const STEPS = [
  {
    title: "Find a route that steers clear of the riskiest intersections",
    body: () => [
      h("p", {}, "SafeCross AI compares ways to get from A to B in New York City and Westchester County."),
      h("ul", {},
        h("li", {}, "You enter a start and a destination."),
        h("li", {}, "Google Maps supplies several route options."),
        h("li", {}, "For every option you see the travel time and how many high-risk intersections it passes.")),
      h("p", {}, "You stay in control. SafeCross compares your options; it never tells you where you have to go."),
    ],
  },
  {
    title: "What does \"high-risk\" mean?",
    body: () => [
      h("p", {}, "Every intersection gets a relative risk tier from a model trained on New York City's crash history, the layout of the roads and recent crash activity nearby."),
      h("p", {}, "Each intersection is ranked against the intersections around it (roughly the surrounding kilometre), so every neighbourhood has its own riskiest spots."),
      h("ul", {},
        h("li", {}, "Highest-priority (top 10%): among the riskiest tenth of nearby intersections. These are the ones we count."),
        h("li", {}, "Elevated: the next tier down (roughly the top 25% of nearby intersections).")),
      h("div", { class: "banner banner-info" }, "These are rankings, not forecasts. A route with fewer flagged intersections is not guaranteed to be safe."),
    ],
  },
  {
    title: "How to plan a trip",
    body: () => [
      h("ol", {},
        h("li", {}, "Type a start and a destination, or tap the location button in the From box. An address, a landmark or coordinates all work."),
        h("li", {}, "Choose driving, cycling or walking and tap Find routes."),
        h("li", {}, "Compare the cards. Badges mark the fastest route and the one with the fewest high-risk intersections."),
        h("li", {}, "Look at the map. Red dots are the high-risk intersections a route passes. Tap a card to focus its route."),
        h("li", {}, "Open the trip in Google Maps to navigate.")),
      h("p", {}, "Want a risk map of the whole region instead? Use the Explore tab."),
    ],
  },
  {
    title: "Good to know",
    body: () => [
      h("ul", {},
        h("li", {}, "Counts are approximate. An intersection counts if it is within about 25 metres of the route."),
        h("li", {}, "Risk is a recent snapshot, not live conditions."),
        h("li", {}, "Westchester County is an unvalidated estimate. We have no Westchester crash history, so its intersections are ranked on road design alone and only against each other."),
        h("li", {}, "Your places are sent to Google to calculate routes. See About for terms and privacy."),
        h("li", {}, "This is not turn-by-turn navigation. Follow traffic laws and use your own judgement.")),
    ],
  },
];

export const hasSeenTour = () => getItem(TOUR_KEY) === "1";
export const shouldAutoOpen = (search) => !hasSeenTour() && new URLSearchParams(search || "").get("tour") !== "off";

/**
 * Opens the tour. `onClose({ example })` runs when it ends; example is true if the user chose "Try an example route".
 * Returns { close }.
 */
export function openTour({ host, onClose, startStep = 0 }) {
  const opener = document.activeElement;
  let step = Math.max(0, Math.min(startStep, STEPS.length - 1));
  let closing = false;
  const overlay = h("div", { class: "overlay" });
  const dialog = h("div", { class: "dialog", role: "dialog", "aria-modal": "true", "aria-labelledby": "tour-title" });
  // The step counter and progress segments stay put between steps so the fill can animate; only the step itself is swapped.
  const counter = h("p", { class: "kicker" });
  const segments = STEPS.map(() => h("span", {}));
  const bar = h("div", { class: "progress", role: "progressbar", "aria-valuemin": "1", "aria-valuemax": String(STEPS.length), style: `--steps:${STEPS.length}` }, segments);
  const stepHost = h("div", {});
  dialog.append(h("div", { class: "tour-meta" }, counter, bar), stepHost);
  overlay.append(dialog);
  host.append(overlay);

  function finish(example) {
    if (closing) return;
    closing = true;
    setItem(TOUR_KEY, "1");
    document.removeEventListener("keydown", onKey, true);
    leave(overlay);
    if (opener && typeof opener.focus === "function") opener.focus();
    if (onClose) onClose({ example: Boolean(example) });
  }

  function go(next) {
    const direction = next < step ? "back" : "next";
    step = next;
    render(direction);
  }

  function render(direction = "next") {
    const current = STEPS[step];
    const last = step === STEPS.length - 1;
    counter.textContent = `Step ${step + 1} of ${STEPS.length}`;
    bar.setAttribute("aria-valuenow", String(step + 1));
    bar.setAttribute("aria-label", `Step ${step + 1} of ${STEPS.length}`);
    segments.forEach((segment, i) => segment.classList.toggle("is-done", i <= step));
    const title = h("h2", { id: "tour-title", tabindex: "-1" }, current.title);
    const buttons = h("div", { class: "btn-row" },
      step > 0 ? h("button", { type: "button", class: "btn btn-ghost", onclick: () => go(step - 1) }, "Back") : null,
      last ? h("button", { type: "button", class: "btn btn-ghost", onclick: () => finish(false) }, "Start planning") : h("button", { type: "button", class: "btn btn-ghost", onclick: () => finish(false) }, "Skip tour"),
      last ? h("button", { type: "button", class: "btn", onclick: () => finish(true) }, "Try an example route") : h("button", { type: "button", class: "btn", onclick: () => go(step + 1) }, "Next", icon("arrow", 18)));
    stepHost.replaceChildren(h("div", { class: "tour-step", dataset: { dir: direction } }, title, ...current.body(), buttons));
    title.focus({ preventScroll: true });
  }

  // Keep keyboard focus inside the dialog, and let Escape skip the tour.
  function onKey(event) {
    if (event.key === "Escape") { event.preventDefault(); finish(false); return; }
    if (event.key !== "Tab") return;
    const focusable = [...dialog.querySelectorAll("button")];
    if (!focusable.length) return;
    const first = focusable[0], lastEl = focusable[focusable.length - 1];
    if (event.shiftKey && (document.activeElement === first || document.activeElement === dialog || document.activeElement.id === "tour-title")) { event.preventDefault(); lastEl.focus(); }
    else if (!event.shiftKey && document.activeElement === lastEl) { event.preventDefault(); first.focus(); }
  }
  document.addEventListener("keydown", onKey, true);
  render();
  return { close: () => finish(false) };
}
