// Civic Air Quality Briefing Studio: a small no-build frontend for the /api backend.
// All DOM is built from text nodes, never from HTML strings, so upload data cannot inject markup.

const main = document.getElementById("main");
const live = document.getElementById("live");
const dialog = document.getElementById("evidence");

const PERSONAS = {
  ward_officer: "Ward officer",
  housing_society: "Housing society",
  school: "School",
  other: "Someone else",
};
const CATEGORY = {
  Good: ["●", "c-good"],
  Satisfactory: ["◐", "c-sat"],
  Moderate: ["▲", "c-mod"],
  Poor: ["◆", "c-poor"],
  "Very Poor": ["■", "c-vpoor"],
  Severe: ["✖", "c-sev"],
  insufficient_data: ["?", "c-na"],
};
const GRADE_SYMBOL = { good: "✔", fair: "◐", poor: "▲", unreliable: "✖" };
const STEPS = [
  "Read the file",
  "Clean and standardise",
  "Check data quality",
  "Calculate facts",
  "Write the brief",
  "Check every claim",
  "Plan actions for you",
];
const STAGES = ["queued", "cleaning", "quality", "facts", "interpreting", "verifying", "actions"];
const LEAFLET = "https://cdnjs.cloudflare.com/ajax/libs/leaflet/1.9.4/";
const LEAFLET_SRI = {
  "leaflet.min.js": "sha384-NElt3Op+9NBMCYaef5HxeJmU4Xeard/Lku8ek6hoPTvYkQPh3zLIrJP7KiRocsxO",
  "leaflet.min.css": "sha384-c6Rcwz4e4CITMbu/NBmnNS8yN2sC3cUElMEMfP3vqqKFp7GOYaaBBCqmaWBjmkjb",
};

// ---------- helpers ----------

function h(tag, attrs = {}, ...kids) {
  const el = document.createElement(tag);
  for (const [key, value] of Object.entries(attrs)) {
    if (value === false || value == null) continue;
    if (key === "class") el.className = value;
    else if (key.startsWith("on")) el.addEventListener(key.slice(2), value);
    else el.setAttribute(key, value === true ? "" : value);
  }
  for (const kid of kids.flat(Infinity)) {
    if (kid == null || kid === false) continue;
    el.append(kid);
  }
  return el;
}

class ApiFail extends Error {
  constructor(status, code, message) {
    super(message);
    this.status = status;
    this.code = code;
  }
}

async function api(path, options = {}) {
  let res;
  try {
    res = await fetch(`/api${path}`, { credentials: "same-origin", ...options });
  } catch {
    throw new ApiFail(0, "network", "Cannot reach the server. Check your connection and try again.");
  }
  let body = null;
  try {
    body = await res.json();
  } catch {
    body = null;
  }
  if (!res.ok) {
    const error = body && body.error;
    throw new ApiFail(res.status, error ? error.code : "error", error ? error.message : "Something went wrong.");
  }
  return body;
}

const sleep = (ms) => new Promise((resolve) => setTimeout(resolve, ms));
const announce = (message) => {
  live.textContent = "";
  setTimeout(() => (live.textContent = message), 50);
};
const words = (text) => String(text).replaceAll("_", " ");
const num = (value, digits = 1) => (value == null ? "n/a" : Number(value).toFixed(digits).replace(/\.0+$/, ""));

function when(iso) {
  if (!iso) return "unknown";
  return (
    new Date(iso).toLocaleString("en-IN", {
      timeZone: "Asia/Kolkata",
      day: "numeric",
      month: "short",
      hour: "2-digit",
      minute: "2-digit",
      hour12: false,
    }) + " IST"
  );
}

function categoryBadge(category) {
  const [symbol, cls] = CATEGORY[category] || CATEGORY.insufficient_data;
  const label = category === "insufficient_data" ? "Not enough data" : category;
  return h("span", { class: `badge ${cls}` }, h("span", { "aria-hidden": "true" }, symbol), label);
}

function gradeBadge(grade) {
  return h(
    "span",
    { class: `badge g-${grade}` },
    h("span", { "aria-hidden": "true" }, GRADE_SYMBOL[grade] || "?"),
    `${grade} reliability`,
  );
}

function errorBox(message, code) {
  return h("div", { class: "alert", role: "alert" }, message, code ? h("span", { class: "small muted" }, ` (${code})`) : null);
}

function table(caption, headers, rows) {
  return h(
    "div",
    { class: "table-wrap", tabindex: "0", role: "region", "aria-label": caption },
    h(
      "table",
      {},
      h("caption", {}, caption),
      h("thead", {}, h("tr", {}, headers.map((t) => h("th", { scope: "col" }, t)))),
      h("tbody", {}, rows.map((r) => h("tr", {}, r.map((c) => h("td", {}, c))))),
    ),
  );
}

let routeToken = 0;
let currentMap = null;

function show(title, ...nodes) {
  if (currentMap) {
    currentMap.remove();
    currentMap = null;
  }
  document.title = `${title} | Air Quality Briefing Studio`;
  main.replaceChildren(...nodes);
  const heading = main.querySelector("h1");
  if (heading) {
    heading.setAttribute("tabindex", "-1");
    heading.focus({ preventScroll: false });
  }
}

