// Shared helpers: DOM builder, API calls, time formatting, icons, setting controls.
// No build step and no dependencies. Everything user-visible is set with textContent,
// never innerHTML, so text from postings and resumes cannot inject markup.

export const S = { status: null, settings: null, warnings: {}, secrets: {}, settingsError: "" };

// ------------------------------------------------------------------ DOM

export function h(tag, attrs, ...kids) {
  const el = document.createElement(tag);
  for (const [k, v] of Object.entries(attrs || {})) {
    if (v == null || v === false) continue;
    if (k === "class") el.className = v;
    else if (k === "for") el.htmlFor = v;
    else if (k.startsWith("on") && typeof v === "function") el.addEventListener(k.slice(2).toLowerCase(), v);
    else if (k === "value" || k === "checked" || k === "disabled" || k === "selected" || k === "readOnly") el[k] = v;
    else el.setAttribute(k, v === true ? "" : String(v));
  }
  append(el, kids);
  return el;
}

export function append(el, kids) {
  for (const k of kids.flat(Infinity)) {
    if (k == null || k === false) continue;
    el.append(k instanceof Node ? k : document.createTextNode(String(k)));
  }
  return el;
}

export const $ = (sel, root = document) => root.querySelector(sel);

const ICONS = {
  home: "M3 11l9-8 9 8M5 10v10h14V10",
  jobs: "M3 8h18v12H3zM9 8V5h6v3",
  apps: "M5 4h14v16H5zM9 9h6M9 13h6M9 17h3",
  answers: "M4 5h16v11H9l-5 4z",
  insights: "M5 20V11M12 20V4M19 20v-6",
  settings: "M4 7h10M18 7h2M4 17h2M10 17h10M14 4v6M6 14v6",
  activity: "M3 12h4l3-8 4 16 3-8h4",
  profile: "M12 12a4 4 0 100-8 4 4 0 000 8zM4 21c0-4 3.6-7 8-7s8 3 8 7",
  more: "M5 12h.01M12 12h.01M19 12h.01",
  upload: "M12 16V4M7 9l5-5 5 5M4 20h16",
  alert: "M12 9v4M12 17h.01M10.3 3.9L2.4 18a2 2 0 001.7 3h15.8a2 2 0 001.7-3L13.7 3.9a2 2 0 00-3.4 0z",
  check: "M5 12.5l4.5 4.5L19 7.5",
  x: "M6 6l12 12M18 6L6 18",
  external: "M14 4h6v6M20 4l-9 9M18 14v5H5V6h5",
  chevron: "M6 9l6 6 6-6",
  inbox: "M3 13l3-8h12l3 8v6H3zM3 13h5l1 3h6l1-3h5",
  plus: "M12 5v14M5 12h14",
  trash: "M4 7h16M10 11v6M14 11v6M6 7l1 13h10l1-13M9 7V4h6v3",
  search: "M11 18a7 7 0 100-14 7 7 0 000 14zM21 21l-5-5",
  lock: "M6 11h12v9H6zM8 11V8a4 4 0 018 0v3",
};

export function icon(name, size = 18) {
  const svg = document.createElementNS("http://www.w3.org/2000/svg", "svg");
  svg.setAttribute("viewBox", "0 0 24 24");
  svg.setAttribute("width", size);
  svg.setAttribute("height", size);
  svg.setAttribute("fill", "none");
  svg.setAttribute("stroke", "currentColor");
  svg.setAttribute("stroke-width", name === "more" ? "3" : "1.75");
  svg.setAttribute("stroke-linecap", "round");
  svg.setAttribute("stroke-linejoin", "round");
  svg.setAttribute("aria-hidden", "true");
  const p = document.createElementNS("http://www.w3.org/2000/svg", "path");
  p.setAttribute("d", ICONS[name] || ICONS.inbox);
  svg.append(p);
  return svg;
}

