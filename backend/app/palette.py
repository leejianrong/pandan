"""The label colour palette (V62, KAN-983) — the canonical list, and the rule.

Two defects in issue #278 share one fix. ``label.color`` accepted any non-empty
string ≤32 chars, so ``"banana"`` was a valid colour that rendered as a blank dot;
and M6's design system defines every colour token **twice** in
``frontend/src/app.css``, once per theme, while a raw ``<input type="color">``
yields a single hex with no dark variant — so roughly half of all free picks are
unreadable in one of the two themes.

So **the palette is the picker** (SHAPING D11). A stored colour is valid when it is
either a palette token name (``"sky"``) or a well-formed hex (``"#0ea5e9"``). The UI
offers only the former; the hex branch exists so the ~existing stored values keep
validating and no value migration is needed (R4.2 — and there is nothing additive to
migrate here, since the column is already ``varchar(32)``).

WHY SEVEN TOKENS AND NOT THE SHAPE'S "~12"
------------------------------------------
The palette is **disjoint from the status colours** (settled 2026-08-23, SHAPING Q5)
so a label can never read as a state. Two things made that far more binding than "~12"
assumed.

First, the exclusion set is wider than the five semantic tokens named in the shape:
``Card.svelte`` renders *priority* as a coloured dot + text — the same visual
primitive as a label dot, in the same card — using amber, orange, ``--danger`` and
``--muted``. Those are exactly as confusable as the semantic tokens.

Second, "disjoint" was measured rather than eyeballed. ``test_palette.py`` computes
CIE Lab ΔE from every candidate to every status colour **in both themes**, and the
first hand-picked set failed it: ``slate`` scored **6.9** against ``--muted`` (which is
literally what priority "low" paints), ``indigo`` **14.4** against ``--agent`` and
``brown`` **14.8** against ``--warning``. All three read as clean hues by name and are
nothing of the kind on screen.

Excluding green, violet, red, orange and grey leaves only blues and magentas — a
narrow arc — so the survivors also have to separate from *each other*. Nine cannot:
mutual ΔE collapses to 11.2. Seven hold at **21.4 mutual**, with every member at least
18.6 from any status colour. Hence seven. Padding to twelve, or even to nine, would
have meant either a green beside "done" or two blues nobody can tell apart, and the
measurement is in the test so the next person who wants a tenth hue finds out what it
costs before shipping it.

THREE PLACES THAT MUST STAY IN SYNC
-----------------------------------
Like ``column``'s ``VALID_COLUMNS``/``ColumnEnum``/``api.ts`` trio, this list lives in
three places by necessity — Python validates, CSS renders, TypeScript draws the grid:

1. :data:`LABEL_PALETTE` here (the authority),
2. ``--label-<token>`` in all three theme blocks of ``frontend/src/app.css``,
3. ``LABEL_PALETTE`` in ``frontend/src/lib/api.ts``.

Unlike that trio, the agreement is **not** left to discipline:
``backend/tests/unit/test_palette.py`` parses the CSS and the TypeScript and asserts
all three match, token for token and hex for hex. Add a hue by editing all three; the
test tells you which one you forgot.
"""

from __future__ import annotations

import re

#: The palette, in the order the swatch grid renders it. Ordered rather than a set
#: because the grid's layout is part of the design: cool hues first, then the
#: magentas, then the two neutrals that read as "no strong colour" without being
#: ``--muted``.
LABEL_PALETTE: tuple[str, ...] = (
    "sky",
    "blue",
    "cyan",
    "fuchsia",
    "mulberry",
    "pink",
    "ink",
)

#: ``token -> (light, dark)``, mirroring the ``--label-<token>`` pairs in ``app.css``.
#: The backend never renders a colour, so this is not used at runtime — it exists so
#: the sync test can compare hexes and not merely names, which is what catches a
#: light value pasted into the dark block.
PALETTE_HEX: dict[str, tuple[str, str]] = {
    "sky": ("#0284c7", "#38bdf8"),
    "blue": ("#2563eb", "#60a5fa"),
    "cyan": ("#0891b2", "#22d3ee"),
    "fuchsia": ("#c026d3", "#e879f9"),
    "mulberry": ("#9d174d", "#fda4d4"),
    "pink": ("#db2777", "#f472b6"),
    # The neutral, and the default. Deliberately slate-800/slate-300 rather than the
    # mid-grey `slate` first proposed: that one measured 6.9 ΔE from --muted, which
    # priority "low" paints as a dot. This one clears it by 18.6 on a large lightness
    # gap, which is what makes a grey-ish label distinguishable from a grey signal.
    "ink": ("#334155", "#cbd5e1"),
}

#: The palette token a colour defaults to when none is given. Shared by the SPA's
#: create form and the CLI's ``label create`` fallback, so a label made in the browser
#: and one made from the terminal start out the same colour — which the two had
#: drifted apart on (the CLI used ``#64748b``, the SPA ``#94a3b8``, each documented as
#: matching the other).
DEFAULT_LABEL_COLOR = "ink"

#: ``#rgb`` or ``#rrggbb``, case-insensitive. Deliberately not accepting ``#rrggbbaa``:
#: a translucent label dot composites against whichever surface it lands on, which is
#: the dual-theme unreadability this slice exists to stop.
HEX_RE = re.compile(r"^#(?:[0-9a-fA-F]{3}|[0-9a-fA-F]{6})$")


def is_valid_label_color(value: str) -> bool:
    """True when ``value`` is a palette token or a well-formed hex.

    Token matching is exact and case-sensitive: the token is an identifier the UI
    sends back verbatim, not free text a human types, so accepting ``"Sky"`` would
    only create two spellings of one colour to store and compare.
    """
    return value in LABEL_PALETTE or bool(HEX_RE.match(value))


def label_color_error() -> str:
    """The 422 detail for a rejected colour.

    It lists every token, because this message *is* the palette's discovery path for
    an agent driving the API or the CLI — neither of which can see the swatch grid,
    and neither of which gets a new command in this slice.
    """
    return (
        "must be a palette token or a hex colour like '#0ea5e9'; "
        f"palette tokens are: {', '.join(LABEL_PALETTE)}"
    )
