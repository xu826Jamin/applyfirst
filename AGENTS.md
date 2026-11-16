# Setting up applyfirst: instructions for the person's AI agent

You are Claude Code (or another coding agent), and the person asked you to set up applyfirst for
them. Follow these steps in order. Your job is to get them from nothing to their first application
**and** to make sure they know every requirement and every limit before they run into it. They
should never be surprised later by something you knew now.

Talk to them in plain words, one step at a time. Lead with what they get. Run the checks yourself
instead of asking them to.

## 1. Before installing anything, tell them this (one message)

Say it in your own words, but cover every point:

- **What they get:** applyfirst finds new job postings from thousands of company career boards
  the hour they go up, fills and submits the applications with Claude, and reads the replies in
  their inbox so they can see what turns into interviews. Everything runs on their own computer.
- **What it needs**, which you will check and install with them:
  - Python 3.10 or newer, and Git
  - Claude Code 2.1.0 or newer, signed in with a Claude plan. Claude does the form filling.
  - Node.js (the LTS version). Claude reaches the Chrome window applyfirst opens through it.
  - Google Chrome, Edge or Chromium
  - Optional: the Claude in Chrome extension, connected to Claude Code, to fill applications in
    their own Chrome with the sign-ins it already has. Without it, applyfirst opens its own Chrome
    window, which works just as well.
  - Their resume file, and about ten minutes for the in-app setup
- **Permissions during this setup:** you will run about ten commands (version checks, installs,
  scheduling the update). Claude Code asks them to approve each one. To let setup run straight
  through, they can quit this session and start a new one with
  `claude --dangerously-skip-permissions`, then paste the setup request again. Say plainly what
  that flag does: you can then run any command without asking, so it is for this setup only, and
  a normal `claude` session afterwards asks again as usual. Let them choose.
- **What only they can do:** applyfirst never creates accounts, types passwords or solves
  CAPTCHAs on job sites. When an application needs one of those, it waits under **Needs you** in
  the app. They create the account or sign in themselves once, in the Chrome window applyfirst
  uses, and every later application on that site reuses it. Workday sites need one account per
  company, so expect a few of these early on.
- **What it costs:** filling a form uses their Claude plan. One measured application used about
  $0.37. A daily spending limit of $10 is on by default and can be changed in Settings.
- **Review mode is the default:** Claude fills each form and stops before the final button so they
  can check it and submit. Auto mode, which submits for them, is a setting they can turn on later.
- **Keep it running:** the app runs while its terminal window is open. Scheduled daily runs need
  the computer awake and them signed in.
- **Updates:** you will schedule applyfirst to update itself every 3 days so they always have the
  latest fixes for job sites that change their forms.

## 2. Check every requirement

Run each check and report the result in one line each ("Python 3.12: ready"). Fix what is
missing with their OK, using the links in [Getting started](docs/GETTING_STARTED.md).

| Check | Command | Needs |
| --- | --- | --- |
| Python | `python --version` (Windows: `py --version` if `python` opens the Microsoft Store) | 3.10+ |
| Git | `git --version` | any |
| Claude Code | `claude --version` | 2.1.0+ and signed in (run `claude` once if they never have) |
| Node.js | `node --version` and `npx --version` | LTS |
| Chrome, Edge or Chromium | look for it in the usual install folders | any one |

On Windows, run everything from regular Windows, not WSL.

## 3. Install

```
pip install git+https://github.com/xu826Jamin/applyfirst
```

Then check it installed: `python -m applyfirst --help`.

## 4. Schedule the update every 3 days

Create the task, then **run it once now and confirm it finished without errors**. A schedule that
has never been seen to work does not count. Use the full path to their Python (`where python` on
Windows, `which python3` elsewhere) so the task finds it.

Windows (Task Scheduler):

```
schtasks /Create /TN "applyfirst update" /SC DAILY /MO 3 /ST 04:00 /TR "\"<full path to python.exe>\" -m pip install -U --force-reinstall git+https://github.com/xu826Jamin/applyfirst"
schtasks /Run /TN "applyfirst update"
```

Linux (cron, `crontab -e`):

```
0 4 */3 * * <full path to python3> -m pip install -U --force-reinstall git+https://github.com/xu826Jamin/applyfirst >> "$HOME/.applyfirst/update.log" 2>&1
```

macOS: a launchd job at `~/Library/LaunchAgents/com.applyfirst.update.plist`, built like the daily
job in [Run it every day](docs/DAILY.md), with `ProgramArguments` set to the python3 path, `-m`,
`pip`, `install`, `-U`, `--force-reinstall`, `git+https://github.com/xu826Jamin/applyfirst`, and
`<key>StartInterval</key><integer>259200</integer>` (3 days) instead of `StartCalendarInterval`.
Load it with `launchctl load` and start it once with `launchctl start com.applyfirst.update`.

Their data in `~/.applyfirst` is never touched by an update and upgrades itself on the next start.
Tell them the update is scheduled and how to remove it (`schtasks /Delete /TN "applyfirst update" /F`,
`crontab -e`, or `launchctl unload` plus deleting the plist).

## 5. Start the app

Ask them to open a **new terminal window** and run `applyfirst` (or `python -m applyfirst`), and to
leave that window open. Starting it from your own session works too, but it stops when your session
ends. The app opens at http://127.0.0.1:8765.

## 6. Walk them through the first run

In the app: upload the resume, confirm the experience it found, fill the profile, say what they
are looking for, press **Find jobs**. The first search takes about ten minutes. Then on **Jobs**:
approve a few postings and press **Apply to approved**.

When the first application opens in the applyfirst Chrome window, remind them: if a job site asks
them to sign in or create an account, they do it right there, once.

Optional next steps, offered once: connect their email for reply tracking ([Connect your email](docs/EMAIL.md))
and turn on daily runs ([Run it every day](docs/DAILY.md)).

## 7. If something goes wrong

[Troubleshooting](docs/TROUBLESHOOTING.md) has the fix for the common snags. Tell them what failed
in one line and what you are doing about it.
