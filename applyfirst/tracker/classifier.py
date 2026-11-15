"""Read one email and say what kind of reply it is.

Ported from the working outcome sweep this package grew out of. The order of the checks is
the whole design: a verdict beats an invitation, an invitation beats a confirmation, and a
subject that only says "update" with no verdict in the visible text stays `other` (it is
listed for the user, never guessed as a confirmation).
"""
from __future__ import annotations

import re

CLASSES = ("confirmation", "rejection", "assessment", "interview", "offer", "other")

# Sender domains that are job boards, newsletters or marketing: never a reply from an employer.
NEWSLETTER_DOMAINS = [
    "mail.beehiiv.com", "substack.com", "mailchimp.com", "mcsv.net", "constantcontact.com",
    "match.indeed.com", "alert.indeed.com", "jobalerts-noreply@linkedin.com", "linkedin.com",
    "glassdoor.com", "ziprecruiter.com", "simplyhired.com", "mail.coursera.org", "medium.com",
    "tldrnewsletter.com", "email.claude.com", "mail.anthropic.com",
]
NEWSLETTER_SENDER_RE = re.compile(
    r"newsletter|beehiiv|substack|mailchimp|constantcontact|@marketing\.|unsubscribe|"
    r"digest@|weekly@|jobalerts?@|job-?alerts?|@news\.|@promo", re.I)

# Applicant tracking systems: mail from these is application mail by construction.
ATS_DOMAINS = [
    "greenhouse-mail.io", "greenhouse.io", "ashbyhq.com", "lever.co", "myworkday.com",
    "smartrecruiters.com", "workablemail.com", "workable.com", "rippling.com",
    "recruitee-mail.com", "pinpoint.email", "breezy-mail.com", "jobvite.com", "icims.com",
    "successfactors", "taleo.net", "collage.co", "interviewstream.com", "hirevue.com",
    "indeedapply@indeed.com", "avature.net", "csod.com", "bamboohr.com", "teamtailor.com",
    "comeet.co", "personio.de", "jibeapply.com", "eightfold.ai", "mail.amazon.jobs",
    "dayforcehcm.com", "ultipro.com", "oraclecloud.com", "paylocity.com", "applytojob.com",
]
FREE_MAIL = ("gmail.com", "outlook.com", "hotmail.com", "yahoo.com", "icloud.com", "live.com",
             "proton.me", "protonmail.com")

APP_EVIDENCE_RE = re.compile(
    r"your application|you applied|applying|application for|your candidacy|candidate|"
    r"co-?op|internship|\bintern\b|the .{0,50}\b(role|position)\b|hiring team|talent|recruit",
    re.I)

REJECT_RE = re.compile(
    r"not (be )?moving forward|not move forward|decided not to (move|proceed|progress)|"
    r"decided to (proceed|move forward|pursue) with (other|another)|decided to pursue (other|another)|"
    r"decided we will not|(proceed|moving forward|move forward|decided)[^.]{0,60}other candidates|"
    r"unfortunately|not (been )?selected|regret to (inform|tell)|"
    r"will not be (moving|proceeding|considered|progressing|advancing)|"
    r"no longer (under consideration|being considered)|not (be )?progress(ing)?|"
    r"not continuing|pursue other|not to move forward|never easy news|difficult (news|decision)|"
    r"appreciate your interest[^.]{0,90}\bhowever\b|selected other candidates|"
    r"have selected other|extremely fortunate to have|fantastic response|"
    r"however,? given the|strong enough alignment|paused hiring|unable to move you forward|"
    r"won.t be moving|more closely align|"
    r"offered the (position|role) to (another|someone)|"
    r"malheureusement|bien que nous ayons|pas retenu|ne donnerons pas suite|"
    r"after (careful|much) (consideration|review)[^.]{0,80}(decided|will not)", re.I)
CLOSED_RE = re.compile(
    r"position (has been |is |was )?(closed|filled|cancel)|"
    r"(role|posting|requisition|job) (has been |is |was )?(closed|filled|cancel)|"
    r"have filled|has been filled|no longer (accepting|available|open)|position closed", re.I)
