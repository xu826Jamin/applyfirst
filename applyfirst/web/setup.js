// First-run setup wizard, the profile form and the experience editor.
import {
  S, h, api, icon, notice, toast, listOf, logoMark, nextId, deepGet, deepSet, loadSettings, saveSettingsNow,
  settingControl, SETTING_DEFS, tagsControl, toggleControl, selectControl, skeletons,
} from "./lib.js";

// ------------------------------------------------------------------ profile form

const LEVELS = ["Native", "Fluent", "Professional", "Conversational", "Beginner"].map((x) => [x, x]);

function bound(profile, path, label, opts = {}) {
  const id = nextId("p");
  const value = deepGet(profile, path, "");
  const input = h("input", {
    type: opts.type || "text", id, value: value ?? "", placeholder: opts.placeholder, autocomplete: opts.autocomplete || "off",
    min: opts.min, step: opts.step,
  });
  input.addEventListener("input", () => {
    if (opts.number) deepSet(profile, path, input.value === "" ? null : Number(input.value));
    else deepSet(profile, path, input.value);
    opts.onInput && opts.onInput();
  });
  return h("div", { class: "field" }, h("label", { for: id }, label), input, opts.help ? h("div", { class: "help" }, opts.help) : null);
}

function section(title, help, ...kids) {
  return h("div", { class: "card card-pad stack" },
    h("div", null, h("h2", null, title), help ? h("p", { class: "help", style: "margin-top:2px" }, help) : null),
    ...kids);
}

export function profileForm(profile) {
  const root = h("div", { class: "stack" });

  profile.name = profile.name || {};
  profile.location = profile.location || {};
  profile.links = profile.links || {};
  profile.availability = profile.availability || {};
  profile.salary = profile.salary || {};
  profile.demographics = profile.demographics || {};
  profile.education = profile.education || [];
  profile.languages = profile.languages || [];
  profile.work_authorization = profile.work_authorization || {};
  profile.citizenship = profile.citizenship || [];

  root.append(
    section("About you", "This fills the standard boxes on every application.",
      h("div", { class: "grid two" },
        bound(profile, "name.first", "First name", { autocomplete: "given-name", placeholder: "First name" }),
        bound(profile, "name.last", "Last name", { autocomplete: "family-name", placeholder: "Last name" }),
        bound(profile, "name.preferred", "Preferred name", { help: "Optional. Used where a form asks what to call you." }),
        bound(profile, "email", "Email", { type: "email", autocomplete: "email", placeholder: "you@example.com" }),
        bound(profile, "phone", "Phone", { type: "tel", autocomplete: "tel", placeholder: "Phone number" }),
      ),
      h("div", { class: "grid four" },
        bound(profile, "location.city", "City", { placeholder: "City" }),
        bound(profile, "location.region", "State or province", { placeholder: "Ontario" }),
        bound(profile, "location.country", "Country", { placeholder: "CA", help: "Two-letter code." }),
        bound(profile, "location.postal_code", "Postal code"),
      ),
    ),
    section("Links", "Optional. Added to applications that ask.",
      h("div", { class: "grid three" },
        bound(profile, "links.linkedin", "LinkedIn", { type: "url", placeholder: "https://" }),
        bound(profile, "links.github", "GitHub", { type: "url", placeholder: "https://github.com/example" }),
        bound(profile, "links.portfolio", "Portfolio", { type: "url", placeholder: "https://" }),
      ),
    ),
    educationSection(profile),
    authSection(profile),
    section("Availability and pay", null,
      h("div", { class: "grid three" },
        bound(profile, "availability.earliest_start", "Earliest start", { type: "date" }),
        bound(profile, "salary.currency", "Currency", { placeholder: "CAD" }),
        h("div"),
        bound(profile, "salary.hourly_min", "Lowest hourly rate", { type: "number", number: true, min: 0, step: "any" }),
        bound(profile, "salary.annual_min", "Lowest yearly pay", { type: "number", number: true, min: 0, step: "any" }),
      ),
      h("div", { class: "field" },
        h("div", { class: "label" }, "Term lengths you can do, in months"),
        tagsControl({
          value: (profile.availability.term_months || []).map(String), label: "Term lengths", placeholder: "4",
          suggest: ["4", "8", "12", "16"], norm: (s) => s.replace(/\D/g, ""),
          onChange: (list) => (profile.availability.term_months = list.map(Number)),
        }),
      ),
      h("div", { class: "row" },
        toggleControl({ value: profile.availability.willing_to_relocate !== false, label: "Willing to relocate", onChange: (v) => (profile.availability.willing_to_relocate = v) }),
        h("span", null, "Willing to relocate"),
      ),
    ),
    languagesSection(profile),
    h("details", { class: "card card-pad more" },
      h("summary", null, "Optional questions some employers ask"),
      h("p", { class: "help", style: "margin:6px 0 14px" }, "Leave any blank and applications will choose \"prefer not to say\" where that option exists."),
      h("div", { class: "grid two" },
        bound(profile, "demographics.gender", "Gender"),
        bound(profile, "demographics.pronouns", "Pronouns"),
        bound(profile, "demographics.ethnicity", "Ethnicity"),
        bound(profile, "demographics.disability", "Disability"),
        bound(profile, "demographics.veteran", "Veteran status"),
      ),
    ),
  );
  return root;
}

