"""workday_fill.js: label matching is where it goes wrong, so it is tested with node."""
import json
import shutil
import subprocess
from pathlib import Path

import pytest

JS = Path(__file__).resolve().parent.parent / "applyfirst" / "apply" / "workday_fill.js"
node = shutil.which("node")
pytestmark = pytest.mark.skipif(node is None, reason="node is not installed")


def run_node(code: str):
    script = f"const m = require({json.dumps(str(JS))});\n{code}"
    p = subprocess.run([node, "-e", script], capture_output=True, text=True, encoding="utf-8", timeout=30)
    assert p.returncode == 0, p.stderr
    return json.loads(p.stdout)


def test_script_parses():
    p = subprocess.run([node, "--check", str(JS)], capture_output=True, text=True)
    assert p.returncode == 0, p.stderr


LABELS = {
    "First Name*": "firstName",
    "Last Name": "lastName",
    "Email Address": "email",
    "Phone Number": "phone",
    "Phone Device Type": "phoneDeviceType",
    "Country Phone Code": None,
    "Phone Extension": None,
    # question wording that contains a short identity key
    "Are you legally authorized to work in the United States?": "workAuth",
    "Are you legally authorized to work in this country?": "workAuth",
    "Will you now or in the future require sponsorship to work in Canada?": "sponsorship",
    "Ethnicity": "race",
    "Race / Ethnicity": "race",
    "Please describe the resource you would need": None,
    "How Did You Hear About Us?": "howHeard",
    "What is the maximum GPA that can be achieved at your school?": "gpaScale",
    "Preferred correspondence and document language": "correspondenceLanguage",
    "Language": "language",
    "Start Date Attended": "schoolStart",
    "Earliest start date": "startDate",
    "Are you willing to relocate?": "relocate",
    "Expected salary": "salary",
    "City": "city",
    "State / Province": "state",
    "Country": "country",
    "Postal Code": "postalCode",
    "School or University": "school",
    "Degree": "degree",
    "Field of Study": "fieldOfStudy",
    "Gender": "gender",
    "Veteran Status": "veteran",
    "Disability Status": "disability",
    "Have you previously worked for us?": "previouslyWorked",
}


def test_label_matching_table():
    got = run_node(f"console.log(JSON.stringify({json.dumps(list(LABELS))}.map(m.wdMatchKey)))")
    for (label, want), have in zip(LABELS.items(), got):
        assert have == want, f"{label!r} -> {have!r}, wanted {want!r}"


def test_country_in_label_and_values():
    out = run_node("""
      const a = {defaultCountry: "CA",
                 workAuth: {CA: {authorized: "Yes", sponsorship: "No"}, US: {authorized: "No", sponsorship: "Yes"}},
                 demographics: {gender: "", race: "Asian"}};
      console.log(JSON.stringify([
        m.wdCountryInLabel("authorized to work in the United States"),
        m.wdCountryInLabel("legally work in Canada"),
        m.wdCountryInLabel("tell us about yourself"),
        m.wdValueFor(a, "workAuth", "Authorized to work in the United States?"),
        m.wdValueFor(a, "sponsorship", "Require sponsorship to work in the U.S.?"),
        m.wdValueFor(a, "workAuth", "Authorized to work in this country?"),
        m.wdValueFor(a, "workAuth", "Authorized to work in Germany?") === undefined,
        m.wdValueFor(a, "gender", "Gender") === m.WD_DECLINE,
        m.wdValueFor(a, "race", "Race"),
        m.wdValueFor(a, "veteran", "Veteran") === undefined,
      ]))
    """)
    assert out == ["US", "CA", None, "No", "Yes", "Yes", True, True, "Asian", True]



def test_wdfill_fills_text_and_dropdown_and_declines_demographics():
    out = run_node(r"""
      const events = [];
      function mkEl(tag, attrs = {}) {
        const el = {tagName: tag, attrs, children: [], value: "", checked: false, textContent: attrs.text || "",
          getAttribute(k) { return this.attrs[k] === undefined ? null : this.attrs[k]; },
          dispatchEvent(e) { events.push(e.type); }, click() { if (this.onclick) this.onclick(); },
          parentElement: null};
        return el;
      }
      globalThis.Event = class { constructor(t) { this.type = t; } };
      globalThis.window = {HTMLInputElement: {prototype: {}}, HTMLTextAreaElement: {prototype: {}}};
      Object.defineProperty(window.HTMLInputElement.prototype, "value", {set(v) { this._v = v; }, get() { return this._v; }});
      // text container
      const input = mkEl("INPUT", {type: "text"});
      Object.defineProperty(input, "value", {set(v) { this._v = v; }, get() { return this._v || ""; }});
      Object.setPrototypeOf(input, window.HTMLInputElement.prototype);
      const textLabel = {textContent: "First Name*"};
      const none = () => [];
      const textBox = {querySelectorAll: none, getAttribute: (k) => k === "data-automation-id" ? "formField-legalName--firstName" : null,
        querySelector(sel) { if (sel.indexOf("label") === 0) return textLabel; if (sel.indexOf("input[type=\"text\"]") === 0) return input; return null; }};
      // dropdown container (gender, answer "" means decline)
      const opts = [{textContent: "Male", click() {}}, {textContent: "I do not wish to answer", click() { btn.textContent = "I do not wish to answer"; }}];
      const list = {querySelectorAll: () => opts};
      const btn = {textContent: "Select One", getAttribute: (k) => k === "aria-controls" ? "lb1" : null, click() {}};
      const ddLabel = {textContent: "Gender"};
      const dd = {querySelectorAll: none, getAttribute: (k) => k === "data-automation-id" ? "formField-gender" : null,
        querySelector(sel) { if (sel.indexOf("label") === 0) return ddLabel; if (sel.indexOf("button") === 0) return btn; return null; }};
      globalThis.document = {
        querySelector: (s) => s.indexOf("jobApplicationFormPage") !== -1 ? null : null,
        getElementById: (id) => id === "lb1" ? list : null,
        body: {querySelectorAll: (s) => s === "[data-automation-id]" ? [textBox, dd] : []},
      };
      globalThis.setTimeout = (f) => f();
      m.wdFill({firstName: "Alex", demographics: {gender: ""}}).then((r) => console.log(JSON.stringify(r)));
    """)
    assert out["errors"] == []
    labels = {f["label"]: f["value"] for f in out["filled"]}
    assert labels["First Name*"] == "Alex"
    assert labels["Gender"] == "I do not wish to answer"
    assert out["consent"] == [] and out["unmatched"] == []
