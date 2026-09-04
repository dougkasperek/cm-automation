# Secrets management: guidance for building the concept

**For Nick, who is building and presenting the concept at the regroup the
week of 2026-09-08.** Written 2026-09-03 by Doug. This is a brief, not the
answer. It says what Brian asked for, the questions the concept has to answer
and the order to take them in, where each answer lives, two things to test on
a real site, and the traps that will sink the pitch if they surface in the
room instead of in the prep.

---

## 1. What Brian asked for, in his words

From the 2026-09-01 regroup: *"bring to this table a proposition on here's
how secrets management could work. Here's the pieces, here's the flow, here's
the steps we got to do to make it work."* And: *"It doesn't have to be a
working thing. It just needs to be like, this is what it should look like and
where it should connect and what it should do."* Assumptions are fine if they
are written down as assumptions. He wants to be able to say either "that is
the right thing for us" or "we don't need this right now".

He scoped it: *"solving the issue where when Autopilot runs, it brings live
down, it steps on dev"*, and then, after Zach said he had fixed the pasting
problem by hand, the part that survives: *"your eyes don't get to see it and
we're injecting it."* So the concept's job is the security one. Nobody's eyes
on a key; a machine places it.

Matt's three steps for Keeper stand: validate it is the right approach, get
it acquired and set up, get the data in. Doug will get the Keeper quote and
covers the CI half (section 5). You cover the WordPress half.

---

## 2. The questions, in order

Answer these in this order, because each one changes the next.

1. **What actually happens to a key on Pantheon today?** Where does a plugin
   store its licence key, what does Autopilot copy between environments and
   what does it not, and why did Zach's "put it on Live once" fix work. Get
   this from Pantheon's Autopilot docs and from Zach, not from memory. If you
   cannot draw this on a whiteboard the rest will not hold.
2. **Where can a key live so that the copy does not touch it?** Pantheon has
   its own answer to this and documents it for licence keys specifically.
   Find it, find what it costs, and find how PHP reads it.
3. **Which of our plugins can take a key from that place?** A key outside the
   database only helps a plugin that reads its key from code. This is
   per plugin and per vendor. Section 4 gives you the list and the site
   counts from the fleet scan; you supply the answer for each. This table is
   the slide the room will remember.
4. **What is Keeper's role, given the above?** Start from `docs/SECRETS.md`,
   which has Doug's notes on how Keeper feeds a CI job. Then find out, from
   Keeper's own docs, whether Keeper can reach a WordPress site directly at
   all. The answer shapes the whole flow, and it is not the answer people in
   the room assume.
5. **What does Nexcess offer?** Nothing is a valid finding. Then note what
   this repo says about Nexcess SSH access in `CLAUDE.md` under Hard
   boundaries, because any write to a Nexcess site over SSH touches a
   control Doug approved, and the concept has to say so rather than walk
   into it.
6. **What does it cost and who has to do what?** Keeper's add-on has no
   published price; Doug is getting the quote. Pantheon's piece and GitHub's
   piece have prices you can find. Effort is per site per plugin; estimate it
   from the counts in section 4.

---

## 3. Two things to test on one real site before you present

Both are ten-minute checks on a single Pantheon site, and both change the
pitch depending on the answer. Pick a sandbox site or ask Zach which one.

- **Can a person read a Pantheon secret back?** Set one, then see what the
  Terminus listing command and the site dashboard show to an ordinary team
  member. If values are visible to anyone with site access, the concept still
  beats the clipboard, but "nobody sees it" becomes "only people with Pantheon
  access see it", and you should say that yourself.
- **Does Autopilot's update process see it?** Autopilot updates plugins with
  WP-CLI on its own environment. Pantheon's docs say which scopes the
  application and its scripts can read and do not mention WP-CLI. Run a
  WP-CLI command on a Multidev that reads the secret. If it comes back empty,
  the plugin is unlicensed at exactly the moment it updates, and the flow
  needs a different shape.

Write down what you ran and what it printed. A measured answer in the room is
worth more than the diagram.

---

## 4. The premium plugins in the fleet

From the fleet scan, latest run per site, 68 sites inventoried, counted as
sites and not installs. For each one, the concept needs: can the key come
from code (a constant in `wp-config.php`, a filter, or a WP-CLI command),
what the vendor documents, and whether the site still has to activate against
the vendor even when the key comes from code.

| plugin | sites |
|---|---|
| Divi (theme) | 65 |
| WP Activity Log | 65 installs, mostly the free tier |
| Divi Booster | 37 |
| Object Cache Pro | 20 |
| Divi Overlays | 17 |
| PDF Embedder Premium | 13 |
| TablePress, paid tiers | 10 |
| UpdraftPlus Premium | 10 |
| Gravity Forms | 9 |
| ACF PRO | 4 |
| Formidable Pro | 2 |
| WPMU DEV Dashboard and Smush Pro | 1 |
| Elementor Pro | 1 |
| Yoast SEO Premium | 1 |

Go to each vendor's documentation, not to a blog. Where the vendor is silent,
say so; where a constant only exists in the plugin's source, say that too,
because it can change without notice. Sort the finished table by site count
so the room sees the biggest rows first.

---

## 5. What Doug is covering

- The Keeper quote, and the questions for the Keeper admin in
  `docs/SECRETS.md` section 4.
- The automation suite's own credentials. `docs/SECRETS.md` section 2 has
  the exact way a GitHub Actions job reads from Keeper; that half is written
  and does not need to be in your concept beyond one sentence.

---

## 6. Traps

Each of these will come up. Better from you than from the room.

- **The pasting problem is already fixed.** Zach said so and Brian accepted
  it. If the concept is pitched as saving Zach's time it loses in the first
  minute. It is about who sees the value, and about a key surviving refreshes
  and new environments without a person.
- **Keeper "injecting at runtime" was said on the call.** Check whether that
  is true for a PHP application on a host where we cannot install anything.
  If it is not, the flow has a courier in it, and the concept has to name it.
- **A key from code is not the same as no activation.** Vendors still count
  site activations. Ask what Dev, Test, Live and the Autopilot environment
  each cost against a licence's site limit, especially for plugins that count
  per site.
- **The biggest plugin may not have a code path.** If the table in section 4
  shows that, put it on the slide and say what the answer for that plugin is
  instead. A concept that quietly skips its largest row is the one Brian will
  poke at.
- **Nexcess is a control, not a configuration.** Section 2, item 5.
- **Do not build it.** Brian said so twice. A diagram, the pieces, the steps,
  the cost, the assumptions, the challenges. Written assumptions are a
  feature of this deliverable.

---

## 7. The shape of a good answer

One page and one diagram. The diagram shows where the value travels: the
store, the courier, the place it lands on the site, and the plugin that reads
it, with the Autopilot copy drawn so the room can see what it does and does
not touch. Under it: the plugin table, the cost line, the steps in order, and
a short list headed "assumptions and known challenges" with the two test
results at the top. If the answer to a question is "we do not know yet", that
is a line on the page, not a gap in it.

Doug has read the vendor material once already and has notes. Ask for them
after you have formed your own view, not before, so the concept is yours.
