// The dangerous intersections this visitor reported. Kept ON THIS DEVICE only (localStorage): nothing is sent to the
// SafeCross server except the ids of the ones marked "avoid", with each route search, so the routes can steer around them.
// SafeCross doesn't file anything with the government; the report page helps the visitor send it themselves.
import { getItem, setItem } from "./storage.js";

const KEY = "safecross.reports.v1";
export const MAX_REPORTS = 50; // the server checks at most this many when ranking routes
export const MAX_NOTE = 1000;

export const ISSUES = [
  ["speeding", "Drivers speed through"],
  ["yielding", "Drivers don't yield to people crossing"],
  ["visibility", "Hard to see oncoming traffic (blind corner, parked cars)"],
  ["crosswalk", "Missing or faded crosswalk"],
  ["signal-time", "Not enough time to cross"],
  ["control", "Needs a traffic signal or stop sign"],
  ["signal-broken", "Traffic signal or sign broken or missing"],
  ["bike", "Unsafe for cycling"],
  ["sidewalk", "Sidewalk or curb ramp blocked or broken"],
  ["lighting", "Poorly lit at night"],
  ["crashes", "I've seen crashes or near misses here"],
];
const ISSUE_TEXT = Object.fromEntries(ISSUES);

function read() {
  try {
    const value = JSON.parse(getItem(KEY) || "[]");
    return Array.isArray(value) ? value.filter((r) => r && typeof r.id === "string") : [];
  } catch { return []; }
}
const write = (reports) => setItem(KEY, JSON.stringify(reports.slice(0, MAX_REPORTS)));

/** Newest first. */
export const listReports = () => read();
export const getReport = (id) => read().find((report) => report.id === String(id)) || null;

/** Adds or replaces the report for this intersection. Returns false if the browser won't store it. */
export function saveReport(report) {
  const others = read().filter((r) => r.id !== String(report.id));
  const clean = {
    id: String(report.id), label: String(report.label), area: String(report.area || ""),
    lat: Number(report.lat), lng: Number(report.lng),
    tier: [0, 1, 2, 3].includes(report.tier) ? report.tier : 3, unvalidated: Boolean(report.unvalidated),
    issues: (report.issues || []).filter((key) => ISSUE_TEXT[key]),
    note: String(report.note || "").slice(0, MAX_NOTE),
    avoid: Boolean(report.avoid),
    createdAt: report.createdAt || new Date().toISOString(),
  };
  return write([clean, ...others]);
}

export function removeReport(id) { write(read().filter((r) => r.id !== String(id))); }

export function setAvoid(id, avoid) {
  write(read().map((r) => (r.id === String(id) ? { ...r, avoid: Boolean(avoid) } : r)));
}

/** Intersection ids to steer routes around. */
export const avoidIds = () => read().filter((r) => r.avoid).map((r) => r.id).slice(0, MAX_REPORTS);

export const issueText = (key) => ISSUE_TEXT[key] || key;

export const formatDate = (iso) => {
  const date = new Date(iso);
  return Number.isNaN(date.getTime()) ? "" : date.toLocaleDateString(undefined, { year: "numeric", month: "short", day: "numeric" });
};

/** The report as plain text, ready to paste into 311 or an email. */
export function reportText(report) {
  const lines = [
    `Traffic safety concern: ${report.label}${report.area ? `, ${report.area}` : ""}`,
    "",
    `Location: ${report.label}${report.area ? `, ${report.area}` : ""}`,
    `Coordinates: ${report.lat.toFixed(5)}, ${report.lng.toFixed(5)} (https://www.google.com/maps/search/?api=1&query=${report.lat.toFixed(5)},${report.lng.toFixed(5)})`,
  ];
  if (report.issues.length) lines.push("", "What makes it dangerous:", ...report.issues.map((key) => `- ${issueText(key)}`));
  if (report.note.trim()) lines.push("", "Details:", report.note.trim());
  lines.push("", `Observed by a resident; reported ${formatDate(report.createdAt)}.`);
  return lines.join("\n");
}

/**
 * Where to send it. NYC: 311 handles street-safety requests for every agency. Westchester: it depends on who owns the
 * road, so all three owners are listed. Only stable home pages are linked, since deep links into these sites move.
 */
export function channelsFor(area) {
  if (/westchester/i.test(area || "")) {
    return {
      intro: "In Westchester County, who fixes an intersection depends on who owns the roads that meet there.",
      links: [
        { title: "Your city, town or village", text: "Most local streets. Contact its public works or highway department, or its police department's non-emergency line." },
        { title: "Westchester County Department of Public Works and Transportation", text: "County roads.", href: "https://www.westchestergov.com/" },
        { title: "New York State Department of Transportation", text: "Numbered state routes (for example Route 9A or Route 100).", href: "https://www.dot.ny.gov/" },
      ],
    };
  }
  return {
    intro: "In New York City, 311 takes street-safety requests and passes them to the Department of Transportation (DOT) or NYPD.",
    links: [
      { title: "NYC 311 online", text: "Search for the problem (for example \"traffic signal\", \"crosswalk\" or \"speed hump\"), then paste your report.", href: "https://portal.311.nyc.gov/" },
      { title: "Call 311", text: "212-NEW-YORK (212-639-9675) from outside New York City.", href: "tel:311" },
    ],
  };
}