function educationSection(profile) {
  const list = h("div");
  const draw = () => {
    list.replaceChildren();
    profile.education.forEach((e, i) => {
      list.append(h("div", { class: "edu" },
        bound(e, "school", "School"),
        bound(e, "degree", "Degree"),
        bound(e, "field", "Field of study"),
        h("button", { type: "button", class: "btn quiet small", "aria-label": `Remove education ${i + 1}`, onclick: () => { profile.education.splice(i, 1); draw(); } }, icon("trash", 16)),
        bound(e, "start", "Start", { placeholder: "2024-09" }),
        bound(e, "end", "End", { placeholder: "2028-04" }),
        bound(e, "gpa", "GPA", { placeholder: "3.6" }),
        h("div", { class: "row" },
          toggleControl({ value: !!e.current, label: "Still studying here", onChange: (v) => (e.current = v) }),
          h("span", { class: "small" }, "Current"),
        ),
      ));
    });
    if (!profile.education.length) list.append(h("p", { class: "help" }, "Nothing added yet."));
  };
  draw();
  return section("Education", null, list,
    h("div", null, h("button", { type: "button", class: "btn small", onclick: () => { profile.education.push({ school: "", degree: "", field: "", start: "", end: "", gpa: "", gpa_scale: "", current: false }); draw(); } }, icon("plus", 14), "Add school")));
}

function authSection(profile) {
  const list = h("div", { class: "stack tight" });
  const draw = () => {
    list.replaceChildren();
    for (const [code, v] of Object.entries(profile.work_authorization)) {
      list.append(h("div", { class: "row wrap" },
        h("span", { class: "pill accent", style: "min-width:40px;justify-content:center" }, code),
        h("span", { class: "row" }, toggleControl({ value: !!v.authorized, label: `Authorized to work in ${code}`, onChange: (x) => (v.authorized = x) }), h("span", { class: "small" }, "Can work here")),
        h("span", { class: "row" }, toggleControl({ value: !!v.needs_sponsorship, label: `Needs sponsorship in ${code}`, onChange: (x) => (v.needs_sponsorship = x) }), h("span", { class: "small" }, "Needs sponsorship")),
        h("button", { type: "button", class: "btn quiet small", "aria-label": `Remove ${code}`, onclick: () => { delete profile.work_authorization[code]; draw(); } }, icon("x", 14)),
      ));
    }
    const input = h("input", { type: "text", placeholder: "Country code, like CA", "aria-label": "Add a country you can work in", style: "max-width:220px" });
    const add = () => {
      const code = input.value.trim().toUpperCase();
      if (code && !profile.work_authorization[code]) profile.work_authorization[code] = { authorized: true, needs_sponsorship: false };
      draw();
    };
    input.addEventListener("keydown", (e) => { if (e.key === "Enter") { e.preventDefault(); add(); } });
    list.append(h("div", { class: "chip-add" }, input, h("button", { type: "button", class: "btn small", onclick: add }, "Add country")));
  };
  draw();
  return section("Work authorization", "Applications ask this country by country.", list,
    h("div", { class: "field" }, h("div", { class: "label" }, "Citizenship"),
      tagsControl({ value: profile.citizenship, label: "Citizenship", placeholder: "CA", norm: (s) => s.trim().toUpperCase(), onChange: (l) => (profile.citizenship = l) })));
}

