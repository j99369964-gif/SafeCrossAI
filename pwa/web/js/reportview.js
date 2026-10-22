// Report a dangerous intersection: pick it (near me, or by searching), say what's wrong, save it on this device so routes
// steer around it, then send it to the government agency that can fix it (SafeCross prepares the report; the visitor sends it).
import { h, icon, pageHeader } from "./dom.js";
import * as api from "./api.js";
import { createSearchBox } from "./searchbox.js";
import { streetTitle, tierPill } from "./detail.js";
import {
  ISSUES, MAX_NOTE, MAX_REPORTS, listReports, getReport, saveReport, removeReport, setAvoid, reportText, channelsFor, issueText, formatDate,
} from "./reports.js";

const hashParams = () => new URLSearchParams((window.location.hash.split("?")[1]) || "");

export function mountReportView(root) {
  const { header, heading } = pageHeader("New York City · Westchester", "Report a dangerous intersection",
    "Tell the people who run your streets about an intersection that feels dangerous. SafeCross also remembers it on this device and steers your routes around it.");
  const page = h("section", { class: "page report-page" }, header);
  root.append(page);

  let destroyed = false;
  let selected = null; // { id, label, area, lat, lng, tier, unvalidated }
  let nearbyToken = 0;

  // ------------------------------------------------------------------ 1. which intersection
  const chosenEl = h("div", {});
  const nearbyEl = h("div", {});
  const pickError = h("div", { role: "alert" });
  const locateButton = h("button", { type: "button", class: "btn btn-ghost", onclick: () => findNearby() }, icon("locate", 18), "Intersections near me");
  const searchBox = createSearchBox({
    label: "Or search for it",
    placeholder: "e.g. Broadway & W 42nd St",
    only: "intersection",
    hint: "Type both streets with \"&\" between them.",
    onPick: (result) => choose(result),
  });
  const pickBody = h("div", { class: "report-pick" }, h("div", { class: "btn-row", style: "margin-top:0" }, locateButton), nearbyEl, searchBox.element);
  page.append(h("div", { class: "card report-step" },
    h("h2", {}, h("span", { class: "step-num" }, "1"), "Which intersection?"), pickError, chosenEl, pickBody));

  function choose(result) {
    selected = {
      id: String(result.id), label: result.label, area: result.area, lat: result.lat, lng: result.lng,
      tier: result.tier, unvalidated: Boolean(result.unvalidated),
    };
    nearbyToken++;
    nearbyEl.replaceChildren();
    pickError.replaceChildren();
    const existing = getReport(selected.id);
    fillForm(existing || { issues: [], note: "", avoid: true });
    renderChosen();
    renderSend(existing);
  }

  function renderChosen() {
    pickBody.hidden = Boolean(selected);
    if (!selected) { chosenEl.replaceChildren(); return; }
    chosenEl.replaceChildren(h("div", { class: "chosen" },
      h("div", {}, streetTitle(selected.label, "h3"),
        h("div", { class: "detail-risk" }, tierPill(selected.tier), h("span", { class: "muted" }, `${selected.area}${selected.unvalidated ? " (unvalidated)" : ""}`)),
        getReport(selected.id) ? h("p", { class: "muted small" }, "You've reported this intersection before. Saving updates that report.") : null),
      h("button", { type: "button", class: "btn btn-small btn-ghost", onclick: () => { selected = null; renderChosen(); renderSend(null); searchBox.clear(); } }, "Change")));
  }

  function findNearby() {
    if (!("geolocation" in navigator)) { pickError.replaceChildren(h("div", { class: "banner banner-error" }, "This browser can't share your location. Search for the intersection instead.")); return; }
    const mine = ++nearbyToken;
    pickError.replaceChildren();
    locateButton.classList.add("is-locating");
    nearbyEl.replaceChildren(h("p", { class: "muted", role: "status" }, h("span", { class: "spinner", "aria-hidden": "true" }), "Finding your location..."));
    navigator.geolocation.getCurrentPosition(async (position) => {
      locateButton.classList.remove("is-locating");
      if (mine !== nearbyToken || destroyed) return;
      try {
        const { results } = await api.nearby(position.coords.latitude, position.coords.longitude);
        if (mine !== nearbyToken || destroyed) return;
        if (!results.length) {
          nearbyEl.replaceChildren(h("div", { class: "banner banner-info" }, "No intersections SafeCross covers are within about 400 metres of you. SafeCross covers New York City and Westchester County. Search for the intersection instead."));
          return;
        }
        nearbyEl.replaceChildren(h("p", { class: "muted small" }, "Closest first. Choose one:"),
          h("ul", { class: "nearby-list" }, results.map((result) => h("li", {},
            h("button", { type: "button", class: "nearby-item", onclick: () => choose(result) },
              h("span", { class: "result-title" }, result.label),
              h("span", { class: "result-sub" }, `${result.meters} m away · ${result.area}`))))));
      } catch (problem) {
        if (mine === nearbyToken && !destroyed) nearbyEl.replaceChildren(h("div", { class: "banner banner-error" }, problem.message));
      }
    }, (problem) => {
      locateButton.classList.remove("is-locating");
      if (mine !== nearbyToken || destroyed) return;
      nearbyEl.replaceChildren(h("div", { class: "banner banner-error" }, problem && problem.code === 1
        ? "Location permission was denied. Allow it in your browser settings, or search for the intersection."
        : "Couldn't get your location. Search for the intersection instead."));
    }, { enableHighAccuracy: true, timeout: 10000, maximumAge: 30000 });
  }

  // ------------------------------------------------------------------ 2. what's wrong
  const issueBoxes = ISSUES.map(([key, text]) => {
    const box = h("input", { type: "checkbox", name: "issue", value: key });
    return { key, box, label: h("label", { class: "check-chip" }, box, h("span", {}, text)) };
  });
  const note = h("textarea", { id: "report-note", rows: 4, maxlength: MAX_NOTE, placeholder: "When is it worst? What happened? Anything that would help someone fix it." });
  const noteCount = h("span", { class: "muted small" }, `0 / ${MAX_NOTE}`);
  note.addEventListener("input", () => { noteCount.textContent = `${note.value.length} / ${MAX_NOTE}`; });
  const avoidBox = h("input", { type: "checkbox", id: "report-avoid", checked: true });
  const formError = h("div", { role: "alert" });
  const saveButton = h("button", { type: "submit", class: "btn" }, icon("flag", 18), "Save report");
  const form = h("form", { class: "card report-step", novalidate: true, onsubmit: (event) => { event.preventDefault(); save(); } },
    h("h2", {}, h("span", { class: "step-num" }, "2"), "What makes it dangerous?"),
    h("fieldset", {}, h("legend", { class: "visually-hidden" }, "Problems"), h("div", { class: "check-grid" }, issueBoxes.map((item) => item.label))),
    h("div", { class: "field" }, h("label", { for: "report-note" }, "Details (optional)"), note, noteCount),
    h("label", { class: "check-row", for: "report-avoid" }, avoidBox,
      h("span", {}, h("strong", {}, "Avoid it when I plan routes."), " Route options that pass it won't be recommended when another option doesn't.")),
    formError,
    h("div", { class: "btn-row" }, saveButton),
    h("p", { class: "form-hint" }, "Saved on this device only. If someone is hurt or in danger right now, call 911."));
  page.append(form);

  function fillForm(report) {
    issueBoxes.forEach(({ key, box }) => { box.checked = report.issues.includes(key); });
    note.value = report.note || "";
    noteCount.textContent = `${note.value.length} / ${MAX_NOTE}`;
    avoidBox.checked = Boolean(report.avoid);
  }

  function save() {
    formError.replaceChildren();
    const issues = issueBoxes.filter(({ box }) => box.checked).map(({ key }) => key);
    const problem = !selected ? "Choose the intersection first (step 1)."
      : !issues.length && !note.value.trim() ? "Tick at least one problem, or describe it in the details box."
        : !getReport(selected.id) && listReports().length >= MAX_REPORTS ? `You can keep up to ${MAX_REPORTS} reports. Delete an old one below first.` : null;
    if (problem) { formError.replaceChildren(h("div", { class: "banner banner-error" }, problem)); return; }
    const previous = getReport(selected.id);
    const report = { ...selected, issues, note: note.value, avoid: avoidBox.checked, createdAt: previous ? previous.createdAt : undefined };
    if (!saveReport(report)) {
      formError.replaceChildren(h("div", { class: "banner banner-error" }, "This browser isn't letting SafeCross save anything (private browsing can do this). You can still send the report below."));
    }
    renderChosen();
    renderSend(getReport(selected.id) || { ...report, createdAt: new Date().toISOString() }, true);
    renderList();
  }

  // ------------------------------------------------------------------ 3. send it
  const sendEl = h("div", {});
  page.append(sendEl);

  async function copy(text, button) {
    let ok = false;
    try { await navigator.clipboard.writeText(text); ok = true; } catch { /* fall back below */ }
    if (!ok) {
      const area = h("textarea", { style: "position:fixed;opacity:0", "aria-hidden": "true" }, text);
      document.body.append(area);
      area.select();
      try { ok = document.execCommand("copy"); } catch { ok = false; }
      area.remove();
    }
    button.replaceChildren(icon(ok ? "check" : "copy", 18), ok ? "Copied" : "Select the text above to copy it");
  }

  function renderSend(report, moveFocus = false) {
    if (!report || !selected || report.id !== selected.id) { sendEl.replaceChildren(); return; }
    const text = reportText(report);
    const subject = text.split("\n")[0];
    const channels = channelsFor(report.area);
    const copyButton = h("button", { type: "button", class: "btn btn-small", onclick: (event) => copy(text, event.currentTarget) }, icon("copy", 18), "Copy report");
    const shareButton = navigator.share ? h("button", { type: "button", class: "btn btn-small btn-ghost", onclick: () => navigator.share({ title: subject, text }).catch(() => {}) }, icon("share", 18), "Share") : null;
    const mail = h("a", { class: "btn btn-small btn-ghost", href: `mailto:?subject=${encodeURIComponent(subject)}&body=${encodeURIComponent(text)}` }, icon("mail", 18), "Email");
    const title = h("h2", { tabindex: "-1" }, h("span", { class: "step-num" }, "3"), "Send it to the government");
    sendEl.replaceChildren(h("div", { class: "card report-step report-send" },
      title,
      h("div", { class: "banner banner-info" }, h("strong", {}, "SafeCross doesn't send reports for you."), " Copy the report below and send it through an official channel, so it gets a case number you can follow up on."),
      h("pre", { class: "report-text", tabindex: "0", "aria-label": "Report text" }, text),
      h("div", { class: "btn-row" }, copyButton, shareButton, mail),
      h("p", {}, channels.intro),
      h("ul", { class: "channel-list" }, channels.links.map((link) => h("li", {},
        link.href ? h("a", { href: link.href, target: link.href.startsWith("http") ? "_blank" : null, rel: link.href.startsWith("http") ? "noopener noreferrer" : null },
          h("strong", {}, link.title), link.href.startsWith("http") ? icon("external", 16) : icon("phone", 16)) : h("strong", {}, link.title),
        h("span", { class: "muted" }, ` ${link.text}`)))),
      h("p", { class: "muted small" }, "If someone is hurt or in danger right now, call 911.")));
    if (moveFocus) { title.focus({ preventScroll: true }); title.scrollIntoView({ behavior: "smooth", block: "start" }); }
  }

  // ------------------------------------------------------------------ your reports
  const listEl = h("div", {});
  page.append(listEl);

  function renderList() {
    const reports = listReports();
    if (!reports.length) { listEl.replaceChildren(); return; }
    const avoided = reports.filter((r) => r.avoid).length;
    listEl.replaceChildren(h("div", { class: "card" },
      h("h2", { style: "margin-top:0" }, "Your reports"),
      h("p", { class: "muted small" }, `${reports.length} saved on this device · ${avoided} avoided when planning routes.`),
      h("ul", { class: "report-list" }, reports.map((report) => {
        const avoid = h("input", { type: "checkbox", checked: report.avoid, onchange: (event) => { setAvoid(report.id, event.target.checked); renderList(); } });
        return h("li", { class: "report-item" },
          h("div", { class: "report-main" },
            h("span", { class: "result-title" }, report.label),
            h("span", { class: "result-sub" }, [report.area, formatDate(report.createdAt), ...report.issues.slice(0, 2).map(issueText)].filter(Boolean).join(" · "))),
          h("label", { class: "check-row compact" }, avoid, h("span", {}, "Avoid on routes")),
          h("div", { class: "report-actions" },
            h("button", { type: "button", class: "btn btn-small btn-ghost", onclick: () => { choose(report); fillForm(report); form.scrollIntoView({ behavior: "smooth" }); } }, "Edit or send"),
            h("a", { class: "btn btn-small btn-ghost", href: `#/explore?id=${encodeURIComponent(report.id)}` }, "Map"),
            h("button", { type: "button", class: "btn btn-small btn-ghost btn-icon-only", "aria-label": `Delete the report for ${report.label}`, title: "Delete",
              onclick: () => {
                removeReport(report.id);
                if (selected && selected.id === report.id) renderSend(null);
                renderChosen();
                renderList();
              } }, icon("trash", 18))));
      }))));
  }
  renderList();

  // ------------------------------------------------------------------ start: #/report?id=123 (from an intersection's details)
  const startId = hashParams().get("id");
  if (startId) {
    api.getIntersection(startId).then((detail) => {
      if (destroyed) return;
      choose({ id: detail.id, label: detail.label, area: detail.area, lat: detail.lat, lng: detail.lng, tier: detail.tierCode, unvalidated: !detail.validated });
    }).catch((problem) => { if (!destroyed) pickError.replaceChildren(h("div", { class: "banner banner-error" }, problem.message)); });
  }

  return { heading, destroy() { destroyed = true; nearbyToken++; } };
}
