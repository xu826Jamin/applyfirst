"""Tell the user when new matches arrive: a desktop notification, and optionally an email to
themselves. Applying first only works if they hear about a posting the hour it goes up.

Desktop notifications use what the operating system already has (PowerShell toast on
Windows, osascript on macOS, notify-send on Linux); nothing extra to install. A failure to
notify is logged on the run and never stops the sweep.
"""
from __future__ import annotations

import platform
import shutil
import smtplib
import ssl
import subprocess
from email.message import EmailMessage

from . import config, store

# PowerShell's own app id: toasts shown under it need no app registration. ASCII only (PS 5.1
# reads scripts in the system code page).
_PS_TOAST = r"""
$ErrorActionPreference = 'Stop'
[Windows.UI.Notifications.ToastNotificationManager, Windows.UI.Notifications, ContentType = WindowsRuntime] | Out-Null
$t = [Windows.UI.Notifications.ToastNotificationManager]::GetTemplateContent([Windows.UI.Notifications.ToastTemplateType]::ToastText02)
$x = $t.GetElementsByTagName('text')
$x.Item(0).AppendChild($t.CreateTextNode($env:AF_TITLE)) | Out-Null
$x.Item(1).AppendChild($t.CreateTextNode($env:AF_BODY)) | Out-Null
$n = [Windows.UI.Notifications.ToastNotification]::new($t)
$id = '{1AC14E77-02E7-4E5D-B744-2EB1AE5198B7}\WindowsPowerShell\v1.0\powershell.exe'
[Windows.UI.Notifications.ToastNotificationManager]::CreateToastNotifier($id).Show($n)
"""


def new_matches_since(started_at: str) -> list[dict]:
    return store.rows(
        "SELECT company, title, location, url FROM postings WHERE verdict='keep' "
        "AND COALESCE(user_action,'')='' AND alive=1 AND COALESCE(duplicate_of,'')='' "
        "AND first_seen_at >= ? ORDER BY first_seen_at DESC", (started_at,))


def message(rows: list[dict]) -> tuple[str, str]:
    n = len(rows)
    title = f"{n} new {'match' if n == 1 else 'matches'} on applyfirst"
    top = "; ".join(f"{r['title']} at {r['company']}" for r in rows[:3])
    more = f" and {n - 3} more" if n > 3 else ""
    return title, top + more


def desktop(title: str, body: str) -> str:
    """Show a notification. Returns '' on success, else a short reason."""
    system = platform.system()
    try:
        if system == "Windows":
            import os
            env = {**os.environ, "AF_TITLE": title, "AF_BODY": body[:250]}
            p = subprocess.run(["powershell", "-NoProfile", "-NonInteractive", "-Command", _PS_TOAST],
                               env=env, capture_output=True, text=True, timeout=30)
            return "" if p.returncode == 0 else (p.stderr.strip()[-200:] or "PowerShell refused the notification")
        if system == "Darwin":
            esc = lambda s: s.replace("\\", "\\\\").replace('"', '\\"')  # noqa: E731
            p = subprocess.run(["osascript", "-e", f'display notification "{esc(body[:250])}" with title "{esc(title)}"'],
                               capture_output=True, text=True, timeout=30)
            return "" if p.returncode == 0 else (p.stderr.strip()[-200:] or "osascript failed")
        if shutil.which("notify-send"):
            p = subprocess.run(["notify-send", title, body[:250]], capture_output=True, text=True, timeout=30)
            return "" if p.returncode == 0 else (p.stderr.strip()[-200:] or "notify-send failed")
        return "no notification tool on this system (install notify-send)"
    except (OSError, subprocess.TimeoutExpired) as e:
        return str(e)


def smtp_host(imap_host: str, configured: str = "") -> str:
    if configured:
        return configured
    h = (imap_host or "").strip().lower()
    return "smtp." + h[5:] if h.startswith("imap.") else h


def email_self(title: str, rows: list[dict], settings: dict) -> str:
    """Email the list to the user's own address with their mail settings. '' on success."""
    em = config.get(settings, "tracker.email", {}) or {}
    user = em.get("username") or ""
    password = config.load_secrets().get("imap_password") or ""
    host = smtp_host(em.get("imap_host", ""), em.get("smtp_host", ""))
    if not (user and password and host):
        return "email is not set up (Settings, Email replies)"
    msg = EmailMessage()
    msg["Subject"] = title
    msg["From"] = user
    msg["To"] = user
    lines = [f"- {r['title']} at {r['company']} ({r['location'] or 'location not stated'})\n  {r['url']}" for r in rows[:25]]
    if len(rows) > 25:
        lines.append(f"...and {len(rows) - 25} more in applyfirst.")
    msg.set_content("New postings that match what you are looking for:\n\n" + "\n".join(lines)
                    + "\n\nOpen applyfirst to approve the ones you want.")
    try:
        port = int(em.get("smtp_port") or 465)
        ctx = ssl.create_default_context()
        if port == 465:
            with smtplib.SMTP_SSL(host, port, context=ctx, timeout=30) as s:
                s.login(user, password)
                s.send_message(msg)
        else:  # 587 and others: plain connect, then STARTTLS (iCloud, Outlook/Office 365)
            with smtplib.SMTP(host, port, timeout=30) as s:
                s.starttls(context=ctx)
                s.login(user, password)
                s.send_message(msg)
        return ""
    except (OSError, smtplib.SMTPException) as e:
        return str(e)[:200]


def after_sweep(run_id: str, started_at: str) -> str:
    """Send the alerts the settings ask for. Returns a short note for the sweep summary."""
    s = config.load_settings()
    a = config.get(s, "alerts", {}) or {}
    rows = new_matches_since(started_at)
    if len(rows) < max(1, int(a.get("min_new") or 1)) or not (a.get("desktop") or a.get("email")):
        return ""
    title, body = message(rows)
    notes = []
    if a.get("desktop"):
        err = desktop(title, body)
        store.log(run_id, f"desktop alert: {'sent' if not err else 'failed: ' + err}")
        if err:
            notes.append(f"Desktop alert failed ({err}).")
    if a.get("email"):
        err = email_self(title, rows, s)
        store.log(run_id, f"email alert: {'sent' if not err else 'failed: ' + err}")
        notes.append("Emailed you the new matches." if not err else f"Email alert failed ({err}).")
    return " ".join(notes)
