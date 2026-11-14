import {
  CATEGORY, CATEGORY_ORDER, PERSONAS, api, categoryBadge, errorBox, gradeBadge, h,
  num, plural, postJson, radioTabs, section, show, sleep, table, when, words,
} from "../dom.js";
import { evidenceChips } from "../evidence.js";
import { drawMap } from "../map.js";

const STEPS = ["Read the file", "Clean and standardise", "Check data quality", "Calculate facts", "Write the brief", "Check every claim", "Plan actions for you"];
const STAGES = ["queued", "cleaning", "quality", "facts", "interpreting", "verifying", "actions"];
const TIER = { now: "Do now", escalate: "Escalate", context: "Good to know" };
const EFFECT = { exposure: "Protects people", source: "Reduces pollution", evidence: "Improves the data" };
const LANGUAGES = { en: "English", hi: "हिन्दी (Hindi)", kn: "ಕನ್ನಡ (Kannada)", mr: "मराठी (Marathi)", bn: "বাংলা (Bengali)", ml: "മലയാളം (Malayalam)" };

export { LANGUAGES };

export async function briefView(id, against) {
  const route = location.hash; // stop polling as soon as the user navigates elsewhere
  let lastStage = null;
  while (location.hash === route) {
    let state;
    try {
      state = await api(`/briefs/${id}`);
    } catch (err) {
      return show("Brief not found", h("h1", {}, "Could not open this brief"), errorBox(err.message, err.code), h("a", { class: "btn", href: "#/" }, "Back to home"));
    }
    if (location.hash !== route) return;
    if (state.status === "processing") {
      if (state.stage !== lastStage) {
        lastStage = state.stage;
        processing(state.stage);
      }
      await sleep(1500);
      continue;
    }
    if (state.status === "failed") {
      return show("Brief failed", h("h1", {}, "No brief was produced"), errorBox(state.error.message, state.error.code), h("p", { class: "muted" }, "Your data was not changed and nothing was made up to fill the gap."), h("a", { class: "btn", href: "#/" }, "Back to home"));
    }
    return render(state.brief, against, state.share_id);
  }
}

function processing(stage) {
  const index = Math.max(0, STAGES.indexOf(stage));
  show("Building your brief",
    h("ol", { class: "flow", "aria-label": "Progress" }, h("li", {}, "Add your data"), h("li", {}, "Check how it was read"), h("li", { "aria-current": "step" }, "Get the brief")),
    h("h1", {}, "Building your brief"),
    h("p", { class: "lede" }, "Usually under a minute. Numbers are calculated by code; the AI only writes the explanation, and every sentence is checked."),
    h("progress", { max: String(STEPS.length), value: String(index), "aria-label": `Step ${index + 1} of ${STEPS.length}` }),
    h("ol", { class: "steps" }, STEPS.map((label, i) => h("li", { "data-state": i < index ? "done" : i === index ? "active" : "todo" }, h("span", { "aria-hidden": "true" }, i < index ? "✔" : i === index ? "…" : "○"), label, h("span", { class: "sr-only" }, i < index ? " (done)" : i === index ? " (in progress)" : "")))));
}

function unsureAbout(brief) {
  const items = [];
  const summary = brief.summary;
  if (summary && summary.unreliable_count) items.push(`${plural(summary.unreliable_count, "station")} graded unreliable`);
  for (const a of brief.assumptions) {
    if (a.kind === "unit_conversion") items.push(a.status === "confirmed" ? `${a.proposed.pollutant} converted from ${a.proposed.from_unit} (you approved)` : `${a.proposed.pollutant} left out: units differ and no conversion was approved`);
    else if (a.alternative_label && a.default_applied && a.status !== "overridden") items.push(a.description.replace(/\.$/, ""));
  }
  if (brief.coordinates_source === "none") items.push("map is off: no coordinates in the data");
  return items.concat(brief.notes);
}

function distribution(stations) {
  const counts = {};
  stations.forEach((s) => (counts[s.category] = (counts[s.category] || 0) + 1));
  const present = CATEGORY_ORDER.filter((c) => counts[c]);
  return h("div", {},
    h("div", { class: "dist", "aria-hidden": "true" }, present.map((c) => h("span", { class: `dist-seg ${CATEGORY[c][1]}`, style: `flex:${counts[c]}` }, CATEGORY[c][0]))),
    h("p", { class: "chips" }, present.map((c) => h("span", {}, categoryBadge(c), ` ${counts[c]}`))));
}