// ---------- sample data (synthetic, clearly labelled in the UI) ----------

function sampleCsv() {
  const stations = [
    ["SAMPLE-A", "Sample Station A", 12.97, 77.55, 55],
    ["SAMPLE-B", "Sample Station B", 12.99, 77.6, 140],
    ["SAMPLE-C", "Sample Station C", 12.93, 77.58, 30],
  ];
  const rows = ["Station ID,Station Name,Latitude,Longitude,Timestamp,PM2.5 (ug/m3),PM10 (ug/m3),NO2 (mg/m3),SO2 (ug/m3)"];
  for (const [id, name, lat, lon, base] of stations) {
    for (let hour = 0; hour < 24; hour += 1) {
      const stamp = `2026-11-13T${String(hour).padStart(2, "0")}:00:00Z`;
      const fault = id === "SAMPLE-B" && hour >= 4 && hour < 14;
      const pm25 = fault ? 500 : base + ((hour * 7) % 23);
      const pm10 = id === "SAMPLE-C" && hour >= 18 ? "" : base * 2 + ((hour * 5) % 31);
      const no2 = ((18 + (hour % 9)) / 1000).toFixed(3);
      rows.push(`${id},${name},${lat},${lon},${stamp},${pm25},${pm10},${no2},${8 + (hour % 5)}`);
    }
  }
  return rows.join("\n");
}

// ---------- home ----------

async function homeView() {
  let tab = "paste";
  let file = null;
  const textarea = h("textarea", { id: "pasted", rows: "10", spellcheck: "false", "aria-describedby": "paste-help" });
  const fileInput = h("input", {
    id: "file",
    type: "file",
    accept: ".csv,.txt",
    "aria-describedby": "file-help",
    onchange: (e) => (file = e.target.files[0] || null),
  });
  const status = h("p", { class: "muted", role: "status" });
  const errors = h("div");
  const submit = h("button", { type: "submit" }, "Check my data");

  const panels = {
    paste: h(
      "div",
      { role: "tabpanel", id: "panel-paste", "aria-labelledby": "tab-paste" },
      h("label", { for: "pasted" }, "Paste a table"),
      h("p", { id: "paste-help", class: "muted small" }, "CSV text with a Station ID column, a Timestamp column and one column per pollutant, such as “PM2.5 (ug/m3)”. Pasted data is treated as data, never as instructions."),
      textarea,
    ),
    upload: h(
      "div",
      { role: "tabpanel", id: "panel-upload", "aria-labelledby": "tab-upload", hidden: true },
      h("label", { for: "file" }, "Choose a CSV or text file (up to 5 MB)"),
      h("p", { id: "file-help", class: "muted small" }, "Excel and PDF files are not supported yet."),
      fileInput,
    ),
    sample: h(
      "div",
      { role: "tabpanel", id: "panel-sample", "aria-labelledby": "tab-sample", hidden: true },
      h("p", { class: "sample-note" }, h("b", {}, "Synthetic sample dataset."), " Made up for this demonstration; these are not real measurements. It includes a sensor fault, a data gap and a column in mg/m3 so you can see how the checks and the unit approval work."),
      h("button", { type: "button", class: "secondary", onclick: () => { textarea.value = sampleCsv(); select("paste"); textarea.focus(); announce("Sample data loaded into the box."); } }, "Load sample into the box"),
    ),
  };
  const tabs = ["paste", "upload", "sample"].map((name) =>
    h("button", { type: "button", role: "tab", id: `tab-${name}`, "aria-controls": `panel-${name}`, onclick: () => select(name) }, { paste: "Paste", upload: "Upload file", sample: "Sample data" }[name]),
  );
  function select(name) {
    tab = name;
    tabs.forEach((button, i) => {
      const active = ["paste", "upload", "sample"][i] === name;
      button.setAttribute("aria-selected", String(active));
      button.tabIndex = active ? 0 : -1;
    });
    Object.entries(panels).forEach(([key, panel]) => (panel.hidden = key !== name));
  }
  const tablist = h("div", { class: "tabs", role: "tablist", "aria-label": "Data source" }, tabs, );
  tablist.addEventListener("keydown", (e) => {
    const names = ["paste", "upload", "sample"];
    const index = names.indexOf(tab);
    if (e.key === "ArrowRight" || e.key === "ArrowLeft") {
      const next = names[(index + (e.key === "ArrowRight" ? 1 : names.length - 1)) % names.length];
      select(next);
      document.getElementById(`tab-${next}`).focus();
    }
  });
  select("paste");

  const form = h(
    "form",
    {
      onsubmit: async (e) => {
        e.preventDefault();
        errors.replaceChildren();
        const options = { method: "POST" };
        if (tab === "upload") {
          if (!file) return errors.append(errorBox("Choose a file first."));
          const body = new FormData();
          body.append("file", file);
          options.body = body;
        } else {
          if (!textarea.value.trim()) return errors.append(errorBox("Paste some data first, or load the sample."));
          options.headers = { "Content-Type": "application/json" };
          options.body = JSON.stringify({ text: textarea.value });
        }
        submit.disabled = true;
        status.textContent = "Checking your data…";
        try {
          const upload = await api("/uploads", options);
          sessionStorage.setItem(`aq.upload.${upload.upload_id}`, JSON.stringify(upload));
          location.hash = `#/review/${upload.upload_id}`;
        } catch (err) {
          errors.append(errorBox(err.message, err.code));
          errors.firstChild.focus?.();
        } finally {
          submit.disabled = false;
          status.textContent = "";
        }
      },
    },
    tablist,
    panels.paste,
    panels.upload,
    panels.sample,
    errors,
    h("div", { class: "actions" }, submit),
    status,
    h("p", { class: "muted small" }, "Next you check how the data was understood. Who the brief is for comes after that."),
  );

  const recent = h("section", { "aria-labelledby": "recent-h" }, h("h2", { id: "recent-h" }, "Recent briefs"), h("p", { class: "muted" }, "Loading…"));
  show(
    "Home",
    h("h1", {}, "Turn air-quality data into a briefing you can act on"),
    h("p", { class: "lede" }, "Add readings from your stations. Numbers are calculated by code; the AI only writes the explanation, and every sentence is checked against the calculated facts. Every claim links back to your data."),
    h("section", { class: "card", "aria-labelledby": "add-h" }, h("h2", { id: "add-h" }, "Add your data"), form),
    recent,
  );
  loadRecent(recent);
}

