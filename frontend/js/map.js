// Leaflet map, loaded only when stations have coordinates, from a pinned, integrity-checked CDN.
import { CATEGORY, h, num, onLeave } from "./dom.js";

const LEAFLET = "https://cdnjs.cloudflare.com/ajax/libs/leaflet/1.9.4/";
const SRI = {
  "leaflet.min.js": "sha384-NElt3Op+9NBMCYaef5HxeJmU4Xeard/Lku8ek6hoPTvYkQPh3zLIrJP7KiRocsxO",
  "leaflet.min.css": "sha384-c6Rcwz4e4CITMbu/NBmnNS8yN2sC3cUElMEMfP3vqqKFp7GOYaaBBCqmaWBjmkjb",
};

function loadLeaflet() {
  if (window.L) return Promise.resolve();
  return new Promise((resolve, reject) => {
    const css = h("link", { rel: "stylesheet", href: `${LEAFLET}leaflet.min.css`, integrity: SRI["leaflet.min.css"], crossorigin: "anonymous" });
    const script = h("script", { src: `${LEAFLET}leaflet.min.js`, integrity: SRI["leaflet.min.js"], crossorigin: "anonymous" });
    script.onload = resolve;
    script.onerror = reject;
    document.head.append(css, script);
  });
}

export async function drawMap(holder, stations) {
  const located = stations.filter((s) => s.lat != null && s.lon != null);
  holder.replaceChildren();
  if (!located.length) {
    holder.append(h("p", { class: "note" }, "The map is off because this data has no coordinates. Coordinates are never guessed. The table shows the same stations; add locations to turn the map on."));
    return;
  }
  const box = h("div", { class: "map", role: "region", "aria-label": "Map of stations. The table has the same information." });
  holder.append(box);
  try {
    await loadLeaflet();
  } catch {
    holder.replaceChildren(h("p", { class: "note" }, "The map library could not load. Use the table."));
    return;
  }
  const map = window.L.map(box);
  onLeave(() => map.remove());
  window.L.tileLayer("https://tile.openstreetmap.org/{z}/{x}/{y}.png", { maxZoom: 18, attribution: "© OpenStreetMap contributors" }).addTo(map);
  for (const s of located) {
    const [symbol, cls] = CATEGORY[s.category] || CATEGORY.insufficient_data;
    const icon = window.L.divIcon({ html: h("div", { class: `marker ${cls}` }, symbol), className: "", iconSize: [32, 32] });
    window.L.marker([s.lat, s.lon], { icon, title: `${s.name}: ${s.category}`, alt: `${s.name}, ${s.category}` })
      .addTo(map)
      .bindPopup(h("div", {}, h("b", {}, s.name), h("div", {}, `${s.category}${s.aqi == null ? "" : `, AQI ${num(s.aqi, 0)}`}`), h("div", {}, `${s.reliability_grade} reliability`)));
  }
  map.fitBounds(located.map((s) => [s.lat, s.lon]), { padding: [30, 30], maxZoom: 14 });
}
