"""A tiny PDF writer for tests: lines of Helvetica text, one page, no dependencies.

Used to make a fictional resume (Alex Rivera) to import, and to make a page with a planted
fabricated line for the provenance check. Text is Latin-1 only.
"""
from __future__ import annotations


def _esc(s: str) -> str:
    return s.replace("\\", "\\\\").replace("(", "\\(").replace(")", "\\)")


def make_pdf(lines: list[str], path: str, size: int = 10, leading: int = 13) -> str:
    """Write `lines` top to bottom on one Letter page (long lines are not wrapped)."""
    ops = ["BT", f"/F1 {size} Tf", f"{leading} TL", "50 750 Td"]
    for ln in lines:
        ops.append(f"({_esc(ln.encode('latin-1', 'replace').decode('latin-1'))}) Tj T*")
    ops.append("ET")
    stream = "\n".join(ops).encode("latin-1")
    objs = [
        b"<< /Type /Catalog /Pages 2 0 R >>",
        b"<< /Type /Pages /Kids [3 0 R] /Count 1 >>",
        b"<< /Type /Page /Parent 2 0 R /MediaBox [0 0 612 792] /Contents 4 0 R "
        b"/Resources << /Font << /F1 5 0 R >> >> >>",
        b"<< /Length " + str(len(stream)).encode() + b" >>\nstream\n" + stream + b"\nendstream",
        b"<< /Type /Font /Subtype /Type1 /BaseFont /Helvetica /Encoding /WinAnsiEncoding >>",
    ]
    out = bytearray(b"%PDF-1.4\n")
    offsets = []
    for i, body in enumerate(objs, 1):
        offsets.append(len(out))
        out += f"{i} 0 obj\n".encode() + body + b"\nendobj\n"
    xref = len(out)
    out += f"xref\n0 {len(objs) + 1}\n".encode() + b"0000000000 65535 f \n"
    for off in offsets:
        out += f"{off:010d} 00000 n \n".encode()
    out += f"trailer\n<< /Size {len(objs) + 1} /Root 1 0 R >>\nstartxref\n{xref}\n%%EOF\n".encode()
    with open(path, "wb") as f:
        f.write(bytes(out))
    return path


ALEX_RESUME = [
    "ALEX RIVERA",
    "Toronto, ON | 555-0100 | alex.rivera@example.com | github.com/example",
    "EDUCATION",
    "Example University - Toronto, ON",
    "BEng Computer Engineering                                  Sep 2024 - Apr 2028",
    "Relevant coursework: Data Structures, Operating Systems, Digital Logic",
    "EXPERIENCE",
    "Software Intern, Northwind Labs                            May 2026 - Aug 2026",
    "- Built a REST API in Python and FastAPI that cut report generation time from 40 seconds to 6 seconds",
    "- Wrote 120 unit tests with pytest and set up continuous integration on GitHub Actions",
    "- Migrated three internal tools from SQLite to PostgreSQL without downtime",
    "Teaching Assistant, Example University                     Sep 2025 - Dec 2025",
    "- Ran weekly labs on digital logic for 60 first-year students",
    "- Graded assignments and held office hours for Verilog and FPGA design",
    "PROJECTS",
    "Smart Plant Monitor | Arduino, C++",
    "- Built a soil moisture sensor network on Arduino that waters plants automatically",
    "- Wrote the firmware in C++ and logged readings to a local SQLite database",
    "Budget Tracker | React, TypeScript",
    "- Built a budgeting web app in React and TypeScript used by 25 classmates",
    "- Added CSV import and a monthly spending chart",
    "TECHNICAL SKILLS",
    "Languages: Python, C++, TypeScript, SQL, Verilog",
    "Tools: FastAPI, React, PostgreSQL, Git, Docker, Arduino",
    "LEADERSHIP",
    "Robotics Club, Example University                         Sep 2024 - Present",
    "- Led the electronics sub-team of 8 students building a competition robot",
]
