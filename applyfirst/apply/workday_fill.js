// workday_fill.js
// One-step filler for the CURRENT step of a Workday application (any *.myworkdayjobs.com tenant).
//
// Usage from the browser tool's JavaScript call: send this whole file, then on the same call
// append `; await wdFill(<answers JSON>)`. It returns {filled, unmatched, consent, errors}.
//
// wdFill NEVER checks a consent / terms / "I agree" / privacy checkbox and NEVER clicks a
// navigation button (Save and Continue, Next, Submit). It fills the fields on the step it is
// called on and reports back. Navigation is a separate, deliberate click.
//
// Answers object (every key optional; a missing key leaves the field in `unmatched`):
//   firstName lastName email phone phoneDeviceType city state postalCode country addressLine1
//   linkedin github citizenship clearance previouslyWorked relocate salary
//   startDate ("MM/DD/YYYY")  termLength  howHeard
//   school degree fieldOfStudy gradDate ("MM/YYYY") schoolStart ("MM/YYYY") gpa gpaScale
//   language correspondenceLanguage skills areasOfInterest
//   workAuth: { "CA": {authorized: "Yes", sponsorship: "No"}, "US": {...} }  per country code
//   defaultCountry: "CA"   (used when a work-authorization question names no country)
//   demographics: { gender, pronouns, race, veteran, disability }
//       "" means decline: the script picks the "prefer not to answer" style option.
//
// Only var and function declarations are used at the top level so the file can be sent again on
// a later step of the same application without a redeclaration error.

var WD_DECLINE = "__decline__";
var WD_DECLINE_RE = /decline|prefer not|do not wish|don't wish|not wish|choose not|rather not|do not want/i;
var WD_DEMO_KEYS = { gender: 1, pronouns: 1, race: 1, veteran: 1, disability: 1 };
var WD_CONSENT_RE = /consent|i agree|terms (of|and) (use|service)|privacy (policy|notice)|certify|acknowledge/i;

// Country names a question may mention, so one workAuth map covers every country.
var WD_COUNTRIES = [
  [/\bcanada\b|\bcanadian\b/, "CA"],
  [/united states|\bu\.s\.?a?(?![a-z])|\busa\b|\(us\)/, "US"],
  [/united kingdom|\bu\.k\b|\buk\b|great britain|england/, "GB"],
  [/\bireland\b/, "IE"],
  [/\baustralia\b/, "AU"],
  [/\bgermany\b/, "DE"],
  [/\bfrance\b/, "FR"],
  [/\bnetherlands\b/, "NL"],
  [/\bindia\b/, "IN"],
  [/\bsingapore\b/, "SG"],
  [/\bmexico\b/, "MX"],
  [/\bjapan\b/, "JP"],
];

// Keyword rules: regex on the lowercased label -> answers key. First match wins, so order
// matters. A short key hides inside longer questions ("state" in "United States", "city" in
// "Ethnicity", "source" in "resource", "phone" in "Country Phone Code"), so question-style rules
// come first, short keys carry word boundaries, and a key that must never be filled maps to null.
var WD_RULES = [
  [/first\s*name|given\s*name/, "firstName"],
  [/last\s*name|surname|family\s*name/, "lastName"],
  [/e-?mail/, "email"],
  [/phone\s*device\s*type/, "phoneDeviceType"],
  // Exclusions BEFORE the generic phone rule: "phone" also appears in "Country Phone Code" and
  // "Phone Extension", which are different fields with no answer of their own.
  [/extension/, null],
  [/country\s*phone\s*code|phone\s*code/, null],
  [/phone|mobile\s*number|telephone/, "phone"],

  // ---- question-style rules ----
  [/sponsor/, "sponsorship"],
  [/citizenship/, "citizenship"],
  [/authori[sz]ed.*work|legally.*(work|employ)|(right|eligible|permitted) to work|work (permit|authori[sz]ation)/, "workAuth"],
  [/security clearance/, "clearance"],
  [/previously (worked|employed)|former employee|worked (here|for us|at)/, "previouslyWorked"],
  [/relocat/, "relocate"],
  [/salary|compensation|pay expectation|expected pay/, "salary"],
  // "Start Date Attended" is a school field, so it is ordered above the generic start date.
  [/^first year attended|start date attended|from date/, "schoolStart"],
  [/start date|availability|available.*start|when.*available|earliest.*start/, "startDate"],
  [/term length|duration|length of (internship|co-?op)/, "termLength"],
  [/how did you hear|\bsource\b/, "howHeard"],
  // The GPA-scale question mentions "school", so it must sit above the school rule.
  [/maximum gpa|gpa scale|gpa.*can be achieved/, "gpaScale"],
  // "preferred correspondence and document language" collides with the generic language rule.
  [/correspondence.*language|preferred.*document language/, "correspondenceLanguage"],
  [/language/, "language"],
  [/gender/, "gender"],
  [/pronoun/, "pronouns"],
  [/\brace\b|ethnicity/, "race"],
  [/veteran/, "veteran"],
  [/disabilit/, "disability"],
  [/area(s)? of interest/, "areasOfInterest"],
  [/^skills?$|skills?\s*(and|&)\s*qualifications|\bskill\b/, "skills"],
  [/\bresume\b|\bcv\b/, "resume"],

  // ---- address and identity block: short, substring-prone keys ----
  [/address\s*line\s*1|street/, "addressLine1"],
  [/\bcity\b/, "city"],
  [/\b(state|province)\b/, "state"],
  [/postal|zip/, "postalCode"],
  [/^country$|country\s*\/\s*region|\bcountry\b/, "country"],
  [/linkedin/, "linkedin"],
  [/github/, "github"],
  [/school|university|institution/, "school"],
  [/^degree$|degree\s*(level|type|earned)|\bdegree\b/, "degree"],
  [/field of study|\bmajor\b/, "fieldOfStudy"],
  [/expected graduation|graduation date/, "gradDate"],
  [/current year|class standing|year in school/, "currentYear"],
  [/grade point|\bgpa\b/, "gpa"],
];