function claims(brief) {
  const ok = brief.claims.filter((c) => c.status === "verified").length;
  return section("sec-claims", "What happened", true,
    h("p", { class: "muted small" }, `${ok} of ${brief.claims.length} sentences checked against the calculated facts. Unverified sentences are shown and marked, never hidden.`),
    brief.claims.length ? brief.claims.map((c) => h("article", { class: "item" },
      h("div", { class: c.status === "verified" ? "verdict ok" : "verdict bad" }, c.status === "verified" ? "✔ Checked against the data" : "⚠ Not verified"),
      h("p", {}, c.text),
      evidenceChips(brief.id, c.fact_ids),
      c.notes.length ? h("ul", { class: "small" }, c.notes.map((n) => h("li", {}, n))) : null)) : h("p", { class: "muted" }, "The AI returned no claims."));
}

function actions(brief) {
  const list = h("div");
  const draw = (filter) => list.replaceChildren(...(brief.actions.filter((a) => filter === "all" || a.effect_type === filter).map((a) => h("article", { class: "item" },
    h("div", { class: "chips" }, h("span", { class: `badge tier-${a.tier}` }, TIER[a.tier] || a.tier), h("span", { class: "badge c-na" }, EFFECT[a.effect_type] || a.effect_type), h("span", { class: "small muted" }, words(a.horizon))),
    h("h3", {}, a.text),
    a.gated_reason ? h("p", { class: "note" }, `⚠ ${a.gated_reason}`) : null,
    h("ol", { class: "small" }, a.steps.map((step) => h("li", {}, step))),
    h("p", { class: "small" }, `Owner: ${a.owner}${a.escalate_to ? ` · Escalate to: ${a.escalate_to}` : ""} · Success looks like: ${a.success_signal}`),
    evidenceChips(brief.id, a.fact_ids)))));
  if (!brief.actions.length) return section("sec-actions", "What to do", true, h("p", { class: "muted" }, "No actions passed the checks for this brief, so none are shown."));
  const tabs = radioTabs("Filter actions", { all: "All", exposure: "Protect people", source: "Reduce pollution", evidence: "Improve data" }, draw);
  tabs.select("all");
  return section("sec-actions", `What to do · ${PERSONAS[brief.persona] || brief.persona}`, true,
    h("p", { class: "muted small" }, "Each action cites the facts it relies on. Actions resting on unreliable data become data checks."), tabs.list, list);
}

function patterns(brief) {
  const of = (kind) => brief.facts.filter((f) => f.kind === kind);
  const rows = [
    ...of("citywide_pattern").map((f) => [`All stations: ${f.values.pollutant} ${f.values.direction} at ${num(f.values.stations_same_direction, 0)} of ${num(f.values.stations_compared, 0)} stations. ${f.values.hint}`, f]),
    ...of("diurnal").map((f) => [`${f.station_id}: ${f.values.pollutant} peaks ${f.values.peak_window} (average ${num(f.values.peak_mean)}), lowest around ${String(f.values.low_hour).padStart(2, "0")}:00 (average ${num(f.values.low_mean)}), over ${num(f.values.days, 0)} days.`, f]),
    ...of("trend").map((f) => [`${f.station_id}: ${f.values.pollutant} ${f.values.direction} in the second half (${num(f.values.first_half_mean)} → ${num(f.values.second_half_mean)}, ${f.values.change_pct > 0 ? "+" : ""}${f.values.change_pct}%) over ${num(f.values.days, 0)} days.`, f]),
  ];
  return section("sec-patterns", "Patterns over time", false,
    h("p", { class: "muted small" }, "Calculated by code. Shown only when there is enough data: 2+ days for daily peaks, 6+ complete days for trends."),
    rows.length ? rows.map(([text, f]) => h("article", { class: "item" }, h("p", {}, text), h("div", { class: "chips" }, gradeBadge(f.reliability_grade)), evidenceChips(brief.id, [f.id]))) : h("p", { class: "muted" }, "Not enough data for daily or multi-day patterns."));
}