async function loadRecent(section) {
  try {
    const items = await api("/briefs");
    section.replaceChildren(h("h2", { id: "recent-h" }, "Recent briefs"));
    if (!items.length) {
      section.append(h("p", { class: "muted" }, "No briefs yet in this browser. Briefs you create appear here."));
      return;
    }
    const list = h("ul", { class: "plain" });
    items.forEach((item, index) => {
      const older = items[index + 1];
      list.append(
        h(
          "li",
          {},
          h("div", {}, h("b", {}, item.label)),
          h("div", {}, item.status_line || "Not finished (processing or failed)"),
          h("div", { class: "chips" }, item.worst_category ? categoryBadge(item.worst_category) : null, item.unreliable_count ? h("span", { class: "badge g-unreliable" }, `${item.unreliable_count} unreliable`) : null),
          h("div", { class: "chips" }, h("a", { class: "btn secondary", href: `#/brief/${item.id}` }, "Open"), older ? h("a", { class: "btn secondary", href: `#/brief/${item.id}?against=${older.id}` }, "Compare with previous") : null),
        ),
      );
    });
    section.append(list);
  } catch (err) {
    section.replaceChildren(h("h2", { id: "recent-h" }, "Recent briefs"), errorBox(`Could not load recent briefs. ${err.message}`));
  }
}

// ---------- review ----------

