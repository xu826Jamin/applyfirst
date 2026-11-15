"""Stock phrases that make a cover letter read like every other one.

Each pattern is a sentence that survives swapping the company name, which is what makes a
letter generic. Hits are reported to the user as notes and fed back to the writer on a retry;
they never invent or remove a fact.
"""
from __future__ import annotations

import re

GENERIC_RE = [
    (r"\b(innovat\w+|cutting[\s-]edge|state[\s-]of[\s-]the[\s-]art|world[\s-]class|"
     r"industry[\s-]leading|market[\s-]leader)\b", "an empty superlative"),
    (r"\b(your|the)\s+(mission|culture|values|vision)\b", "mission or culture with nothing specific"),
    (r"\bi\s+(have\s+)?(long\s+)?(admired|been\s+a\s+fan|followed\s+your)\b",
     "a claimed long-standing interest nobody can check"),
    (r"\bpassionate\s+about\b", "'passionate about' is filler"),
    (r"\bi\s+(am|'m)\s+excited\s+(to|about)\s+(join|work|the\s+opportunity)\b", "excitement with no object"),
    (r"\bgreat\s+(place\s+to\s+work|team|company)\b", "flattery with nothing specific"),
    (r"\bperfect\s+(fit|match)\b", "asserts the conclusion instead of showing it"),
    (r"\bas\s+a\s+(leader|pioneer)\s+in\b", "restates their own about page"),
]

# Always flagged: no ordinary use in an application letter.
TIER1 = [
    (r"\bleverag(e|es|ed|ing)\b", "'leverage': say what was used and for what"),
    (r"\bspearhead(s|ed|ing)?\b", "'spearhead': name the act instead"),
    (r"\bdelv(e|es|ed|ing)\b", "'delve': no content"),
    (r"\b(robust|seamless(ly)?)\b(?!\s+(mode|api))", "an unearned adjective: state the property"),
    (r"\b(meticulous(ly)?|holistic|synerg(y|ies|istic)|tapestry)\b", "resume-generator vocabulary"),
    (r"\b(pivotal|crucial|vital|integral)\s+(role|part|member)\b", "asserts importance instead of showing it"),
    (r"\b(showcas(e|es|ed|ing)|underscor(e|es|ed|ing)|exemplif(y|ies|ied))\b",
     "narrates the resume instead of stating the fact"),
    (r"\b(demonstrated\s+ability|proven\s+track\s+record|wide\s+range\s+of|valuable\s+asset|"
     r"strong\s+foundation\s+in)\b", "a boilerplate claim"),
    (r"\bin\s+today'?s\s+(fast[\s-]paced|ever[\s-]changing|rapidly\s+evolving)\b", "an essay opener"),
    (r"\bnot\s+only\b[^.]{0,80}\bbut\s+also\b", "the 'not only ... but also' cadence"),
    (r"\b(i\s+am|i'm)\s+confident\s+that\b", "confidence asserted, not shown"),
    (r"\b(align(s|ed|ing)?)\s+(perfectly\s+)?with\s+(your|the\s+(company|team))\b",
     "claims fit instead of demonstrating it"),
    (r"\bthriv(e|es|ing)\s+in\b", "a personality claim with nothing to check"),
]

# Ordinary words alone; two distinct ones in one paragraph is the signal.
TIER2 = [
    (r"\bharness(es|ed|ing)?\b", "harness"), (r"\bnavigat(e|es|ed|ing)\b", "navigate"),
    (r"\bfoster(s|ed|ing)?\b", "foster"), (r"\belevat(e|es|ed|ing)\b", "elevate"),
    (r"\bunleash(es|ed|ing)?\b", "unleash"), (r"\bstreamlin(e|es|ed|ing)\b", "streamline"),
    (r"\bempower(s|ed|ing)?\b", "empower"), (r"\bbolster(s|ed|ing)?\b", "bolster"),
    (r"\bresonat(e|es|ed|ing)\b", "resonate"), (r"\brevolutioniz(e|es|ed|ing)\b", "revolutionize"),
    (r"\bfacilitat(e|es|ed|ing)\b", "facilitate"), (r"\bunderpin(s|ned|ning)?\b", "underpin"),
    (r"\bnuanced\b", "nuanced"), (r"\bmyriad\b", "myriad"), (r"\bplethora\b", "plethora"),
    (r"\bencompass(es|ed|ing)?\b", "encompass"), (r"\bcultivat(e|es|ed|ing)\b", "cultivate"),
    (r"\becosystem\b", "ecosystem"), (r"\btransformativ(e|ely)\b|\btransformation\b", "transformative"),
    (r"\bcornerstone\b", "cornerstone"), (r"\bparamount\b", "paramount"),
    (r"\boverarching\b", "overarching"),
]


def style_findings(text: str) -> list[str]:
    """Plain-language notes on stock phrasing in `text`. Empty when it reads as written by a person."""
    notes = []
    for pattern, why in GENERIC_RE + TIER1:
        m = re.search(pattern, text, re.I)
        if m:
            notes.append(f"\"{m.group(0)}\": {why}")
    for para in re.split(r"\n\s*\n", text):
        hits = [word for pattern, word in TIER2 if re.search(pattern, para, re.I)]
        if len(hits) >= 2:
            notes.append("stock words together: " + ", ".join(hits))
    return notes