export function logoMark(size = 24) {
  const svg = document.createElementNS("http://www.w3.org/2000/svg", "svg");
  svg.setAttribute("viewBox", "0 0 24 24");
  svg.setAttribute("width", size);
  svg.setAttribute("height", size);
  svg.setAttribute("aria-hidden", "true");
  svg.innerHTML =
    '<rect width="24" height="24" rx="6" fill="currentColor"/>' +
    '<path d="M7 12.5l3.2 3.2L17 8.8" fill="none" stroke="#fff" stroke-width="2.4" stroke-linecap="round" stroke-linejoin="round"/>';
  return svg;
}

// ------------------------------------------------------------------ messages

export function toast(message, opts = {}) {
  const box = document.getElementById("toasts");
  if (!box) return;
  const t = h("div", { class: "toast" + (opts.error ? " error" : "") }, h("span", null, message));
  if (opts.href) t.append(h("a", { href: opts.href }, opts.link || "View"));
  box.append(t);
  setTimeout(() => t.remove(), opts.error ? 7000 : 4500);
}

export function notice(text, kind = "") {
  return h("div", { class: "notice " + kind, role: kind === "error" ? "alert" : null }, icon("alert", 16), h("div", null, text));
}

export function empty(iconName, title, text, ...actions) {
  return h(
    "div",
    { class: "empty" },
    icon(iconName, 36),
    h("h2", null, title),
    h("p", null, text),
    actions.length ? h("div", { class: "row wrap" }, actions) : null,
  );
}

export function skeletons(n = 3) {
  return h("div", { class: "stack tight", "aria-hidden": "true" }, Array.from({ length: n }, () => h("div", { class: "skeleton" })));
}

// ------------------------------------------------------------------ API

function errorText(data, status) {
  if (status === 404) return "This part isn't available yet.";
  if (status === 0) return "Can't reach the app. Is it still running?";
  if (data && typeof data === "object" && data.detail) {
    const d = data.detail;
    if (typeof d === "string") return d;
    if (Array.isArray(d)) return d.map((x) => x.msg || String(x)).join(" ");
  }
  if (typeof data === "string" && data.trim() && data.length < 300) return data;
  return "Something went wrong. Try again.";
}

export async function api(method, path, body) {
  try {
    const init = { method, headers: {} };
    if (body instanceof FormData) init.body = body;
    else if (body !== undefined) {
      init.headers["Content-Type"] = "application/json";
      init.body = JSON.stringify(body);
    }
    const res = await fetch("/api" + path, init);
    const type = res.headers.get("content-type") || "";
    let data = null;
    try {
      data = type.includes("json") ? await res.json() : await res.text();
    } catch (e) {
      data = null;
    }
    return { ok: res.ok, status: res.status, data, error: res.ok ? "" : errorText(data, res.status) };
  } catch (e) {
    return { ok: false, status: 0, data: null, error: errorText(null, 0) };
  }
}

// Package routes may return a bare list or an object wrapping one.
export function listOf(data, ...keys) {
  if (Array.isArray(data)) return data;
  if (data && typeof data === "object") {
    for (const k of [...keys, "items", "postings", "rows", "applications", "answers", "experience", "results", "data"]) {
      if (Array.isArray(data[k])) return data[k];
    }
  }
  return [];
}

export function runningKinds(status) {
  const r = status && status.running;
  if (!r) return [];
  if (Array.isArray(r)) return r.map((x) => (typeof x === "string" ? x : x.kind || x.id || "job"));
  if (typeof r === "object") return Object.keys(r);
  return ["job"];
}

// ------------------------------------------------------------------ settings state

export async function loadSettings(force = false) {
  if (S.settings && !force) return S.settings;
  const r = await api("GET", "/settings");
  if (r.ok && r.data && r.data.settings) {
    S.settings = r.data.settings;
    S.warnings = r.data.warnings || {};
    S.settingsError = "";
  } else {
    S.settingsError = r.error || "Could not load settings.";
  }
  return S.settings;
}

let saveTimer = null;
let saveListeners = [];
export function onSaved(fn) { saveListeners.push(fn); return () => { saveListeners = saveListeners.filter((f) => f !== fn); }; }

