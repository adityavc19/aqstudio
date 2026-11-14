import { PERSONAS, api, errorBox, h, postJson, show, table, when, words } from "../dom.js";

export function reviewView(uploadId) {
  const raw = sessionStorage.getItem(`aq.upload.${uploadId}`);
  if (!raw) {
    return show("Upload not found", h("h1", {}, "This upload is no longer in this tab"), h("p", {}, "Add your data again to continue."), h("a", { class: "btn", href: "#/" }, "Back to home"));
  }
  const upload = JSON.parse(raw);
  const stats = upload.stats;
  const errors = h("div");
  const status = h("p", { role: "status", class: "muted" });
  const readers = {};
  const assumptionItems = upload.assumptions.map((a) => {
    if (!a.alternative_label) return h("li", {}, a.description);
    const name = `as-${a.id}`;
    readers[a.id] = () => {
      const picked = document.querySelector(`input[name="${CSS.escape(name)}"]:checked`);
      if (picked && picked.value === "confirm") return "confirmed";
      return a.default_applied ? "overridden" : "proposed";
    };
    return h("li", {}, h("fieldset", { class: a.default_applied ? "" : "needs-approval" },
      h("legend", {}, a.description),
      h("label", { class: "choice" }, h("input", { type: "radio", name, value: "confirm", checked: a.default_applied }), a.confirm_label),
      h("label", { class: "choice" }, h("input", { type: "radio", name, value: "alternative", checked: !a.default_applied }), a.alternative_label)));
  });
  const mappingEditor = editableMapping(upload.mapping);
  const context = h("input", { type: "text", id: "context", maxlength: "1000", "aria-describedby": "context-help" });
  const previous = h("select", { id: "previous" }, h("option", { value: "" }, "No comparison"));
  api("/briefs").then((items) => items.filter((i) => i.status_line).forEach((i) => previous.append(h("option", { value: i.id }, `${i.label}: ${i.status_line}`)))).catch(() => {});
  const create = h("button", { type: "submit" }, "Looks right, create brief");
  const form = h("form", {
    class: "card",
    onsubmit: async (e) => {
      e.preventDefault();
      errors.replaceChildren();
      create.disabled = true;
      status.textContent = "Starting your brief…";
      try {
        const accepted = await postJson("/briefs", {
          upload_id: uploadId,
          persona: document.querySelector('input[name="persona"]:checked').value,
          context: context.value.trim() || null,
          assumptions: Object.entries(readers).map(([id, read]) => ({ id, status: read() })),
          mapping: mappingEditor.changed() ? mappingEditor.read() : null,
          previous_brief_id: previous.value || null,
        });
        location.hash = `#/brief/${accepted.brief_id}`;
      } catch (err) {
        errors.append(errorBox(err.message, err.code));
      } finally {
        create.disabled = false;
        status.textContent = "";
      }
    },
  },
    h("h2", {}, "Who is this brief for?"),
    h("fieldset", {}, h("legend", { class: "sr-only" }, "Audience"), Object.entries(PERSONAS).map(([value, label], i) => h("label", { class: "choice" }, h("input", { type: "radio", name: "persona", value, checked: i === 0 }), label))),
    h("label", { for: "context" }, "Area or notes this data covers (optional)"),
    h("p", { id: "context-help", class: "muted small" }, "Shown to the AI as background only. Up to 1000 characters."),
    context,
    h("label", { for: "previous" }, "Compare with an earlier brief (optional)"),
    previous, errors,
    h("div", { class: "actions" }, create, h("a", { class: "btn secondary", href: "#/" }, "Back and edit data")),
    status);

  const flags = upload.early_flags;
  show("Check understanding",
    h("ol", { class: "flow", "aria-label": "Progress" }, h("li", {}, "Add your data"), h("li", { "aria-current": "step" }, "Check how it was read"), h("li", {}, "Get the brief")),
    h("h1", {}, "Here is how I understood your data"),
    h("p", { class: "lede" }, "Nothing has been summarised yet. Change anything that looks wrong."),
    upload.warnings.map((w) => h("p", { class: "note" }, w)),
    h("div", { class: "grid stats" },
      h("div", { class: "stat" }, "Rows", h("b", {}, stats.rows.toLocaleString())),
      h("div", { class: "stat" }, "Stations", h("b", {}, stats.stations.length)),
      h("div", { class: "stat" }, "Period (IST)", h("b", { class: "small-b" }, `${when(stats.period_start)} to ${when(stats.period_end)}`)),
      h("div", { class: "stat" }, "Pollutants", h("b", { class: "small-b" }, stats.pollutants.join(", ") || "none"))),
    h("div", { class: "grid two" },
      h("section", { class: "card", "aria-labelledby": "as-h" }, h("h2", { id: "as-h" }, "Assumptions to confirm"), assumptionItems.length ? h("ul", { class: "plain" }, assumptionItems) : h("p", { class: "muted" }, "No assumptions needed.")),
      h("section", { class: "card", "aria-labelledby": "ef-h" }, h("h2", { id: "ef-h" }, "Early flags"),
        flags.length ? h("ul", { class: "plain" }, flags.map((f) => h("li", {}, h("span", { class: `sev sev-${f.severity}` }, f.severity), ` ${f.station_id}${f.pollutant ? ` · ${f.pollutant}` : ""}: `, f.detail))) : h("p", { class: "muted" }, "No data-quality problems found."))),
    h("details", { class: "card" }, h("summary", {}, "Column mapping (you can correct it)"),
      h("p", { class: "muted small" }, "Fix how a column is read instead of editing your file. The server checks the result: exactly one station and one timestamp column, and at least one pollutant."),
      mappingEditor.node),
    form);
}

const MEANINGS = ["station_id", "timestamp", "station_name", "latitude", "longitude", "pollutant", "ignore"];

function editableMapping(mapping) {
  // One row per column: a meaning select, plus pollutant name and unit when it is a pollutant.
  const rows = mapping.map((m, i) => {
    const meaning = h("select", { id: `map-m-${i}`, "aria-label": `Meaning of column ${m.column}` }, MEANINGS.map((v) => h("option", { value: v, selected: v === m.meaning }, words(v))));
    const pollutant = h("input", { type: "text", maxlength: "32", value: m.pollutant || "", "aria-label": `Pollutant name for ${m.column}` });
    const unit = h("input", { type: "text", maxlength: "16", value: m.unit || "", placeholder: "e.g. ug/m3", "aria-label": `Unit for ${m.column}` });
    const sync = () => {
      const isPollutant = meaning.value === "pollutant";
      pollutant.disabled = !isPollutant;
      unit.disabled = !isPollutant;
    };
    meaning.addEventListener("change", sync);
    sync();
    return { m, meaning, pollutant, unit, cells: [m.column, meaning, pollutant, unit] };
  });
  const read = () => rows.map(({ m, meaning, pollutant, unit }) => ({
    column: m.column,
    meaning: meaning.value,
    pollutant: meaning.value === "pollutant" ? pollutant.value.trim() || null : null,
    unit: meaning.value === "pollutant" ? unit.value.trim() || null : null,
    confidence: 1.0,
  }));
  const changed = () => rows.some(({ m, meaning, pollutant, unit }) => meaning.value !== m.meaning || (meaning.value === "pollutant" && (pollutant.value.trim() !== (m.pollutant || "") || unit.value.trim() !== (m.unit || ""))));
  return { node: table("How each column is read", ["Column", "Meaning", "Pollutant", "Unit"], rows.map((r) => r.cells)), read, changed };
}
