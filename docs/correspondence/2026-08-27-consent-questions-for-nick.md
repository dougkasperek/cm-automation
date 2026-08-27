# Consent: questions for Nick

**Edit this file directly.** Tick boxes with `[x]`, fill blanks after the
arrows. Anything you don't know or don't want to answer, leave — a blank is
more useful to us than a guess.

**Why we're asking.** We built a scanner that loads each site's homepage and
records what fires before consent. It flagged `interstatewaste.com` as leaking
four trackers. You told Doug that's expected on an opt-out model, and you were
right — when we re-tested by actually clicking Reject All, three of the four
stopped cleanly.

The scanner can see *what happens*. It can't see *what was intended*, and
that's the difference between a finding and a false alarm. These questions are
the intent.

---

## 1. Which sites do we manage consent for?

Doug says roughly 15, and that it grows as clients onboard. We need to know
which ones so the dashboard stops reporting other people's configuration as
our defect.

**Tick every site where clevermethod manages cookie consent.**

Sites where we detected consent tooling:

- [ ] actioncarting.com
- [ ] animatics.com
- [ ] blockclub.co
- [ ] breakstones.com
- [ ] choosechq.com
- [ ] ciminelli.com
- [ ] cottrillspharmacy.com
- [ ] crackerbarrelcheese.com
- [ ] galbanicheese.com
- [ ] gmroot.com
- [ ] icegame.com
- [ ] interstatewaste.com
- [ ] knudsen.com
- [ ] kraftnaturalcheese.com
- [ ] lactalisamericangroup.com
- [ ] lactalisheritagedairy.com
- [ ] lactalisyogurtusa.com
- [ ] lifebreath.com
- [ ] midwestyogurt.com
- [ ] newmarkciminelli.com
- [ ] runtalnorthamerica.com
- [ ] scottishcheddarcheese.com
- [ ] summerstreetcapital.com
- [ ] valbresocheese.com
- [ ] zehnder-rittling.com
- [ ] zehnderamerica.com

**Any site we manage that is NOT in the list above?**

→ 

**Is "we manage it" the same as "it's in our OneTrust tenant"?**

- [ ] Yes, same thing
- [ ] No — some tenant sites aren't ours to manage, or vice versa
- [ ] Depends → 

---

## 2. The consent model

**Is opt-out the default across the tenant?**

- [ ] Yes, all sites
- [ ] No, all opt-in
- [ ] Varies by client → which are opt-in? 

**Which regions have geo rules that switch to opt-in?**

- [ ] California only
- [ ] California + EU/UK
- [ ] Other → 
- [ ] Varies by site → 

**Our scanner runs from one location and doesn't record where.** Outside a
restricted region, an opt-out site fires everything on load — correctly. Should
that ever be reported as a problem?

- [ ] No — never a finding, it's the intended behaviour
- [ ] Only if the site is supposed to be opt-in
- [ ] Yes, we'd want to see it anyway → why: 

---

## 3. What "correctly configured" means

This is the one that decides how the whole check works.

**Is this the right pass/fail test: load the page, click Reject All, reload —
and nothing should fire except strictly necessary?**

- [ ] Yes, that's the test
- [ ] Almost — with exceptions, listed below
- [ ] No → the right test is: 

**Should anything be expected to still fire after Reject All?**

- [ ] Nothing
- [ ] These are fine → 

**On `interstatewaste.com`, after clicking Reject All, DoubleClick, GA4 and
Meta Pixel all stopped. MS Clarity kept firing.** After the rejection the
consent state read `C0001:1, C0002:0, C0003:0, C0004:0` — so functional stayed
granted while performance and targeting were denied.

**Which OneTrust category is MS Clarity assigned to?**

- [ ] C0002 performance
- [ ] C0003 functional
- [ ] C0004 targeting
- [ ] Other / not sure → 

**Is Clarity continuing to fire after Reject All expected?**

- [ ] Yes, it's categorised so that's correct
- [ ] No, that's a gap we should fix
- [ ] Need to look → 

---

## 4. Sites with no consent tooling

37 sites load trackers and have no consent banner at all. Some are ours, some
are not, and we don't know which. Examples: `sgroilawley.com`,
`alliedcircuits.com`, `iroquoisfence.com`, `lasershows.com`,
`ciminelliflorida.com` (3 trackers each).

**For sites with no banner yet — how should we read that?**

- [ ] In progress, banner coming
- [ ] Out of scope, client declined or never asked
- [ ] Mix → the in-progress ones are: 
- [ ] No plan either way

**You mentioned these take longer because every third-party script has to be
found and fed into GTM. Is there a list of which sites are in that queue?**

- [ ] Yes → where: 
- [ ] No, it's ad hoc

---

## 5. Two we couldn't test

The scanner never got a clean look at these — a block page or a load failure,
so we have no reading at all rather than a clean one:

`42northbrewing.com`, `clevermethod.com`, `ecmea.org`, `elmanyhistory.org`,
`hitsfoundation.org`, `hoosierfeeder.com`, `internationaljuniormasters.com`,
`kulinskigolf.com`

**Anything we should know about these?**

→ 

---

## 6. Anything we're getting wrong

We're building the check around what you've told us. If the model above is
wrong in a way these questions don't cover, this is the place to say so.

→ 
