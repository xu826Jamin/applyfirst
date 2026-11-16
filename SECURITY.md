# Security

applyfirst handles your resume, your answers, your inbox and your job applications, so it is built
to keep that on your computer and to give the Claude that works for you as little power as
possible. Here is exactly what is protected, and how.

## What is protected

**Claude only gets browser tools.** The Claude that runs in the background reads job postings,
which are text written by strangers. So applyfirst starts it locked down: it can use the browser
tools it needs to fill a form, and nothing else. It has no shell, cannot read or write your files,
and cannot fetch web pages on its own. Anything outside that list is refused without asking
(Claude Code's `dontAsk` permission mode), so there is no prompt for a posting to talk you into
approving. The settings are in `applyfirst/claude.py`, with tests in `tests/test_security.py`.

**The local app answers only you.** applyfirst's API listens on `127.0.0.1`, which is this computer
only. It also refuses any request that does not come from the app's own page: other websites you
have open in your browser cannot start applications or change settings, and a page that tricks your
browser into reaching the app under another name is turned away too.

**A daily cap on Claude spending.** A limit of $10 a day is on by default, and Claude stops for the
day once it is used. Change it under **Daily spending limit (USD)** in the **Claude** group of
Settings. Setting it to 0 removes the limit, and Settings shows a warning when you do.

**Your data stays in `~/.applyfirst`.** Your profile, settings, experience bank, resumes,
applications and a local database live in that folder (or wherever `APPLYFIRST_HOME` points). Nothing
is stored in the repo or sent to a server we run. The only things that leave your computer are the
applications you send to employers and the work Claude does for you.

**Your mailbox is read only.** applyfirst never sends, moves, flags or deletes a message. If you
turn on email alerts, it sends a short list of matches to your own address and nowhere else. The mail
password is kept in `secrets.json` in your data folder (readable only by you where the operating
system supports it) and the app never shows it back.

**You approve what goes out.** In review mode, every application stops before the final button, so
you see each one before it is sent. Auto mode sends without asking, and Settings says so beside it.
Claude does not create accounts, type passwords or solve CAPTCHAs; those wait for you.

**The applyfirst Chrome window has its own profile and a local-only port.** By default applications
are filled in a Chrome window applyfirst opens itself (see `applyfirst/own_window.py`). It runs on a
separate profile inside your applyfirst folder, so your own Chrome profile, tabs and saved passwords
are never touched, and Claude is not allowed to read that profile folder. Claude reaches the window
through a Chrome debugging port that is bound to `127.0.0.1`, which is this computer only; nothing
on your network can connect to it. Like any Chrome debugging port, a program already running as you
on this computer could connect to it while the window is open, so close the window when you are not
applying. The file-upload tool in this route can only attach files from an empty folder of its own
that holds a copy of the resume and cover letter for that one application.

## The limit to know about on the extension route

If you choose to fill applications in your own Chrome through the Claude in Chrome extension,
that extension's file-upload tool
can attach any file on the computer. That is how your resume gets onto an application. It also means
that a posting written to trick Claude could, in principle, ask it to upload a different file to
the employer's form.

What helps today:

- **Review mode** lets you see every application, including what is attached, before it goes.
  Use it until you trust what it does.
- Anthropic's documentation says Claude Code refuses to upload files whose names or folders are
  where credentials are kept, such as `.env`, `.pem` and `.key` files and anything under `.ssh`
  (Claude Code 2.1.293 or newer). See
  [Use Claude Code with Chrome](https://code.claude.com/docs/en/chrome).
- Keep Claude Code up to date.

## Reporting a problem

If you find a security problem, tell us so we can fix it:

- **Private (best for anything that could be misused before it is fixed):** open a private
  advisory at
  [github.com/xu826Jamin/applyfirst/security/advisories/new](https://github.com/xu826Jamin/applyfirst/security/advisories/new).
- **Public:** open an issue at
  [github.com/xu826Jamin/applyfirst/issues](https://github.com/xu826Jamin/applyfirst/issues) and
  mark it **security** in the title. Leave exploit details out of a public issue; say what you found
  and we will move the details to a private advisory.

Please include what you did, what you expected, and what happened. Never include your real
resume, mailbox password or other personal data in a report.
