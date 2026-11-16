# Changelog

## Unreleased

- **Gets better with every application.** After each form, applyfirst keeps short notes on how
  that kind of form behaves (Greenhouse, Ashby, Workday and so on) and uses them on the next one.
  See and remove them under **Answers**. When most recent applications on one kind of form fail,
  the run says so.
- **Emailed security codes are entered for you.** When a form emails a code after submit
  (Greenhouse does), auto mode reads it from your connected inbox, enters it and finishes the
  application. Only codes that arrive while that application is open count; sign-in codes never do.
- **Resume uploads work again** with current Claude Code, which only lets the browser attach
  files the session may read. Each application may now read exactly its resume and cover letter,
  from an empty folder of its own, and nothing else.

## 0.1.0 (2026-11-15)

First public release, under the GNU Affero General Public License v3.0 or later.

- **Fresh postings first.** Thousands of company career boards (Greenhouse, Lever, Ashby, Workday,
  SmartRecruiters, Workable and more) checked directly. The first search reads the built-in boards
  in about ten minutes, then grows to thousands of boards in the background. Optional extras:
  Indeed, Glassdoor, LinkedIn, Google's past-24-hours results, job-alert emails and your school's
  job board. Paste a link to add any posting.
- **Only what you want.** Filter by location, remote, career level, field, start term, term
  length, keywords, companies to skip and languages. Every skipped posting says why.
- **Your order.** Newest first, soonest deadline, company, or best match.
- **Resumes from your real experience.** Import your resume, confirm your experience once, then
  choose: an ideal resume per role group adjusted to each job, one built fresh per job, or your own
  file as-is. Every generated line traces back to something you confirmed.
- **Applications filled for you.** Claude fills and submits applications in your own Chrome,
  including Workday. Review mode stops before the final button; auto mode submits and saves the
  confirmation.
- **Answer once.** New form questions are asked one time and remembered.
- **Know what is working.** Replies are read from your inbox (read only) and matched to
  applications. Insights shows your interview rate by source, resume, field and posting age.
- **Alerts.** A desktop notification when new matches arrive, and an optional email to yourself (ports 465 and 587, so iCloud and Outlook work too).
- **Continue or try again.** One button puts a waiting or failed application back in the queue.
- **Run every day.** An in-app schedule that also searches every 6 hours while the app is open, plus `applyfirst sweep`, `apply`, `sync` and `daily`
  commands for your computer's own scheduler.
- **Built to be safe.** Background Claude gets browser tools only, the local app answers only your
  computer and its own page, and a daily Claude spending limit ($10) is on by default.
- **Your data stays with you** in `~/.applyfirst`. Your data upgrades itself between versions.
