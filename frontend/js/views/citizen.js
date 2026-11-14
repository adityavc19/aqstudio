import { api, categoryBadge, errorBox, gradeBadge, h, num, radioTabs, show, when } from "../dom.js";
import { LANGUAGES } from "./brief.js";

const GROUPS = { everyone: "Everyone", children: "Children", older_adults: "Older adults", sensitive_groups: "Sensitive groups", data: "About the data" };

export async function citizenView(shareId) {
  let page;
  try {
    page = await api(`/share/${encodeURIComponent(shareId)}`);
  } catch (err) {
    return show("Citizen page", h("h1", {}, "Air near you"), errorBox(err.message, err.code), h("a", { class: "btn", href: "#/" }, "Home"));
  }
  const query = h("input", { type: "text", id: "area", autocomplete: "off", "aria-describedby": "area-help" });
  const result = h("div", { "aria-live": "polite" });
  const lang = h("select", { id: "cit-lang" }, Object.entries(LANGUAGES).map(([code, name]) => h("option", { value: code }, name)));
  const level = h("select", { id: "cit-level" }, h("option", { value: "simple" }, "Simple"), h("option", { value: "standard" }, "Standard"));
  const advice = h("div", { "aria-live": "polite" });

  function search() {
    const q = query.value.trim().toLowerCase();
    const matches = page.stations.filter((s) => !q || s.name.toLowerCase().includes(q) || s.station_id.toLowerCase().includes(q));
    if (!matches.length) {
      result.replaceChildren(h("p", { class: "note" }, `No station in this data matches “${query.value}”. Try another name, or see all stations below.`), list(page.stations));
      return;
    }
    const top = [...matches].sort((a, b) => (b.aqi ?? -1) - (a.aqi ?? -1))[0];
    result.replaceChildren(stationCard(top), matches.length > 1 ? list(matches) : null);
  }

  async function loadAdvice() {
    advice.replaceChildren(h("p", { class: "muted" }, "Loading advice…"));
    try {
      const doc = await api(`/share/${encodeURIComponent(shareId)}/advisory?${new URLSearchParams({ language: lang.value, level: level.value })}`);
      const byKey = Object.fromEntries(doc.sections.map((s) => [s.key, s]));
      const panel = h("div", { role: "tabpanel" });
      const tabs = radioTabs("Advice for", GROUPS, (key) => {
        const s = byKey[key];
        panel.replaceChildren(h("section", { lang: s.translated ? doc.language : "en" }, h("h3", {}, s.title), h("p", { class: "big-text" }, s.text), s.verified ? null : h("p", { class: "note small", lang: "en" }, "⚠ This part could not be fully checked against the data.")));
      });
      tabs.select("everyone");
      const head = byKey.headline;
      advice.replaceChildren(h("article", { class: "card printable", lang: doc.language },
        h("h2", { lang: head.translated ? doc.language : "en" }, head.text), tabs.list, panel,
        h("p", { class: "small muted", lang: "en" }, doc.disclaimer),
        h("div", { class: "actions no-print" }, h("button", { type: "button", class: "secondary", onclick: () => window.print() }, "Print"))));
    } catch (err) {
      advice.replaceChildren(errorBox(err.message, err.code));
    }
  }

  show("Air near you",
    h("p", { class: "badge c-na notice" }, page.notice),
    h("h1", {}, "Air near you"),
    h("p", { class: "lede" }, `${page.status_line}. Data for ${page.period || "the uploaded period"}, published ${when(page.created_at)}.`),
    h("p", { class: "note" }, page.data_note),
    h("form", { class: "card inline", role: "search", onsubmit: (e) => { e.preventDefault(); search(); } },
      h("label", { for: "area" }, "Your area or nearest station"), h("p", { id: "area-help", class: "muted small" }, "Type part of a station name."), query, h("button", { type: "submit" }, "Check")),
    result,
    h("section", { class: "card", "aria-labelledby": "adv-h" }, h("h2", { id: "adv-h" }, "What to do today"),
      h("div", { class: "grid controls" }, h("div", {}, h("label", { for: "cit-lang" }, "Language"), lang), h("div", {}, h("label", { for: "cit-level" }, "Reading level"), level), h("div", { class: "actions" }, h("button", { type: "button", onclick: loadAdvice }, "Show advice"))),
      advice));
  search();
  loadAdvice();
}

function stationCard(s) {
  const weak = s.reliability_grade === "poor" || s.reliability_grade === "unreliable";
  return h("section", { class: "card station" },
    h("p", { class: "small muted" }, s.name),
    h("p", {}, categoryBadge(s.category, "big")),
    s.aqi == null ? h("p", {}, "Not enough data for an AQI at this station.") : h("p", { class: "big-text" }, `AQI ${num(s.aqi, 0)}`),
    h("div", { class: "chips" }, gradeBadge(s.reliability_grade)),
    weak ? h("p", { class: "note" }, "This station's data is unreliable, so treat this reading with caution.") : null);
}

function list(stations) {
  return h("ul", { class: "plain" }, stations.map((s) => h("li", {}, h("b", {}, s.name), " ", categoryBadge(s.category), s.aqi == null ? "" : ` AQI ${num(s.aqi, 0)}`)));
}