export async function saveSettingsNow() {
  clearTimeout(saveTimer);
  const r = await api("PUT", "/settings", S.settings);
  if (r.ok && r.data && r.data.settings) {
    S.settings = r.data.settings;
    if (r.data.warnings) S.warnings = r.data.warnings;
  } else {
    toast("Settings were not saved. " + r.error, { error: true });
  }
  saveListeners.forEach((f) => f(r.ok));
  return r.ok;
}

export function scheduleSave(delay = 500) {
  clearTimeout(saveTimer);
  saveTimer = setTimeout(saveSettingsNow, delay);
}

export function deepGet(obj, path, fallback) {
  let cur = obj;
  for (const p of Array.isArray(path) ? path : String(path).split(".")) {
    if (cur == null || typeof cur !== "object" || !(p in cur)) return fallback;
    cur = cur[p];
  }
  return cur == null ? fallback : cur;
}

export function deepSet(obj, path, value) {
  const parts = Array.isArray(path) ? path : String(path).split(".");
  let cur = obj;
  for (let i = 0; i < parts.length - 1; i++) {
    if (cur[parts[i]] == null || typeof cur[parts[i]] !== "object") cur[parts[i]] = {};
    cur = cur[parts[i]];
  }
  cur[parts[parts.length - 1]] = value;
}

// ------------------------------------------------------------------ time

export function parseTime(s) {
  if (!s) return null;
  let t = String(s).trim().replace(" ", "T");
  if (t.includes("T") && !/(Z|[+-]\d\d:?\d\d)$/i.test(t)) t += "Z";
  const d = new Date(t);
  return isNaN(d) ? null : d;
}

export function ago(s) {
  const d = parseTime(s);
  if (!d) return "";
  const mins = Math.max(0, Math.round((Date.now() - d.getTime()) / 60000));
  if (mins < 1) return "just now";
  if (mins < 60) return `${mins} min ago`;
  const hrs = Math.round(mins / 60);
  if (hrs < 48) return `${hrs} h ago`;
  const days = Math.round(hrs / 24);
  if (days < 60) return `${days} d ago`;
  return `${Math.round(days / 30)} mo ago`;
}

export function hoursSince(s) {
  const d = parseTime(s);
  return d ? (Date.now() - d.getTime()) / 3600000 : null;
}

export function fmtDate(s) {
  const d = parseTime(s);
  if (!d) return String(s || "");
  const dateOnly = /^\d{4}-\d{2}-\d{2}$/.test(String(s).trim());
  return d.toLocaleDateString(undefined, { month: "short", day: "numeric", ...(dateOnly ? { timeZone: "UTC" } : {}) });
}

// Returns {text, soon} or null.
export function deadlineInfo(s) {
  if (!s) return null;
  const d = parseTime(String(s).length === 10 ? s + "T23:59:59" : s);
  if (!d) return null;
  const days = Math.ceil((d.getTime() - Date.now()) / 86400000);
  if (days < 0) return { text: "Closed " + fmtDate(s), soon: false };
  if (days === 0) return { text: "Closes today", soon: true };
  if (days === 1) return { text: "Closes tomorrow", soon: true };
  if (days <= 14) return { text: `Closes in ${days} days`, soon: true };
  return { text: "Closes " + fmtDate(s), soon: false };
}

export function fmtTerm(t) {
  const m = /^(\d{4})-(\d{2})$/.exec(t);
  if (!m) return t;
  const names = ["Jan", "Feb", "Mar", "Apr", "May", "Jun", "Jul", "Aug", "Sep", "Oct", "Nov", "Dec"];
  return `${names[Number(m[2]) - 1] || m[2]} ${m[1]}`;
}

export function upcomingTerms(n = 6) {
  const now = new Date();
  const cur = `${now.getFullYear()}-${String(now.getMonth() + 1).padStart(2, "0")}`;
  const out = [];
  for (let y = now.getFullYear(); out.length < n; y++) {
    for (const m of ["01", "05", "09"]) {
      const t = `${y}-${m}`;
      if (t >= cur && out.length < n) out.push(t);
    }
  }
  return out;
}

export function humanize(s) {
  const t = String(s).replace(/[_-]+/g, " ").trim();
  return t.charAt(0).toUpperCase() + t.slice(1);
}

