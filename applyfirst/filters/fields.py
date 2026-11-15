"""Which field a posting is in: a keyword classifier per field.

The software and hardware sets are the private pipeline's TECH_RE (the whole computer
engineering title space: FPGA, ASIC, RTL, DSP, controls, DevOps, photonics, French words),
the other fields are reasonable sets in the same style. A posting can sit in several fields
("Machine Learning Software Engineer" is software and data-ml).

Calibration rules carried over:
  * A hard-engineering word overrides an off-field word: "Software Engineer, Financial Crimes
    Platform" is software even though 'financial' is a finance word. A posting is kept when ANY
    field found in its title is one the user chose.
  * Widening a keyword list needs a precision look: the first live run of a wide gate let in a
    Delivery Driver Apprentice, a Student Networking Event and a Financial Governance and
    Controls Analyst. Fields that are not on the list at all live under 'other', so a user who
    did not pick 'other' never sees them.
  * A title with no field word gives no field from the title; the description can then decide,
    only when one field clearly dominates. Otherwise the field is unknown and the posting is not
    removed: silence is not a different profession.
"""
from __future__ import annotations

import re

FIELDS = ["software", "hardware", "data-ml", "quant", "product", "design", "it-security",
          "research", "mechanical", "electrical", "civil", "business", "finance", "marketing",
          "sales", "operations", "other"]

FIELD_LABEL = {
    "software": "software", "hardware": "hardware", "data-ml": "data and machine learning",
    "quant": "quantitative", "product": "product", "design": "design",
    "it-security": "IT and security", "research": "research", "mechanical": "mechanical",
    "electrical": "electrical", "civil": "civil", "business": "business", "finance": "finance",
    "marketing": "marketing", "sales": "sales", "operations": "operations", "other": "other",
}


def _rx(pattern: str) -> re.Pattern:
    return re.compile(r"\b(?:" + pattern + r")", re.I)