function heatGrid(brief) {
  if (!brief.hourly.length) return h("p", { class: "muted" }, "No hourly PM2.5 series to show (daily data or no PM2.5).");
  const hours = brief.hourly[0].cells.map((c) => new Date(c.ts).toLocaleTimeString("en-IN", { timeZone: "Asia/Kolkata", hour: "2-digit", hour12: false }));
  return h("div", {},
    h("h3", {}, "Last 24 hours, hourly PM2.5"),
    h("p", { class: "muted small" }, "Each cell is one hour (IST). Colours show an indicative PM2.5 band; the official AQI uses 24-hour averages. Empty cells had no valid reading."),
    h("div", { class: "table-wrap", tabindex: "0", role: "region", "aria-label": "Hourly PM2.5 grid" },
      h("table", { class: "grid-table" },
        h("caption", { class: "sr-only" }, "Hourly PM2.5 by station"),
        h("thead", {}, h("tr", {}, h("th", { scope: "col" }, "Station"), hours.map((hh) => h("th", { scope: "col", class: "hour" }, hh)))),
        h("tbody", {}, brief.hourly.map((row) => h("tr", {}, h("th", { scope: "row" }, row.station_id), row.cells.map((c, i) => {
          const [symbol, cls] = c.band ? CATEGORY[c.band] : ["", "empty"];
          return h("td", { class: `cell ${cls}`, title: `${hours[i]}:00 IST: ${c.value == null ? "no reading" : `${c.value} ug/m3, ${c.band}`}` }, h("span", { "aria-hidden": "true" }, symbol), h("span", { class: "sr-only" }, c.value == null ? "no reading" : `${c.value}, ${c.band}`));
        })))))));
}

function where(brief) {
  const tableHolder = h("div");
  const mapHolder = h("div");
  const result = h("div", { role: "status" });
  let sortKey = "aqi";
  const draw = () => {
    const rows = [...brief.stations].sort((a, b) => (sortKey === "name" ? a.name.localeCompare(b.name) : (b.aqi ?? -1) - (a.aqi ?? -1)));
    tableHolder.replaceChildren(
      h("div", { class: "chips" }, h("span", { class: "small muted" }, "Sort:"), h("button", { type: "button", class: "link", "aria-pressed": String(sortKey === "aqi"), onclick: () => { sortKey = "aqi"; draw(); } }, "AQI, highest first"), h("button", { type: "button", class: "link", "aria-pressed": String(sortKey === "name"), onclick: () => { sortKey = "name"; draw(); } }, "Name")),
      table("Stations (the full alternative to the map)", ["Station", "AQI category", "AQI", "Reliability", "Position"], rows.map((s) => [h("span", {}, s.name, s.name !== s.station_id ? h("span", { class: "muted small" }, ` (${s.station_id})`) : null), categoryBadge(s.category), s.aqi == null ? "n/a" : num(s.aqi, 0), gradeBadge(s.reliability_grade), s.lat == null ? "no coordinates" : `${num(s.lat, 4)}, ${num(s.lon, 4)}`])));
  };
  const text = h("textarea", { id: "locations", rows: "3", spellcheck: "false", "aria-describedby": "loc-help" });
  const form = h("form", {
    onsubmit: async (e) => {
      e.preventDefault();
      result.replaceChildren();
      try {
        const res = await postJson(`/briefs/${brief.id}/locations`, { text: text.value });
        brief.stations = res.stations;
        draw();
        await drawMap(mapHolder, brief.stations);
        result.append(h("p", {}, `${plural(res.matched.length, "row")} matched.`), res.unmatched.length ? h("ul", {}, res.unmatched.map((u) => h("li", {}, `Row ${u.row} (${u.file_station}): ${u.reason}`))) : null);
      } catch (err) {
        result.append(errorBox(err.message, err.code));
      }
    },
  }, h("label", { for: "locations" }, "Add or correct station locations"), h("p", { id: "loc-help", class: "muted small" }, "CSV with columns station_id,lat,lon. Only the map changes; nothing is re-analysed."), text, h("div", { class: "actions" }, h("button", { type: "submit", class: "secondary" }, "Update map")), result);
  draw();
  drawMap(mapHolder, brief.stations);
  return section("sec-where", "Where", true, tableHolder, heatGrid(brief), mapHolder, h("details", {}, h("summary", {}, "Add locations"), form));
}