export function debounce(fn, ms) {
  let t;
  return (...a) => { clearTimeout(t); t = setTimeout(() => fn(...a), ms); };
}

// ------------------------------------------------------------------ controls

let uid = 0;
export const nextId = (p = "f") => `${p}${++uid}`;

export function toggleControl({ value, onChange, label, id }) {
  const input = h("input", { type: "checkbox", role: "switch", id, checked: !!value, "aria-label": label });
  input.addEventListener("change", () => onChange(input.checked));
  return h("span", { class: "switch" }, input, h("span", { class: "track" }));
}

export function selectControl({ value, options, onChange, label, id }) {
  const sel = h("select", { id, "aria-label": label },
    options.map(([v, l]) => h("option", { value: v, selected: v === value }, l)));
  if (!options.some(([v]) => v === value)) sel.prepend(h("option", { value, selected: true }, String(value)));
  sel.addEventListener("change", () => onChange(sel.value));
  return sel;
}

export function inputControl({ value, type = "text", onChange, label, id, placeholder, list, min, step, parse }) {
  const input = h("input", { type, id, value: value ?? "", placeholder, "aria-label": label, list, min, step, autocomplete: type === "password" ? "new-password" : "off" });
  input.addEventListener("input", () => {
    if (type === "number") {
      const n = parse ? parse(input.value) : input.value === "" ? null : Number(input.value);
      onChange(Number.isNaN(n) ? null : n);
    } else onChange(input.value);
  });
  return input;
}

export function multiControl({ value, options, onChange, label }) {
  let list = [...(value || [])];
  const wrap = h("div", { class: "chips", role: "group", "aria-label": label });
  const draw = () => {
    wrap.replaceChildren(
      ...options.map(([v, l]) =>
        h("button", {
          type: "button", class: "pick", "aria-pressed": String(list.includes(v)),
          onclick: () => {
            list = list.includes(v) ? list.filter((x) => x !== v) : [...list, v];
            onChange(list);
            draw();
          },
        }, l)),
    );
  };
  draw();
  return wrap;
}

export function tagsControl({ value, onChange, label, suggest = [], norm, placeholder, display = (v) => v }) {
  let list = [...(value || [])];
  const normalize = norm || ((s) => s.trim());
  const wrap = h("div");
  let refocus = false;
  const draw = () => {
    wrap.replaceChildren();
    if (list.length) {
      wrap.append(h("div", { class: "chips" }, list.map((v) =>
        h("span", { class: "chip" }, display(v),
          h("button", { type: "button", "aria-label": `Remove ${display(v)}`, onclick: () => { list = list.filter((x) => x !== v); onChange(list); draw(); } }, icon("x", 12))))));
    }
    const rest = suggest.filter((s) => !list.includes(s));
    if (rest.length) {
      wrap.append(h("div", { class: "chips", style: "margin-top:8px" }, rest.map((s) =>
        h("button", { type: "button", class: "pick", "aria-pressed": "false", onclick: () => { list = [...list, s]; onChange(list); draw(); } }, "+ " + display(s)))));
    }
    const input = h("input", { type: "text", placeholder: placeholder || "Type and press Enter", "aria-label": `${label}: add another` });
    const add = () => {
      const parts = input.value.split(",").map(normalize).filter((x) => x && !list.includes(x));
      if (!parts.length) { input.value = ""; return; }
      list = [...list, ...parts];
      onChange(list);
      refocus = true;
      draw();
    };
    input.addEventListener("keydown", (e) => { if (e.key === "Enter") { e.preventDefault(); add(); } });
    wrap.append(h("div", { class: "chip-add" }, input, h("button", { type: "button", class: "btn small", onclick: add }, "Add")));
    if (refocus) { refocus = false; input.focus(); }
  };
  draw();
  return wrap;
}

// ------------------------------------------------------------------ setting definitions

