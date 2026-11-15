# Getting started

From nothing to your first application takes about fifteen minutes: five to install, ten to set up.
Everything runs on your own computer.

Stuck anywhere? [TROUBLESHOOTING.md](TROUBLESHOOTING.md) has the fix for the common snags.

## 1. Install what applyfirst runs on

You need four things.

| You need | Why | Check it |
| --- | --- | --- |
| **Python 3.10 or newer** | applyfirst is a Python app | `python --version` |
| **Git** | pip uses it to download applyfirst from GitHub ([download Git](https://git-scm.com/downloads)) | `git --version` |
| **Claude Code**, signed in | Claude does the form filling | `claude --version` |
| **Google Chrome** with the **Claude in Chrome** extension, connected to Claude Code | Applications are filled in your own Chrome, so every site you are already signed in to just works | see "Claude in Chrome" below |

### Claude Code

Install it with Anthropic's own instructions: [Claude Code quickstart](https://code.claude.com/docs/en/quickstart).
In short, open a terminal and run the line for your system.

macOS, Linux or WSL:

```
curl -fsSL https://claude.ai/install.sh | bash
```

Windows PowerShell:

```
irm https://claude.ai/install.ps1 | iex
```

Open a new terminal window, run `claude`, and sign in when it asks. You only do this once. Then
check the version:

```
claude --version
```

applyfirst was tested with Claude Code 2.1.325 and needs **2.1.0 or newer**. If yours is older,
update it (the quickstart page above covers updating).

### Claude in Chrome

applyfirst fills forms through the [Claude in Chrome extension](https://chromewebstore.google.com/detail/claude/fcoeoabgfenejglbffodgkkbkcdhcgfn).
Anthropic's page for connecting it to Claude Code is
[Use Claude Code with Chrome](https://code.claude.com/docs/en/chrome). The short version:

1. Install the extension from the Chrome Web Store link above (Anthropic's page asks for version
   1.0.36 or later) and sign in to it with the same Claude account you use for Claude Code.
2. In a terminal, run `claude --chrome` once. The first time, it shows a short one-time dialog.
   Press Enter to continue.
3. Inside Claude Code, run `/chrome`. You are connected when the panel shows **Status: Enabled** and
   **Extension: Installed**. If it does not, restart Chrome and run `/chrome` again.
4. Type `/exit` to leave Claude Code.

Two things from Anthropic's page worth knowing:

- Chrome connection needs a Claude plan (Pro, Max, Ultra, Team or Enterprise) and a sign-in with
  `/login`. An API key does not work for it.
- It does not work inside WSL. On Windows, run applyfirst in regular Windows, not in WSL.

## 2. Install applyfirst

```
pip install git+https://github.com/xu826Jamin/applyfirst
```

Then start it:

```
applyfirst
```

Your browser opens the app at http://127.0.0.1:8765.

**If your terminal says `applyfirst` is not found** (common on Windows), run it through Python
instead. It does exactly the same thing:

```
python -m applyfirst
```

**Keep the terminal window open while you use applyfirst.** The window is the app. Closing it
stops the app, and any search or application in progress. To stop it on purpose, press Ctrl+C in
that window. Next time, run the same command to open it again; your work is saved.

## 3. Set up (about ten minutes)

The first time you open the app it walks you through four steps. You can come back and change
anything later under **Profile** and **Settings**.

1. **Resume.** Upload the resume you already have (a PDF). applyfirst reads out your experience.
2. **Experience.** Check what it found and fix anything that is off. Only lines you confirm are
   ever used on an application, and every line on a resume it builds traces back to one of
   them. Later, **Settings, Resume versions** lets you choose how resumes are made: an ideal resume
   for each role group you pick, adjusted to each job (the default); one built fresh for every job;
   or your own file sent as-is. Each choice shows its pros and cons there.
3. **Profile.** The basics every application asks for: your name, contact details, where you can
   work, when you can start, and so on. Anything you leave blank on the demographic questions is
   answered "prefer not to say" where a form offers it.
4. **Targets.** What you are looking for: **Countries** (at least one, as two-letter codes like
   `CA` or `US`), states or provinces, cities, remote, career level, fields, start terms, and
   when to send applications (see "Review mode and auto mode" below).

Press **Find jobs**.

## 4. Your first search

The first search reads the built-in company boards in about ten minutes, then grows in the
background to thousands of boards. Later searches only pick up what is new, so they are quicker.

You do not have to wait. Matches show up on the **Jobs** screen as they are found, newest first,
and the list updates by itself. To watch it work, open **Activity**: every search, application
and email check is listed there with a plain log.

Each job shows why it was kept. Press **Why** to see the reasons. Press **Open** to read the
posting itself. If a posting you want is not listed, paste its link into the box at the top of
Jobs and press **Add**; it is added and approved in one step.

## 5. Approve and apply

1. On **Jobs**, the **Kept** tab holds the postings that fit you. Press **Approve** on the ones you
   want. You can also tick several and approve them together.
2. Press **Apply to approved** (the button shows how many, for example "Apply to 3 approved").
3. Claude opens each application in your Chrome, attaches your resume and fills every field it
   can from your profile and your saved answers.

How many applications go out in one day is capped by **Applications per day** in Settings
(25 to start).

### Review mode and auto mode

You choose under **When to send** in Settings (the setup step offers the same choice).

- **Show me each one before it is sent** (review mode, the default). Claude fills the form and
  stops before the final button, leaving the tab open in Chrome. Look it over, press the
  employer's submit button yourself, then open **Applications** and press **I submitted it**. If
  you have connected email, the employer's confirmation email marks it for you.
- **Send without asking** (auto mode). Claude submits and saves the confirmation. You can still
  have it show you the first few before it sends on its own: **Still show me the first** is set
  to 5 to start. Some employers accept only one application per role or per season, so start in
  review mode and move to auto once you trust what it fills.

You can switch any time.

### Needs you

Some things only you can do. The browser tool Claude uses does not create accounts, type
passwords or solve CAPTCHAs. When an application needs one of those, or a question it has no
answer for, it waits in the **Needs you** column of **Applications** (and the Home screen tells
you how many are waiting). Each one says what to do. Do that step, and the application carries
on. Applications that stop in review mode sit in **Ready to submit** until you press
submit.

### Answers

The first time a form asks something new, applyfirst asks you once. Open **Answers**: questions
under **Waiting for you** need a reply. Type it and press **Save answer**. It is used on every
application from then on. Everything you have answered lives under **Saved answers**, where you
can change it any time.

## 6. See what is working

Connect your email under **Settings**, in the **Email replies** group, and applyfirst reads your
replies, matches them to applications, and shows your interview rate by source, resume, field and
how fresh the posting was when you applied. Setup for Gmail, iCloud and Yahoo is in
[EMAIL.md](EMAIL.md). Replies are read during the daily run (step 7), or any time you run
`applyfirst sync` in a terminal. Your results appear on **Insights**.

## 7. Let it run every day

Turn on **Run every day** in Settings and applyfirst searches, applies (in auto mode) and reads
replies on its own, while the app is open. [DAILY.md](DAILY.md) also covers running it when the
app is closed, and the new-match alerts.

## What it costs

Filling a form uses Claude, which draws on your Claude plan. One application measured about
$0.37 on a single test run. Your real average shows on **Insights**. A daily spending limit is
on by default ($10; change it under **Daily spending limit (USD)** in the **Claude** group of
Settings).
