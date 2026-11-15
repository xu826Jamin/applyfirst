"""Filters: reading level, field, term, deadline, language and eligibility out of posting text."""
import datetime as dt

import pytest

from applyfirst.filters import fields as F, levels as L, terms as T
from applyfirst.filters import classify

TODAY = dt.date(2026, 11, 15)


# ------------------------------------------------------------------ level


@pytest.mark.parametrize("title,expected", [
    ("Junior Software Developer Co-op", ["co-op"]),          # a student marker in the title wins
    ("Software Engineer Intern", ["internship"]),
    ("Senior Software Engineer", ["senior"]),
    ("Research Fellow", ["internship"]),                      # fellow programs are early career
    ("New Grad Software Engineer", ["new-grad"]),
    ("Summer Analyst 2027", ["internship"]),
    ("Software Developer II", ["mid"]),
    ("Associate Software Engineer", ["entry"]),
    ("Software Developer, Co-op (Winter 2027)", ["co-op"]),   # the term is not a second level
    ("Software Developer, Summer 2027", ["internship"]),
    ("Software Engineer", []),                                # no signal is no level
    ("Principal Responsibilities Engineer", []),              # "principal responsibilities" is not a level
])
def test_title_levels(title, expected):
    assert L.title_levels(title) == expected


def test_description_decides_when_title_is_silent():
    desc = "Join our internship program. As an intern you will write code. Interns work in teams."
    assert L.detect_levels("Software Developer", desc) == ["internship"]
    assert L.detect_levels("Software Developer", "We build things.") == []


def test_years_of_experience_ignored_on_student_postings():
    desc = "A full-time employee would need 5 years of experience, however interns are welcome."
    assert L.years_required("Software Intern", desc) is None
    assert L.years_required("Software Engineer", "Requires 5 years of experience in Python.") == 5
    assert L.detect_levels("Software Engineer", "Requires 8 years of experience.") == ["senior"]


def test_optional_years_do_not_count():
    assert L.years_required("Engineer", "3 years of experience is an asset.") is None


# ------------------------------------------------------------------ field


@pytest.mark.parametrize("title,field,not_field", [
    ("Software Engineer, Financial Crimes Platform", "software", None),
    ("Sales Engineer", "sales", "software"),
    ("Machine Learning Engineer", "data-ml", "mechanical"),
    ("FPGA Engineer Intern", "hardware", None),
    ("Quantitative Researcher Intern", "quant", None),
    ("Marketing Intern", "marketing", "software"),
    ("Mechanical Engineering Co-op", "mechanical", "software"),
    ("Delivery Driver Apprentice", "other", "software"),
    ("Student Networking Event", "other", "software"),
])
def test_title_fields(title, field, not_field):
    found = F.title_fields(title)
    assert field in found
    if not_field:
        assert not_field not in found


def test_unknown_field_is_empty_not_other():
    assert F.detect_fields("Device Driver Engineer")[0] in ([], ["software"], ["hardware"])
    assert F.detect_fields("Associate")[0] == []


# ------------------------------------------------------------------ term length


@pytest.mark.parametrize("text,expected", [
    ("8-12 month internship", [8, 12]),
    ("4 to 8 months", [4, 8]),
    ("a 12 month co-op", [12]),
    ("4/8 month term", [4, 8]),
    ("year-long internship", [12]),
    ("16-month PEY", [16]),
    ("Have you interviewed with us in the past 12 months?", []),
    ("We want 3 months of experience", []),
    ("No term stated here", []),
])
def test_term_months(text, expected):
    assert T.term_months(text) == expected


# ------------------------------------------------------------------ deadlines


def test_deadline_stated_with_year():
    d = T.extract_deadline("Applications close on March 5, 2027.", TODAY)
    assert d["date"] == "2027-03-05" and d["date_basis"] == "stated"


def test_deadline_skips_start_open_and_end_dates():
    d = T.extract_deadline("Application Opens: Jan 5, 2027. Deadline to apply is Feb 10, 2027", TODAY)
    assert d["date"] == "2027-02-10"
    d = T.extract_deadline("Position start date: May 4, 2027. Deadline: June 1, 2027", TODAY)
    assert d["date"] == "2027-06-01"


def test_deadline_without_a_year_is_inferred_and_never_stored():
    d = T.extract_deadline("apply by Feb 10", TODAY)
    assert d["date_basis"] == "inferred-year"
    assert T.stated_deadline({"description": "apply by Feb 10", "deadline": ""}, TODAY) == ""


