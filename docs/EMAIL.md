# Connect your email

Connect your inbox and applyfirst does two things for you:

- **Reads your replies.** Confirmations, assessments, interviews, offers and rejections are spotted
  and matched to your applications. A confirmation email marks an application as submitted, and
  **Insights** then shows what is actually getting you interviews.
- **Can email you new matches.** Optional. Turn it on and a short list goes to your own address
  whenever new postings fit you.

It takes about two minutes.

## What it can and cannot do

- **Read only.** applyfirst never sends, moves, flags or deletes a message in your mailbox. The only
  email it ever sends is the optional alert to yourself, and only when you turn that alert on.
- It asks your mail server for messages that look like replies about a job (subjects and words like
  "interview", "assessment", "unfortunately", "next steps"), not for your whole inbox. The first
  check covers the last 35 days; after that it picks up what is new.
- Your password stays on your computer, in `~/.applyfirst/secrets.json`. The app never shows it back.
- Skip this and nothing breaks. You can mark any submitted application as **Assessment**,
  **Interview**, **Offer**, **Rejected** or **Withdrawn** by hand on the **Applications** screen.

## Use an app password

Most providers do not let a third-party app sign in with your everyday password. They let you make
a separate **app password**: a one-off code that works only for one app and can be deleted any time
without touching your real password. That is what you paste into applyfirst.

## Where to put it

1. Open **Settings** and find the **Email replies** group.
2. Turn on **Read my replies**.
3. Fill in the three boxes that appear:
   - **Mail server**: your provider's IMAP server (below).
   - **Mail server port**: `993` for all three providers below.
   - **Email address**: the login for your mailbox.
4. In **Email password**, paste the app password and press **Save password**. The note beside it
   changes to "A password is saved".

Replies are read whenever the daily run happens (turn on **Run every day**, see
[DAILY.md](DAILY.md)) and any time you run this in a terminal:

```
applyfirst sync
```

Run it once now to test. The result appears on **Activity** under "Email check". A bad password or
server shows up as "Could not sign in to the mail server".

## Gmail

| Setting | Value |
| --- | --- |
| Mail server | `imap.gmail.com` |
| Mail server port | `993` |
| Email address | your full Gmail address |
| Password | a Google app password |

1. Turn on 2-Step Verification for your Google Account. App passwords need it.
2. Go to [myaccount.google.com/apppasswords](https://myaccount.google.com/apppasswords), name it
   "applyfirst", and create it.
3. Paste the 16-character code into **Email password** and press **Save password**.

Google's steps: [Sign in with app passwords](https://support.google.com/accounts/answer/185833).
Server details: [Gmail IMAP settings](https://developers.google.com/workspace/gmail/imap/imap-smtp).

Good to know from Google's page: you will not see the app password option if 2-Step Verification
is set up with security keys only, if you are signed in with a work or school account, or if your
account has Advanced Protection. Changing your Google password revokes your app passwords, so you
would make a new one. IMAP is always on for personal Google Accounts, so there is nothing to
enable.

## iCloud Mail

| Setting | Value |
| --- | --- |
| Mail server | `imap.mail.me.com` |
| Mail server port | `993` |
| Email address | see below |
| Password | an app-specific password |

1. Make sure two-factor authentication is on for your Apple Account.
2. Go to [account.apple.com](https://account.apple.com), sign in, open **Sign-In and Security**,
   then **App-Specific Passwords**, and generate one.
3. Paste it into **Email password** and press **Save password**.

Apple's pages: [iCloud Mail server settings](https://support.apple.com/en-us/102525) and
[App-specific passwords](https://support.apple.com/en-us/102654).

For the email address, Apple's server settings page says to use the part before the `@`, for
example `johnappleseed` rather than `johnappleseed@icloud.com`. Try that first. If sign-in fails,
try the full address.

For alert emails to yourself, set **Smtp host** to `smtp.mail.me.com` and **Smtp port** to
`587` (bottom of the **Email replies** group). Apple's outgoing server uses port 587, and
applyfirst switches to the matching secure connection on that port by itself.

## Yahoo Mail

| Setting | Value |
| --- | --- |
| Mail server | `imap.mail.yahoo.com` |
| Mail server port | `993` |
| Email address | your full Yahoo address |
| Password | a Yahoo app password |

1. Go to [Yahoo Account Security](https://login.yahoo.com/account/security).
2. Under **External connections**, choose **Create app password**, name it "applyfirst", and
   generate it.
3. Paste it into **Email password** and press **Save password**.

Yahoo's pages: [server settings](https://help.yahoo.com/kb/SLN4075.html) and
[app passwords](https://help.yahoo.com/kb/SLN15241.html). Yahoo suggests creating the password in a
browser you have used to sign in to Yahoo for a few days, and not in a private or Incognito window.

## Outlook.com and Hotmail: not supported yet

applyfirst signs in with a password, and Microsoft's own
[Outlook.com settings page](https://support.microsoft.com/en-us/office/pop-imap-and-smtp-settings-for-outlook-com-d088b986-291d-42b8-9564-9c414e2aa040)
says Outlook.com requires modern sign-in (OAuth2). So Outlook.com and Hotmail mailboxes are not
supported yet. Until they are, mark outcomes by hand on the **Applications** screen. You can still use
everything else in applyfirst.

## Any other provider

If your provider offers IMAP and an app password, it should work. Check your provider's help page
for the IMAP server name and whether it asks for an app password, then enter those under
**Mail server** and **Mail server port**.

## New-match alert emails

Under **Alerts** in Settings, **Email me new matches** sends a short list to your own address, using
the email settings above. Turn it on only if you want email on top of the desktop notification.
**Only when at least** sets how many new matches it takes before an alert goes out.

The alert uses the same address and app password, sends to that address and nowhere else, and
connects to your provider's outgoing server (applyfirst fills in `smtp.` plus your mail server's
name, for example `smtp.gmail.com`, over port 465). Gmail and Yahoo both accept this. The
**Smtp host** and **Smtp port** boxes at the bottom of the **Email replies** group let you change
them if your provider differs. Port 587 works too (iCloud and Outlook use it): applyfirst picks
the right secure connection for the port.

## If it does not work

See [TROUBLESHOOTING.md](TROUBLESHOOTING.md#email-sync-fails).
