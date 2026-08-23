# Reading the fleet page

`fleet.thudstaff.com` shows how 84 client sites across 6 hosts are actually
doing — backups, WordPress versions, tracker leakage, mail authentication. It
replaces the audit spreadsheet. Everything on it was measured by a script, not
typed by a person.

Numbers below were measured 2026-08-23 and will drift. The live page wins.

---

## It never touches a client site

Every tool feeding the page is read-only. Nothing updates a plugin, edits a file
or changes a setting anywhere. Applying fixes stays a human decision made
somewhere else, so you can click anything on the page without consequence.

## Three cards, three separate questions

A site has a status on each **independently**. A site can be well maintained and
still leak trackers — there is no single overall grade.

| card | question | now |
|---|---|---|
| Fleet health | Is this site being maintained: backups, PHP, WordPress, plugins? | 2 CRIT, 73 WARN, 4 OK, 3 SKIP, 1 FROZEN |
| Cookie consent | Does the homepage fire trackers before anyone consents? | 48 WARN, 21 OK, 10 UNKNOWN |
| Email DNS | Can this domain send mail that authenticates? | SPF 72/78, DKIM 70/78, DMARC 78/78 |

Consent is never CRIT by design — CRIT stays a security tier so it remains a
list somebody works through. Those are technical observations, not legal
conclusions. Email DNS is scored per *domain*, not per site, so it has no column
in the table at the bottom of the page.

## What the states mean

| state | means |
|---|---|
| CRIT | act now |
| WARN | schedule it |
| OK | nothing pending that needs a person |
| SKIP | no environment to measure |
| FROZEN | site frozen by Pantheon |

**WARN is blue, not amber.** The obvious green-and-amber pair failed colourblind
separation when it was tested, so the page uses a validated set instead.

Statuses are worked out when the page is drawn, not when the scan ran, so
retuning a threshold rescores all of history at once instead of looking like 84
sites changed overnight.

## The one idea worth carrying away

**Not knowing is never shown as a pass.**

The failure this system is built against is a confident-looking value standing
in for an absence: `plugin_updates: 0` when nobody looked, `up-to-date` when the
check timed out. That has happened repeatedly, and almost every instance was
caught by a person reading a page rather than by a test.

So coverage sits on the same screen as the answer. A green row is worth exactly
as much as the coverage behind it.

## Why almost everything is WARN

Because **32 sites have been looked at but have no health evidence at all** — no
backup age, no plugin count, no theme count. They score WARN for that reason
alone, not because anything is known to be wrong.

**That 32 is the scoreboard.** It measures whether this project is working, and
watching it fall is what progress looks like. Most of it is sites on a host the
scanner cannot reach yet. Filter the table to *No health evidence* to see them.

Among the sites we can see: 42 are behind on WordPress core, 18 have a plugin
backlog, 2 have no recent database backup, 1 runs PHP past end of security
support.

## How fresh is it

**Nothing is scheduled.** Every number came from a run someone started by hand.

| source | last run | coverage |
|---|---|---|
| Health (Pantheon + WP-CLI) | Aug 23, 9:21 AM | 48 of 52 |
| Cookie consent | Aug 22, 9:09 PM | 69 of 78 |
| Email DNS | Aug 22, 9:08 PM | 78 of 78 |
| Nexcess estate | never run | 0 of 21 |

Nexcess is built but blocked — the host's API sits behind a bot challenge. It is
listed anyway, reading zero, because a source that is silently missing looks
identical to one that found nothing.

## Where a person is actually needed

- **Needs a decision** — 5 sites with no owner and no ruling on whether they
  count as production. They are treated as production until someone decides,
  because guessing the other way once hid the worst-maintained site on the fleet.
- **Sites that do not reconcile** — sites in one source but not another. Every
  one of those disagreements has been worth looking at.
- **What changed** — the short list since each tool last ran. The section to
  read if you only read one.

---

Access is per person. If the page asks you to sign in and then says you are not
authorised, you need adding to the list — ask Doug.
