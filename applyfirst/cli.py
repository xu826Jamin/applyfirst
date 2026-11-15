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

        wanted = getattr(args, "port", 8765)
        port = _free_port(wanted)
        if port is None:
            print(f"Ports {wanted} to {wanted + 9} are all in use. Close the other program or run "
                  f"`applyfirst serve --port <number>`.")
            return 1
        if port != wanted:
            print(f"Port {wanted} is in use (is applyfirst already open?), so using {port}.")
        url = f"http://127.0.0.1:{port}/"
        print(f"applyfirst is running at {url}\nKeep this window open while you use it. "
              f"Press Ctrl+C to stop.")
        if not getattr(args, "no_browser", False):
            webbrowser.open(url)
        uvicorn.run("applyfirst.server:app", host="127.0.0.1", port=port, log_level="warning")
        return 0

    from . import jobs

    def run(kind: str, fn) -> bool:
        rid, summary, ok = jobs.run_now(kind, fn)
        print(f"{kind}: {summary}")
        return ok

    if args.cmd == "daily":
        from .daily import routine

        return 0 if run("daily", routine) else 1
    if args.cmd == "sweep":
        from .sources import sweep

        return 0 if run("sweep", sweep) else 1
    if args.cmd == "apply":
        from .apply import apply_queue

        return 0 if run("apply", lambda rid: apply_queue(rid, limit=args.limit)) else 1
    if args.cmd == "sync":
        from .tracker import sync

        return 0 if run("sync", sync) else 1
    return 1


def _free_port(start: int, tries: int = 10) -> int | None:
    import socket

    for port in range(start, start + tries):
        with socket.socket(socket.AF_INET, socket.SOCK_STREAM) as s:
            try:
                s.bind(("127.0.0.1", port))
                return port
            except OSError:
                continue
    return None


if __name__ == "__main__":
    sys.exit(main())
