import { api, categoryBadge, errorBox, h, radioTabs, show } from "../dom.js";
import { sampleCsv } from "../sample.js";

export function homeView() {
  let tab = "paste";
  let file = null;
  const textarea = h("textarea", { id: "pasted", rows: "10", spellcheck: "false", "aria-describedby": "paste-help" });
  const errors = h("div");
  const status = h("p", { class: "muted", role: "status" });
  const submit = h("button", { type: "submit" }, "Check my data");
  const panels = {
    paste: h("div", { role: "tabpanel" },
      h("label", { for: "pasted" }, "Paste a table"),
      h("p", { id: "paste-help", class: "muted small" }, "CSV with a Station ID column, a Timestamp column and one column per pollutant, such as “PM2.5 (ug/m3)”. Pasted data is treated as data, never as instructions."),
      textarea),
    upload: h("div", { role: "tabpanel", hidden: true },
      h("label", { for: "file" }, "Choose a CSV, text or Excel (.xlsx) file (up to 5 MB)"),
      h("p", { id: "file-help", class: "muted small" }, "The first sheet with data is read; formulas are not evaluated. PDF is not supported yet."),
      h("input", { id: "file", type: "file", accept: ".csv,.txt,.xlsx", "aria-describedby": "file-help", onchange: (e) => (file = e.target.files[0] || null) })),
    sample: h("div", { role: "tabpanel", hidden: true },
      h("p", { class: "sample-note" }, h("b", {}, "Synthetic sample dataset. "), "Made up for this demonstration; these are not real measurements. It includes a sensor fault, a data gap and a column in mg/m3, so you can see the checks and the unit approval."),
      h("button", { type: "button", class: "secondary", onclick: () => { textarea.value = sampleCsv(); tabs.select("paste"); textarea.focus(); } }, "Load sample into the box")),
  };
  const tabs = radioTabs("Data source", { paste: "Paste", upload: "Upload file", sample: "Sample data" }, (key) => {
    tab = key;
    Object.entries(panels).forEach(([name, panel]) => (panel.hidden = name !== key));
  });
  tabs.select("paste");

  async function send(labels) {
    errors.replaceChildren();
    const options = { method: "POST" };
    if (tab === "upload") {
      if (!file) return errors.append(errorBox("Choose a file first."));
      options.body = new FormData();
      options.body.append("file", file);
      if (labels) Object.entries(labels).forEach(([k, v]) => options.body.append(k, v));
    } else {
      if (!textarea.value.trim()) return errors.append(errorBox("Paste some data first, or load the sample."));
      options.headers = { "Content-Type": "application/json" };
      options.body = JSON.stringify({ text: textarea.value, ...(labels || {}) });
    }
    submit.disabled = true;
    status.textContent = "Checking your data…";
    try {
      const upload = await api("/uploads", options);
      sessionStorage.setItem(`aq.upload.${upload.upload_id}`, JSON.stringify(upload));
      location.hash = `#/review/${upload.upload_id}`;
    } catch (err) {
      errors.append(err.code === "labels_required" ? labelsForm(err.message, send) : errorBox(err.message, err.code));
    } finally {
      submit.disabled = false;
      status.textContent = "";
    }
  }

  const form = h("form", { onsubmit: (e) => { e.preventDefault(); send(null); } },
    tabs.list, panels.paste, panels.upload, panels.sample, errors, h("div", { class: "actions" }, submit), status);

  const shareInput = h("input", { type: "text", id: "share-link", "aria-describedby": "share-help", placeholder: "https://…/#/c/…" });
  const citizen = h("section", { class: "card soft", "aria-labelledby": "cit-h" },
    h("h2", { id: "cit-h" }, "Just checking the air near you?"),
    h("p", { id: "share-help", class: "muted small" }, "Open a citizen page someone shared with you."),
    h("form", { class: "inline", onsubmit: (e) => { e.preventDefault(); const id = shareInput.value.trim().split("/c/").pop(); if (id) location.hash = `#/c/${id}`; } },
      h("label", { for: "share-link", class: "sr-only" }, "Citizen page link"), shareInput, h("button", { type: "submit", class: "secondary" }, "Open")));

  const recent = h("section", { class: "card", "aria-labelledby": "recent-h" }, h("h2", { id: "recent-h" }, "Recent briefs"), h("p", { class: "muted" }, "Loading…"));
  show("Home",
    h("div", { class: "hero" }, h("h1", {}, "Turn air-quality data into a briefing you can act on"),
      h("p", { class: "lede" }, "Add readings from your stations. Code calculates every number; the AI only writes the explanation, and every sentence is checked against the calculated facts and linked to your data.")),
    h("ol", { class: "flow", "aria-label": "How it works" }, h("li", { "aria-current": "step" }, "Add your data"), h("li", {}, "Check how it was read"), h("li", {}, "Get the brief")),
    h("div", { class: "grid two" }, h("section", { class: "card", "aria-labelledby": "add-h" }, h("h2", { id: "add-h" }, "Add your data"), form), h("div", {}, recent, citizen)),
  );
  loadRecent(recent);
}