def test_deadlines_as_a_duty_is_not_a_deadline():
    d = T.extract_deadline("You will be meeting deadlines in a fast team.", TODAY)
    assert d is None or d["date"] is None


def test_own_deadline_field_wins():
    assert T.stated_deadline({"deadline": "2027-01-31", "description": "Deadline: 2027-05-05"}) == "2027-01-31"


# ------------------------------------------------------------------ start terms


def test_start_terms():
    assert T.start_terms("Software Intern Summer 2027")[0][2] == "Summer 2027"
    assert T.start_terms("Intern", "This internship starts in May 2027")[0][1] == {5}
    fits, _ = T.start_term_fits(T.start_terms("Software Intern Summer 2027"), ["2027-05"])
    assert fits
    fits, why = T.start_term_fits(T.start_terms("Intern Fall 2027"), ["2027-05"])
    assert not fits and "Fall 2027" in why
    assert T.start_term_fits([], ["2027-05"])[0]                   # nothing stated: kept
    assert T.start_term_fits(T.start_terms("Intern Fall 2027"), [])[0]


def test_graduation_year_is_not_a_start_term():
    assert T.start_terms("Intern", "Open to students graduating in May 2028.") == []


# ------------------------------------------------------------------ language


@pytest.mark.parametrize("text,lang,expected", [
    ("French is required.", "French", "required"),
    ("French is an asset.", "French", "asset"),
    ("English is required and French is an asset.", "French", "asset"),
    ("Fluent in French and English", "French", "required"),
    ("Bilingual (English/French) preferred", "French", "asset"),
    ("Bilingue requis", "French", "required"),
    ("Spanish and English fluency required", "Spanish", "required"),
    ("Fluency in French is not required", "French", "asset"),
    ("We build compilers.", "French", ""),
])
def test_language_flag(text, lang, expected):
    assert T.language_flag(text, lang) == expected


def test_bilingual_title_means_required():
    assert T.language_flag("", "French", title="Bilingual Support Intern") == "required"


def test_french_only_posting():
    french = ("Vous serez dans une equipe qui est au coeur de nos projets pour les clients. " * 30)
    assert T.posting_written_only_in(french, "French")
    english = "You will work with our team on the projects for the clients and we are hiring. " * 30
    assert not T.posting_written_only_in(english, "French")


# ------------------------------------------------------------------ eligibility


def test_us_only_phrases():
    assert T.us_only_phrase("Must be a US citizen")
    assert T.us_only_phrase("Requires an active TS/SCI clearance")
    assert T.us_only_phrase("Government of Canada reliability status") == ""
    assert T.us_only_phrase("We welcome all applicants") == ""


def test_no_sponsorship_phrases():
    assert T.no_sponsorship_phrase("We are unable to provide visa sponsorship.")
    assert T.no_sponsorship_phrase("We will not sponsor work visas")
    assert T.no_sponsorship_phrase("Sponsorship is available") == ""


def test_school_restriction_is_found_only_for_other_schools():
    text = "Open to students enrolled at the University of Waterloo."
    assert "Waterloo" in T.school_restriction(text, ["Example University"])
    assert T.school_restriction(text, ["University of Waterloo"]) == ""
    assert T.school_restriction(text, []) == ""


# ------------------------------------------------------------------ classify()


def test_classify_fills_and_does_not_mutate():
    p = {"id": "x:1", "title": "Software Engineer Intern (Summer 2027)", "company": "Acme",
         "location": "Toronto, ON", "description": "A 4 month internship. Deadline: 2027-02-01", "level": "",
         "field": "", "term_months": None, "deadline": "", "country": ""}
    out = classify(p)
    assert out is not p and p["level"] == ""
    assert out["level"] == "internship" and out["field"] == "software"
    assert out["term_months"] == 4 and out["deadline"] == "2027-02-01"
    assert out["country"] == "CA" and out["region"] == "Ontario"


def test_classify_keeps_an_existing_value_unless_forced():
    p = {"title": "Software Engineer Intern", "level": "senior", "field": "", "description": "",
         "location": "", "deadline": "2027-01-01", "country": "US"}
    out = classify(p)
    assert out["level"] == "senior" and out["deadline"] == "2027-01-01" and out["country"] == "US"
    assert classify(p, force=True)["level"] == "internship"


def test_classify_tolerates_empty_posting():
    out = classify({})
    assert out["level"] == "" and out["field"] == ""
