// applyfirst interface: shell, hash router, and the main screens.
// Setup lives in setup.js, Settings in settings.js, shared helpers in lib.js.
import {
  S, h, api, icon, notice, empty, toast, skeletons, listOf, runningKinds, logoMark, loadSettings, saveSettingsNow,
  ago, hoursSince, deadlineInfo, fmtDate, humanize, OPTIONS, selectControl, deepGet,
} from "./lib.js";
import { setupScreen, profileScreen } from "./setup.js";
import { settingsScreen } from "./settings.js";

const main = document.getElementById("content");
const navEl = document.getElementById("nav");

const ctx = { name: "", onTick: null, onRunDone: null };
let prevRunning = [];
let tickTimer = null;

function safeUrl(u) {
  return /^https?:\/\//i.test(String(u || "")) ? u : "";
}

// ------------------------------------------------------------------ status polling

async function tick() {
  clearTimeout(tickTimer);
  const r = await api("GET", "/status");
  if (r.ok && r.data && typeof r.data === "object") {
    S.status = r.data;
    const now = runningKinds(S.status);
    updateNav();
    if (prevRunning.length && !now.length && ctx.onRunDone) ctx.onRunDone();
    if (ctx.onTick) ctx.onTick(S.status, now);
    prevRunning = now;
  }
  tickTimer = setTimeout(tick, runningKinds(S.status).length ? 3000 : 15000);
}

// A run was just started: look again soon and refresh the screen when it ends.
function afterStart() {
  prevRunning = ["pending"];
  clearTimeout(tickTimer);
  tickTimer = setTimeout(tick, 800);
}

// ------------------------------------------------------------------ navigation

const NAV = [
  { name: "home", label: "Home", icon: "home", primary: true },
  { name: "jobs", label: "Jobs", icon: "jobs", primary: true, badge: () => S.status && S.status.new_today },
  { name: "applications", label: "Applications", short: "Applied", icon: "apps", primary: true, badge: () => S.status && S.status.needs_you },
  { name: "answers", label: "Answers", icon: "answers", primary: true, badge: () => S.status && S.status.pending_questions },
  { name: "insights", label: "Insights", icon: "insights" },
  { name: "activity", label: "Activity", icon: "activity" },
  { name: "settings", label: "Settings", icon: "settings" },
  { name: "profile", label: "Profile", icon: "profile" },
];

function buildNav() {
  const link = (n) => h("a", { href: "#/" + n.name, "data-nav": n.name, onclick: () => navEl.classList.remove("open") },
    icon(n.icon, 18), h("span", { class: "lbl-full" }, n.label), h("span", { class: "lbl-short" }, n.short || n.label), h("span", { class: "badge", hidden: true, "data-badge": n.name }));
  navEl.replaceChildren(
    h("div", { class: "brand" }, logoMark(24), "applyfirst"),
    h("div", { class: "nav-group nav-primary" }, NAV.filter((n) => n.primary).map(link)),
    h("button", { class: "more-btn", type: "button", "aria-expanded": "false", onclick: (e) => {
      const open = navEl.classList.toggle("open");
      e.currentTarget.setAttribute("aria-expanded", String(open));
    } }, icon("more", 18), h("span", null, "More")),
    h("div", { class: "nav-label" }, "More"),
    h("div", { class: "nav-group nav-secondary" }, NAV.filter((n) => !n.primary).map(link)),
    h("div", { class: "nav-foot", id: "nav-foot" }),
  );
}

function updateNav() {
  for (const n of NAV) {
    const b = navEl.querySelector(`[data-badge="${n.name}"]`);
    if (!b) continue;
    const v = n.badge ? Number(n.badge()) || 0 : 0;
    b.hidden = v <= 0;
    b.textContent = v > 99 ? "99+" : String(v);
  }
  const foot = document.getElementById("nav-foot");
  if (foot) {
    const kinds = runningKinds(S.status);
    foot.replaceChildren(kinds.length ? h("span", { class: "pulse" }, "Working in the background") : "Runs on this computer");
  }
}

const ROUTES = {
  home: { title: "Home", fn: homeScreen },
  jobs: { title: "Jobs", fn: jobsScreen },
  applications: { title: "Applications", fn: applicationsScreen },
  answers: { title: "Answers", fn: answersScreen },
  insights: { title: "Insights", fn: insightsScreen },
  activity: { title: "Activity", fn: activityScreen },
  settings: { title: "Settings", fn: settingsScreen },
  profile: { title: "Profile", fn: profileScreen },
  setup: { title: "Set up", fn: setupScreen },
};

