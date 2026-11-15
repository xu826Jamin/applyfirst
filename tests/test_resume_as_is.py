"""apply.resume_tailoring = as-is: the person's own file goes out untouched, under their name."""
import os
import time

import pytest

from applyfirst import config
from applyfirst.resume import builder


def _settings(fields=("software",)):
    s = config.load_settings()
    s["apply"]["resume_tailoring"] = "as-is"
    s["search"]["fields"] = list(fields)
    config.save_settings(s)
    return s


def test_latest_import_is_sent_unchanged_with_their_name(alex):
    s = _settings()
    imp = builder.resumes_dir() / "imports"
    imp.mkdir(parents=True, exist_ok=True)
    (imp / "20260101-000000-old.pdf").write_bytes(b"%PDF-old")
    time.sleep(0.02)
    newer = imp / "20260102-000000-new.pdf"
    newer.write_bytes(b"%PDF-new exact bytes")
    os.utime(newer, (time.time() + 5, time.time() + 5))
    path = builder.resume_for({"field": "software"}, s)
    assert os.path.basename(path) == "Alex_Rivera_Resume.pdf"
    assert open(path, "rb").read() == b"%PDF-new exact bytes"


def test_field_file_beats_default(alex):
    s = _settings(("software", "hardware"))
    own = builder.resumes_dir() / "own"
    own.mkdir(parents=True, exist_ok=True)
    (own / "default.pdf").write_bytes(b"%PDF-default")
    (own / "hardware.pdf").write_bytes(b"%PDF-hardware")
    assert open(builder.resume_for({"field": "hardware"}, s), "rb").read() == b"%PDF-hardware"
    assert open(builder.resume_for({"field": "software"}, s), "rb").read() == b"%PDF-default"


def test_no_file_says_what_to_do(alex):
    s = _settings()
    with pytest.raises(builder.NoOwnResume, match="Upload your resume"):
        builder.resume_for({"field": "software"}, s)