async function reviewView(uploadId) {
  const raw = sessionStorage.getItem(`aq.upload.${uploadId}`);
  if (!raw) {
    return show("Upload not found", h("h1", {}, "This upload is no longer in this tab"), h("p", {}, "Add your data again to continue."), h("a", { class: "btn", href: "#/" }, "Back to home"));
  }
  const upload = JSON.parse(raw);
  const stats = upload.stats;
  const errors = h("div");
  const status = h("p", { role: "status", class: "muted" });

  const choices = {};
  const assumptionNodes = upload.assumptions.map((a) => {
    if (!a.alternative_label) {
      return h("li", {}, a.description);
    }
    const name = `as-${a.id}`;
    const confirmValue = "confirm";
    choices[a.id] = () => {
      const picked = main.querySelector(`input[name="${CSS.escape(name)}"]:checked`);
      const confirmed = picked && picked.value === confirmValue;
      if (confirmed) return "confirmed";
      return a.default_applied ? "overridden" : "proposed";
    };
    const confirmedByDefault = a.default_applied;
    return h(
      "li",
      {},
      h("fieldset", {},
        h("legend", {}, a.description),
        h("label", { class: "choice" }, h("input", { type: "radio", name, value: confirmValue, checked: confirmedByDefault }), a.confirm_label),
        h("label", { class: "choice" }, h("input", { type: "radio", name, value: "alternative", checked: !confirmedByDefault }), a.alternative_label),
      ),
    );
  });

  const personaRadios = Object.entries(PERSONAS).map(([value, label], i) =>
    h("label", { class: "choice" }, h("input", { type: "radio", name: "persona", value, checked: i === 0 }), label),
  );
  const context = h("input", { type: "text", id: "context", maxlength: "1000", "aria-describedby": "context-help" });
  const previous = h("select", { id: "previous" }, h("option", { value: "" }, "No comparison"));
  api("/briefs").then((items) => items.filter((i) => i.status_line).forEach((i) => previous.append(h("option", { value: i.id }, `${i.label}: ${i.status_line}`)))).catch(() => {});
  const create = h("button", { type: "submit" }, "Looks right, create brief");

  const form = h(
    "form",
    {
      onsubmit: async (e) => {
        e.preventDefault();
        errors.replaceChildren();
        const persona = main.querySelector('input[name="persona"]:checked').value;
        const body = {
          upload_id: uploadId,
          persona,
          context: context.value.trim() || null,
          assumptions: Object.entries(choices).map(([id, read]) => ({ id, status: read() })),
          previous_brief_id: previous.value || null,
        };
        create.disabled = true;
        status.textContent = "Starting your brief…";
        try {
          const accepted = await api("/briefs", { method: "POST", headers: { "Content-Type": "application/json" }, body: JSON.stringify(body) });
          location.hash = `#/brief/${accepted.brief_id}`;
        } catch (err) {
          errors.append(errorBox(err.message, err.code));
        } finally {
          create.disabled = false;
          status.textContent = "";
        }
      },
    },
    h("fieldset", {}, h("legend", {}, "Who is this brief for?"), personaRadios),
    h("label", { for: "context" }, "Area or notes this data covers (optional)"),
    h("p", { id: "context-help", class: "muted small" }, "Shown to the AI as background only. Up to 1000 characters."),
    context,
    h("label", { for: "previous" }, "Compare with an earlier brief (optional)"),
    previous,
    errors,
    h("div", { class: "actions" }, create, h("a", { class: "btn secondary", href: "#/" }, "Back and edit data")),
    status,
  );

  const flags = upload.early_flags;
  show(
    "Check understanding",
    h("h1", {}, "Here is how I understood your data"),
    h("p", { class: "lede" }, "Nothing has been summarised yet. Change anything that looks wrong."),
    upload.warnings.map((w) => h("p", { class: "note" }, w)),
    h("div", { class: "grid stats" },
      h("div", { class: "stat" }, "Rows", h("b", {}, stats.rows.toLocaleString())),
      h("div", { class: "stat" }, "Stations", h("b", {}, stats.stations.length)),
      h("div", { class: "stat" }, "Period (IST)", h("b", {}, `${when(stats.period_start)} to ${when(stats.period_end)}`)),
      h("div", { class: "stat" }, "Pollutants", h("b", {}, stats.pollutants.join(", ") || "none")),
    ),
    h("section", { class: "card", "aria-labelledby": "map-h" }, h("h2", { id: "map-h" }, "Column mapping"),
      table("How each column is read", ["Column", "Meaning", "Unit"], upload.mapping.map((m) => [m.column, m.meaning === "pollutant" ? `pollutant: ${m.pollutant}` : words(m.meaning), m.unit || (m.meaning === "pollutant" ? "not stated" : "")]))),
    h("section", { class: "card", "aria-labelledby": "as-h" }, h("h2", { id: "as-h" }, "Assumptions to confirm"), assumptionNodes.length ? h("ul", { class: "plain" }, assumptionNodes) : h("p", { class: "muted" }, "No assumptions needed.")),
    h("section", { class: "card", "aria-labelledby": "ef-h" }, h("h2", { id: "ef-h" }, "Early flags"),
      flags.length
        ? table("Problems found while cleaning", ["Kind", "Station", "Pollutant", "Severity", "What was found"], flags.map((f) => [words(f.kind), f.station_id, f.pollutant || "", f.severity, f.detail]))
        : h("p", { class: "muted" }, "No data-quality problems found.")),
    form,
  );
}

// ---------- brief ----------

function stepList(index) {
  return h("ol", { class: "steps" }, STEPS.map((label, i) => h("li", { "data-state": i < index ? "done" : i === index ? "active" : "todo" }, h("span", { "aria-hidden": "true" }, i < index ? "✔" : i === index ? "…" : "○"), label, i < index ? h("span", { class: "sr-only" }, " (done)") : i === index ? h("span", { class: "sr-only" }, " (in progress)") : null)));
}

function processingView(stage) {
  const index = Math.max(0, STAGES.indexOf(stage));
  const holder = h("div");
  holder.append(h("progress", { max: String(STEPS.length), value: String(index), "aria-label": "Brief progress" }), stepList(index));
  show("Building your brief", h("h1", {}, "Building your brief"), h("p", { class: "lede" }, "Usually under a minute. You can leave this page; the brief appears in Recent briefs."), h("p", { class: "muted" }, "Numbers are calculated by code. The AI only writes the explanation, and every sentence is checked against the calculated facts."), holder);
  announce(`Step ${index + 1} of ${STEPS.length}: ${STEPS[index]}`);
}

async function briefView(id, against) {
  const token = ++routeToken;
  let lastStage = null;
  while (token === routeToken) {
    let state;
    try {
      state = await api(`/briefs/${id}`);
    } catch (err) {
      return show("Brief not found", h("h1", {}, "Could not open this brief"), errorBox(err.message, err.code), h("a", { class: "btn", href: "#/" }, "Back to home"));
    }
    if (token !== routeToken) return;
    if (state.status === "processing") {
      if (state.stage !== lastStage) {
        lastStage = state.stage;
        processingView(state.stage);
      }
      await sleep(1500);
      continue;
    }
    if (state.status === "failed") {
      return show("Brief failed", h("h1", {}, "No brief was produced"), errorBox(state.error.message, state.error.code), h("p", { class: "muted" }, "Your data was not changed. Nothing was made up to fill the gap."), h("a", { class: "btn", href: "#/" }, "Back to home"));
    }
    return renderBrief(state.brief, against);
  }
}