async function route() {
  let name = (location.hash.replace(/^#\/?/, "").split(/[/?]/)[0] || "").toLowerCase();
  if (!name) name = "home";
  if (!ROUTES[name]) name = "home";
  if (!S.status || S.status.set_up === false) {
    const r = await api("GET", "/status");
    if (r.ok && r.data) S.status = r.data;
  }
  if (S.status && S.status.set_up === false && name !== "setup" && !S.skipSetup) {
    location.replace("#/setup");
    return;
  }
  ctx.name = name;
  ctx.onTick = null;
  ctx.onRunDone = null;
  document.title = `${ROUTES[name].title} · applyfirst`;
  document.body.classList.toggle("wizard", name === "setup");
  navEl.classList.remove("open");
  for (const a of navEl.querySelectorAll("[data-nav]")) {
    if (a.dataset.nav === name) a.setAttribute("aria-current", "page");
    else a.removeAttribute("aria-current");
  }
  const page = h("div", { class: "page" });
  main.replaceChildren(page);
  updateNav();
  window.scrollTo(0, 0);
  try {
    await ROUTES[name].fn(page, ctx);
  } catch (e) {
    console.error(e);
    page.replaceChildren(
      h("div", { class: "page-head" }, h("h1", null, ROUTES[name].title)),
      empty("alert", "This page hit a problem", "Nothing was lost. Reload to try again.", h("button", { class: "btn", onclick: () => location.reload() }, "Reload")),
    );
  }
}

function head(title, sub, ...actions) {
  return h("div", { class: "page-head" },
    h("div", null, h("h1", null, title), sub ? h("p", null, sub) : null),
    actions.length ? h("div", { class: "head-actions" }, actions) : null);
}

async function startSweep(btn) {
  if (btn) btn.disabled = true;
  const r = await api("POST", "/sources/sweep", {});
  if (btn) btn.disabled = false;
  if (r.ok) {
    toast("Searching now. New matches show up as they are found.", { href: "#/activity", link: "Watch" });
    afterStart();
  } else toast("The search did not start. " + r.error, { error: true });
  return r.ok;
}

// ------------------------------------------------------------------ home

async function homeScreen(page, c) {
  page.append(head("Home", "Where things stand today."), skeletons(2));
  const fresh = await api("GET", "/status");
  if (fresh.ok && fresh.data) S.status = fresh.data;
  updateNav();
  const st = S.status;
  page.replaceChildren(head("Home", "Where things stand today."));
  if (!st) {
    page.append(empty("alert", "Can't reach the app", "Check that applyfirst is still running on this computer, then reload.", h("button", { class: "btn", onclick: () => location.reload() }, "Reload")));
    return;
  }
  const searchBtn = h("button", { class: "btn primary", onclick: () => startSweep(searchBtn) }, icon("search", 16), "Search for new postings");
  const cl = st.claude || {};
  if (cl.installed === false) {
    page.append(notice("Claude Code is not installed, so applications cannot be filled yet. Searching still works. Install Claude Code, sign in once, then reload this page. See the setup guide on GitHub.", "error"));
  } else if (cl.installed && cl.version && cl.ok === false) {
    page.append(notice(`Claude Code ${cl.version} is too old for applyfirst. Update it, then reload this page.`, "error"));
  }

  // One primary action: the most useful thing to do next.
  let hero;
  if (st.needs_you > 0) hero = ["" + st.needs_you + (st.needs_you === 1 ? " application needs" : " applications need") + " you", "A short step from you and they go out.", h("a", { class: "btn primary", href: "#/applications" }, "Review now")];
  else if (st.pending_questions > 0) hero = [`${st.pending_questions} new ${st.pending_questions === 1 ? "question" : "questions"} to answer`, "Answer once and it is used on every application from now on.", h("a", { class: "btn primary", href: "#/answers" }, "Answer them")];
  else if (st.kept > 0) hero = [`${st.kept} ${st.kept === 1 ? "job matches" : "jobs match"} what you want`, "Approve the ones you like and applyfirst fills them in.", h("a", { class: "btn primary", href: "#/jobs" }, "Review matches")];
  else hero = ["Find the newest postings", "Search company career pages the hour new roles go up.", searchBtn];
  page.append(h("div", { class: "card hero" }, h("div", null, h("h2", null, hero[0]), h("p", null, hero[1])), hero[2]));

  const tile = (n, label, href, hot) => h("a", { class: "card tile" + (hot && n > 0 ? " hot" : ""), href },
    h("div", { class: "num" }, String(n || 0)), h("div", { class: "lbl" }, label));
  page.append(h("div", { class: "tiles", style: "margin-top:16px" },
    tile(st.new_today, "New matches today", "#/jobs", true),
    tile(st.needs_you, "Need you", "#/applications", true),
    tile(st.applied, "Applied", "#/applications"),
    tile(st.interviews, "Interviews and offers", "#/insights"),
  ));

  const runs = listOf(st.last_runs).slice(0, 6);
  const card = h("div", { class: "card", style: "margin-top:24px" },
    h("div", { class: "list-head" }, h("h2", null, "Recent activity"), h("a", { class: "small", href: "#/activity" }, "See all")));
  if (!runs.length) {
    card.append(empty("activity", "Nothing yet", "Your first search will show up here, with what it found."));
  } else {
    card.append(h("ul", { class: "list" }, runs.map((r) => h("li", null,
      statusPill(r.status), h("span", { style: "flex:1;min-width:0;overflow-wrap:anywhere" }, runSummary(r)),
      h("span", { class: "muted tiny" }, ago(r.started_at))))));
  }
  page.append(card);
  if (st.kept > 0 && hero[2] !== searchBtn) page.append(h("div", { style: "margin-top:16px" }, searchBtn));

  c.onRunDone = () => ctx.name === "home" && route();
}

const KIND = { sweep: "Search", apply: "Apply", sync: "Email check", resume: "Resume", daily: "Daily routine", discover: "Board discovery" };
function runSummary(r) {
  const k = KIND[r.kind] || humanize(r.kind || "Job");
  return `${k}: ${r.summary || (r.status === "running" ? "In progress" : "No summary")}`;
}
function statusPill(s) {
  const map = { done: ["good", "Done"], failed: ["bad", "Failed"], running: ["accent", "Running"] };
  const [cls, text] = map[s] || ["", humanize(s || "")];
  return h("span", { class: "pill " + cls }, text);
}

// ------------------------------------------------------------------ jobs

async function jobsScreen(page, c) {
  // A list holds at most LIST_LIMIT rows; past that the tab shows the true total from the server.
  const shownCount = (v) => (J.counts && J.lists[v].length >= LIST_LIMIT ? J.counts[v] : J.lists[v].length);
  const J = { view: "kept", lists: { kept: [], approved: [], skipped: [] }, sel: new Set(), open: new Set(), why: {}, loaded: false, unavailable: false, error: "" };
  const LIST_LIMIT = 500;
  const VIEWS = [["kept", "Kept"], ["approved", "Approved"], ["skipped", "Skipped"]];

  const settings = await loadSettings();
  const searchBtn = h("button", { class: "btn", onclick: () => startSweep(searchBtn) }, icon("search", 16), "Search now");
  const applyBtn = h("button", { class: "btn primary", onclick: applyApproved }, "Apply to approved");
  page.append(head("Jobs", "New postings that fit what you want, newest first.", searchBtn, applyBtn));

  // Order picker, bound to the queue settings.
  const orderBox = h("div", { class: "order" });
  const drawOrder = () => {
    if (!settings) return orderBox.replaceChildren();
    const mk = (key, label) => h("label", { class: "row", style: "gap:6px" }, label,
      selectControl({ value: deepGet(settings, key, "newest"), options: OPTIONS.order, label,
        onChange: async (v) => { settings.queue = settings.queue || {}; settings.queue[key.split(".")[1]] = v; await saveSettingsNow(); load(); } }));
    orderBox.replaceChildren(mk("queue.order_by", "Order by"), mk("queue.then_by", "then by"));
  };
  drawOrder();

  // Paste a link.
  const linkInput = h("input", { type: "url", placeholder: "Paste a link to a job posting", "aria-label": "Link to a job posting" });
  const addBtn = h("button", { class: "btn", type: "submit" }, icon("plus", 16), "Add");
  const addForm = h("form", { class: "card addlink", onsubmit: async (e) => {
    e.preventDefault();
    const url = linkInput.value.trim();
    if (!safeUrl(url)) { toast("Paste the full link, starting with https://", { error: true }); return; }
    addBtn.disabled = true;
    const r = await api("POST", "/sources/manual", { url });
    addBtn.disabled = false;
    if (!r.ok) { toast("That link was not added. " + r.error, { error: true }); return; }
    linkInput.value = "";
    const id = r.data && r.data.id;
    if (id) await api("POST", `/filters/postings/${encodeURIComponent(id)}/action`, { action: "approve" });
    toast(id ? "Added and approved." : "Added.");
    load();
  } }, linkInput, addBtn);

  const box = h("div");
  page.append(addForm, orderBox, h("div", { style: "height:14px" }), box);

  async function load() {
    const res = await Promise.all(VIEWS.map(([v]) => api("GET", `/filters/queue?view=${v}&limit=${LIST_LIMIT}`)));
    const withCounts = res.find((r) => r.ok && r.data && r.data.counts);
    J.counts = withCounts ? withCounts.data.counts : null;
    VIEWS.forEach(([v], i) => { J.lists[v] = res[i].ok ? listOf(res[i].data) : []; });
    J.unavailable = res.every((r) => !r.ok);
    J.error = (res.find((r) => !r.ok) || {}).error || "";
    J.loaded = true;
    render();
  }

  function sig() { return VIEWS.map(([v]) => J.lists[v].map((p) => p.id).join(",")).join("|"); }

  function place(p) {
    for (const [v] of VIEWS) J.lists[v] = J.lists[v].filter((x) => x.id !== p.id);
    const target = p.user_action === "approved" ? "approved" : p.user_action === "skipped" ? "skipped" : p.verdict === "skip" ? "skipped" : "kept";
    J.lists[target].unshift(p);
  }

  async function act(p, action) {
    const r = await api("POST", `/filters/postings/${encodeURIComponent(p.id)}/action`, { action });
    if (!r.ok) { toast("That did not go through. " + r.error, { error: true }); return false; }
    p.user_action = action === "approve" ? "approved" : action === "skip" ? "skipped" : "";
    J.sel.delete(p.id);
    place(p);
    return true;
  }

  async function bulk(action) {
    const items = J.lists[J.view].filter((p) => J.sel.has(p.id));
    const results = await Promise.all(items.map((p) => act(p, action)));
    const ok = results.filter(Boolean).length;
    if (ok) toast(`${action === "approve" ? "Approved" : "Skipped"} ${ok}.`);
    render();
  }

  async function applyApproved() {
    const n = J.lists.approved.length;
    if (!n) return;
    if (deepGet(S.settings, "apply.mode") === "auto" && !confirm(`Auto mode sends applications without showing you first. Apply to ${n} now?`)) return;
    applyBtn.disabled = true;
    const limit = deepGet(S.settings, "queue.daily_limit", null);
    const r = await api("POST", "/apply/run", limit ? { limit } : {});
    applyBtn.disabled = false;
    if (r.ok) { toast("Applying now. Anything that needs you will show up in Applications.", { href: "#/activity", link: "Watch" }); afterStart(); }
    else toast("Applying did not start. " + r.error, { error: true });
  }

  async function toggleWhy(p) {
    if (J.open.has(p.id)) J.open.delete(p.id);
    else {
      J.open.add(p.id);
      if (!J.why[p.id] && !reasonsOf(p).length) {
        const r = await api("GET", `/filters/postings/${encodeURIComponent(p.id)}`);
        if (r.ok && r.data) {
          const d = r.data;
          J.why[p.id] = reasonsFrom(d.reasons) .length ? reasonsFrom(d.reasons) : reasonsFrom(d.verdict_reasons).length ? reasonsFrom(d.verdict_reasons) : reasonsFrom(d.posting && d.posting.verdict_reasons);
        } else J.why[p.id] = [];
      }
    }
    render();
  }

  function reasonsFrom(v) {
    if (Array.isArray(v)) return v.map(String);
    if (typeof v === "string") { try { const a = JSON.parse(v); return Array.isArray(a) ? a.map(String) : []; } catch (e) { return []; } }
    return [];
  }
  function reasonsOf(p) { const own = reasonsFrom(p.verdict_reasons); return own.length ? own : J.why[p.id] || []; }

  function row(p) {
    const hrs = hoursSince(p.posted_at || p.first_seen_at);
    const when = p.posted_at ? "Posted " + ago(p.posted_at) : p.first_seen_at ? "Found " + ago(p.first_seen_at) : "";
    const dl = deadlineInfo(p.deadline);
    const loc = [p.location, p.remote ? "Remote" : ""].filter(Boolean).join(" · ");
    const open = J.open.has(p.id);
    const url = safeUrl(p.url || p.apply_url);
    const mkBtn = (label, cls, action) => h("button", { class: "btn small " + cls, onclick: async () => { if (await act(p, action)) render(); } }, label);
    let actions;
    if (J.view === "kept") actions = [mkBtn("Approve", "primary", "approve"), mkBtn("Skip", "quiet", "skip")];
    else if (J.view === "approved") actions = [mkBtn("Skip", "quiet", "skip"), mkBtn("Undo", "quiet", "reset")];
    else actions = p.user_action === "skipped" ? [mkBtn("Approve", "primary", "approve"), mkBtn("Restore", "quiet", "reset")] : [mkBtn("Approve anyway", "", "approve")];
    const reasons = open ? reasonsOf(p) : [];
    const whyHead = J.view === "skipped" ? "Why it was skipped" : J.view === "approved" ? "Why it matched" : "Why it was kept";
    return h("div", { class: "job" },
      h("div", { class: "job-main" },
        h("input", { type: "checkbox", checked: J.sel.has(p.id), "aria-label": `Select ${p.title} at ${p.company}`, onchange: (e) => { e.target.checked ? J.sel.add(p.id) : J.sel.delete(p.id); render(true); } }),
        h("div", { class: "job-body" },
          h("div", { class: "job-title" }, p.title || "Untitled role"),
          h("div", { class: "job-co" }, p.company || ""),
          h("div", { class: "job-meta" },
            loc ? h("span", null, loc) : null,
            when ? h("span", { class: hrs != null && hrs < 6 ? "fresh" : "" }, when) : null,
            dl ? h("span", { class: dl.soon ? "soon" : "" }, dl.text) : null),
        ),
        h("div", { class: "job-actions" }, actions,
          h("button", { class: "btn quiet small", "aria-expanded": String(open), onclick: () => toggleWhy(p) }, "Why", icon("chevron", 14)),
          url ? h("a", { class: "btn quiet small", href: url, target: "_blank", rel: "noopener noreferrer", "aria-label": `Open posting for ${p.title}` }, "Open", icon("external", 14)) : null),
      ),
      open ? h("div", { class: "job-why" }, h("strong", null, whyHead),
        reasons.length ? h("ul", null, reasons.map((r) => h("li", null, r))) : h("p", null, "No extra detail was recorded for this one.")) : null,
    );
  }

  function render(keepScroll) {
    const list = J.lists[J.view];
    applyBtn.textContent = J.lists.approved.length ? `Apply to ${J.lists.approved.length} approved` : "Apply to approved";
    applyBtn.disabled = !J.lists.approved.length;
    const tabs = h("div", { class: "toolbar" },
      h("div", { class: "seg", role: "group", "aria-label": "Job views" }, VIEWS.map(([v, l]) =>
        h("button", { type: "button", "aria-pressed": String(J.view === v), onclick: () => { J.view = v; J.sel.clear(); render(); } },
          l, h("span", { class: "count" }, String(shownCount(v)))))),
      list.length ? h("label", { class: "row small muted" }, h("input", { type: "checkbox", checked: list.length > 0 && J.sel.size === list.length,
        onchange: (e) => { J.sel = e.target.checked ? new Set(list.map((p) => p.id)) : new Set(); render(true); } }), "Select all") : null);
    const parts = [];
    if (runningKinds(S.status).includes("sweep")) parts.push(h("div", { style: "margin-bottom:12px" }, notice("Searching for new postings. This list updates as they arrive.", "info")));
    parts.push(tabs);
    if (J.sel.size) {
      parts.push(h("div", { class: "bulkbar" }, h("strong", null, `${J.sel.size} selected`),
        J.view !== "approved" ? h("button", { class: "btn small primary", onclick: () => bulk("approve") }, "Approve") : null,
        J.view !== "skipped" ? h("button", { class: "btn small", onclick: () => bulk("skip") }, "Skip") : null,
        h("button", { class: "btn small quiet", onclick: () => { J.sel.clear(); render(true); } }, "Clear")));
    }
    if (!J.loaded) parts.push(skeletons(4));
    else if (J.unavailable) {
      parts.push(empty("inbox", "Jobs will show up here", "Run your first search and the postings that fit you land on this page, newest first.",
        h("button", { class: "btn primary", onclick: () => startSweep() }, "Search now"), h("a", { class: "btn", href: "#/settings" }, "Adjust what you look for")));
    } else if (!list.length) parts.push(emptyFor(J.view));
    else parts.push(h("div", { class: "card" }, list.map(row)));
    const y = window.scrollY;
    box.replaceChildren(...parts);
    if (keepScroll) window.scrollTo(0, y);
  }

  function emptyFor(view) {
    const total = VIEWS.reduce((n, [v]) => n + J.lists[v].length, 0);
    if (!total) return empty("search", "No jobs yet", "Search company career pages for postings that fit you. New ones appear here the hour they go up.",
      h("button", { class: "btn primary", onclick: () => startSweep() }, "Search now"), h("a", { class: "btn", href: "#/settings" }, "Adjust what you look for"));
    if (view === "kept") return empty("check", "You are all caught up", "Every match has been approved or skipped. New postings will land here.", h("button", { class: "btn", onclick: () => startSweep() }, "Search again"));
    if (view === "approved") return empty("jobs", "Nothing approved yet", "Approve jobs from Kept. They wait here until you press Apply to approved.", h("button", { class: "btn", onclick: () => { J.view = "kept"; render(); } }, "Go to Kept"));
    return empty("inbox", "Nothing skipped", "Postings you skip, and ones that did not fit, show up here with the reason.");
  }

  render();
  await load();

  let n = 0;
  c.onRunDone = load;
  c.onTick = async (st, kinds) => {
    if (!kinds.includes("sweep") || ++n % 2) return;
    const before = sig();
    const res = await api("GET", "/filters/queue?view=kept&limit=500");
    if (res.ok) { const keptNow = listOf(res.data); if (keptNow.map((p) => p.id).join(",") !== J.lists.kept.map((p) => p.id).join(",")) { await load(); } else if (before !== sig()) render(true); }
  };
}

// ------------------------------------------------------------------ applications

const OUTCOMES = [["assessment", "Assessment"], ["interview", "Interview"], ["offer", "Offer"], ["rejected", "Rejected"], ["withdrawn", "Withdrawn"]];

function todoText(a) {
  const raw = (a.needs_you || "").trim();
  const low = raw.toLowerCase();
  const co = a.company || "the employer";
  if (a.status === "ready-to-submit") return `Look over the filled form in the open browser tab for ${co}, press Submit, then click I submitted it.`;
  if (/sign.?in|log.?in|account|password/.test(low)) return `Sign in to the ${co} site in the open browser tab, then press Continue.`;
  if (/captcha|robot|verify/.test(low)) return `Solve the check on the ${co} page in the open browser tab, then press Continue.`;
  if (/question|answer/.test(low)) return "New questions need your answer. Answer them in Answers and the application carries on.";
  if (raw.length > 14 && raw.includes(" ")) return raw;
  return raw || `Open the ${co} tab in your browser and finish the last step.`;
}

async function applicationsScreen(page, c) {
  const A = { items: [], view: "status", loaded: false, error: "" };
  page.append(head("Applications", "Everything applyfirst is working on, and how it turned out."));
  const box = h("div", null, skeletons(3));
  page.append(box);

  async function load() {
    const r = await api("GET", "/apply/applications");
    A.items = r.ok ? listOf(r.data) : [];
    A.error = r.ok ? "" : r.error;
    A.loaded = true;
    render();
  }

  async function setStatus(a, status) {
    const r = await api("POST", `/apply/applications/${encodeURIComponent(a.id)}/status`, { status });
    if (r.ok) { a.status = status; toast("Marked as submitted."); render(); tick(); } else toast("That did not save. " + r.error, { error: true });
  }
  async function retry(a) {
    const r = await api("POST", `/apply/applications/${encodeURIComponent(a.id)}/status`, { status: "queued" });
    if (!r.ok) return toast("That did not save. " + r.error, { error: true });
    a.status = "queued";
    const run = await api("POST", "/apply/run", {});
    toast(run.ok ? "Back in the queue. Filling now." : "Back in the queue. It goes out with the next run.");
    render(); tick();
  }
  async function setOutcome(a, outcome) {
    const r = await api("POST", `/tracker/applications/${encodeURIComponent(a.id)}/outcome`, { outcome });
    if (r.ok) { a.outcome = outcome; a.outcome_source = "manual"; toast(outcome ? `Marked as ${outcome}.` : "Outcome cleared."); render(); tick(); } else toast("That did not save. " + r.error, { error: true });
  }

  function card(a) {
    const needs = a.status === "needs-you" || a.status === "ready-to-submit";
    const acts = [];
    if (needs) acts.push(h("button", { class: "btn small primary", onclick: () => setStatus(a, "submitted") }, "I submitted it"));
    if (a.status === "needs-you" && /question|answer/i.test(a.needs_you || "")) acts.push(h("a", { class: "btn small", href: "#/answers" }, "Open Answers"));
    if (a.status === "needs-you") acts.push(h("button", { class: "btn small", onclick: () => retry(a) }, "Continue"));
    if (a.status === "failed") acts.push(h("button", { class: "btn small primary", onclick: () => retry(a) }, "Try again"));
    if (a.status === "submitted") {
      acts.push(selectControl({ value: a.outcome || "", label: `Outcome for ${a.company}`,
        options: [["", a.outcome ? "No outcome" : "Mark outcome"], ...OUTCOMES], onChange: (v) => setOutcome(a, v) }));
    }
    const when = a.status === "submitted" ? (a.submitted_at ? "Submitted " + ago(a.submitted_at) : "Submitted") : a.updated_at ? "Updated " + ago(a.updated_at) : "";
    return h("div", { class: "card app-card" },
      h("div", { class: "co" }, a.company), h("div", { class: "ti" }, a.title),
      needs ? h("div", { class: "todo" }, todoText(a)) : null,
      h("div", { class: "tiny muted", style: "margin-top:6px" }, when, a.outcome ? ` · ${humanize(a.outcome)}${a.outcome_source === "email" ? " (from email)" : ""}` : ""),
      acts.length ? h("div", { class: "acts" }, acts) : null);
  }

  function column(title, items, emptyText) {
    return h("div", { class: "col" }, h("div", { class: "col-head" }, h("span", null, title), h("span", { class: "n" }, String(items.length))),
      items.length ? items.map(card) : h("div", { class: "empty-col" }, emptyText));
  }

  function render() {
    if (!A.loaded) return;
    if (A.error && !A.items.length) {
      box.replaceChildren(empty("apps", "No applications yet", "Approve jobs in Jobs, then press Apply to approved. Each application shows up here while it is being filled in.", h("a", { class: "btn primary", href: "#/jobs" }, "Go to Jobs")));
      return;
    }
    if (!A.items.length) {
      box.replaceChildren(empty("apps", "No applications yet", "Approve jobs in Jobs, then press Apply to approved. Each application shows up here while it is being filled in.", h("a", { class: "btn primary", href: "#/jobs" }, "Go to Jobs")));
      return;
    }
    const withOutcome = A.items.filter((a) => a.outcome);
    const rest = A.items.filter((a) => !a.outcome);
    const by = (s) => rest.filter((a) => (Array.isArray(s) ? s.includes(a.status) : a.status === s));
    const tabs = h("div", { class: "seg", role: "group", "aria-label": "Board" },
      h("button", { type: "button", "aria-pressed": String(A.view === "status"), onclick: () => { A.view = "status"; render(); } }, "Progress"),
      h("button", { type: "button", "aria-pressed": String(A.view === "outcome"), onclick: () => { A.view = "outcome"; render(); } }, "Outcomes", h("span", { class: "count" }, String(withOutcome.length))));
    const parts = [h("div", { style: "margin-bottom:16px" }, tabs)];
    if (A.view === "status") {
      parts.push(h("div", { class: "board" },
        column("Filling", by(["queued", "filling"]), "Nothing being filled in right now."),
        column("Needs you", by("needs-you"), "Nothing waiting on you."),
        column("Ready to submit", by("ready-to-submit"), "Nothing waiting for your final click."),
        column("Submitted", by("submitted"), "Submitted applications show here."),
      ));
      const failed = by("failed");
      if (failed.length) parts.push(h("div", { class: "section-title" }, h("h2", null, "Did not finish")), h("div", { class: "board" }, failed.map(card)));
    } else {
      const o = (k) => withOutcome.filter((a) => a.outcome === k);
      const cols = [column("Assessment", o("assessment"), "None yet."), column("Interview", o("interview"), "None yet."), column("Offer", o("offer"), "None yet."), column("Rejected", o("rejected"), "None yet.")];
      if (o("withdrawn").length) cols.push(column("Withdrawn", o("withdrawn"), ""));
      parts.push(h("div", { class: "board" }, cols));
      if (!withOutcome.length) parts.push(h("p", { class: "help", style: "margin-top:12px" }, "Replies are picked up from your email, or mark one yourself on a submitted application."));
    }
    box.replaceChildren(...parts);
  }

  await load();
  c.onRunDone = load;
}

// ------------------------------------------------------------------ answers

async function answersScreen(page) {
  page.append(head("Answers", "Answer a question once and it is used on every application."));
  const box = h("div", null, skeletons(3));
  page.append(box);
  const [pend, all, notesRes] = await Promise.all([api("GET", "/apply/answers?pending=1"), api("GET", "/apply/answers"), api("GET", "/apply/form-notes")]);
  let systems = notesRes.ok ? listOf(notesRes.data).filter((s) => (s.notes || []).length) : [];
  if (!pend.ok && !all.ok) {
    box.replaceChildren(empty("answers", "Questions will show up here", "When an application asks something new, it lands here for you to answer once. Your answers are saved for next time.", h("a", { class: "btn primary", href: "#/jobs" }, "Go to Jobs")));
    return;
  }
  let pending = listOf(pend.data).filter((a) => a.pending !== 0 && a.pending !== false);
  let learned = listOf(all.data).filter((a) => !a.pending);
  let query = "";

  const put = async (a, value) => {
    const r = await api("PUT", `/apply/answers/${encodeURIComponent(a.key)}`, { answer: value });
    if (!r.ok) toast("That answer was not saved. " + r.error, { error: true });
    return r.ok;
  };

  function pendingCard(a) {
    const ta = h("textarea", { "aria-label": `Your answer to: ${a.question}`, rows: 3, placeholder: "Type your answer" });
    const btn = h("button", { class: "btn primary small", onclick: async () => {
      if (!ta.value.trim()) { toast("Type an answer first.", { error: true }); return; }
      btn.disabled = true;
      if (await put(a, ta.value.trim())) {
        pending = pending.filter((x) => x.key !== a.key);
        learned.unshift({ ...a, answer: ta.value.trim(), pending: 0, source: "user" });
        toast("Saved. It will be used from now on.");
        draw(); tick();
      } else btn.disabled = false;
    } }, "Save answer");
    return h("div", { class: "qa" }, h("div", { class: "q" }, a.question || a.key), ta, h("div", null, btn));
  }

  function learnedCard(a) {
    const locked = a.source === "profile";
    const ta = h("textarea", { "aria-label": `Answer to: ${a.question}`, rows: 2, readOnly: locked }, a.answer || "");
    const save = h("button", { class: "btn small", hidden: true, onclick: async () => {
      save.disabled = true;
      if (await put(a, ta.value)) { a.answer = ta.value; a.source = "user"; toast("Saved."); save.hidden = true; }
      save.disabled = false;
    } }, "Save");
    ta.addEventListener("input", () => (save.hidden = ta.value === (a.answer || "")));
    return h("div", { class: "qa" }, h("div", { class: "q" }, a.question || a.key), ta,
      h("div", { class: "row wrap" }, save,
        h("span", { class: "meta" },
          h("span", null, locked ? "From your profile" : a.source === "user" ? "You wrote this" : "Learned from an application"),
          a.uses ? h("span", null, `Used ${a.uses} ${a.uses === 1 ? "time" : "times"}`) : null,
          locked ? h("a", { href: "#/profile" }, "Edit in your profile") : null)));
  }

  function draw() {
    const parts = [];
    if (pending.length) {
      parts.push(h("div", { class: "section-title", style: "margin-top:0" }, h("h2", null, "Waiting for you"), h("span", { class: "pill accent" }, String(pending.length))),
        h("div", { class: "card" }, pending.map(pendingCard)));
    }
    const q = query.trim().toLowerCase();
    const shown = learned.filter((a) => !q || `${a.question} ${a.answer}`.toLowerCase().includes(q));
    parts.push(h("div", { class: "section-title" }, h("h2", null, "Saved answers"), h("span", { class: "muted small" }, String(learned.length))));
    if (learned.length > 6) {
      const s = h("input", { type: "search", placeholder: "Search your answers", "aria-label": "Search saved answers", value: query, style: "margin-bottom:12px" });
      s.addEventListener("input", () => { query = s.value; drawList(); });
      parts.push(s);
    }
    const listBox = h("div", { id: "learned-list" });
    parts.push(listBox);
    if (systems.length) {
      parts.push(h("div", { class: "section-title" }, h("h2", null, "What it has learned about application forms"),
        h("span", { class: "muted small" }, "Used on the next form of the same kind")));
      parts.push(h("div", { class: "card" }, systems.map((s) => h("div", { class: "qa" },
        h("div", { class: "q" }, s.system.charAt(0).toUpperCase() + s.system.slice(1)),
        h("ul", { class: "form-notes" }, s.notes.map((n) => {
          const del = h("button", { class: "btn small quiet", "aria-label": `Forget: ${n.note}`, onclick: async () => {
            del.disabled = true;
            const r = await api("DELETE", `/apply/form-notes/${encodeURIComponent(s.system)}/${encodeURIComponent(n.key)}`);
            if (!r.ok) { toast("That note was not removed. " + r.error, { error: true }); del.disabled = false; return; }
            s.notes = s.notes.filter((x) => x.key !== n.key);
            systems = systems.filter((x) => x.notes.length);
            draw();
          } }, "Forget");
          return h("li", null, h("span", null, n.note),
            n.seen > 1 ? h("span", { class: "meta" }, ` Seen on ${n.seen} applications`) : null, " ", del);
        }))))));
    }
    box.replaceChildren(...parts);
    drawList();
    function drawList() {
      const q2 = query.trim().toLowerCase();
      const items = learned.filter((a) => !q2 || `${a.question} ${a.answer}`.toLowerCase().includes(q2));
      const target = box.querySelector("#learned-list");
      if (!target) return;
      if (!items.length) target.replaceChildren(empty("answers", learned.length ? "No answers match" : (pending.length ? "Nothing saved yet" : "No questions yet"),
        learned.length ? "Try different words." : "When an application asks something new, you answer it once here and it is remembered.", learned.length ? null : h("a", { class: "btn", href: "#/jobs" }, "Go to Jobs")));
      else target.replaceChildren(h("div", { class: "card" }, items.map(learnedCard)));
    }
    void shown;
  }
  draw();
}

// ------------------------------------------------------------------ insights

const firstNum = (...vals) => { for (const v of vals) if (typeof v === "number" && !Number.isNaN(v)) return v; return null; };

function normGroup(raw) {
  let rows = [];
  if (Array.isArray(raw)) rows = raw;
  else if (raw && typeof raw === "object") rows = Object.entries(raw).map(([k, v]) => (v && typeof v === "object" ? { name: k, ...v } : { name: k, rate: v }));
  return rows.map((r) => {
    const name = [r.name, r.label, r.key, r.group, r.value, r.source, r.variant, r.field, r.bucket].find((x) => x != null && x !== "");
    const n = firstNum(r.applications, r.n, r.count, r.total, r.sample, r.applied, r.sample_size);
    const interviews = firstNum(r.interviews, r.interview_count);
    let rate = firstNum(r.interview_rate, r.rate);
    if (rate == null && n && interviews != null) rate = interviews / n;
    if (rate != null && rate > 1) rate = rate / 100;
    let few = [r.too_few, r.small, r.small_sample, r.low_sample, r.too_few_to_compare].find((x) => typeof x === "boolean");
    if (few === undefined && typeof r.note === "string") few = /few|small/i.test(r.note);
    if (few === undefined && typeof r.label === "string" && /few|small/i.test(r.label) && r.name != null) few = true;
    if (few === undefined) few = n != null ? n < 5 : false;
    return { name: name == null ? "Unknown" : humanize(String(name)), n, interviews, rate, few };
  });
}

const pct = (r) => (r == null ? "n/a" : `${Math.round(r * 1000) / 10}%`);

async function insightsScreen(page) {
  page.append(head("Insights", "What is actually getting you interviews."));
  const box = h("div", null, skeletons(3));
  page.append(box);
  const [st, cost] = await Promise.all([api("GET", "/tracker/stats"), api("GET", "/apply/cost")]);
  const stats = st.ok && st.data && typeof st.data === "object" ? st.data : null;
  const o = (stats && (stats.totals || stats.overall)) || stats || {};
  const apps = firstNum(o.applications, o.applied, o.total, o.n);
  const interviews = firstNum(o.interviews, o.interview_count);
  const responses = firstNum(o.responses, o.replies);
  let rate = firstNum(o.interview_rate, o.rate);
  if (apps && interviews != null) rate = interviews / apps;
  else if (rate != null && rate > 1) rate /= 100;

  if (!stats || !apps) {
    box.replaceChildren(empty("insights", "Nothing to compare yet", "Once you have applied to some jobs and replies come in, this shows which sources, resumes and timing get you interviews.",
      h("a", { class: "btn primary", href: "#/jobs" }, "Find jobs to apply to"), h("a", { class: "btn", href: "#/settings" }, "Connect your email")));
    if (cost.ok) box.append(costCard(cost.data));
    return;
  }

  const parts = [];
  parts.push(h("div", { class: "grid two" },
    h("div", { class: "card card-pad" }, h("div", { class: "bignum" }, pct(rate)), h("div", { class: "muted", style: "margin-top:6px" }, "interview rate"),
      h("div", { class: "help", style: "margin-top:4px" }, `${interviews ?? 0} ${interviews === 1 ? "interview" : "interviews"} from ${apps} ${apps === 1 ? "application" : "applications"}${responses != null ? `, ${responses} ${responses === 1 ? "reply" : "replies"}` : ""}`)),
    cost.ok ? costCard(cost.data) : h("div")));

  const keys = Object.keys(stats);
  const find = (re) => keys.find((k) => re.test(k) && stats[k] && typeof stats[k] === "object");
  const GROUPS = [["Where the posting came from", /source/i], ["Resume version", /resume|variant/i], ["Field", /field/i], ["How old the posting was when you applied", /age|hours/i]];
  for (const [title, re] of GROUPS) {
    const k = find(re);
    const rows = k ? normGroup(stats[k]) : [];
    if (!rows.length) continue;
    const max = Math.max(0.0001, ...rows.map((r) => r.rate || 0));
    parts.push(h("div", { class: "section-title" }, h("h2", null, title)),
      h("div", { class: "card table-wrap" }, h("table", { class: "group-table" },
        h("thead", null, h("tr", null, h("th", { scope: "col" }, "Group"), h("th", { scope: "col", class: "num" }, "Applications"), h("th", { scope: "col", class: "num" }, "Interviews"), h("th", { scope: "col" }, "Interview rate"))),
        h("tbody", null, rows.map((r) => h("tr", { class: r.few ? "too-few" : "" },
          h("td", null, r.name), h("td", { class: "num" }, r.n ?? "n/a"), h("td", { class: "num" }, r.interviews ?? "n/a"),
          h("td", null, h("div", { class: "row" }, h("div", { class: "bar", style: "flex:1" }, h("i", { style: `width:${Math.min(100, ((r.rate || 0) / max) * 100)}%` })),
            h("span", { style: "min-width:48px;text-align:right" }, pct(r.rate)), r.few ? h("span", { class: "tiny" }, "too few to compare") : null))))))));
  }

  const wk = find(/week/i) || (Array.isArray(stats.weekly) ? "weekly" : null);
  const weeks = wk ? (Array.isArray(stats[wk]) ? stats[wk] : []) : [];
  if (weeks.length) {
    const data = weeks.slice(-12).map((w, i) => ({ label: String(w.week_start ?? w.week ?? w.start ?? i + 1).slice(-8), n: firstNum(w.applications, w.n, w.count, w.applied) || 0 }));
    const top = Math.max(1, ...data.map((d) => d.n));
    parts.push(h("div", { class: "section-title" }, h("h2", null, "Applications per week")),
      h("div", { class: "card", style: "padding-bottom:12px" }, h("div", { class: "weeks", role: "img", "aria-label": "Applications per week: " + data.map((d) => `${d.label} ${d.n}`).join(", ") },
        data.map((d) => h("div", { class: "wk", title: `${d.label}: ${d.n}` }, h("i", { style: `height:${(d.n / top) * 90}px` }), h("span", null, d.label))))));
  }
  box.replaceChildren(...parts);
}

function costCard(data) {
  let v = typeof data === "number" ? data : null;
  if (v == null && data && typeof data === "object") {
    v = firstNum(data.average_usd, data.per_application, data.avg_cost_usd, data.average, data.cost_per_application, data.avg, data.usd);
    if (v == null) v = firstNum(...Object.values(data));
  }
  const n = data && typeof data === "object" ? firstNum(data.applications, data.count, data.n) : null;
  return h("div", { class: "card card-pad" },
    h("div", { class: "bignum" }, v == null ? "n/a" : new Intl.NumberFormat(undefined, { style: "currency", currency: "USD", minimumFractionDigits: 2 }).format(v)),
    h("div", { class: "muted", style: "margin-top:6px" }, "average cost per application"),
    n != null ? h("div", { class: "help", style: "margin-top:4px" }, `Across ${n} ${n === 1 ? "application" : "applications"}`) : null);
}

// ------------------------------------------------------------------ activity

async function activityScreen(page, c) {
  const A = { runs: [], open: null, log: "", loaded: false, error: "" };
  page.append(head("Activity", "Searches, applications and email checks, with their logs."));
  const box = h("div", null, skeletons(3));
  page.append(box);

  async function load() {
    const r = await api("GET", "/runs?limit=50");
    A.runs = r.ok ? listOf(r.data) : [];
    A.error = r.ok ? "" : r.error;
    A.loaded = true;
    if (A.open) await loadLog();
    render();
  }
  async function loadLog() {
    const r = await api("GET", `/runs/${encodeURIComponent(A.open)}/log`);
    A.log = r.ok ? (typeof r.data === "string" ? r.data : "") : "The log could not be loaded. " + r.error;
  }
  function render() {
    if (A.error && !A.runs.length) { box.replaceChildren(notice(A.error, "error")); return; }
    if (!A.runs.length) {
      box.replaceChildren(empty("activity", "Nothing has run yet", "Start a search and its progress shows up here, with a full log.", h("button", { class: "btn primary", onclick: () => startSweep() }, "Search now")));
      return;
    }
    box.replaceChildren(h("div", { class: "card" }, A.runs.map((r) => {
      const open = A.open === r.id;
      const btn = h("button", { class: "run", "aria-expanded": String(open), onclick: async () => {
        A.open = open ? null : r.id; A.log = "";
        if (A.open) { render(); await loadLog(); }
        render();
      } },
        statusPill(r.status),
        h("span", { class: "sum" }, h("strong", null, KIND[r.kind] || humanize(r.kind || "Job")), r.summary ? ` · ${r.summary}` : r.status === "running" ? " · In progress" : ""),
        h("span", { class: "when" }, r.status === "running" ? "started " + ago(r.started_at) : ago(r.finished_at || r.started_at)));
      return h("div", null, btn, open ? h("pre", { class: "log", tabindex: "0", "aria-label": "Run log" }, A.log || "No log lines yet.") : null);
    })));
  }
  await load();
  c.onTick = (st, kinds) => { if (kinds.length || A.runs.some((r) => r.status === "running")) load(); };
  c.onRunDone = load;
}

// ------------------------------------------------------------------ start

buildNav();
window.addEventListener("hashchange", route);
document.addEventListener("keydown", (e) => { if (e.key === "Escape") navEl.classList.remove("open"); });
route().then(tick);
