"""tracker: replies and what is working. See docs/CONTRACTS.md.

    sync(run_id)                      read mail over IMAP (read only), classify, place, record
    classify(subject, body, sender)   confirmation | rejection | assessment | interview | offer | other
    stats()                           interviews per application, by what the user can change
"""
from .classifier import CLASSES, classify
from .insights import stats
from .record import set_manual_outcome
from .syncer import sync

__all__ = ["CLASSES", "classify", "stats", "sync", "set_manual_outcome"]