function unsureAbout(brief) {
  const items = [];
  const summary = brief.summary;
  if (summary && summary.unreliable_count) items.push(`${summary.unreliable_count} station${summary.unreliable_count === 1 ? "" : "s"} graded unreliable`);
  for (const a of brief.assumptions) {
    if (a.kind === "unit_conversion" && a.status !== "confirmed") items.push(`${a.proposed.pollutant} left out: its units differ and no conversion was approved`);
    else if (a.alternative_label && a.default_applied && a.status !== "overridden") items.push(a.description.replace(/\.$/, ""));
    else if (a.kind === "unit_conversion") items.push(`${a.proposed.pollutant} converted from ${a.proposed.from_unit} (approved by you)`);
  }
  if (brief.coordinates_source === "none") items.push("the map is off: no coordinates in the data");
  return items.concat(brief.notes);
}

function claimsSection(brief) {
  const checked = brief.claims.filter((c) => c.status === "verified").length;
  const list = brief.claims.map((c) =>
    h("div", { class: "claim" },
      h("div", { class: c.status === "verified" ? "verdict ok" : "verdict bad" }, c.status === "verified" ? "✔ Checked against the data" : "⚠ Not verified"),
      h("p", {}, c.text),
      h("div", { class: "chips" }, "Evidence:", c.fact_ids.map((fid) => h("button", { type: "button", class: "secondary fact-chip", onclick: () => openEvidence(brief.id, fid), "aria-label": `Show evidence ${fid}` }, fid))),
      c.notes.length ? h("ul", { class: "small" }, c.notes.map((n) => h("li", {}, n))) : null,
    ),
  );
  return section("What happened", true, h("p", { class: "muted small" }, `${checked} of ${brief.claims.length} sentences checked against the calculated facts. Unverified sentences are shown and marked, never hidden.`), list.length ? list : h("p", { class: "muted" }, "The AI returned no claims."));
}

const TIER = { now: "Do now", escalate: "Escalate", context: "Good to know" };
const EFFECT = { exposure: "Protects people", source: "Reduces pollution", evidence: "Improves the data" };

function actionsSection(brief) {
  if (!brief.actions.length) {
    return section("What to do", true, h("p", { class: "muted" }, "No actions passed the checks for this brief, so none are shown."));
  }
  return section(
    "What to do",
    true,
    h("p", { class: "muted small" }, `Actions for: ${PERSONAS[brief.persona] || brief.persona}. Each one cites the facts it relies on; actions resting on unreliable data are turned into data checks.`),
    brief.actions.map((a) =>
      h("div", { class: "claim" },
        h("div", { class: "chips" }, h("span", { class: "badge c-na" }, TIER[a.tier] || a.tier), h("span", { class: "badge c-na" }, EFFECT[a.effect_type] || a.effect_type), h("span", { class: "small muted" }, words(a.horizon))),
        h("p", {}, h("b", {}, a.text)),
        a.gated_reason ? h("p", { class: "note" }, `⚠ ${a.gated_reason}`) : null,
        h("ol", { class: "small" }, a.steps.map((step) => h("li", {}, step))),
        h("p", { class: "small" }, `Owner: ${a.owner}${a.escalate_to ? ` · Escalate to: ${a.escalate_to}` : ""} · Success looks like: ${a.success_signal}`),
        h("div", { class: "chips" }, "Evidence:", a.fact_ids.map((fid) => h("button", { type: "button", class: "secondary fact-chip", onclick: () => openEvidence(brief.id, fid), "aria-label": `Show evidence ${fid}` }, fid))),
      ),
    ),
  );
}

const LANGUAGES = { en: "English", hi: "हिन्दी (Hindi)", kn: "ಕನ್ನಡ (Kannada)", mr: "मराठी (Marathi)", bn: "বাংলা (Bengali)", ml: "മലയാളം (Malayalam)" };

function advisorySection(brief) {
  const fmt = h("select", { id: "adv-format" }, h("option", { value: "citizen" }, "Citizen advisory"), h("option", { value: "note" }, "Internal briefing note"));
  const lang = h("select", { id: "adv-lang" }, Object.entries(LANGUAGES).map(([code, name]) => h("option", { value: code }, name)));
  const level = h("select", { id: "adv-level" }, h("option", { value: "simple" }, "Simple"), h("option", { value: "standard" }, "Standard"));
  const out = h("div", { "aria-live": "polite" });
  const go = h("button", { type: "submit" }, "Show");
  const form = h(
    "form",
    {
      class: "grid stats",
      onsubmit: async (e) => {
        e.preventDefault();
        go.disabled = true;
        out.replaceChildren(h("p", { class: "muted" }, "Preparing…"));
        try {
          const params = new URLSearchParams({ format: fmt.value, language: lang.value, level: level.value });
          const doc = await api(`/briefs/${brief.id}/render?${params}`);
          out.replaceChildren(renderDocument(doc));
        } catch (err) {
          out.replaceChildren(errorBox(err.message, err.code));
        } finally {
          go.disabled = false;
        }
      },
    },
    h("div", {}, h("label", { for: "adv-format" }, "Document"), fmt),
    h("div", {}, h("label", { for: "adv-lang" }, "Language"), lang),
    h("div", {}, h("label", { for: "adv-level" }, "Reading level"), level),
    h("div", { class: "actions" }, go),
  );
  return section("Advisory and briefing note", false, h("p", { class: "muted small" }, "The internal note is assembled only from verified findings and actions. The citizen advisory is written by the AI and every section is checked; translations are machine-made and their numbers are checked."), form, out);
}

