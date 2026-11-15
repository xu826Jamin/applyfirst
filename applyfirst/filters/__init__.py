"""Which postings a user sees, and in what order. See docs/CONTRACTS.md (filters).

classify(posting)                  fill level, field, term_months, deadline, country
evaluate(posting, settings, profile)  ("keep" | "skip", plain-language reasons)
evaluate_all(run_id=None)          evaluate every live posting and store the verdicts
order(postings, settings)          sort by queue.order_by then queue.then_by
queue(settings, view, limit)       the postings in one view, in order
"""
from .core import classify, evaluate, evaluate_all, queue
from .ordering import order

__all__ = ["classify", "evaluate", "evaluate_all", "order", "queue"]