async function loadRecent(section) {
  const heading = h("h2", { id: "recent-h" }, "Recent briefs");
  try {
    const items = await api("/briefs");
    if (!items.length) return section.replaceChildren(heading, h("p", { class: "muted" }, "No briefs yet in this browser."));
    section.replaceChildren(heading, h("ul", { class: "plain" }, items.map((item, i) => {
      const older = items[i + 1];
      return h("li", {},
        h("div", { class: "small muted" }, item.label),
        h("div", {}, h("b", {}, item.status_line || "Processing or failed")),
        h("div", { class: "chips" }, item.worst_category ? categoryBadge(item.worst_category) : null, item.unreliable_count ? h("span", { class: "badge g-unreliable" }, `${item.unreliable_count} unreliable`) : null),
        h("div", { class: "chips" }, h("a", { class: "btn secondary small-btn", href: `#/brief/${item.id}` }, "Open"), older ? h("a", { class: "btn secondary small-btn", href: `#/brief/${item.id}?against=${older.id}` }, "Compare with previous") : null));
    })));
  } catch (err) {
    section.replaceChildren(heading, errorBox(`Could not load recent briefs. ${err.message}`));
  }
}

function labelsForm(message, send) {
  // A wide hourly grid has no labels; ask rather than guess what it measures.
  const station = h("input", { type: "text", id: "lbl-station", maxlength: "64", required: true });
  const pollutant = h("select", { id: "lbl-pollutant" }, ["PM2.5", "PM10", "NO2", "SO2", "O3", "CO", "NH3"].map((p) => h("option", { value: p }, p)));
  const unit = h("select", { id: "lbl-unit" }, ["ug/m3", "mg/m3", "ppb", "ppm"].map((u) => h("option", { value: u }, u)));
  const go = h("button", { type: "button", onclick: () => {
    if (!station.value.trim()) return station.focus();
    send({ station: station.value.trim(), pollutant: pollutant.value, unit: unit.value });
  } }, "Convert grid and continue");
  const box = h("fieldset", { class: "needs-approval", role: "group", "aria-labelledby": "lbl-legend" },
    h("legend", { id: "lbl-legend" }, "This looks like a wide hourly grid"),
    h("p", { class: "small" }, message, " Grid hours are read as IST clock hours."),
    h("div", { class: "grid controls" },
      h("div", {}, h("label", { for: "lbl-station" }, "Station name"), station),
      h("div", {}, h("label", { for: "lbl-pollutant" }, "Pollutant"), pollutant),
      h("div", {}, h("label", { for: "lbl-unit" }, "Unit"), unit)),
    h("div", { class: "actions" }, go));
  setTimeout(() => station.focus(), 0);
  return box;
}
