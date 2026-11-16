# Troubleshooting

Find your symptom, follow the steps, and you are back to applying. New here? Start with
[GETTING_STARTED.md](GETTING_STARTED.md).

- [`applyfirst` command not found](#applyfirst-command-not-found)
- ["Claude Code is not installed" banner](#claude-code-is-not-installed-banner)
- [Applications fail in the applyfirst Chrome window](#applications-fail-in-the-applyfirst-chrome-window)
- [Applications fail because Chrome is not connected](#applications-fail-because-chrome-is-not-connected)
- [Jobs is empty](#jobs-is-empty)
- [Port already in use](#port-already-in-use)
- ["Spending limit used up"](#spending-limit-used-up)
- [Email sync fails](#email-sync-fails)
- [Desktop notifications do not show](#desktop-notifications-do-not-show)
- [An employer's site needs a sign-in](#an-employers-site-needs-a-sign-in)

Two places always tell you what happened. The **Activity** screen lists every search, application
and email check with its log (press a row to open it). And the terminal window you started
applyfirst from prints anything the app could not do.

## `applyfirst` command not found

Run it through Python instead. It does exactly the same thing:

```
python -m applyfirst
```

On Windows, `py -m applyfirst` works too. Every command has the same form:
`python -m applyfirst daily`, `python -m applyfirst sync`, and so on.

To make plain `applyfirst` work, add Python's **Scripts** folder to your PATH. When you ran
`pip install`, pip printed a warning that named the folder ("The script applyfirst.exe is installed
in ... which is not on PATH"). Add that folder to your PATH (on Windows: Start, search "Edit
environment variables for your account", edit **Path**), then open a new terminal window. Python's own
page covers this: [Using Python on Windows](https://docs.python.org/3/using/windows.html).

If `python` itself opens the Microsoft Store or is not found, install Python from
[python.org](https://www.python.org/downloads/) and tick the option to add it to PATH.

If `pip install git+https://...` fails with a message about `git`, install
[Git](https://git-scm.com/downloads) first. pip needs it to download from GitHub.

## "Claude Code is not installed" banner

The red banner on the Home screen says applications cannot be filled yet. Searching still works.

1. Open a new terminal window and run `claude --version`. If it prints a version, Claude Code is
   installed, and the banner means applyfirst cannot find it from where it was started. Close
   applyfirst, open a new terminal, and start it again. Still there? Open **Settings**, the **Claude**
   group, and put the full path to Claude Code in **Claude command**. (`where claude` on Windows or
   `which claude` on macOS and Linux prints the path.)
2. If `claude` is not found, install it: [Claude Code quickstart](https://code.claude.com/docs/en/quickstart).
   Run `claude` once and sign in.
3. Reload the applyfirst page.

A banner that says your Claude Code version is too old means update it. applyfirst needs 2.1.0 or
newer.

## Applications fail in the applyfirst Chrome window

This is the default way applications are filled: applyfirst opens its own Chrome window.
Symptoms: a banner asking you to install Node.js or Chrome, or **Activity** saying the window did
not start.

1. **Install [Node.js](https://nodejs.org/)** (the LTS version) if the banner asks for it, then
   reload the applyfirst page. Check it with `node --version` in a new terminal.
2. **A Chrome, Edge or Chromium must be installed.** applyfirst uses the first one it finds. To pick
   one, set the `APPLYFIRST_BROWSER` environment variable to its full path.
3. **"The window did not start"**: close any leftover applyfirst Chrome window and try again. If it
   keeps happening, delete the `browser-window` folder inside your applyfirst folder (you will sign
   in to your job sites again) and try again.
4. **Applications stop on a sign-in page.** Sign in to that site in the applyfirst Chrome window,
   once, then press **Try again**. It remembers you afterwards.
5. Closing the window while applications are running stops them. Leave it open until the run ends;
   applyfirst opens it again by itself next time.
6. Your own Chrome is never used by this route. To use it, with its sign-ins, set up Claude in
   Chrome (next section) and leave **Browser** on **Automatic**, or choose **My own Chrome and its
   sign-ins**.

## Applications fail because Chrome is not connected

Only for **My own Chrome and its sign-ins**, or when **Automatic** found Claude in Chrome set up.
Symptoms: applications land under **Did not finish** on the **Applications** screen, or **Activity**
shows messages like "Browser extension is not connected" or "No browsers are connected".
After three applications in a row fail, the run stops so nothing is wasted.

To stop using the extension, set **Browser** to **The applyfirst Chrome window** in Settings.
Otherwise work down this list, using Anthropic's page as the reference:
[Use Claude Code with Chrome](https://code.claude.com/docs/en/chrome).

1. **Chrome is open**, with the Claude in Chrome extension installed and enabled
   (`chrome://extensions`).
2. **The extension is signed in to the same Claude account as Claude Code.** If you belong to more
   than one organization, it must be the same organization too. In Claude Code, `/status` shows the
   organization.
3. In a terminal, run `claude`, then `/chrome`. You want **Status: Enabled** and
   **Extension: Installed**. If not, choose **Reconnect extension**.
4. Restart Chrome. The first time the connection is set up, Chrome only notices it after a restart.
5. A site dialog (an alert or confirm box) left open in the tab blocks Claude. Close it.
6. The connection needs a signed-in Claude plan (`/login`), not an API key.
7. On Windows, run applyfirst from regular Windows, not from WSL. Chrome connection does not work in WSL.

When it is fixed, press **Try again** on any card under **Did not finish** on **Applications**.
It goes back in the queue and Claude fills it again.

## Jobs is empty

Work through these in order.

1. **Countries are not set.** Under **Settings**, **What to look for**, **Countries**, add at least
   one two-letter code (`CA`, `US`). The search needs it to know where to look.
2. **The first search is still running.** The first one reads the built-in boards in about ten
   minutes, then keeps growing in the background. Open **Activity**: a row marked Running means it
   is still working, and matches appear on Jobs as they are found. A banner on Jobs says
   "Searching for new postings."
3. **Your filters are tight.** Open the **Skipped** tab on Jobs. Every skipped posting says why
   (press **Why**). If everything is skipped for the same reason, loosen that setting: career
   level, fields, start terms, **Shortest term**, **Newest postings only** (30 days to start), or
   **Words to avoid**.
4. **The source is off.** **Company career pages** under **Where to look** must be on.
5. **A narrow field.** The built-in and discovered boards come mostly from technology and
   engineering employers, so other fields and senior roles turn up fewer postings today. Paste a
   link to any posting at the top of Jobs and press **Add** to bring it in.
6. **Nothing happened yet.** Press **Search now** on Jobs.

## Port already in use

applyfirst opens at http://127.0.0.1:8765. If that port is busy, it picks the next free one and tells
you in the terminal:

```
Port 8765 is in use (is applyfirst already open?), so using 8766.
applyfirst is running at http://127.0.0.1:8766/
```

Use the address it prints. The most common cause is applyfirst already running in another
terminal window. If you want a particular port, run `applyfirst serve --port 9000`. If ports 8765
to 8774 are all taken, it says so and stops. Close the other program or pick another port.

## "Spending limit used up"

The message reads "Today's Claude spending limit ... is used up." A daily cap on Claude usage is on
by default ($10) so a big batch cannot surprise you. It resets at midnight.

To raise it: **Settings**, the **Claude** group, **Daily spending limit (USD)**. Set a higher
number, then press **Apply to approved** again. A filled application measured about $0.37 on one
test, and **Insights** shows your real average, so you can pick a limit that fits how many you
send. `0` means no limit.

## Email sync fails

A failed check shows on **Activity** as "Could not sign in to the mail server", or as "Email is set up but
no mail password is saved yet".

1. **Use an app password**, not your everyday password. Make one with your provider and paste it
   under **Email password**, then press **Save password**. The note beside it should read "A password
   is saved". Steps for each provider are in [EMAIL.md](EMAIL.md).
2. **Check the server and port.** Gmail `imap.gmail.com`, iCloud `imap.mail.me.com`, Yahoo
   `imap.mail.yahoo.com`, all on port `993`.
3. **Check the email address.** It is the login for your mailbox. (iCloud uses the part before the
   `@`; see [EMAIL.md](EMAIL.md#icloud-mail).)
4. **Check your provider allows app passwords.** Work and school Google accounts often do not.
   Outlook.com and Hotmail are not supported yet.
5. Run `applyfirst sync` in a terminal to test again and see the message.

## Desktop notifications do not show

Turn on **Desktop notification** under **Alerts** in Settings. When a notification cannot be shown,
the search still finishes, and the run's log on **Activity** (press the row) has a line such as
"desktop alert: failed: ...". The cause depends on your system. Menu names change between versions, so look for the nearest match.

- **Windows.** Notifications are blocked when Focus assist or Do not disturb is on. Open
  **Settings, System, Notifications**, turn those off (or allow alerts), and make sure notifications
  are on. applyfirst sends them through PowerShell, so they may be listed there as "Windows
  PowerShell".
- **macOS.** applyfirst sends them with `osascript`, and macOS can attribute them to **Script
  Editor**. Open **System Settings, Notifications**, find **Script Editor**, and allow
  notifications. If it is not listed yet, open Script Editor once and run
  `display notification "test" with title "applyfirst"`; macOS then asks for permission.
  Focus modes also hide them.
- **Linux.** The `notify-send` program must be installed. It comes from your distribution's
  libnotify package. On a desktop without a notification service, none will appear.

Prefer email? Turn on **Email me new matches** instead (see [EMAIL.md](EMAIL.md)).

## An employer's site needs a sign-in

Some employers want an account before you can apply. The browser tool Claude uses will not create
accounts, type passwords or solve CAPTCHAs, so the application waits under **Needs you** and says
which site.

1. Sign in (or create the account) yourself, in the same Chrome window that applyfirst is using (the applyfirst Chrome window, or your own Chrome if you chose that). Chrome
   remembers it, so every later application to that employer just works.
2. Finish the application, in either of two ways:
   - **Do it yourself.** Switch to the open tab, complete the form, press the employer's submit
     button, then press **I submitted it** under **Applications**.
   - **Have Claude finish it.** Press **Continue** on the card. It goes back in the queue and
     Claude picks up from the signed-in page.

The same steps work for a CAPTCHA: solve it in the tab, then finish it or press **Continue**.