function languagesSection(profile) {
  const list = h("div", { class: "stack tight" });
  const draw = () => {
    list.replaceChildren();
    profile.languages.forEach((l, i) => {
      list.append(h("div", { class: "row wrap" },
        h("div", { style: "width:200px" }, bound(l, "language", "Language")),
        h("div", { class: "field", style: "width:200px" }, h("div", { class: "label" }, "Level"),
          selectControl({ value: l.level || "Fluent", options: LEVELS, label: "Level", onChange: (v) => (l.level = v) })),
        h("button", { type: "button", class: "btn quiet small", style: "align-self:flex-end", "aria-label": `Remove language ${i + 1}`, onclick: () => { profile.languages.splice(i, 1); draw(); } }, icon("trash", 16)),
      ));
    });
  };
  draw();
  return section("Languages", null, list,
    h("div", null, h("button", { type: "button", class: "btn small", onclick: () => { profile.languages.push({ language: "", level: "Fluent" }); draw(); } }, icon("plus", 14), "Add language")));
}

// ------------------------------------------------------------------ experience editor

const SECTIONS = [["experience", "Work"], ["projects", "Projects"], ["education", "Education"], ["skills", "Skills"], ["other", "Other"]];

export function experienceEditor(initial) {
  let rows = initial.slice();
  const root = h("div");

  const rowUrl = (r) => `/resume/experience/${encodeURIComponent(r.id)}`;
  const save = async (r) => {
    const res = await api("PUT", rowUrl(r), r);
    if (!res.ok) toast("That edit was not saved. " + res.error, { error: true });
  };

  const draw = () => {
    root.replaceChildren();
    const entries = rows.filter((r) => !r.parent_id).sort((a, b) => (a.position || 0) - (b.position || 0));
    const bulletsOf = (id) => rows.filter((r) => r.parent_id === id).sort((a, b) => (a.position || 0) - (b.position || 0));
    const card = h("div", { class: "card" });
    for (const e of entries) card.append(entryCard(e, bulletsOf(e.id)));
    if (entries.length) root.append(card);
    root.append(addEntryBar());
  };

  const field = (r, key, label, placeholder) => {
    const input = h("input", { type: "text", value: r[key] || "", "aria-label": label, placeholder });
    input.addEventListener("change", () => { r[key] = input.value; save(r); });
    return input;
  };

  const entryCard = (e, bullets) => {
    const sec = (SECTIONS.find(([k]) => k === e.section) || [, e.section || "Other"])[1];
    const head = h("div", { class: "entry-head" },
      field(e, "title", "Role or project", "Role or project"),
      field(e, "org", "Organization", "Organization"),
      field(e, "dates", "Dates", "2025-05 to 2025-08"),
      h("button", { type: "button", class: "btn quiet small", "aria-label": `Remove ${e.title || "entry"}`, onclick: async () => {
        const res = await api("DELETE", rowUrl(e));
        if (res.ok) { rows = rows.filter((r) => r.id !== e.id && r.parent_id !== e.id); draw(); } else toast(res.error, { error: true });
      } }, icon("trash", 16)),
    );
    const card = h("div", { class: "entry" }, h("div", { class: "tag" }, sec), head);
    if (e.text) {
      const ta = h("textarea", { "aria-label": "Text", style: "margin-top:8px" }, e.text);
      ta.addEventListener("change", () => { e.text = ta.value; save(e); });
      card.append(ta);
    }
    const ul = h("ul", { class: "bullets" });
    for (const b of bullets) {
      const ta = h("textarea", { "aria-label": "Bullet", rows: 2 }, b.text || "");
      ta.addEventListener("change", () => { b.text = ta.value; save(b); });
      ul.append(h("li", null, ta,
        h("button", { type: "button", class: "btn quiet small", "aria-label": "Remove bullet", onclick: async () => {
          const res = await api("DELETE", rowUrl(b));
          if (res.ok) { rows = rows.filter((r) => r.id !== b.id); draw(); } else toast(res.error, { error: true });
        } }, icon("x", 14))));
    }
    card.append(ul, h("div", { style: "margin-top:8px" }, h("button", { type: "button", class: "btn quiet small", onclick: async () => {
      const res = await api("POST", "/resume/experience", { parent_id: e.id, section: e.section || "experience", text: "", confirmed: 0 });
      if (res.ok && res.data && res.data.id) { rows.push(res.data); draw(); }
      else if (res.ok) { await reload(); } else toast(res.error, { error: true });
    } }, icon("plus", 14), "Add a line")));
    return card;
  };

  const addEntryBar = () => {
    let sectionValue = "experience";
    return h("div", { class: "row wrap", style: "margin-top:12px" },
      selectControl({ value: sectionValue, options: SECTIONS, label: "Type of entry", onChange: (v) => (sectionValue = v) }),
      h("button", { type: "button", class: "btn", onclick: async () => {
        const res = await api("POST", "/resume/experience", { parent_id: "", section: sectionValue, title: "New entry", org: "", dates: "", text: "", confirmed: 0 });
        if (res.ok && res.data && res.data.id) { rows.push(res.data); draw(); }
        else if (res.ok) { await reload(); } else toast(res.error, { error: true });
      } }, icon("plus", 14), "Add an entry"),
    );
  };

  const reload = async () => {
    const res = await api("GET", "/resume/experience");
    if (res.ok) { rows = listOf(res.data, "experience"); draw(); }
  };

  draw();
  return { el: root, count: () => ({ entries: rows.filter((r) => !r.parent_id).length, lines: rows.filter((r) => r.parent_id).length }), reload, rows: () => rows };
}