async function changed(brief, againstId, holder) {
  try {
    const d = await api(`/briefs/${brief.id}/diff?against=${encodeURIComponent(againstId)}`);
    const label = (key) => { const [kind, station, pollutant] = key.split("|"); return `${station || "All stations"} ${pollutant || words(kind)}`.trim(); };
    const line = (c) => h("li", {}, `${label(c.key)}: ${num(c.before)} → ${num(c.after)}${c.delta_pct == null ? "" : ` (${c.delta_pct > 0 ? "+" : ""}${c.delta_pct}%)`}`);
    const s = d.summary_inputs;
    holder.replaceChildren(section("sec-changed", "What changed", true,
      h("p", {}, `${plural(s.genuine_changes, "real change")}, ${s.coverage_explained_changes} only look changed, ${plural(s.new_flags, "new flag")}, ${s.resolved_flags} resolved.`),
      d.changed.length ? [h("h3", {}, "Real changes"), h("ul", {}, d.changed.map(line))] : null,
      d.explained_by_coverage.length ? [h("h3", {}, "Only looks changed"), h("p", { class: "muted small" }, "Coverage or reliability differs between the briefs, so these are data gaps, not a real trend."), h("ul", {}, d.explained_by_coverage.map(line))] : null,
      d.new_flags.length ? [h("h3", {}, "New data-quality flags"), h("ul", {}, d.new_flags.map((f) => h("li", {}, `${words(f.kind)} at ${f.station_id}`)))] : null));
  } catch (err) {
    holder.replaceChildren(errorBox(`Could not compare: ${err.message}`, err.code));
  }
}

function quality(brief) {
  const flags = brief.flags.filter((f) => f.kind !== "no_coords");
  return section("sec-quality", "Data quality", false,
    h("h3", {}, "Station reliability"),
    brief.reliability.length ? table("Reliability by station", ["Station", "Grade", "Score", "Coverage", "Why"], brief.reliability.map((r) => [r.station_id, gradeBadge(r.grade), num(r.score), `${num(r.coverage_pct)}%`, r.reasons.join(" ")])) : h("p", { class: "muted" }, "No station had usable data."),
    h("h3", {}, "Flags"),
    flags.length ? table("Problems found in the data", ["Id", "Kind", "Station", "Pollutant", "Severity", "What was found"], flags.map((f) => [f.id, words(f.kind), f.station_id, f.pollutant || "", f.severity, f.detail])) : h("p", { class: "muted" }, "No data-quality problems detected."),
    h("h3", {}, "What was changed while cleaning"),
    h("ul", {}, Object.entries(brief.ledger_summary).map(([rule, n]) => h("li", {}, `${words(rule)}: ${n}`))),
    brief.ledger.length ? h("details", {}, h("summary", {}, `Show the first ${brief.ledger.length} cleaning entries`), table("Cleaning ledger", ["Row", "Rule", "Before", "After", "Reason"], brief.ledger.map((e) => [e.row_ref, words(e.rule), e.before ?? "", e.after ?? "", e.reason]))) : null,
    h("h3", {}, "Assumptions"),
    brief.assumptions.length ? h("ul", {}, brief.assumptions.map((a) => h("li", {}, `${a.description} (${a.status})`))) : h("p", { class: "muted" }, "None."));
}

export function renderDocument(doc) {
  return h("article", { class: "card printable", lang: doc.language },
    doc.sections.map((sec) => h("section", { lang: sec.translated ? doc.language : "en" },
      h("h3", {}, sec.title), h("p", {}, sec.text),
      sec.verified ? null : h("p", { class: "note small", lang: "en" }, "⚠ This part could not be fully checked against the data."),
      doc.language !== "en" && !sec.translated ? h("p", { class: "small muted", lang: "en" }, "Shown in English: the translation could not keep the numbers exactly.") : null)),
    h("p", { class: "small muted", lang: "en" }, doc.disclaimer),
    h("div", { class: "actions no-print" }, h("button", { type: "button", class: "secondary", onclick: () => window.print() }, "Print")));
}

