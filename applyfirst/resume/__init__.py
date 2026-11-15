"""The experience bank and resume files. See docs/CONTRACTS.md.

    import_pdf(path, run_id=None)   PDF -> unconfirmed experience rows (Claude, or a plain parser)
    build(role_type=None, posting=None) -> path   one page, lines from the confirmed bank only
    verify(pdf_path) -> [problems]  every line on the PDF must trace to the bank
    resume_for(posting, settings)   follows apply.resume_tailoring
    cover_letter(posting, run_id)   None when the posting has no body

Beyond the contract: build_detailed (the checks behind a build), build_all (one resume per
field), BankEmpty (raised when nothing is confirmed), list_files.
"""
from .builder import (BankEmpty, BuildResult, build, build_all, build_detailed, list_files,  # noqa: F401
                      resume_for, verify)
from .letter import cover_letter  # noqa: F401
from .parse import import_pdf  # noqa: F401