function renderDocument(doc) {
  const langCode = doc.language;
  return h(
    "article",
    { class: "card printable", lang: langCode },
    doc.sections.map((sec) =>
      h("section", { lang: sec.translated ? langCode : "en" },
        h("h3", {}, sec.title),
        h("p", {}, sec.text),
        !sec.verified ? h("p", { class: "note small", lang: "en" }, "⚠ This part could not be fully checked against the data.") : null,
        langCode !== "en" && !sec.translated ? h("p", { class: "small muted", lang: "en" }, "Shown in English: the translation could not keep the numbers exactly.") : null,
      ),
    ),
    h("p", { class: "small muted", lang: "en" }, doc.disclaimer),
    h("div", { class: "actions no-print" }, h("button", { type: "button", class: "secondary", onclick: () => window.print() }, "Print")),
  );
}

function section(title, open, ...nodes) {
  const details = h("details", { class: "section" }, h("summary", {}, title), h("div", { class: "body" }, nodes));
  if (open) details.open = true;
  return details;
}

function whereSection(brief) {
  const stations = brief.stations;
  let sortKey = "aqi";
  const body = h("div");
  const mapHolder = h("div");
  const locationStatus = h("div", { role: "status" });
  const tableHolder = h("div");

  function drawTable() {
    const sorted = [...stations].sort((a, b) => (sortKey === "name" ? a.name.localeCompare(b.name) : (b.aqi ?? -1) - (a.aqi ?? -1)));
    tableHolder.replaceChildren(
      h("div", { class: "chips" }, "Sort by:", h("button", { type: "button", class: "link", onclick: () => { sortKey = "aqi"; drawTable(); } }, "AQI, highest first"), h("button", { type: "button", class: "link", onclick: () => { sortKey = "name"; drawTable(); } }, "Name")),
      table("Stations, ranked from the data (the table is the full alternative to the map)", ["Station", "AQI category", "AQI", "Reliability", "Position"], sorted.map((s) => [h("span", {}, s.name, s.name !== s.station_id ? h("span", { class: "muted small" }, ` (${s.station_id})`) : null), categoryBadge(s.category), s.aqi == null ? "n/a" : num(s.aqi, 0), gradeBadge(s.reliability_grade), s.lat == null ? "no coordinates" : `${num(s.lat, 4)}, ${num(s.lon, 4)}`])),
    );
  }
  async function drawMap() {
    const located = stations.filter((s) => s.lat != null && s.lon != null);
    mapHolder.replaceChildren();
    if (!located.length) {
      mapHolder.append(h("p", { class: "note" }, "The map is off because this data has no coordinates. Coordinates are never guessed. The table above shows the same stations; add locations below to turn the map on."));
      return;
    }
    mapHolder.append(h("div", { id: "map", role: "region", "aria-label": "Map of stations. The table above has the same information." }));
    try {
      await loadLeaflet();
    } catch {
      mapHolder.replaceChildren(h("p", { class: "note" }, "The map library could not load. Use the table above."));
      return;
    }
    if (currentMap) currentMap.remove();
    const map = window.L.map("map");
    currentMap = map;
    window.L.tileLayer("https://tile.openstreetmap.org/{z}/{x}/{y}.png", { maxZoom: 18, attribution: "© OpenStreetMap contributors" }).addTo(map);
    const bounds = [];
    for (const s of located) {
      const [symbol, cls] = CATEGORY[s.category] || CATEGORY.insufficient_data;
      const pin = h("div", { class: `marker ${cls}` }, symbol);
      const icon = window.L.divIcon({ html: pin, className: "", iconSize: [32, 32] });
      const marker = window.L.marker([s.lat, s.lon], { icon, title: `${s.name}: ${s.category}`, alt: `${s.name}, ${s.category}` }).addTo(map);
      marker.bindPopup(h("div", {}, h("b", {}, s.name), h("div", {}, `${s.category}${s.aqi == null ? "" : `, AQI ${num(s.aqi, 0)}`}`), h("div", {}, `${s.reliability_grade} reliability`)));
      bounds.push([s.lat, s.lon]);
    }
    map.fitBounds(bounds, { padding: [30, 30], maxZoom: 14 });
  }

  const textarea = h("textarea", { id: "locations", rows: "4", spellcheck: "false", "aria-describedby": "loc-help" });
  const form = h(
    "form",
    {
      onsubmit: async (e) => {
        e.preventDefault();
        locationStatus.replaceChildren();
        try {
          const result = await api(`/briefs/${brief.id}/locations`, { method: "POST", headers: { "Content-Type": "application/json" }, body: JSON.stringify({ text: textarea.value }) });
          brief.stations = result.stations;
          brief.coordinates_source = result.coordinates_source;
          stations.splice(0, stations.length, ...result.stations);
          drawTable();
          await drawMap();
          locationStatus.append(h("p", {}, `${result.matched.length} row${result.matched.length === 1 ? "" : "s"} matched.`), result.unmatched.length ? h("ul", {}, result.unmatched.map((u) => h("li", {}, `Row ${u.row} (${u.file_station}): ${u.reason}`))) : null);
          announce("Locations updated.");
        } catch (err) {
          locationStatus.append(errorBox(err.message, err.code));
        }
      },
    },
    h("h3", {}, "Add or correct locations"),
    h("label", { for: "locations" }, "Paste station locations"),
    h("p", { id: "loc-help", class: "muted small" }, "CSV with the columns station_id,lat,lon. Only the map changes; nothing is re-analysed."),
    textarea,
    h("div", { class: "actions" }, h("button", { type: "submit", class: "secondary" }, "Update map")),
    locationStatus,
  );
  body.append(tableHolder, mapHolder, form);
  drawTable();
  drawMap();
  return section("Where", true, body);
}