export const OPTIONS = {
  remote: [["include", "Include remote roles"], ["only", "Remote roles only"], ["exclude", "On-site and hybrid only"]],
  levels: [["internship", "Internship"], ["co-op", "Co-op"], ["new-grad", "New grad"], ["entry", "Entry level"], ["mid", "Mid level"], ["senior", "Senior"]],
  fields: [
    ["software", "Software"], ["hardware", "Hardware"], ["data-ml", "Data and ML"], ["quant", "Quant"], ["product", "Product"],
    ["design", "Design"], ["it-security", "IT and security"], ["research", "Research"], ["mechanical", "Mechanical"],
    ["electrical", "Electrical"], ["civil", "Civil"], ["business", "Business"], ["finance", "Finance"],
    ["marketing", "Marketing"], ["sales", "Sales"], ["operations", "Operations"], ["other", "Other"],
  ],
  order: [["newest", "Newest first"], ["deadline", "Closing soonest"], ["company", "Company A to Z"], ["match", "Best match"]],
  mode: [["review", "Show me each one before it is sent"], ["auto", "Send without asking"]],
  tailoring: [["ideal", "Ideal per role group, adjusted to each job"], ["per-job", "Built fresh for every job"], ["as-is", "My own resume, sent as I made it"]],
  letters: [["never", "Never"], ["when-required", "Only when the job asks"], ["always", "Always"]],
  commitments: [["yes", "Say yes to relocation, start date, term and travel"], ["literal", "Answer exactly as my profile says"]],
  browser: [["auto", "Automatic (recommended)"], ["own-window", "The applyfirst Chrome window"], ["chrome-extension", "My own Chrome and its sign-ins"]],
};

const upper = (s) => s.trim().toUpperCase();