OFFER_RE = re.compile(
    r"pleased to (offer|extend)|(delighted|thrilled|happy|excited) to (offer|extend)|"
    r"offer of employment|extend (you )?(an|a|the) (formal |verbal |written )?offer|"
    r"your offer letter|congratulations[^.]{0,80}\boffer\b|offer (is|has been) (attached|enclosed)",
    re.I)
ASSESS_RE = re.compile(
    r"online assessment|(technical|coding|skills?|pre-?employment|cognitive) (assessment|test)|"
    r"assessment (task|link|invitation)|invitation to online|hirevue|codesignal|hackerrank|"
    r"coding challenge|take-?home|codility|pymetrics|testgorilla|game-?based", re.I)
INTERVIEW_SUBJECT_RE = re.compile(r"interview|phone screen|video call", re.I)
INTERVIEW_TEXT_RE = re.compile(
    r"(invite|invited) you to (an |a )?(video |virtual |phone )?interview|"
    r"schedule (an|your|a) (interview|phone|call|chat)|interview (has been |is )?scheduled|"
    r"you.re confirmed for your interview|advance you to the (final|next) (stage|round)|"
    r"we.d like to (speak|chat|meet|talk)|would like to (speak with|schedule|meet)|"
    r"digital interview|video interview|virtual interview", re.I)
UPDATE_SUBJECT_RE = re.compile(r"update|status|decision|important information|regarding|progress",
                               re.I)
CONFIRM_RE = re.compile(
    r"thank you for (applying|your application|your interest|submitting|taking the time to apply)|"
    r"thanks for (applying|your application)|(received|receiving) your application|"
    r"application (has been |was )?(received|submitted|confirmation|acknowledg)|"
    r"successfully (submitted|received)|we.ve (successfully )?received|"
    r"confirm(s|ing)? (that )?we (have )?received|your application (to|for|with) .{0,80}(has been|was)|"
    r"thanks for completing", re.I)


def sender_domain(frm: str) -> str:
    m = re.search(r"@([A-Za-z0-9.-]+)", frm or "")
    return m.group(1).lower().rstrip(".") if m else ""


def sender_addr(frm: str) -> str:
    m = re.search(r"([A-Za-z0-9._%+-]+@[A-Za-z0-9.-]+)", frm or "")
    return m.group(1).lower() if m else ""


def is_newsletter(frm: str) -> bool:
    addr, dom = sender_addr(frm), sender_domain(frm)
    for known in NEWSLETTER_DOMAINS:
        if "@" in known:
            if addr == known:
                return True
        elif dom == known or dom.endswith("." + known):
            return True
    return bool(NEWSLETTER_SENDER_RE.search(addr))


def is_ats(frm: str) -> bool:
    addr, dom = sender_addr(frm), sender_domain(frm)
    for a in ATS_DOMAINS:
        if "@" in a:
            if addr == a:
                return True
        elif a in dom:
            return True
    return False


def wording_class(subject: str, text: str) -> str:
    """The class from the words alone, no sender judgement."""
    low = text.lower()
    subj = (subject or "").lower()
    if "daily digest" in subj:
        return "other"      # a digest lists several notices; never guess from it
    if REJECT_RE.search(low):
        return "rejection"
    if CLOSED_RE.search(low):
        return "rejection"  # a closed or filled posting ends that application
    if OFFER_RE.search(low):
        return "offer"
    if ASSESS_RE.search(low):
        return "assessment"
    if INTERVIEW_SUBJECT_RE.search(subj) or INTERVIEW_TEXT_RE.search(low):
        return "interview"
    if UPDATE_SUBJECT_RE.search(subj):
        return "other"
    if CONFIRM_RE.search(low):
        return "confirmation"
    return "other"


def classify(subject: str, body: str, sender: str) -> str:
    """confirmation | rejection | assessment | interview | offer | other.

    Mail from a newsletter, job-alert or marketing sender is always `other`, however the
    words read: a digest with "interview" in its subject is not an interview.
    """
    if is_newsletter(sender or ""):
        return "other"
    text = " ".join([subject or "", (body or "")[:4000]])
    return wording_class(subject or "", text)
