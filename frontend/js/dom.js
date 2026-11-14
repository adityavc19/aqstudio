// Shared DOM and API helpers. All DOM is built from text nodes, never from HTML strings,
// so data from uploads cannot inject markup.

export const main = document.getElementById("main");
const live = document.getElementById("live");

export const PERSONAS = {
  ward_officer: "Ward officer",
  housing_society: "Housing society",
  school: "School",
  citizen: "Citizen",
  other: "Someone else",
};
export const CATEGORY = {
  Good: ["●", "c-good"],
  Satisfactory: ["◐", "c-sat"],
  Moderate: ["▲", "c-mod"],
  Poor: ["◆", "c-poor"],
  "Very Poor": ["■", "c-vpoor"],
  Severe: ["✖", "c-sev"],
  insufficient_data: ["?", "c-na"],
};
export const CATEGORY_ORDER = ["Good", "Satisfactory", "Moderate", "Poor", "Very Poor", "Severe", "insufficient_data"];
const GRADE_SYMBOL = { good: "✔", fair: "◐", poor: "▲", unreliable: "✖" };

export function h(tag, attrs = {}, ...kids) {
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

export class ApiFail extends Error {
  constructor(status, code, message) {
    super(message);
    this.status = status;
    this.code = code;
  }
}

export async function api(path, options = {}) {
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

export const postJson = (path, body) =>
  api(path, { method: "POST", headers: { "Content-Type": "application/json" }, body: JSON.stringify(body) });
export const sleep = (ms) => new Promise((resolve) => setTimeout(resolve, ms));
export const words = (text) => String(text).replaceAll("_", " ");
export const num = (value, digits = 1) => (value == null ? "n/a" : Number(value).toFixed(digits).replace(/\.0+$/, ""));
export const plural = (n, word) => `${n} ${word}${n === 1 ? "" : "s"}`;

export function announce(message) {
  live.textContent = "";
  setTimeout(() => (live.textContent = message), 50);
}

export function when(iso) {
  if (!iso) return "unknown";
  return `${new Date(iso).toLocaleString("en-IN", { timeZone: "Asia/Kolkata", day: "numeric", month: "short", hour: "2-digit", minute: "2-digit", hour12: false })} IST`;
}

export function periodLabel(period) {
  // "2026-11-13..2026-11-15" -> "13 Nov – 15 Nov 2026"
  const [a, b] = String(period).split("..");
  const fmt = (d, year) => new Date(`${d}T00:00:00`).toLocaleDateString("en-IN", { day: "numeric", month: "short", ...(year ? { year: "numeric" } : {}) });
  return b && b !== a ? `${fmt(a, false)} – ${fmt(b, true)}` : fmt(a, true);
}

export function categoryLabel(category) {
  return category === "insufficient_data" ? "Not enough data" : category;
}

export function categoryBadge(category, extra = "") {
  const [symbol, cls] = CATEGORY[category] || CATEGORY.insufficient_data;
  return h("span", { class: `badge ${cls} ${extra}` }, h("span", { "aria-hidden": "true" }, symbol), categoryLabel(category));
}

export function gradeBadge(grade) {
  return h("span", { class: `badge g-${grade}` }, h("span", { "aria-hidden": "true" }, GRADE_SYMBOL[grade] || "?"), `${grade} reliability`);
}

export function errorBox(message, code) {
  return h("div", { class: "alert", role: "alert" }, message, code ? h("span", { class: "small muted" }, ` (${code})`) : null);
}

export function table(caption, headers, rows) {
  return h(
    "div",
    { class: "table-wrap", tabindex: "0", role: "region", "aria-label": caption },
    h("table", {}, h("caption", {}, caption), h("thead", {}, h("tr", {}, headers.map((t) => h("th", { scope: "col" }, t)))), h("tbody", {}, rows.map((r) => h("tr", {}, r.map((c) => h("td", {}, c)))))),
  );
}

export function section(id, title, open, ...nodes) {
  const details = h("details", { class: "section", id }, h("summary", {}, h("h2", {}, title)), h("div", { class: "body" }, nodes));
  if (open) details.open = true;
  return details;
}

export function radioTabs(label, options, onSelect) {
  // Accessible tablist: arrow keys move between tabs, only the selected tab is in tab order.
  const keys = Object.keys(options);
  const buttons = keys.map((key) => h("button", { type: "button", role: "tab", "data-key": key, onclick: () => select(key) }, options[key]));
  const list = h("div", { class: "tabs", role: "tablist", "aria-label": label }, buttons);
  function select(key) {
    buttons.forEach((b) => {
      const on = b.dataset.key === key;
      b.setAttribute("aria-selected", String(on));
      b.tabIndex = on ? 0 : -1;
    });
    onSelect(key);
  }
  list.addEventListener("keydown", (e) => {
    if (e.key !== "ArrowRight" && e.key !== "ArrowLeft") return;
    const current = keys.indexOf(buttons.find((b) => b.getAttribute("aria-selected") === "true").dataset.key);
    const next = keys[(current + (e.key === "ArrowRight" ? 1 : keys.length - 1)) % keys.length];
    select(next);
    buttons[keys.indexOf(next)].focus();
  });
  return { list, select };
}

const leaveHooks = [];
export const onLeave = (fn) => leaveHooks.push(fn);

export function show(title, ...nodes) {
  while (leaveHooks.length) leaveHooks.pop()();
  document.title = `${title} | Air Quality Briefing Studio`;
  main.replaceChildren(...nodes);
  const heading = main.querySelector("h1");
  if (heading) {
    heading.setAttribute("tabindex", "-1");
    heading.focus();
  }
}