async function changedSection(brief, againstId) {
  const body = h("div", {}, h("p", { class: "muted" }, "Loading comparison…"));
  const box = section("What changed", true, body);
  try {
    const diff = await api(`/briefs/${brief.id}/diff?against=${encodeURIComponent(againstId)}`);
    const label = (key) => {
      const [kind, station, pollutant] = key.split("|");
      return `${station || "All stations"} ${pollutant || words(kind)}`.trim();
    };
    const change = (c) => h("li", {}, `${label(c.key)}: ${num(c.before)} → ${num(c.after)}${c.delta_pct == null ? "" : ` (${c.delta_pct > 0 ? "+" : ""}${c.delta_pct}%)`}`);
    const s = diff.summary_inputs;
    body.replaceChildren(
      h("p", {}, `${s.genuine_changes} real change${s.genuine_changes === 1 ? "" : "s"}, ${s.coverage_explained_changes} that only look${s.coverage_explained_changes === 1 ? "s" : ""} changed, ${s.new_flags} new flag${s.new_flags === 1 ? "" : "s"}, ${s.resolved_flags} resolved.`),
      diff.changed.length ? h("div", {}, h("h3", {}, "Real changes"), h("ul", {}, diff.changed.map(change))) : null,
      diff.explained_by_coverage.length ? h("div", {}, h("h3", {}, "Only looks changed"), h("p", { class: "muted small" }, "Coverage or reliability differs between the two briefs, so these are data gaps, not a real trend."), h("ul", {}, diff.explained_by_coverage.map(change))) : null,
      diff.new_flags.length ? h("div", {}, h("h3", {}, "New data-quality flags"), h("ul", {}, diff.new_flags.map((f) => h("li", {}, `${words(f.kind)} at ${f.station_id}${f.pollutant ? ` (${f.pollutant})` : ""}`)))) : null,
      diff.resolved_flags.length ? h("div", {}, h("h3", {}, "Resolved flags"), h("ul", {}, diff.resolved_flags.map((f) => h("li", {}, `${words(f.kind)} at ${f.station_id}${f.pollutant ? ` (${f.pollutant})` : ""}`)))) : null,
    );
  } catch (err) {
    body.replaceChildren(errorBox(`Could not compare: ${err.message}`, err.code));
  }
  return box;
}

function qualitySection(brief) {
  const flags = brief.flags.filter((f) => f.kind !== "no_coords");
  return section(
    "Data quality",
    false,
    h("h3", {}, "Station reliability"),
    brief.reliability.length ? table("Reliability by station", ["Station", "Grade", "Score", "Coverage", "Why"], brief.reliability.map((r) => [r.station_id, gradeBadge(r.grade), num(r.score), `${num(r.coverage_pct)}%`, r.reasons.join(" ")])) : h("p", { class: "muted" }, "No station had usable data."),
    h("h3", {}, "Flags"),
    flags.length ? table("Problems found in the data", ["Id", "Kind", "Station", "Pollutant", "Severity", "What was found"], flags.map((f) => [f.id, words(f.kind), f.station_id, f.pollutant || "", f.severity, f.detail])) : h("p", { class: "muted" }, "No data-quality problems detected."),
    h("h3", {}, "What was changed while cleaning"),
    Object.keys(brief.ledger_summary).length ? h("ul", {}, Object.entries(brief.ledger_summary).map(([rule, n]) => h("li", {}, `${words(rule)}: ${n}`))) : h("p", { class: "muted" }, "Nothing was changed."),
    brief.ledger.length ? h("details", {}, h("summary", {}, `Show the first ${brief.ledger.length} cleaning entries`), table("Cleaning ledger", ["Row", "Rule", "Before", "After", "Reason"], brief.ledger.map((e) => [e.row_ref, words(e.rule), e.before ?? "", e.after ?? "", e.reason]))) : null,
    h("h3", {}, "Assumptions"),
    brief.assumptions.length ? h("ul", {}, brief.assumptions.map((a) => h("li", {}, `${a.description} (${a.status})`))) : h("p", { class: "muted" }, "None."),
  );
}

