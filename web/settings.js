// Settings screen: every key of the settings document as a plain control, grouped,
// with the matching warning shown inline while that option is on.
import {
  S, h, api, icon, notice, toast, loadSettings, scheduleSave, onSaved, deepGet, leafPaths, defFor, groupFor,
  GROUP_ORDER, SETTING_DEFS, settingControl, warningActive, inputControl, skeletons,
} from "./lib.js";

const PASSWORD_AFTER = "tracker.email.username";

function visible(def, settings) {
  const cond = def.showIf;
  if (!cond) return true;
  if (Array.isArray(cond)) return deepGet(settings, cond[0]) === cond[1];
  return !!deepGet(settings, cond);
}

export async function settingsScreen(page) {
  const saved = h("span", { class: "saved", "aria-live": "polite" });
  page.append(
    h("div", { class: "page-head" },
      h("div", null, h("h1", null, "Settings"), h("p", null, "Change anything here and it is saved straight away.")),
      h("div", { class: "head-actions" }, saved, h("a", { class: "btn", href: "#/profile" }, icon("profile", 16), "Your profile")),
    ),
  );
  const body = h("div", null, skeletons(4));
  page.append(body);

  const settings = await loadSettings(true);
  if (!settings) {
    body.replaceChildren(
      notice(S.settingsError || "Settings could not be loaded.", "error"),
      h("div", { style: "margin-top:12px" }, h("button", { class: "btn", onclick: () => location.reload() }, "Try again")),
    );
    return;
  }

  let timer;
  const off = onSaved((ok) => {
    if (!saved.isConnected) return off();
    saved.textContent = ok ? "Saved" : "";
    clearTimeout(timer);
    timer = setTimeout(() => (saved.textContent = ""), 2200);
  });

  // Order: known settings in their defined order, then anything new the app added.
  const leaves = new Set(leafPaths(settings));
  const known = Object.keys(SETTING_DEFS).filter((p) => leaves.has(p));
  const extra = [...leaves].filter((p) => !SETTING_DEFS[p]);
  const groups = new Map(GROUP_ORDER.map((g) => [g, []]));
  for (const p of [...known, ...extra]) groups.get(groupFor(p)).push(p);

  const rows = [];
  const refresh = () => {
    for (const r of rows) {
      r.el.hidden = !visible(r.def, settings);
      if (r.warn) r.warn.hidden = !(r.el.hidden === false && warningActive(r.path, deepGet(settings, r.path)));
    }
  };
  const changed = () => { refresh(); scheduleSave(); };

  const sections = [];
  for (const [name, paths] of groups) {
    if (!paths.length) continue;
    const card = h("div", { class: "card" });
    for (const path of paths) {
      const def = defFor(path, deepGet(settings, path));
      const wide = def.type === "multi" || def.type === "tags";
      const inline = def.type === "toggle";
      const warnText = S.warnings[path];
      const warn = warnText ? h("div", { class: "warn-line" }, notice(warnText)) : null;
      const el = h("div", { class: "setting" + (inline ? " inline" : "") + (wide ? " wide" : ""), "data-setting": path },
        h("div", null, h("div", { class: "lab" }, def.label), def.help ? h("div", { class: "help" }, def.help) : null),
        h("div", { class: "ctl" }, settingControl(path, def, settings, changed)),
        warn,
      );
      rows.push({ el, def, path, warn });
      card.append(el);
      if (path === PASSWORD_AFTER) {
        const pw = passwordRow();
        rows.push({ el: pw, def: SETTING_DEFS["tracker.email.imap_host"], path: "@pw" });
        card.append(pw);
      }
    }
    const section = h("section", { class: "sgroup", id: "g-" + name.replace(/\W+/g, "-") }, h("h2", null, name), card);
    sections.push([name, section]);
  }
  refresh();

  const jump = h("div", { class: "jump" }, sections.map(([name, el]) =>
    h("button", { type: "button", class: "pick", "aria-pressed": "false", onclick: () => el.scrollIntoView({ behavior: "smooth", block: "start" }) }, name)));
  const models = h("datalist", { id: "models" }, ["sonnet", "opus", "haiku"].map((m) => h("option", { value: m })));
  body.replaceChildren(jump, ...sections.map(([, el]) => el), models);
}

// The mail password is write-only: it is sent to the secrets store and never shown back.
function passwordRow() {
  const pill = h("span", { class: "pill" }, "Checking");
  const refreshState = async () => {
    const r = await api("GET", "/secrets");
    if (r.ok && r.data) {
      S.secrets = r.data;
      const set = !!r.data.imap_password;
      pill.textContent = set ? "A password is saved" : "Not set";
      pill.className = "pill " + (set ? "good" : "");
    } else {
      pill.textContent = "";
    }
  };
  refreshState();
  let value = "";
  const input = inputControl({ value: "", type: "password", onChange: (v) => (value = v), label: "Email app password", placeholder: "Paste an app password" });
  const btn = h("button", { type: "button", class: "btn", onclick: async () => {
    if (!value) { toast("Type the password first.", { error: true }); return; }
    btn.disabled = true;
    const r = await api("PUT", "/secrets/imap_password", { value });
    btn.disabled = false;
    if (r.ok) { input.value = ""; value = ""; toast("Password saved on this computer."); refreshState(); }
    else toast("Password was not saved. " + r.error, { error: true });
  } }, "Save password");
  return h("div", { class: "setting" },
    h("div", null, h("div", { class: "lab" }, "Email password"), h("div", { class: "help" }, "Use an app password if your provider offers one. It stays on this computer and is never shown again."), h("div", { style: "margin-top:6px" }, pill)),
    h("div", { class: "ctl row" }, input, btn),
  );
}