_PATTERNS: dict[str, str] = {
    "software": (
        r"software|swe\b|sde\b|developers?\b|dev\b|programm(?:er|ers|ing)\b|backend|back-end|"
        r"back\s+end|frontend|front-end|front\s+end|full[\s-]?stack|web\s+(?:dev\w*|engineer\w*|"
        r"applications?)|mobile\b|ios\b|android\b|devops|devsecops|sre\b|site\s+reliability|"
        r"platform\s+(?:engineer\w*|developer|software)|infrastructure\s+(?:engineer\w*|software)|"
        r"cloud\b|compiler|kernel|firmware|embedded|systems?\s+(?:engineer\w*|software|developer|"
        r"programming)|applications?\s+(?:engineer\w*|developer)|game\s+(?:dev\w*|engineer\w*|"
        r"programm\w+)|graphics\b|gpu\b|api\b|saas\b|qa\b|quality\s+assurance|test\s+(?:engineer\w*|"
        r"automation|developer)|sdet|test\s+automation|automation\s+(?:engineer\w*|developer)|"
        r"computer\s+(?:science|engineer\w*)|solutions?\s+engineer\w*|data\s+engineer\w*|"
        r"machine\s+learning\s+engineer\w*|logiciel|d[eé]veloppeu\w+|informatique|"
        r"programmeu\w+|(?-i:TI)\b|blockchain|web\s+developer|ux\s+engineer"),
    "hardware": (
        r"hardware|fpga|asic\b|rtl\b|vlsi|silicon|semiconductor|chip\b|soc\s+(?:design|verification)|"
        r"verilog|vhdl|digital\s+design|physical\s+design|(?:ic|pcb|analog|physical|chip|layout)\s+"
        r"(?:layout|design)\w*|mixed[\s-]?signal|analog\b|pcb\b|embedded|firmware|photonic\w*|"
        r"dsp\b|signal\s+processing|wireless\b|rf\b|antenna\w*|circuit\w*|board\s+design|"
        r"mat[eé]riel|computer\s+engineer\w*|(?:design|hardware|silicon|rtl|asic|fpga|system|"
        r"pre-?silicon|post-?silicon)\s+(?:validation|verification)|verification\s+engineer\w*|"
        r"validation\s+engineer\w*|bring-?up|memory\s+(?:design|circuit)|power\s+integrity|"
        r"signal\s+integrity|robotics?\b|mechatronic\w*|iot\b|instrumentation|device\s+(?:engineer\w*|"
        r"physics)|optical|optics|quantum"),
    "data-ml": (
        r"data\s+(?:scien\w*|analy\w*|engineer\w*|platform|infrastructure|visuali\w*|quality|"
        r"intern\w*|science)|machine\s*learning|ml\b|ai\b|artificial\s+intelligence|deep\s+learning|"
        r"nlp\b|natural\s+language|computer\s+vision|llm\b|generative|analytics?\b|"
        r"business\s+intelligence|bi\s+(?:analyst|developer|engineer)|statistic\w*|mlops|"
        r"applied\s+scientist|research\s+scientist|big\s+data|etl\b|reinforcement\s+learning|"
        r"donn[eé]es|intelligence\s+artificielle|data\b"),
    "quant": (
        r"quant\w*|trading|trader|derivatives?|algorithmic|algo\s+trad\w*|market\s+making|"
        r"systematic|strats?\b|portfolio\s+(?:manager|construction)|risk\s+(?:quant|model\w*)|"
        r"hft\b|high[\s-]frequency|volatility|stochastic|pricing\s+(?:model\w*|quant\w*)|"
        r"options\s+(?:trad\w*|pricing)"),
    "product": (
        r"product\s+(?:manage\w*|owner|analyst|operations|marketing|management|intern\w*|co-?op|"
        r"specialist|associate|strategy|lead)|apm\b|program\s+manage\w*|technical\s+program|"
        r"scrum\s+master|business\s+analy\w*|project\s+manage\w*"),
    "design": (
        r"ux\b|ui\b|user\s+(?:experience|interface)|graphic\w*|visual\s+design\w*|brand\s+design\w*|"
        r"product\s+design\w*|interaction\s+design\w*|motion\s+design\w*|industrial\s+design\w*|"
        r"creative\b|illustrat\w*|figma|art\s+director|3d\s+(?:artist|model\w*)|animator|"
        r"video\s+editor|content\s+creator|design\s+(?:intern|co-?op|student)"),
    "it-security": (
        r"security\s+(?:engineer\w*|analyst|intern\w*|software|operations|research\w*|architect|"
        r"consultant|specialist|co-?op|developer)|cyber\s*security|cyber\b|infosec|"
        r"information\s+security|appsec|product\s+security|penetration|pentest|soc\s+analyst|"
        r"threat\b|vulnerabilit\w*|cryptograph\w*|encryption|grc\b|identity\s+(?:and|&)\s+access|"
        r"iam\b|forensic\w*|malware|red\s+team|blue\s+team|s[eé]curit[eé]|help\s*desk|"
        r"it\s+(?:support|intern\w*|analyst|technician|specialist|admin\w*|operations|co-?op|"
        r"services?)|information\s+technology|systems?\s+admin\w*|sysadmin|network\s+(?:admin\w*|"
        r"engineer\w*|operations|support|technician|security)|desktop\s+support|technical\s+support|"
        r"support\s+(?:specialist|technician|analyst)|(?-i:IT)\b"),
    "research": (
        r"research(?:er|ers)?\b|scientist|r\s*&\s*d\b|laborator\w+|lab\s+(?:assistant|intern|"
        r"technician)|ph\.?d\b|postdoc\w*|chercheu\w+|recherche|scientific|physicist|chemist|"
        r"biolog\w+|bioinformatic\w*|neuroscien\w+|genomic\w*|clinical\s+research"),
    "mechanical": (
        r"mechanical|m[eé]canique|mecanique|cad\b|solidworks|manufacturing|"
        r"product\s+development|thermal\b|hvac|fluid|aerospace|aeronautic\w*|automotive|vehicle|"
        r"machin(?:ing|ist)\b|machine\s+(?:shop|operator|design)|tooling|industrial\s+engineer\w*|mechatronic\w*|robotic\w*|"
        r"materials?\s+engineer\w*|reliability\s+engineer\w*|gd&t|fea\b|cfd\b|propulsion|"
        r"quality\s+engineer\w*|process\s+engineer\w*|production\s+engineer\w*|biomedical|"
        r"medical\s+device|mining|chemical\s+engineer\w*|petroleum|nuclear|energy\s+engineer\w*|"
        r"controls?\s+engineer\w*|plant\s+engineer\w*"),
    "electrical": (
        r"electrical|electric\b|electronics?\b|[eé]lectrique|[eé]lectronique|"
        r"power\s+(?:systems?|electronics|engineer\w*|grid|distribution)|substation|"
        r"protection\s+(?:and|&)\s+control|circuit\w*|embedded|firmware|pcb\b|analog\b|rf\b|"
        r"antenna\w*|fpga|asic\b|vlsi|controls?\s+(?:engineer\w*|systems?)|instrumentation|"
        r"automation\s+engineer\w*|utility\b|transmission\b|hydro\b|renewable\w*|battery|"
        r"test\s+engineer\w*|hardware"),
    "civil": (
        r"civil\b|structural|geotechnical|construction|infrastructure\s+engineer\w*|"
        r"transportation\s+engineer\w*|water\s+resources|hydraulic\w*|survey(?:or|ing)\b|municipal|"
        r"environmental\b|land\s+development|site\s+engineer\w*|bridge\b|highway|"
        r"building\s+(?:systems|engineer\w*)|geomatics|gis\b|urban\s+plan\w*|architectural|"
        r"building\s+architect|geolog\w+|geoscien\w+"),
    "business": (
        r"business\s+(?:analy\w*|development|operations|administration|systems?\s+analy\w*|"
        r"intern\w*)|consult\w*|strateg\w*|management\s+(?:intern\w*|trainee|co-?op)|commerce|"
        r"economi\w+|entrepreneur\w*|general\s+management|bizops|corporate\s+development|"
        r"human\s+resources|hr\b|people\s+(?:ops|operations|partner\w*|team)|talent\b|recruit\w*|"
        r"legal\b|paralegal|law\b|administrat\w+|executive\s+assistant|coordinator|office\b|"
        r"real\s+estate|manager\b"),
    "finance": (
        r"financ\w*|accounting|accountants?\b|audit\w*|tax(?:ation)?\b|treasury|investments?\b|"
        r"banking|equity\b|credit\b|lending|mortgages?\b|wealth|asset\s+management|private\s+equity|"
        r"venture\b|vc\b|fp&a|fpa\b|actuar\w+|insurance|capital\s+markets|portfolio|trading|"
        r"trader|risk\b|compliance|fraud|payments?\b|cpa\b|cfa\b|summer\s+analyst|campus\s+analyst"),
    "marketing": (
        r"marketing|growth\b|brand\b|seo\b|sem\b|social\s+media|communications?\b|"
        r"public\s+relations|pr\b|copywrit\w*|community\b|campaigns?\b|advertis\w*|"
        r"demand\s+gen\w*|lifecycle|crm\b|influencer|journalis\w*|editor\b|writer\b|"
        r"content\s+(?:creat\w+|writer|marketing|strateg\w+|manager|designer)|media\b|publicist"),
    "sales": (
        r"sales|account\s+(?:executive|manager|development)|business\s+development|bdr\b|sdr\b|"
        r"inside\s+sales|customer\s+success|solutions?\s+(?:engineer|consultant|architect)|"
        r"pre-?sales|partnerships?\b|revenue|territory|channel\s+(?:sales|partner\w*)|"
        r"go-to-market|gtm\b|customer\s+(?:support|service|experience|happiness)|"
        r"support\s+(?:agent|rep\w*)|client\s+(?:services|success|relations)"),
    "operations": (
        r"operations?\b|supply\s+chain|logistics|procurement|purchasing|planning\b|"
        r"project\s+(?:manage\w*|coordinat\w*)|program\s+(?:manage\w*|coordinat\w*)|"
        r"process\s+improvement|lean\b|six\s+sigma|continuous\s+improvement|warehouse|inventory|"
        r"fulfil+ment|production\s+(?:planner|planning|supervisor)|facilit(?:y|ies)\b|"
        r"vendor|sourcing|quality\s+(?:assurance|control|inspector)|field\s+operations"),
    # Not on the user's list at all: only a user who picks 'other' sees these.
    "other": (
        r"nurs(?:e|es|ing)\b|dietitian|pharmac\w+|dental|physician|medical\s+(?:assistant|office|"
        r"receptionist)|health\s?care|retail\b|cashier|barista|cook\b|chef\b|kitchen|restaurant|"
        r"hospitality|custodian|janitor|landscap\w*|(?:delivery|truck|forklift|bus|taxi)\s+driver|"
        r"driver\s+apprentice|teacher|teaching\s+"
        r"assistant|instructional\s+assistant|instructor|tutor|lifeguard|camp\s+counsel\w*|"
        r"counsell?or|agronom\w*|crop\b|seed\b|fish\w*|farm\w*|forestry|veterinar\w*|"
        r"electrician|plumber|carpent\w*|welder|security\s+guard|networking\s+event|"
        r"internist|intern(?:al)?\s+medicine"),
}