function wdMatchKey(label) {
  var l = (label || "").toLowerCase();
  for (var i = 0; i < WD_RULES.length; i++) {
    if (WD_RULES[i][0].test(l)) return WD_RULES[i][1];
  }
  return null;
}

function wdCountryInLabel(label) {
  var l = (label || "").toLowerCase();
  for (var i = 0; i < WD_COUNTRIES.length; i++) {
    if (WD_COUNTRIES[i][0].test(l)) return WD_COUNTRIES[i][1];
  }
  return null;
}

// The value for one question. Work authorization and sponsorship depend on the country the
// question names; demographics "" means decline.
function wdValueFor(answers, key, label) {
  if (key === "workAuth" || key === "sponsorship") {
    var code = wdCountryInLabel(label) || answers.defaultCountry;
    var entry = answers.workAuth && answers.workAuth[code];
    if (!entry) return undefined;
    return key === "workAuth" ? entry.authorized : entry.sponsorship;
  }
  if (WD_DEMO_KEYS[key]) {
    var d = answers.demographics || {};
    var v = d[key];
    if (v === undefined || v === null) return undefined;
    return v === "" ? WD_DECLINE : v;
  }
  return answers[key];
}

async function wdFill(answers) {
  var result = { filled: [], unmatched: [], consent: [], errors: [] };
  var sleep = function (ms) { return new Promise(function (r) { setTimeout(r, ms); }); };
  var empty = function (v) { return v === undefined || v === null || v === ""; };

  function setNativeValue(el, value) {
    // React tracks the value itself, so the native setter is needed for the change to count.
    var proto = el.tagName === "TEXTAREA" ? window.HTMLTextAreaElement.prototype : window.HTMLInputElement.prototype;
    var setter = Object.getOwnPropertyDescriptor(proto, "value").set;
    setter.call(el, value);
    el.dispatchEvent(new Event("input", { bubbles: true }));
    el.dispatchEvent(new Event("change", { bubbles: true }));
    el.dispatchEvent(new Event("blur", { bubbles: true }));
  }

  function findAllFieldContainers() {
    var root = document.querySelector('[data-automation-id="jobApplicationFormPage"]') || document.body;
    var containers = new Set();
    root.querySelectorAll("[data-automation-id]").forEach(function (el) {
      // Workday ids are prefixed ("formField-legalName--firstName"), never suffixed.
      if (/^formfield-/i.test(el.getAttribute("data-automation-id") || "")) containers.add(el);
    });
    // Radio groups often live in a fieldset with no formField wrapper.
    root.querySelectorAll("fieldset").forEach(function (el) { containers.add(el); });
    return Array.from(containers);
  }

  // The short visible text of one radio option. Workday radios carry no aria-label; the option
  // text sits in a plain element a level or two up, below the group container.
  function radioOptionLabel(radio, container) {
    var node = radio.parentElement;
    while (node && node !== container) {
      var t = node.textContent.trim();
      if (t) return t;
      node = node.parentElement;
    }
    return "";
  }

  function pickOption(options, value) {
    if (value === WD_DECLINE) {
      return options.find(function (o) { return WD_DECLINE_RE.test(o.textContent.trim()); });
    }
    var wanted = String(value).trim().toLowerCase();
    // Exact match first: "Male" is a substring of "Female". Substring only when it names one option.
    var exact = options.find(function (o) { return o.textContent.trim().toLowerCase() === wanted; });
    if (exact) return exact;
    var contains = options.filter(function (o) { return o.textContent.trim().toLowerCase().indexOf(wanted) !== -1; });
    return contains.length === 1 ? contains[0] : undefined;
  }

  async function fillText(container, label, value) {
    var input = container.querySelector('input[type="text"], input[type="tel"], input[type="email"], input:not([type]), textarea');
    if (!input || empty(value) || value === WD_DECLINE) return false;
    setNativeValue(input, String(value));
    await sleep(150);
    // A tool's success is not evidence: read the value back off the page.
    if (input.value !== String(value)) {
      result.errors.push({ label: label, error: 'field reads "' + input.value + '" after typing "' + value + '"' });
      return true;
    }
    result.filled.push({ label: label, value: String(value) });
    return true;
  }

  async function fillDropdown(container, label, value) {
    var btn = container.querySelector('button[aria-haspopup="listbox"]');
    if (!btn || empty(value)) return false;
    // A click toggles; close a listbox left open before opening it.
    if (btn.getAttribute("aria-expanded") === "true") { btn.click(); await sleep(300); }
    btn.click();
    await sleep(500);
    // Every field's listbox sits in the DOM; the button's own aria-controls names the real one.
    var listboxId = btn.getAttribute("aria-controls");
    var listbox = (listboxId && document.getElementById(listboxId)) || document.querySelector('ul[role="listbox"]');
    if (!listbox) {
      result.errors.push({ label: label, error: "dropdown listbox did not open" });
      return false;
    }
    var target = pickOption(Array.from(listbox.querySelectorAll('[role="option"]')), value);
    if (!target) { btn.click(); return false; }
    var expected = target.textContent.trim();
    target.click();
    await sleep(400);
    var shown = btn.textContent.trim();
    if (shown.toLowerCase().indexOf(expected.toLowerCase()) === -1) {
      result.errors.push({ label: label, error: 'dropdown shows "' + shown + '" after selecting "' + expected + '"' });
      return false;
    }
    result.filled.push({ label: label, value: shown });
    return true;
  }

  async function fillRadio(container, label, value) {
    var radios = Array.from(container.querySelectorAll('input[type="radio"]'));
    if (!radios.length || empty(value)) return false;
    var target = null;
    for (var i = 0; i < radios.length; i++) {
      var t = radioOptionLabel(radios[i], container).trim();
      var hit = value === WD_DECLINE ? WD_DECLINE_RE.test(t) : t.toLowerCase() === String(value).trim().toLowerCase();
      if (hit) { target = radios[i]; break; }
    }
    // Some Yes/No radios expose no option text; their DOM values are "true" and "false".
    if (!target && value !== WD_DECLINE && radios.length === 2 &&
        radios.every(function (r) { return r.value === "true" || r.value === "false"; })) {
      var v = String(value).trim().toLowerCase();
      if (v === "yes") target = radios.find(function (r) { return r.value === "true"; });
      if (v === "no") target = radios.find(function (r) { return r.value === "false"; });
    }
    if (!target) return false;
    target.click();
    await sleep(200);
    if (!target.checked) {
      result.errors.push({ label: label, error: "radio did not stay selected" });
      return true;
    }
    result.filled.push({ label: label, value: value === WD_DECLINE ? "declined" : String(value) });
    return true;
  }

  async function fillCheckbox(container, label, value) {
    var box = container.querySelector('input[type="checkbox"]');
    if (!box) return false;
    if (WD_CONSENT_RE.test(label)) { result.consent.push(label); return true; }
    if (value === undefined || value === null || value === WD_DECLINE) return false;
    var want = value === true || String(value).toLowerCase() === "yes" || String(value).toLowerCase() === "true";
    if (!!box.checked !== want) box.click();
    await sleep(150);
    result.filled.push({ label: label, value: String(!!box.checked) });
    return true;
  }

  async function fillDate(container, label, value) {
    var month = container.querySelector('[data-automation-id="dateSectionMonth-input"]');
    var day = container.querySelector('[data-automation-id="dateSectionDay-input"]');
    var year = container.querySelector('[data-automation-id="dateSectionYear-input"]');
    if (!month && !day && !year) return false;
    if (empty(value) || value === WD_DECLINE) return false;
    var parts = String(value).split("/");
    var mm, dd, yyyy;
    if (parts.length === 3) { mm = parts[0]; dd = parts[1]; yyyy = parts[2]; }
    else if (parts.length === 2) { mm = parts[0]; yyyy = parts[1]; dd = null; }
    else return false;
    if (month && mm) setNativeValue(month, mm);
    if (day && dd) setNativeValue(day, dd);
    if (year && yyyy) setNativeValue(year, yyyy);
    await sleep(200);
    result.filled.push({ label: label, value: String(value) });
    return true;
  }

  async function fillMultiselect(container, label, value) {
    var search = container.querySelector('input[data-automation-id="searchBox"], input[type="text"][role="combobox"]');
    var hasPopupList = container.querySelector('[data-automation-id="multiSelectContainer"], [data-automation-id="multiselectInputContainer"]');
    if (!search || !hasPopupList || empty(value) || value === WD_DECLINE) return false;
    var list = Array.isArray(value) ? value : [value];
    for (var i = 0; i < list.length; i++) {
      var v = String(list[i]);
      setNativeValue(search, v);
      await sleep(600);
      var listboxId = search.getAttribute("aria-controls") || search.getAttribute("aria-owns");
      var listbox = (listboxId && document.getElementById(listboxId)) || document.querySelector('ul[role="listbox"]');
      if (!listbox) { result.errors.push({ label: label, error: 'multiselect: no options for "' + v + '"' }); continue; }
      var target = pickOption(Array.from(listbox.querySelectorAll('[role="option"]')), v);
      if (!target) { result.errors.push({ label: label, error: 'multiselect: "' + v + '" not in list' }); continue; }
      target.click();
      await sleep(300);
    }
    result.filled.push({ label: label, value: list.join(", ") });
    return true;
  }

  // File inputs are listed but not filled here: the resume path is the caller's, uploaded with
  // the browser tool's file upload against the input this script reports in `unmatched`.

  var containers = findAllFieldContainers();
  for (var c = 0; c < containers.length; c++) {
    var container = containers[c];
    var label = "";
    var labelEl = container.querySelector('label, legend, [data-automation-id="richText"]');
    if (labelEl) label = labelEl.textContent.trim();
    if (!label) label = container.getAttribute("data-automation-id") || "(unlabeled)";
    var requiredMark = /\*/.test(label) || !!container.querySelector('[aria-required="true"]');

    if (container.querySelector('input[type="file"]')) {
      result.unmatched.push({ label: label, type: "file", required: requiredMark });
      continue;
    }
    if (WD_CONSENT_RE.test(label) && container.querySelector('input[type="checkbox"]')) {
      result.consent.push(label);
      continue;
    }

    var key = wdMatchKey(label);
    var value = key ? wdValueFor(answers, key, label) : undefined;
    if (!key || (empty(value) && value !== false)) {
      var type = container.querySelector('button[aria-haspopup="listbox"]') ? "dropdown"
        : container.querySelector('input[type="radio"]') ? "radio"
        : container.querySelector('input[type="checkbox"]') ? "checkbox"
        : container.querySelector('[data-automation-id="dateSectionMonth-input"]') ? "date"
        : container.querySelector('input[data-automation-id="searchBox"]') ? "multiselect"
        : "text";
      result.unmatched.push({ label: label, type: type, required: requiredMark, key: key });
      continue;
    }

    var handled = false;
    try {
      handled = (await fillDate(container, label, value))
        || (await fillDropdown(container, label, value))
        || (await fillRadio(container, label, value))
        || (await fillCheckbox(container, label, value))
        || (await fillMultiselect(container, label, value))
        || (await fillText(container, label, value));
    } catch (e) {
      result.errors.push({ label: label, error: String((e && e.message) || e) });
    }
    if (!handled) result.unmatched.push({ label: label, type: "unhandled", required: requiredMark, key: key });
  }

  return result;
}

if (typeof module !== "undefined" && module.exports) {
  module.exports = { wdFill: wdFill, wdMatchKey: wdMatchKey, wdCountryInLabel: wdCountryInLabel, wdValueFor: wdValueFor, WD_DECLINE: WD_DECLINE };
}
