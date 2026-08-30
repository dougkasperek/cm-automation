#!/usr/bin/env python3
"""
vercmp.py - WordPress version comparison, and Wordfence affected-range matching.

Step 4 of docs/VULN-INTEL-REVIEW.md, and the piece that has to be right: every
vulnerability finding this suite ever produces rests on the answer to "is this
installed version inside that affected range".

WHY NOT semver, AND WHY NOT `packaging`
---------------------------------------
WordPress plugin versions are not semver. Measured in this fleet's own
catalogue on 2026-08-30: 96 installs carry FOUR-part versions (`4.9.97.43`),
107 carry a single component, and one is `42.1.1c` -- a letter suffix. The
repo's contract is stdlib Python, so `packaging` is not available, and it
would give the wrong answer here anyway: it rejects `42.1.1c` outright.

The right target is PHP's `version_compare`, because that is what WordPress
itself uses and therefore what a plugin author means by "3.3.9.1 is newer than
3.3.9".

THE ANSWER IS THREE-VALUED, ALWAYS
----------------------------------
`is_affected` returns True, False, or **None meaning "cannot say"**. It is
never a boolean with a caveat rendered next to it.

This is not defensive style, it is the single bug this repo keeps making. In
the current catalogue **17 of 85 sites have no component rows at all** and
**106 installs carry no readable version**, including one active theme. If
"we could not read the version" renders the same as "not affected", the page
reports a clean site that nobody looked at -- line 1 of CLAUDE.md's bug table,
on the security axis, where it is worst.

Callers must handle None explicitly. There is no default.
"""

# Absence sentinels used across this repo. The ledger stores the STRING
# "unknown", not None, which is why a falsiness test is not enough -- that
# exact mistake put `<code>unknown</code>` into a hostname cell once.
ABSENT = (None, "", "unknown", "n/a", "none")

# PHP's ordering of non-numeric version parts, from php_version_compare.
# Anything not listed sorts BELOW dev, which is PHP's behaviour for an
# unrecognised form.
_FORMS = {
    "dev": 0,
    "alpha": 1, "a": 1,
    "beta": 2, "b": 2,
    "rc": 3,
    "pl": 5, "p": 5,
}
_NUMBER = 4
_UNKNOWN_FORM = -1

# A part that is absent because one version has fewer parts than the other.
# It must sort ABOVE dev/alpha/beta/rc and BELOW a number, so that:
#     1.0     >  1.0-dev      (missing beats dev)
#     1.0     <  1.0.0        (missing loses to a number)
# PHP reaches this with a sentinel form; the value is what matters, not the
# spelling.
_MISSING = 3.5


def _order(part):
    if part is None:
        return _MISSING
    if part[:1].isdigit():
        return _NUMBER
    return _FORMS.get(part.lower(), _UNKNOWN_FORM)


def canonicalize(v):
    """Split a version the way PHP does.

    `_`, `-` and `+` become separators, and a separator is inserted at every
    digit/non-digit boundary. So `1.0.1c` -> ['1','0','1','c'] and
    `4.3.2-dev` -> ['4','3','2','dev'].
    """
    s = str(v)
    out, cur, prev = [], [], None
    for ch in s:
        if ch in "._-+":
            if cur:
                out.append("".join(cur))
                cur = []
            prev = None
            continue
        kind = "d" if ch.isdigit() else "s"
        if prev is not None and kind != prev and cur:
            out.append("".join(cur))
            cur = []
        cur.append(ch)
        prev = kind
    if cur:
        out.append("".join(cur))
    return out


def compare(a, b):
    """-1 if a < b, 0 if equal, 1 if a > b. PHP `version_compare` semantics.

    Raises on an absent version rather than guessing. Callers that might hold
    one must check `is_absent` first -- an exception is noisy, and a silently
    wrong comparison here becomes a silently wrong security finding.
    """
    if is_absent(a) or is_absent(b):
        raise ValueError("cannot compare absent version: %r vs %r" % (a, b))
    pa, pb = canonicalize(a), canonicalize(b)
    for i in range(max(len(pa), len(pb))):
        x = pa[i] if i < len(pa) else None
        y = pb[i] if i < len(pb) else None
        ox, oy = _order(x), _order(y)
        if ox != oy:
            return -1 if ox < oy else 1
        # Same class. Numbers compare numerically, so 10 > 9; anything else is
        # already equal by class.
        if ox == _NUMBER:
            ix, iy = int(x), int(y)
            if ix != iy:
                return -1 if ix < iy else 1
    return 0


def is_absent(v):
    return v is None or str(v).strip().lower() in ABSENT


def in_range(version, rng):
    """Is `version` inside one Wordfence affected-version range?

    True / False / None, where None means the question could not be answered.

    The range shape is verified against the vendor's own V3 documentation
    (read 2026-08-30), not guessed:

        {"from_version": "1.0.0", "from_inclusive": true,
         "to_version":   "1.2.3", "to_inclusive":   true}

    `*` means unbounded, and ONLY as the entire string -- the vendor states
    that `1.*` matches an asterisk literally rather than globbing. So there is
    no pattern expansion here on purpose.

    The KEY of an affected_versions entry (`"1.0.0 - 1.2.3"`) is display text
    and is never parsed. Only this object is the contract.
    """
    if is_absent(version):
        return None
    if not isinstance(rng, dict):
        return None

    lo, hi = rng.get("from_version"), rng.get("to_version")
    if is_absent(lo) and lo != "*":
        return None
    if is_absent(hi) and hi != "*":
        return None

    if lo != "*":
        try:
            c = compare(version, lo)
        except ValueError:
            return None
        if c < 0 or (c == 0 and not rng.get("from_inclusive", False)):
            return False
    if hi != "*":
        try:
            c = compare(version, hi)
        except ValueError:
            return None
        if c > 0 or (c == 0 and not rng.get("to_inclusive", False)):
            return False
    return True


def is_affected(version, affected_versions):
    """Is `version` inside ANY of a software entry's affected ranges?

    True / False / None. None wins over False: if some range could not be
    evaluated and no other range matched, the honest answer is "cannot say",
    not "clean". A range we failed to parse is not a range we cleared.
    """
    if is_absent(version):
        return None
    if not isinstance(affected_versions, dict) or not affected_versions:
        return None
    unsure = False
    for rng in affected_versions.values():
        r = in_range(version, rng)
        if r is True:
            return True
        if r is None:
            unsure = True
    return None if unsure else False
