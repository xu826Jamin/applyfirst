"""Command line: `applyfirst serve` opens the interface; the rest are for scheduled runs."""
from __future__ import annotations

import argparse
import sys
import webbrowser


def main(argv: list[str] | None = None) -> int:
    ap = argparse.ArgumentParser(prog="applyfirst")
    sub = ap.add_subparsers(dest="cmd")
    s = sub.add_parser("serve", help="open the interface in your browser")
    s.add_argument("--port", type=int, default=8765)
    s.add_argument("--no-browser", action="store_true")
    sub.add_parser("sweep", help="find new postings now")
    a = sub.add_parser("apply", help="apply to the approved queue now")
    a.add_argument("--limit", type=int, default=None)
    sub.add_parser("sync", help="read replies from your email now")
    sub.add_parser("daily", help="sweep, apply (if auto mode) and sync; for a scheduler")
    args = ap.parse_args(argv)

    if args.cmd in (None, "serve"):
        import uvicorn

        port = getattr(args, "port", 8765)
        if not getattr(args, "no_browser", False):
            webbrowser.open(f"http://127.0.0.1:{port}/")
        uvicorn.run("applyfirst.server:app", host="127.0.0.1", port=port, log_level="warning")
        return 0

    from . import jobs

    def run(kind: str, fn) -> bool:
        rid, summary, ok = jobs.run_now(kind, fn)
        print(f"{kind}: {summary}")
        return ok

    ok = True
    if args.cmd in ("sweep", "daily"):
        from .sources import sweep

        ok &= run("sweep", sweep)
    if args.cmd == "apply" or args.cmd == "daily":
        from . import config
        from .apply import apply_queue

        if args.cmd == "apply" or config.get(config.load_settings(), "apply.mode") == "auto":
            ok &= run("apply", lambda rid: apply_queue(rid, limit=getattr(args, "limit", None)))
    if args.cmd in ("sync", "daily"):
        from .tracker import sync

        ok &= run("sync", sync)
    return 0 if ok else 1


if __name__ == "__main__":
    sys.exit(main())
