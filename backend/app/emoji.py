"""Single-grapheme validation for ``label.emoji`` (M8 V64, KAN-985, issue #278).

A label's emoji is a second, independent visual dimension from its colour — the
point of the slice (SHAPING D12) is that **two labels sharing a colour must still
be distinguishable at a glance**, and a colour palette alone tops out at seven
hues. Unlike ``label.color`` there is no palette here: the field accepts *any*
single Unicode grapheme cluster, not a fixed set — emoji, a letter, a digit,
whatever renders as one glyph.

WHY "GRAPHEME CLUSTER" AND NOT "CHARACTER"
-------------------------------------------
The obvious check, ``len(value) == 1``, counts Python string *codepoints*, not
what a person perceives as one character. Several common emoji are built from
more than one codepoint on purpose:

- a flag is a PAIR of Regional Indicator Symbols (``"🇺🇸"`` is 2 codepoints),
- a family/couple emoji is several people joined by ZERO WIDTH JOINER
  (``"👨‍👩‍👧‍👦"`` is 7 codepoints: 4 people + 3 U+200D),
- a skin-tone variant is a base emoji plus a Fitzpatrick modifier
  (``"👍🏽"`` is 2 codepoints),
- a keycap (``"3️⃣"``) is a digit + U+FE0F (variation selector) + U+20E3
  (combining enclosing keycap) — 3 codepoints,
- a subdivision flag (e.g. the Scotland flag) is a black-flag base plus a TAG
  sequence terminated by U+E007F — 7 codepoints.

Each of the above is ONE grapheme cluster — the thing a person would call "one
emoji" and the thing a text cursor moves over in one keypress — built from
MULTIPLE codepoints. ``len(value) == 1`` would reject every one of them, which
is precisely backwards: they're exactly the rich emoji this field exists for.

Grapheme cluster boundaries are Unicode's own algorithm (UAX #29), and Python's
standard library does not implement it (``len``/iteration are codepoint-based,
and ``unicodedata`` has no boundary API). The ``regex`` package's ``\\X`` pattern
does implement UAX #29, so this module is a thin wrapper around it rather than a
hand-rolled reimplementation of a spec with this many edge cases.
"""
from __future__ import annotations

import regex

#: label.emoji varchar(8) — Postgres counts a varchar's length in characters
#: (codepoints), not bytes, so this comfortably covers every example in the
#: module docstring: the longest, a tag-sequence flag, is 7 codepoints.
MAX_LABEL_EMOJI_LEN = 8


def is_single_grapheme(value: str) -> bool:
    """True when ``value`` is exactly one Unicode grapheme cluster.

    Empty string → False (zero clusters); a plain multi-character string like
    ``"bug"`` → False (three clusters) — both fall out of "exactly one" with no
    special-casing needed.
    """
    return len(regex.findall(r"\X", value)) == 1


def label_emoji_error() -> str:
    """The 422 detail for a rejected emoji — the discovery path for an agent
    driving the API or CLI directly, neither of which sees a picker."""
    return "must be exactly one character (a single emoji or other grapheme cluster)"
