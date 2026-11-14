import { CATEGORY, PLAIN, api, categoryBadge, categoryLabel, errorBox, h, show, when } from "../dom.js";

function ago(minutes) {
  if (minutes < 60) return `${minutes} min ago`;
  const hours = Math.round(minutes / 60);
  return `${hours} hour${hours === 1 ? "" : "s"} ago`;
}

function answer(station) {
  const [, cls] = CATEGORY[station.category] || CATEGORY.insufficient_data;
  return h("section", { class: `answer ${cls}`, "aria-labelledby": "answer-h" },
    h("p", { class: "answer-place" }, `${station.name} · ${station.distance_km} km away`),
    h("h2", { id: "answer-h", class: "answer-cat" }, categoryLabel(station.category), station.aqi == null ? null : h("span", { class: "answer-aqi" }, ` · AQI ${station.aqi}`)),
    h("p", { class: "answer-line" }, PLAIN[station.category] || "There is not enough recent data at this station to rate the air."),
    h("p", { class: "small" }, `Last reading ${ago(station.last_reading_age_min)}${station.dominant ? ` · driven by ${station.dominant}` : ""}`));
}

function stationRow(s) {
  return h("li", {},
    h("div", { class: "chips" }, h("b", {}, s.name), categoryBadge(s.category), s.aqi == null ? null : h("span", {}, `AQI ${s.aqi}`)),
    h("div", { class: "small muted" }, `${s.distance_km} km away · last reading ${ago(s.last_reading_age_min)} · ${s.pollutants.map((p) => `${p.pollutant} ${p.value == null ? "n/a" : p.value} (${p.hours} h)`).join(", ") || "no usable pollutants"}`),
    s.reason ? h("div", { class: "small warn-text" }, s.reason) : null,
    s.skipped.length ? h("div", { class: "small muted" }, `Not used: ${s.skipped.join(", ")}. Gas readings in ppb or ppm are not converted automatically.`) : null);
}

export async function liveView(params) {
  const lat = params.get("lat");
  const lon = params.get("lon");
  const place = params.get("place") || "this location";
  show("Air near you", h("h1", {}, `Air near ${place}`), h("p", { class: "muted", role: "status" }, "Checking nearby public monitors…"));
  let area;
  try {
    area = await api(`/areas/live?${new URLSearchParams({ lat, lon })}`);
  } catch (err) {
    const msg = err.code === "no_data" ? err.message : `Live data is not available right now. ${err.message}`;
    return show("Air near you", h("h1", {}, `Air near ${place}`), errorBox(msg, err.code), h("a", { class: "btn secondary", href: "#/" }, "Back"));
  }
  const rated = area.stations.filter((s) => s.aqi != null);
  const lead = rated[0] || area.stations[0];
  show("Air near you",
    h("h1", {}, `Air near ${place}`),
    h("p", { class: "muted" }, `Rolling 24-hour CPCB rating · checked ${when(area.generated_at)}`),
    answer(lead),
    lead !== area.stations[0] ? h("p", { class: "small muted" }, `The nearest monitor, ${area.stations[0].name}, did not have enough recent data, so the next one is shown.`) : null,
    area.health_statement ? h("section", { class: "card", "aria-labelledby": "health-h" },
      h("h2", { id: "health-h" }, "What CPCB says about this level"),
      h("p", {}, area.health_statement),
      h("p", { class: "small muted" }, "Official CPCB health statement for the worst category nearby. For medical concerns, contact your doctor or local health authority.")) : null,
    h("section", { "aria-labelledby": "near-h" }, h("h2", { id: "near-h" }, "Nearby monitors"), h("ul", { class: "plain" }, area.stations.map(stationRow))),
    h("p", { class: "small muted fineprint" }, area.source),
    h("div", { class: "actions" }, h("a", { class: "btn secondary", href: "#/" }, "Back")));
}
