import { CATEGORY, api, categoryBadge, categoryLabel, errorBox, gradeBadge, h, num, periodLabel, radioTabs, show, when } from "../dom.js";
import { LANGUAGES, viewToggle } from "./brief.js";

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
      const spokenLevel = level.value;
      const tabs = radioTabs("Advice for", GROUPS, (key) => {
        const s = byKey[key];
        const player = h("div", { class: "no-print" });
        const listen = h("button", { type: "button", class: "secondary", onclick: () => {
          const src = `/api/share/${encodeURIComponent(shareId)}/audio?${new URLSearchParams({ language: doc.language, level: spokenLevel, group: key })}`;
          const audio = h("audio", { controls: true, src, "aria-label": `Advice for ${GROUPS[key]}, read aloud` });
          audio.addEventListener("error", () => player.replaceChildren(errorBox("Audio is not available right now. The written advice above is complete.")));
          player.replaceChildren(audio);
          audio.play().catch(() => {});
        } }, "▶ Listen");
        panel.replaceChildren(h("section", { lang: s.translated ? doc.language : "en" }, h("h3", {}, s.title), h("p", { class: "big-text" }, s.text), s.verified ? null : h("p", { class: "note small", lang: "en" }, "⚠ This part could not be fully checked against the data.")), h("div", { class: "actions no-print" }, listen), player);
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
    viewToggle("citizen", sessionStorage.getItem(`aq.share.${shareId}`), shareId),
    h("h1", {}, "Air near you"),
    h("p", { class: "muted" }, `${page.period ? periodLabel(page.period) : "Uploaded period"} · published ${when(page.created_at)}`),
    result,
    h("form", { class: "search-row", role: "search", onsubmit: (e) => { e.preventDefault(); search(); } },
      h("label", { for: "area" }, "Not your area? Search by station name"), h("div", { class: "inline-field" }, query, h("button", { type: "submit", class: "secondary" }, "Search")), h("p", { id: "area-help", class: "muted small" }, "Showing the station with the worst air until you search.")),
    h("section", { class: "card", "aria-labelledby": "adv-h" }, h("h2", { id: "adv-h" }, "What to do today"),
      h("div", { class: "grid controls" }, h("div", {}, h("label", { for: "cit-lang" }, "Language"), lang), h("div", {}, h("label", { for: "cit-level" }, "Reading level"), level), h("div", { class: "actions" }, h("button", { type: "button", class: "secondary", onclick: loadAdvice }, "Update"))),
      advice),
    h("p", { class: "small muted fineprint" }, `${page.data_note} ${page.notice}`));
  search();
  loadAdvice();
}

const PLAIN = {
  Good: "Air is good. Enjoy outdoor activity.",
  Satisfactory: "Air is acceptable. Very sensitive people may want to take it easy.",
  Moderate: "Sensitive groups should reduce long or heavy outdoor exertion.",
  Poor: "Reduce long outdoor activity, especially children, older adults and people with asthma.",
  "Very Poor": "Avoid long outdoor activity. Children and older adults should stay indoors where possible.",
  Severe: "Stay indoors where possible and avoid all outdoor exertion.",
};

function stationCard(s) {
  // The answer first: category, a plain-language line, then how far to trust it.
  const weak = s.reliability_grade === "poor" || s.reliability_grade === "unreliable";
  const [, cls] = CATEGORY[s.category] || CATEGORY.insufficient_data;
  return h("section", { class: `answer ${cls}`, "aria-labelledby": "answer-h" },
    h("p", { class: "answer-place" }, s.name),
    h("h2", { id: "answer-h", class: "answer-cat" }, categoryLabel(s.category), s.aqi == null ? null : h("span", { class: "answer-aqi" }, ` · AQI ${num(s.aqi, 0)}`)),
    h("p", { class: "answer-line" }, PLAIN[s.category] || "There is not enough data at this station to say how the air is."),
    h("div", { class: "chips" }, gradeBadge(s.reliability_grade)),
    weak ? h("p", { class: "small" }, "⚠ This station's data is unreliable, so treat this reading with caution.") : null);
}

function list(stations) {
  return h("ul", { class: "plain" }, stations.map((s) => h("li", {}, h("b", {}, s.name), " ", categoryBadge(s.category), s.aqi == null ? "" : ` AQI ${num(s.aqi, 0)}`)));
}