_COMPILED = {f: _rx(p) for f, p in _PATTERNS.items()}

# Bare 'designer' counts as design only when the title names no other discipline.
_BARE_DESIGNER = re.compile(r"\bdesigner\b", re.I)
_ENGINEERING_WORDS = re.compile(
    r"\b(?:hardware|chip|ic|asic|digital|analog|circuit|pcb|layout|rtl|mechanical|electrical|"
    r"structural|civil|process|systems?|software|fpga|rf|power)\s+(?:\w+\s+)?designer\b", re.I)

# Words that are field evidence on their own only weakly; used for the description fallback
# so one passing 'data' or 'management' cannot pick a field.
_WEAK_FOR_BODY = {"other", "business", "operations", "marketing", "data-ml", "finance", "sales",
                  "product", "design", "civil", "research", "it-security"}


def title_fields(title: str) -> list[str]:
    """Fields the title names, in FIELDS order. Empty when it names none."""
    title = title or ""
    out = [f for f in FIELDS if _COMPILED[f].search(title)]
    if "design" not in out and _BARE_DESIGNER.search(title) and not _ENGINEERING_WORDS.search(title) \
            and not out:
        out.append("design")
    return out


def body_fields(description: str, minimum: int = 4) -> list[str]:
    """The one field a description clearly dominates in, as a single-item list, or []. Needs
    at least `minimum` keyword hits and twice the runner-up, so a posting about everything is
    left unclassified."""
    text = (description or "")[:4000]
    if len(text) < 80:
        return []
    counts = {f: len(_COMPILED[f].findall(text)) for f in FIELDS}
    ranked = sorted(counts.items(), key=lambda kv: -kv[1])
    (top, n1), (_, n2) = ranked[0], ranked[1]
    if n1 < minimum or n1 < 2 * max(n2, 1):
        return []
    return [top]


def detect_fields(title: str, description: str = "") -> tuple[list[str], str]:
    """(fields, basis) where basis is 'title', 'description' or '' (nothing found)."""
    t = title_fields(title)
    if t:
        return t, "title"
    b = body_fields(description)
    if b:
        return b, "description"
    return [], ""


def label(fields: list[str]) -> str:
    return ", ".join(FIELD_LABEL.get(f, f) for f in fields)
