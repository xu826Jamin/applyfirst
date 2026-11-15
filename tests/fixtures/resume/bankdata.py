"""A fictional experience bank for Alex Rivera, written straight into the store."""
from applyfirst.resume import bank

R = bank.ROLE_PREFIX


def seed(confirmed: bool = True) -> dict:
    """Insert Alex's bank. Returns {name: entry id} for the entries."""
    c = 1 if confirmed else 0
    ids = {}

    def entry(key, section, title, org="", dates="", tags=()):
        ids[key] = bank.add({"section": section, "title": title, "org": org, "dates": dates,
                             "tags": list(tags), "confirmed": c})["id"]

    def bullet(key, text, tags=()):
        bank.add({"parent_id": ids[key], "text": text, "tags": list(tags), "confirmed": c})

    entry("edu", "education", "BEng Computer Engineering", "Example University", "Sep 2024 - Apr 2028")
    bullet("edu", "Relevant coursework: Data Structures, Operating Systems, Digital Logic")

    entry("intern", "experience", "Software Intern", "Northwind Labs", "May 2026 - Aug 2026", [R + "software"])
    bullet("intern", "Built a REST API in Python and FastAPI that cut report generation time from 40 seconds to 6 seconds",
           ["python", "fastapi", R + "software"])
    bullet("intern", "Wrote 120 unit tests with pytest and set up continuous integration on GitHub Actions",
           ["python", "git"])
    bullet("intern", "Migrated three internal tools from SQLite to PostgreSQL without downtime",
           ["sql", "postgresql"])

    entry("ta", "experience", "Teaching Assistant", "Example University", "Sep 2025 - Dec 2025", [R + "hardware"])
    bullet("ta", "Ran weekly labs on digital logic for 60 first-year students", ["verilog", R + "hardware"])
    bullet("ta", "Graded assignments and held office hours for Verilog and FPGA design", ["verilog", "fpga"])

    entry("plant", "projects", "Smart Plant Monitor", "Arduino, C++", "", [R + "hardware"])
    bullet("plant", "Built a soil moisture sensor network on Arduino that waters plants automatically",
           ["arduino", R + "hardware"])
    bullet("plant", "Wrote the firmware in C++ and logged readings to a local SQLite database", ["c++", "sql"])

    entry("budget", "projects", "Budget Tracker", "React, TypeScript", "", [R + "software"])
    bullet("budget", "Built a budgeting web app in React and TypeScript used by 25 classmates",
           ["react", "typescript", R + "software"])
    bullet("budget", "Added CSV import and a monthly spending chart", ["react"])

    entry("club", "other", "Robotics Club", "Example University", "Sep 2024 - Present")
    bullet("club", "Led the electronics sub-team of 8 students building a competition robot")

    for term, group in [("Python", "Languages"), ("C++", "Languages"), ("TypeScript", "Languages"),
                        ("SQL", "Languages"), ("Verilog", "Languages"), ("Rust", "Languages"),
                        ("FastAPI", "Tools"), ("React", "Tools"), ("PostgreSQL", "Tools"),
                        ("Git", "Tools"), ("Arduino", "Tools"), ("Docker", "Tools")]:
        entry("skill-" + term, "skills", term, group, "", [])
    return ids
