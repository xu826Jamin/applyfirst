"""A skills row typed by hand as a list must render and must pass the line check."""
from applyfirst.resume import tailor


def test_hand_typed_skills_list_is_expanded():
    entries = [{"section": "skills", "title": "Languages", "org": "", "text": "Python, SQL; Rust", "dates": ""}]
    chosen = [{"section": "experience", "selected": [{"text": "Built a Python and SQL reporting tool", "tags": ["python", "sql"]}]}]
    groups = dict(tailor.pick_skills(entries, chosen, set()))
    assert "Languages" in groups
    assert "Python" in groups["Languages"] and "SQL" in groups["Languages"]
    assert "Rust" not in groups["Languages"]  # not used by any line on the page


def test_one_term_rows_still_work():
    entries = [{"section": "skills", "title": "Python", "org": "Languages", "text": "", "dates": ""}]
    chosen = [{"section": "experience", "selected": [{"text": "Wrote Python scripts", "tags": ["python"]}]}]
    assert dict(tailor.pick_skills(entries, chosen, set())) == {"Languages": ["Python"]}
