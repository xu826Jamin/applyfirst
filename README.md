# applyfirst

**Find jobs the hour they go up. Apply first. See what is actually getting you interviews.**

Most postings fill on a rolling basis, so the people who apply in the first day get read first.
applyfirst checks thousands of company career boards directly, puts the newest postings that
match you at the top, fills and submits the applications with Claude, and reads the replies in
your inbox so you can see which applications turn into interviews and which do not.

Everything runs on your own computer. Your resume, answers and inbox never leave it, except
the applications you send to employers and the work Claude does for you.

## What you get

- **Fresh postings first.** Thousands of company boards (Greenhouse, Lever, Ashby, Workday,
  SmartRecruiters, Workable and more) checked directly, not days later through a reposting site.
  Optional extras: Indeed, Glassdoor, LinkedIn, Google's past-24-hours results, job-alert emails,
  and your school's job board.
- **Only what you want.** Location, remote, career level (internship and co-op through senior),
  field, start date, term length, keywords, companies to skip, languages you do not speak.
  Every skipped posting tells you why.
- **Your order.** Newest first, soonest deadline, company, or best match: you choose.
- **Resumes from your real experience.** Upload the resume you have. applyfirst turns it into an
  experience bank you confirm once, then builds a clean one-page resume per type of role. Every
  line traces back to something you confirmed, so nothing on it surprises you in an interview.
- **Applications filled for you.** Claude fills the form in your browser, including Workday.
  Review mode stops before submit so you can check it; auto mode submits and saves the confirmation.
- **Answer once.** Every new form question is asked once and remembered for every application after.
- **Know what is working.** Replies are read from your inbox and matched to applications. See your
  interview rate by source, resume, field, and how fresh the posting was when you applied.

## Install

You need Python 3.10 or newer and [Claude Code](https://docs.anthropic.com/en/docs/claude-code)
signed in. For filling forms, either the Claude in Chrome extension or Node.js (for the Playwright
browser).

```
pip install git+https://github.com/<owner>/applyfirst
applyfirst
```

`applyfirst` opens the app in your browser at http://127.0.0.1:8765. The setup takes about ten
minutes: upload your resume, confirm your experience, say what you are looking for, press
**Find jobs**.

## Run it every day

Turn on **Run daily** in Settings, or schedule `applyfirst daily` yourself (Task Scheduler,
cron or launchd). It finds new postings, applies in auto mode, and reads new replies.

```
applyfirst sweep     # find new postings now
applyfirst apply     # apply to the approved queue now
applyfirst sync      # read replies now
applyfirst daily     # all three
```

## Settings worth knowing

You have full control. A few options come with a warning, shown next to them in Settings:

- **LinkedIn, Indeed, Glassdoor** as sources: these sites may restrict or sign out accounts they
  think are automated.
- **Auto mode** submits without showing you first. Some employers accept one application per role
  or per season.
- **Resume line checking** off: generated lines are no longer checked against your experience.

The browser tool Claude uses will not create accounts, type passwords or solve CAPTCHAs. When an
application needs one of those, it waits for you under **Needs you**, and continues once you are
done.

## What it costs

Filling a form uses Claude. The **Insights** screen shows your real average cost per application,
measured from Claude Code's own usage report.

## Where your data lives

`~/.applyfirst` (set `APPLYFIRST_HOME` to move it): your profile, settings, experience bank,
resumes, applications and a local database. The mail password, if you connect your inbox, is in
`secrets.json` there and is never shown back by the app. Mail is read only: applyfirst never sends,
moves, flags or deletes a message.

## Contributing

Job sites change their forms. When one breaks, open an issue with the site and the step, or send a
fix. `docs/CONTRACTS.md` explains how the parts fit together. Tests run offline:

```
pip install -e ".[dev]"
pytest
```

## License

MIT. The public list of company boards that discovery starts from is downloaded at run time from
[an open internship list](https://github.com/zshah101/Automated-List-Of-Summer-2027-and-Fall-2026-Tech-Internships).