export const SETTING_DEFS = {
  "search.countries": { label: "Countries", help: "Where you would work, as two-letter codes like CA or US.", type: "tags", suggest: ["CA", "US", "GB", "DE", "FR", "NL", "IE", "AU", "SG", "IN"], norm: upper, placeholder: "CA" },
  "search.regions": { label: "States and provinces", help: "Narrow your countries to these. Leave empty for everywhere.", type: "tags", placeholder: "Ontario" },
  "search.cities": { label: "Cities", help: "Narrow further to these cities. Leave empty for any city.", type: "tags", placeholder: "Toronto" },
  "search.remote": { label: "Remote roles", help: "Whether to include jobs you could do from home.", type: "select", options: OPTIONS.remote },
  "search.levels": { label: "Career level", help: "The kinds of role you want to see.", type: "multi", options: OPTIONS.levels },
  "search.fields": { label: "Fields", help: "The kinds of work you are after.", type: "multi", options: OPTIONS.fields },
  "search.include_keywords": { label: "Words to look for", help: "Words a posting should mention.", type: "tags" },
  "search.exclude_keywords": { label: "Words to avoid", help: "Skip postings that mention any of these.", type: "tags" },
  "search.exclude_companies": { label: "Companies to skip", help: "You will never see postings from these.", type: "tags" },
  "search.start_terms": { label: "Start terms", help: "When you can start. Leave empty to see every term.", type: "tags", suggest: upcomingTerms(), display: fmtTerm, placeholder: "2027-05" },
  "search.min_term_months": { label: "Shortest term", help: "In months. 0 means no minimum.", type: "number", min: 0 },
  "search.max_posting_age_days": { label: "Newest postings only", help: "Ignore postings older than this many days.", type: "number", min: 1 },
  "search.skip_language_required": { label: "Languages you do not speak", help: "Skip postings that require one of these, for example French.", type: "tags" },

  "sources.company_boards": { label: "Company career pages", help: "Greenhouse, Lever, Ashby, Workday, SmartRecruiters and more. The fastest way to catch a posting the hour it goes up.", type: "toggle" },
  "sources.indeed": { label: "Indeed", help: "Also search Indeed.", type: "toggle" },
  "sources.glassdoor": { label: "Glassdoor", help: "Also search Glassdoor.", type: "toggle" },
  "sources.linkedin": { label: "LinkedIn", help: "Also search LinkedIn.", type: "toggle" },
  "sources.google_recent": { label: "Google, past day", help: "Jobs Google has found in the last day.", type: "toggle" },
  "sources.email_alerts": { label: "Job alert emails", help: "Read postings from alert emails in your inbox.", type: "toggle" },
  "sources.school_board.enabled": { label: "School job board", help: "Include your school's job board.", type: "toggle" },
  "sources.school_board.name": { label: "School job board name", help: "What to call it.", type: "text", showIf: "sources.school_board.enabled", placeholder: "Example University careers" },
  "sources.school_board.url": { label: "School job board link", help: "The address of the board.", type: "text", showIf: "sources.school_board.enabled", placeholder: "https://" },
  "sources.sweep_interval_hours": { group: "Schedule", label: "Search for new postings every", help: "In hours.", type: "number", min: 1, unit: "hours" },

  "queue.order_by": { label: "Order by", help: "How your job list is sorted first.", type: "select", options: OPTIONS.order },
  "queue.then_by": { label: "Then by", help: "How ties are broken.", type: "select", options: OPTIONS.order },
  "queue.daily_limit": { label: "Applications per day", help: "The most applications sent in one day.", type: "number", min: 1 },

  "apply.mode": { label: "When to send", help: "You can switch any time.", type: "select", options: OPTIONS.mode },
  "apply.review_first": { label: "Still show me the first", help: "In auto mode, this many applications are shown to you before they are sent.", type: "number", min: 0, showIf: ["apply.mode", "auto"] },
  "apply.resume_tailoring": { label: "Resume versions", help: "How your resume is made for each job. Every line still comes from your own confirmed experience.", type: "select", options: OPTIONS.tailoring,
    notes: {
      ideal: "Each role group you pick gets a resume built against what the strongest resumes in that field lead with, then nudged toward each job's wording. Good: every resume starts from a strong, field-shaped base and stays consistent. Less good: a job outside your groups gets your closest group's version.",
      "by-role-type": "Each role group you pick gets a resume built against what the strongest resumes in that field lead with, then nudged toward each job's wording.",
      "per-job": "Lines are picked from scratch for each posting's own wording. Good: the closest match to each job description. Less good: no consistent base, so two similar jobs can get noticeably different resumes.",
      "as-is": "Your uploaded PDF goes out exactly as you made it, named First_Last_Resume.pdf. Good: you control every word and the layout. Less good: nothing is aimed at the job, and every employer gets the same page.",
      one: "One resume for every job.",
    } },
  "apply.resume_groups": { label: "Role groups", help: "The kinds of role that get their own ideal resume. Leave empty to use your search fields.", type: "multi", options: OPTIONS.fields, showIf: ["apply.resume_tailoring", "ideal"] },
  "apply.cover_letters": { label: "Cover letters", help: "When to write one.", type: "select", options: OPTIONS.letters },
  "apply.future_commitments": { label: "Relocation, start date, term, travel", help: "How to answer questions about future commitments.", type: "select", options: OPTIONS.commitments },
  "apply.verify_resume_lines": { label: "Check resume lines", help: "Every line on a resume must trace back to your experience.", type: "toggle" },
  "apply.browser": { label: "Browser", help: "Where applications are filled. Automatic uses your own Chrome when Claude in Chrome is set up, and a Chrome window applyfirst opens for you otherwise.", type: "select", options: OPTIONS.browser },
  "apply.pace_seconds": { label: "Pause between requests", help: "Minimum seconds between requests to one site.", type: "number", min: 0, unit: "seconds" },

  "tracker.email.enabled": { label: "Read my replies", help: "Spots confirmations, interviews and rejections in your inbox. It only reads: it never sends, moves or deletes mail.", type: "toggle" },
  "tracker.email.imap_host": { label: "Mail server", help: "For example imap.example.com.", type: "text", showIf: "tracker.email.enabled", placeholder: "imap.example.com" },
  "tracker.email.imap_port": { label: "Mail server port", help: "Usually 993.", type: "number", min: 1, showIf: "tracker.email.enabled" },
  "tracker.email.username": { label: "Email address", help: "The login for your mailbox.", type: "text", showIf: "tracker.email.enabled", placeholder: "alex.rivera@example.com" },
  "tracker.sync_interval_hours": { label: "Check for replies every", help: "In hours.", type: "number", min: 1, unit: "hours", showIf: "tracker.email.enabled" },

  "schedule.run_daily": { label: "Run every day", help: "Search, apply (in auto mode) and read replies on a schedule.", type: "toggle" },
  "schedule.time": { label: "Time of day", help: "When the daily run starts.", type: "time", showIf: "schedule.run_daily" },

  "claude.command": { label: "Claude command", help: "The command that starts Claude Code on this computer.", type: "text" },
  "claude.model": { label: "Model", help: "Which Claude model does the work.", type: "text", list: "models" },
  "claude.max_turns_per_application": { label: "Steps per application", help: "A cap on how long Claude works on one application.", type: "number", min: 1 },
  "claude.daily_budget_usd": { label: "Daily spending limit (USD)", help: "Claude stops for the day once this much of your plan is used. 0 means no limit.", type: "number", min: 0 },
  "alerts.desktop": { label: "Desktop notification", help: "A notification on this computer when new matches arrive.", type: "toggle" },
  "alerts.email": { label: "Email me new matches", help: "Sends a short list to your own address, using the email settings above.", type: "toggle" },
  "alerts.min_new": { label: "Only when at least", help: "How many new matches before an alert is sent.", type: "number", min: 1 },
};