async function confirmAll() {
  const res = await api("POST", "/resume/experience/confirm-all");
  if (!res.ok) toast("Could not confirm. " + res.error, { error: true });
  return res.ok;
}

// ------------------------------------------------------------------ wizard

const STEPS = ["Resume", "Experience", "Profile", "Targets"];
const W = { step: 0, rows: [], profile: null, prefilled: false, busy: false, error: "" };

function stepper(n) {
  return h("ol", { class: "steps", "aria-label": "Progress" }, STEPS.map((s, i) =>
    h("li", { class: i < n ? "done" : i === n ? "now" : "", "aria-current": i === n ? "step" : null }, s)));
}

export async function setupScreen(page) {
  const [p] = await Promise.all([api("GET", "/profile"), loadSettings()]);
  W.step = 0;
  W.prefilled = false;
  W.rows = [];
  W.profile = p.ok && p.data ? p.data : {};
  const shell = h("div", { class: "wiz" });
  page.append(shell);
  const draw = () => {
    shell.replaceChildren(
      h("div", { class: "wiz-brand" }, logoMark(26), "applyfirst"),
      stepper(W.step),
    );
    [stepResume, stepExperience, stepProfile, stepTargets][W.step](shell, draw);
    window.scrollTo(0, 0);
  };
  draw();
}

