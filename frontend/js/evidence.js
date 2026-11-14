// Evidence drawer: a fact, its values and coverage, the source rows, and related flags.
import { api, errorBox, gradeBadge, h, num, words } from "./dom.js";

const dialog = document.getElementById("evidence");
dialog.addEventListener("click", (e) => {
  if (e.target === dialog) dialog.close();
});

export const closeEvidence = () => dialog.open && dialog.close();

export function factTitle(fact) {
  const who = fact.station_id ? `${fact.station_id} · ` : "";
  const kinds = {
    pollutant_mean: `${fact.values.pollutant} average`,
    aqi_latest: "latest AQI",
    aqi_worst: "worst-day AQI",
    aqi_insufficient: "AQI (not enough data)",
    pm_ratio: "PM2.5/PM10 ratio",
    hotspot: "hotspot ranking",
    station_reliability: "station reliability",
    quality_flag: `data-quality flag: ${words(fact.values.kind || "")}`,
    diurnal: `${fact.values.pollutant} daily pattern`,
    trend: `${fact.values.pollutant} trend`,
    citywide_pattern: `citywide ${fact.values.pollutant} movement`,
  };
  return who + (kinds[fact.kind] || words(fact.kind));
}

export function evidenceChips(briefId, factIds) {
  return h("div", { class: "chips" }, h("span", { class: "small muted" }, "Evidence:"), factIds.map((fid) => h("button", { type: "button", class: "secondary chip", onclick: () => openEvidence(briefId, fid), "aria-label": `Show evidence ${fid}` }, fid)));
}

export async function openEvidence(briefId, factId) {
  const close = h("button", { type: "button", onclick: () => dialog.close() }, "Close");
  dialog.replaceChildren(h("h2", { id: "evidence-title" }, `Evidence ${factId}`), h("p", { class: "muted" }, "Loading…"));
  dialog.showModal();
  try {
    const ev = await api(`/briefs/${briefId}/evidence/${encodeURIComponent(factId)}`);
    const fact = ev.fact;
    const pairs = (obj) => h("dl", { class: "facts" }, Object.entries(obj).flatMap(([k, v]) => [h("dt", {}, words(k)), h("dd", {}, v == null ? "n/a" : String(v))]));
    dialog.replaceChildren(
      h("h2", { id: "evidence-title" }, `${fact.id}: ${factTitle(fact)}`),
      h("div", { class: "chips" }, gradeBadge(fact.reliability_grade), h("span", { class: "badge c-na" }, `coverage ${num(fact.coverage_pct)}%`)),
      h("p", { class: "small muted" }, `Period ${fact.period || "n/a"}. Calculated by code from the rows below.`),
      h("h3", {}, "Values"),
      pairs(fact.values),
      ev.reliability ? h("p", { class: "small" }, `Station reliability: ${ev.reliability.grade}, score ${num(ev.reliability.score)}.`) : null,
      ev.rows.length ? [h("h3", {}, "Source rows"), ev.rows.map((r) => [h("p", { class: "small" }, h("b", {}, r.row_ref)), pairs(r.values)])] : null,
      ev.flags.length ? [h("h3", {}, "Related data-quality flags"), h("ul", {}, ev.flags.map((f) => h("li", {}, `${f.id}: ${f.detail}`)))] : null,
      h("div", { class: "actions" }, close),
    );
    close.focus();
  } catch (err) {
    dialog.replaceChildren(h("h2", { id: "evidence-title" }, `Evidence ${factId}`), errorBox(err.message, err.code), close);
  }
}