function advisory(brief) {
  const fmt = h("select", { id: "adv-format" }, h("option", { value: "citizen" }, "Citizen advisory"), h("option", { value: "note" }, "Internal briefing note"));
  const lang = h("select", { id: "adv-lang" }, Object.entries(LANGUAGES).map(([code, name]) => h("option", { value: code }, name)));
  const level = h("select", { id: "adv-level" }, h("option", { value: "simple" }, "Simple"), h("option", { value: "standard" }, "Standard"));
  const out = h("div", { "aria-live": "polite" });
  const go = h("button", { type: "submit" }, "Show");
  const form = h("form", {
    class: "grid controls",
    onsubmit: async (e) => {
      e.preventDefault();
      go.disabled = true;
      out.replaceChildren(h("p", { class: "muted" }, "Preparing…"));
      try {
        out.replaceChildren(renderDocument(await api(`/briefs/${brief.id}/render?${new URLSearchParams({ format: fmt.value, language: lang.value, level: level.value })}`)));
      } catch (err) {
        out.replaceChildren(errorBox(err.message, err.code));
      } finally {
        go.disabled = false;
      }
    },
  }, h("div", {}, h("label", { for: "adv-format" }, "Document"), fmt), h("div", {}, h("label", { for: "adv-lang" }, "Language"), lang), h("div", {}, h("label", { for: "adv-level" }, "Reading level"), level), h("div", { class: "actions" }, go));
  return section("sec-advisory", "Advisory and briefing note", false, h("p", { class: "muted small" }, "The internal note uses only verified findings and actions. The citizen advisory is written by the AI and every section is checked; translations are machine-made and their numbers are checked."), form, out);
}

export function viewToggle(current, briefId, shareId) {
  // Operator and citizen views of the same brief; switching is navigation, not a setup step.
  if (shareId) sessionStorage.setItem(`aq.share.${shareId}`, briefId);
  const link = (key, label, href) =>
    key === current
      ? h("span", { class: "seg on", "aria-current": "page" }, label)
      : h("a", { class: "seg", href }, label);
  const copy = shareId
    ? h("button", { type: "button", class: "link small", onclick: (e) => {
        navigator.clipboard?.writeText(`${location.origin}/#/c/${shareId}`);
        e.currentTarget.textContent = "Citizen link copied";
      } }, "Copy citizen link")
    : null;
  return h("nav", { class: "view-toggle", "aria-label": "View" },
    briefId ? link("operator", "Operator view", `#/brief/${briefId}`) : null,
    shareId ? link("citizen", "Citizen view", `#/c/${shareId}`) : null,
    copy);
}

async function ensureShare(brief, shareId) {
  // Briefs made before links were automatic get one on first view.
  if (shareId) return shareId;
  try {
    return (await postJson(`/briefs/${brief.id}/share`, {})).share_id;
  } catch {
    return null;
  }
}

async function render(brief, against, shareId) {
  shareId = await ensureShare(brief, shareId);
  const unsure = unsureAbout(brief);
  const compareId = against || brief.previous_id;
  const changedHolder = h("div");
  const toc = [["sec-claims", "What happened"], ["sec-actions", "What to do"], ["sec-patterns", "Patterns"], ["sec-where", "Where"], ...(compareId ? [["sec-changed", "What changed"]] : []), ["sec-quality", "Data quality"], ["sec-advisory", "Advisory"]];
  show("Brief",
    viewToggle("operator", brief.id, shareId),
    h("section", { class: "summary card" },
      h("p", { class: "small muted" }, `${PERSONAS[brief.persona] || brief.persona} · created ${when(brief.created_at)}${brief.context ? ` · ${brief.context}` : ""}`),
      h("h1", {}, brief.summary ? brief.summary.status_line : "Air quality brief"),
      distribution(brief.stations),
      unsure.length ? h("p", { class: "note" }, h("b", {}, "Unsure about: "), unsure.join("; "), ".") : null),
    h("nav", { class: "toc", "aria-label": "In this brief" }, toc.map(([id, label]) => h("a", { href: `#${id}`, onclick: (e) => { e.preventDefault(); const el = document.getElementById(id); if (el) { el.open = true; el.scrollIntoView({ block: "start" }); el.querySelector("summary").focus(); } } }, label))),
    claims(brief), actions(brief), patterns(brief), where(brief), changedHolder, quality(brief), advisory(brief),
    h("div", { class: "actions" }, h("a", { class: "btn secondary", href: "#/" }, "Add more data")));
  if (compareId) changed(brief, compareId, changedHolder);
}