function stepResume(shell, draw) {
  const status = h("div", { "aria-live": "polite" });
  const input = h("input", { type: "file", accept: "application/pdf,.pdf", id: "resume-file" });
  const zone = h("label", { class: "drop", for: "resume-file" },
    icon("upload", 32), h("div", { style: "font-weight:600" }, "Choose your resume PDF"),
    h("div", { class: "help" }, "or drop it here. Claude reads it once to pull out your experience."), input);
  const upload = async (file) => {
    if (!file) return;
    status.replaceChildren(notice("Reading your resume. This can take a minute.", "info"));
    zone.style.pointerEvents = "none";
    const fd = new FormData();
    fd.append("file", file);
    const res = await api("POST", "/resume/import", fd);
    zone.style.pointerEvents = "";
    if (res.ok) {
      W.rows = listOf(res.data, "experience");
      // The import fills blank profile fields (name, email, phone, links) from the resume
      // header; reload so the Profile step shows them and saving does not blank them again.
      const fresh = await api("GET", "/profile");
      if (fresh.ok && fresh.data) W.profile = fresh.data;
      W.step = 1;
      draw();
    } else {
      status.replaceChildren(
        notice("We could not read that file. " + res.error, "error"),
        h("div", { style: "margin-top:10px" }, h("button", { class: "btn", onclick: () => { W.step = 2; draw(); } }, "Continue and add details by hand")),
      );
    }
  };
  input.addEventListener("change", () => upload(input.files[0]));
  zone.addEventListener("dragover", (e) => { e.preventDefault(); zone.classList.add("over"); });
  zone.addEventListener("dragleave", () => zone.classList.remove("over"));
  zone.addEventListener("drop", (e) => { e.preventDefault(); zone.classList.remove("over"); upload(e.dataTransfer.files[0]); });
  shell.append(
    h("h1", null, "Start with your resume"),
    h("p", { class: "lead" }, "We pull out your experience once, then use only your real lines on every application. About five minutes to set up."),
    zone, status,
    h("div", { class: "wiz-foot" },
      h("span"),
      h("button", { class: "btn quiet", onclick: () => { W.step = 2; draw(); } }, "I'll add my details by hand"),
    ),
  );
}

async function stepExperience(shell, draw) {
  shell.append(h("h1", null, "Check what we found"), h("p", { class: "lead" }, "Fix anything that is off. Only lines you confirm are ever used on an application."));
  const holder = h("div", null, skeletons(3));
  shell.append(holder);
  const res = await api("GET", "/resume/experience");
  const rows = res.ok ? listOf(res.data, "experience") : W.rows;
  W.rows = rows;
  const ed = experienceEditor(rows);
  const { entries, lines } = ed.count();
  holder.replaceChildren(
    entries ? h("p", { class: "help", style: "margin-bottom:10px" }, `${entries} entries and ${lines} lines found.`) : notice("Nothing was found in that file. Add your experience below, or continue and add it later."),
    ed.el,
  );
  const next = h("button", { class: "btn primary", onclick: async () => {
    next.disabled = true;
    if (entries || ed.rows().length) await confirmAll();
    W.step = 2;
    draw();
  } }, "Looks right, confirm all");
  shell.append(h("div", { class: "wiz-foot" },
    h("button", { class: "btn quiet", onclick: () => { W.step = 0; draw(); } }, "Back"), next));
}

function prefillEducation(profile) {
  if (W.prefilled || (profile.education || []).length) return;
  W.prefilled = true;
  const edu = W.rows.filter((r) => r.section === "education" && !r.parent_id);
  profile.education = edu.map((r) => {
    const years = String(r.dates || "").match(/\d{4}(?:[-/.]\d{1,2})?/g) || [];
    const norm = (s) => (s ? s.replace(/[/.]/g, "-").replace(/^(\d{4})-(\d)$/, "$1-0$2") : "");
    return {
      school: r.org || r.title || "", degree: r.org ? r.title || "" : "", field: "",
      start: norm(years[0]), end: years.length > 1 ? norm(years[years.length - 1]) : "",
      gpa: "", gpa_scale: "", current: /present|current|now/i.test(r.dates || ""),
    };
  });
}

function stepProfile(shell, draw) {
  prefillEducation(W.profile);
  shell.append(h("h1", null, "About you"), h("p", { class: "lead" }, "The basics every application asks for. You can change these any time."));
  const err = h("div", { "aria-live": "assertive" });
  shell.append(profileForm(W.profile), err);
  const next = h("button", { class: "btn primary", onclick: async () => {
    const p = W.profile;
    if (!(p.name.first || "").trim() || !(p.email || "").trim()) {
      err.replaceChildren(h("div", { style: "margin-top:12px" }, notice("Add your first name and email to continue.", "error")));
      return;
    }
    next.disabled = true;
    const res = await api("PUT", "/profile", p);
    next.disabled = false;
    if (!res.ok) { err.replaceChildren(h("div", { style: "margin-top:12px" }, notice("Your profile was not saved. " + res.error, "error"))); return; }
    W.profile = res.data || p;
    W.step = 3;
    draw();
  } }, "Continue");
  shell.append(h("div", { class: "wiz-foot" }, h("button", { class: "btn quiet", onclick: () => { W.step = 1; draw(); } }, "Back"), next));
}

