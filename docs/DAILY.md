# Run it every day

Postings fill on a rolling basis, so the people who apply in the first day get read first. Let
applyfirst do the checking for you, and you open the app to a fresh list.

A daily run does three things:

1. **Finds** new postings from your boards and sources.
2. **Applies**, in auto mode only, to what you have approved and to new matches, within your
   **Applications per day** limit. In review mode it does not apply; it leaves the choosing to you.
3. **Reads replies**, if you have [connected email](EMAIL.md).

## Option 1: the in-app schedule (easiest)

1. Open **Settings** and find the **Schedule** group.
2. Turn on **Run every day**.
3. Set **Time of day** (08:00 to start).

That is all. It works while applyfirst is open, so keep the terminal window you started it from
open. Each day, once the time has passed, it runs once. If the app was closed at that hour and you
open it later, it runs as soon as it starts that day. The run shows up on **Activity**.

While the app is open it also searches again every 6 hours, so new postings reach you the same
day, and reads your inbox for replies every 24 hours if email is connected. Change either in
**Settings**: **Sweep interval hours** under Sources and **Sync interval hours** under Tracker.
Set one to `0` to turn it off.

## Option 2: schedule it yourself, so it runs with the app closed

Your computer's own scheduler can run applyfirst without you opening anything. Use the same
command on every system:

```
applyfirst daily
```

(or `python -m applyfirst daily` if the `applyfirst` command is not found; see
[TROUBLESHOOTING.md](TROUBLESHOOTING.md#applyfirst-command-not-found)).

If you also keep **Run every day** on, nothing doubles up: the app skips its own run on a day
when one has already happened.

Good to know:

- **Applying needs your desktop.** Search and email checking run without it. Filling applications
  happens in a Chrome window on your desktop, so for auto mode the computer must be awake, you signed in, and
  Chrome available.
- **Claude Code must be reachable from the scheduler.** Schedulers start with a thinner
  environment than your terminal. If a scheduled run says Claude Code is not installed, put the
  full path to it in **Claude command** under **Settings, Claude**.
- A failed run says so on **Activity** and the command exits with an error, which your scheduler
  records.
- To catch postings sooner than once a day, schedule `applyfirst sweep` more often (every hour,
  say). It only searches; it does not apply. New-match alerts go out after each search.

### Windows: Task Scheduler

Open Command Prompt or PowerShell and create a task that runs every day at 08:00:

```
schtasks /Create /TN "applyfirst daily" /SC DAILY /ST 08:00 /TR "python -m applyfirst daily"
```

If `python` is not found when the task runs, give the full path. Find it with `where python`, then:

```
schtasks /Create /TN "applyfirst daily" /SC DAILY /ST 08:00 /TR "\"C:\Users\you\AppData\Local\Programs\Python\Python312\python.exe\" -m applyfirst daily"
```

Useful companions:

```
schtasks /Run /TN "applyfirst daily"        # run it now to test
schtasks /Delete /TN "applyfirst daily" /F   # remove it
```

Created this way, the task runs as you, while you are signed in, which is what Chrome needs. Prefer
a window? Open **Task Scheduler** from the Start menu, choose **Create Basic Task**, pick Daily,
and set the action to start `python` with the arguments `-m applyfirst daily`.

To also search every hour:

```
schtasks /Create /TN "applyfirst sweep" /SC HOURLY /MO 1 /TR "python -m applyfirst sweep"
```

### Linux: cron

Run `crontab -e` and add a line. This runs at 08:00 every day and keeps a log:

```
0 8 * * * PATH="$HOME/.local/bin:/usr/local/bin:/usr/bin:/bin" python3 -m applyfirst daily >> "$HOME/.applyfirst/cron.log" 2>&1
```

cron starts with a short PATH, so include the folder that holds `claude` (run `which claude` in
your terminal to see it) and `python3`. To search every hour as well:

```
0 * * * * PATH="$HOME/.local/bin:/usr/local/bin:/usr/bin:/bin" python3 -m applyfirst sweep >> "$HOME/.applyfirst/cron.log" 2>&1
```

Desktop notifications on Linux need `notify-send`, and a job started by cron may not reach your
desktop's notification service. Email alerts do not have that problem.

### macOS: launchd (or cron)

Save this as `~/Library/LaunchAgents/com.applyfirst.daily.plist`. Change `/Users/you` to your home
folder, and make sure the folders in PATH include where `python3` and `claude` live (`which python3`,
`which claude`):

```xml
<?xml version="1.0" encoding="UTF-8"?>
<!DOCTYPE plist PUBLIC "-//Apple//DTD PLIST 1.0//EN" "http://www.apple.com/DTDs/PropertyList-1.0.dtd">
<plist version="1.0">
<dict>
  <key>Label</key><string>com.applyfirst.daily</string>
  <key>ProgramArguments</key>
  <array>
    <string>/usr/bin/env</string>
    <string>python3</string>
    <string>-m</string>
    <string>applyfirst</string>
    <string>daily</string>
  </array>
  <key>EnvironmentVariables</key>
  <dict>
    <key>PATH</key><string>/opt/homebrew/bin:/usr/local/bin:/usr/bin:/bin:/Users/you/.local/bin</string>
  </dict>
  <key>StartCalendarInterval</key>
  <dict>
    <key>Hour</key><integer>8</integer>
    <key>Minute</key><integer>0</integer>
  </dict>
  <key>StandardOutPath</key><string>/tmp/applyfirst-daily.log</string>
  <key>StandardErrorPath</key><string>/tmp/applyfirst-daily.log</string>
</dict>
</plist>
```

Then load it:

```
launchctl load ~/Library/LaunchAgents/com.applyfirst.daily.plist
```

To stop it, run `launchctl unload` on the same file. If you would rather use cron, the Linux line
above works on macOS too.

## Alerts

applyfirst tells you when new matches arrive, so you can approve the fresh ones before anyone
else applies. It happens after any search, whether you pressed **Search now**, the in-app run, or
a scheduled one.

Under **Alerts** in Settings:

- **Desktop notification**: on by default. A notification on this computer.
- **Email me new matches**: optional, off by default. Sends a short list to your own address, using
  your [email settings](EMAIL.md).
- **Only when at least**: how many new matches it takes before an alert goes out (1 to start).

If notifications do not appear, see
[TROUBLESHOOTING.md](TROUBLESHOOTING.md#desktop-notifications-do-not-show).