export const GROUP_OF = { search: "What to look for", sources: "Where to look", queue: "Order", apply: "Applying", tracker: "Email replies", schedule: "Schedule", alerts: "Alerts", claude: "Claude" };
export const GROUP_ORDER = ["What to look for", "Where to look", "Order", "Applying", "Email replies", "Schedule", "Alerts", "Claude", "More"];

export function leafPaths(obj, prefix = "") {
  const out = [];
  for (const [k, v] of Object.entries(obj || {})) {
    const p = prefix ? `${prefix}.${k}` : k;
    if (v && typeof v === "object" && !Array.isArray(v)) out.push(...leafPaths(v, p));
    else out.push(p);
  }
  return out;
}

export function defFor(path, value) {
  if (SETTING_DEFS[path]) return SETTING_DEFS[path];
  const type = typeof value === "boolean" ? "toggle" : typeof value === "number" ? "number" : Array.isArray(value) ? "tags" : "text";
  return { label: humanize(path.split(".").pop()), help: "", type };
}

export function groupFor(path) {
  return (SETTING_DEFS[path] && SETTING_DEFS[path].group) || GROUP_OF[path.split(".")[0]] || "More";
}

// Whether the warning for a setting applies to its current value.
export function warningActive(path, value) {
  if (path === "apply.mode") return value === "auto";
  if (path === "apply.verify_resume_lines") return value === false;
  if (path === "apply.pace_seconds") return typeof value === "number" && value < 3;
  if (path === "claude.daily_budget_usd") return value === 0;
  if (typeof value === "boolean") return value;
  return !!value;
}

// Build the control element for a definition bound to the settings object.
export function settingControl(path, def, settings, onAfter) {
  const value = deepGet(settings, path, def.type === "tags" || def.type === "multi" ? [] : "");
  const id = nextId("s");
  const set = (v) => { deepSet(settings, path, v); onAfter && onAfter(path, v); };
  switch (def.type) {
    case "toggle": return toggleControl({ value, onChange: set, label: def.label, id });
    case "select": return selectControl({ value, options: def.options, onChange: set, label: def.label, id });
    case "multi": return multiControl({ value, options: def.options, onChange: set, label: def.label });
    case "tags": return tagsControl({ value, onChange: set, label: def.label, suggest: def.suggest, norm: def.norm, placeholder: def.placeholder, display: def.display });
    case "number": {
      const input = inputControl({ value, type: "number", onChange: (n) => set(n == null ? 0 : n), label: def.label, id, min: def.min, step: "any" });
      if (!def.unit) return input;
      return h("div", { class: "row" }, h("div", { style: "width:110px" }, input), h("span", { class: "muted small" }, def.unit));
    }
    case "time": return inputControl({ value, type: "time", onChange: set, label: def.label, id });
    default: return inputControl({ value, type: "text", onChange: set, label: def.label, id, placeholder: def.placeholder, list: def.list });
  }
}
