"""Where postings come from: employer job boards read directly, plus the browser sources the
user switches on. See docs/CONTRACTS.md.

    sweep(run_id)   read every enabled source, store new postings, close dead ones, filter
    add_manual(url) add one posting by its link
    discover(run_id) grow the board list from public directories
"""
from .boards import discover
from .run import add_manual, sweep

__all__ = ["sweep", "add_manual", "discover"]