function renderBrief(brief, against) {
  const stations = brief.stations;
  const counts = {};
  stations.forEach((s) => (counts[s.category] = (counts[s.category] || 0) + 1));
  const unsure = unsureAbout(brief);
  const where = whereSection(brief);
  const compareId = against || brief.previous_id;
  show(
    "Brief",
    h("h1", {}, brief.summary ? brief.summary.status_line : "Air quality brief"),
    h("p", { class: "muted" }, `${PERSONAS[brief.persona] || brief.persona} · created ${when(brief.created_at)}${brief.context ? ` · ${brief.context}` : ""}`),
    h("div", { class: "chips" }, Object.entries(counts).map(([category, n]) => h("span", {}, categoryBadge(category), ` ${n}`))),
    unsure.length ? h("p", { class: "note" }, h("b", {}, "Unsure about: "), unsure.join("; "), ".") : null,
    claimsSection(brief),
    actionsSection(brief),
    advisorySection(brief),
    where,
    qualitySection(brief),
    h("div", { class: "actions" }, h("a", { class: "btn secondary", href: "#/" }, "Add more data")),
  );
  if (compareId) changedSection(brief, compareId).then((node) => where.after(node));
}

// ---------- evidence panel ----------

function factTitle(fact) {
  const who = fact.station_id ? `${fact.station_id} · ` : "";
  const kinds = {
    pollutant_mean: `${fact.values.pollutant} mean`,
    aqi_latest: "latest AQI",
    aqi_worst: "worst-day AQI",
    aqi_insufficient: "AQI (not enough data)",
    pm_ratio: "PM2.5/PM10 ratio",
    hotspot: "hotspot ranking",
    station_reliability: "station reliability",
    quality_flag: `data-quality flag: ${words(fact.values.kind || "")}`,
  };
  return who + (kinds[fact.kind] || words(fact.kind));
}

async function openEvidence(briefId, factId) {
  dialog.replaceChildren(h("h2", { id: "evidence-title" }, `Evidence ${factId}`), h("p", { class: "muted" }, "Loading…"));
  dialog.showModal();
  try {
    const ev = await api(`/briefs/${briefId}/evidence/${encodeURIComponent(factId)}`);
    const fact = ev.fact;
    dialog.replaceChildren(
      h("h2", { id: "evidence-title" }, `${fact.id}: ${factTitle(fact)}`),
      h("div", { class: "chips" }, gradeBadge(fact.reliability_grade), h("span", { class: "badge c-na" }, `coverage ${num(fact.coverage_pct)}%`)),
      h("p", { class: "muted small" }, `Period ${fact.period || "n/a"}. Calculated by code from the rows below.`),
      h("h3", {}, "Values"),
      h("dl", { class: "facts" }, Object.entries(fact.values).flatMap(([k, v]) => [h("dt", {}, words(k)), h("dd", {}, v == null ? "n/a" : String(v))])),
      ev.reliability ? h("p", { class: "small" }, `Station reliability: ${ev.reliability.grade}, score ${num(ev.reliability.score)}.`) : null,
      ev.rows.length ? h("div", {}, h("h3", {}, "Source rows"), ...ev.rows.map((r) => h("div", {}, h("p", { class: "small" }, h("b", {}, r.row_ref)), h("dl", { class: "facts" }, Object.entries(r.values).flatMap(([k, v]) => [h("dt", {}, k), h("dd", {}, v)]))))) : null,
      ev.flags.length ? h("div", {}, h("h3", {}, "Related data-quality flags"), h("ul", {}, ev.flags.map((f) => h("li", {}, `${f.id}: ${f.detail}`)))) : null,
      h("div", { class: "actions" }, h("button", { type: "button", onclick: () => dialog.close() }, "Close")),
    );
  } catch (err) {
    dialog.replaceChildren(h("h2", { id: "evidence-title" }, `Evidence ${factId}`), errorBox(err.message, err.code), h("button", { type: "button", onclick: () => dialog.close() }, "Close"));
  }
}

// ---------- map library (loaded only when needed, integrity-checked) ----------

function loadLeaflet() {
  if (window.L) return Promise.resolve();
  return new Promise((resolve, reject) => {
    const css = h("link", { rel: "stylesheet", href: `${LEAFLET}leaflet.min.css`, integrity: LEAFLET_SRI["leaflet.min.css"], crossorigin: "anonymous" });
    const script = h("script", { src: `${LEAFLET}leaflet.min.js`, integrity: LEAFLET_SRI["leaflet.min.js"], crossorigin: "anonymous" });
    script.onload = resolve;
    script.onerror = reject;
    document.head.append(css, script);
  });
}

// ---------- router ----------

function route() {
  routeToken += 1;
  if (dialog.open) dialog.close();
  const [path, query = ""] = location.hash.replace(/^#/, "").split("?");
  const parts = path.split("/").filter(Boolean);
  const params = new URLSearchParams(query);
  if (parts[0] === "review" && parts[1]) return reviewView(parts[1]);
  if (parts[0] === "brief" && parts[1]) return briefView(parts[1], params.get("against"));
  return homeView();
}

dialog.addEventListener("click", (e) => {
  if (e.target === dialog) dialog.close();
});
window.addEventListener("hashchange", route);
route();