const TARGET_KEYS = ["search.countries", "search.regions", "search.cities", "search.remote", "search.levels", "search.fields", "search.start_terms"];

function stepTargets(shell, draw) {
  shell.append(h("h1", null, "What are you looking for?"), h("p", { class: "lead" }, "We check thousands of company career pages and keep only what fits. Narrow it down now, change it any time."));
  const settings = S.settings;
  if (!settings) {
    shell.append(notice(S.settingsError || "Settings could not be loaded.", "error"), h("div", { class: "wiz-foot" }, h("button", { class: "btn", onclick: () => location.reload() }, "Try again")));
    return;
  }
  const form = h("div", { class: "card card-pad stack" });
  for (const path of TARGET_KEYS) {
    const def = SETTING_DEFS[path];
    form.append(h("div", { class: "field" }, h("div", { class: "label" }, def.label), settingControl(path, def, settings), h("div", { class: "help" }, def.help)));
  }
  const err = h("div", { "aria-live": "assertive" });
  const go = h("button", { class: "btn primary big", onclick: async () => {
    if (!(settings.search.countries || []).length) {
      err.replaceChildren(h("div", { style: "margin-top:12px" }, notice("Add at least one country so we know where to look.", "error")));
      return;
    }
    go.disabled = true;
    go.textContent = "Starting your search...";
    const saved = await saveSettingsNow();
    const run = saved ? await api("POST", "/sources/sweep", {}) : { ok: false, error: "" };
    go.disabled = false;
    go.textContent = "Find jobs";
    if (saved && run.ok) {
      toast("Searching now. Matches appear on this page as they are found.");
      location.hash = "#/jobs";
    } else if (saved) {
      err.replaceChildren(h("div", { style: "margin-top:12px" }, notice("Your choices are saved, but the search did not start. " + run.error, "error"),
        h("div", { style: "margin-top:10px" }, h("a", { class: "btn", href: "#/jobs" }, "Go to Jobs"))));
    }
  } }, "Find jobs");
  shell.append(form, err, h("div", { class: "wiz-foot" }, h("button", { class: "btn quiet", onclick: () => { W.step = 2; draw(); } }, "Back"), go));
}

// ------------------------------------------------------------------ profile page

export async function profileScreen(page) {
  page.append(h("div", { class: "page-head" }, h("div", null, h("h1", null, "Your profile"), h("p", null, "What applications say about you, and the experience lines your resumes are built from."))));
  const body = h("div", null, skeletons(3));
  page.append(body);
  const [p, ex] = await Promise.all([api("GET", "/profile"), api("GET", "/resume/experience")]);
  if (!p.ok) { body.replaceChildren(notice("Your profile could not be loaded. " + p.error, "error")); return; }
  const profile = p.data;
  const saved = h("span", { class: "saved", "aria-live": "polite" });
  const btn = h("button", { class: "btn primary", onclick: async () => {
    btn.disabled = true;
    const res = await api("PUT", "/profile", profile);
    btn.disabled = false;
    if (res.ok) { saved.textContent = "Saved"; setTimeout(() => (saved.textContent = ""), 2200); }
    else toast("Your profile was not saved. " + res.error, { error: true });
  } }, "Save profile");
  const ed = experienceEditor(ex.ok ? listOf(ex.data, "experience") : []);
  body.replaceChildren(
    profileForm(profile),
    h("div", { class: "row", style: "margin-top:16px" }, btn, saved),
    h("div", { class: "section-title" }, h("h2", null, "Your experience"),
      h("button", { class: "btn small", onclick: async () => { if (await confirmAll()) { toast("All lines confirmed."); ed.reload(); } } }, icon("check", 14), "Confirm all")),
    ex.ok ? null : notice("Your experience could not be loaded. " + ex.error),
    ed.el,
    h("div", { class: "section-title" }, h("a", { class: "btn", href: "#/setup" }, icon("upload", 16), "Import a new resume")),
  );
}
