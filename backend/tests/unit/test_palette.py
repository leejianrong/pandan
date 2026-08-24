"""The label palette agrees across all three places it lives (V62, KAN-983).

``LABEL_PALETTE`` is necessarily duplicated — Python validates it, CSS renders it,
TypeScript draws the swatch grid, and the CLI prints it in ``--help`` — which is the
same shape as the app's other
"three places that must stay in sync" rules (``VALID_COLUMNS``/``ColumnEnum``/
``api.ts`` for ``column``, and the priority trio).

The difference is that this one is **proven instead of trusted**. Those older rules
are enforced by a line in CLAUDE.md and the hope that the next person reads it; this
file parses the CSS and the TypeScript and fails with the specific token you forgot.
That matters more here than for ``column`` because the failure is *silent and
half-visible*: a token added to Python and TypeScript but missing from ``app.css``
validates fine, renders as a swatch in the picker, saves without error, and then
paints nothing at all on the card — and a token added to only ONE of the two dark
blocks in ``app.css`` is invisible until someone happens to use that theme.

Deliberately in ``tests/unit`` — it needs no database, only the repo on disk.
"""

from __future__ import annotations

import itertools
import re
from pathlib import Path

import pytest

from app.palette import (
    DEFAULT_LABEL_COLOR,
    HEX_RE,
    LABEL_PALETTE,
    PALETTE_HEX,
    is_valid_label_color,
    label_color_error,
)

ROOT = Path(__file__).resolve().parents[3]
APP_CSS = ROOT / "frontend" / "src" / "app.css"
API_TS = ROOT / "frontend" / "src" / "lib" / "api.ts"
CLI_PY = ROOT / "pandan-cli" / "pandan_cli" / "cli.py"

#: The three theme blocks every colour token must appear in, as the selector that
#: opens each. M6's design system defines each token once per block; a palette token
#: present in fewer than all three is the dual-theme unreadability V62 exists to fix.
THEME_BLOCKS = (
    ':root,\n:root[data-theme="light"] {',
    ':root:not([data-theme="light"]) {',
    ':root[data-theme="dark"] {',
)


def _block(css: str, opener: str) -> str:
    """The declarations inside the block that ``opener`` starts.

    Brace-counted from the opener rather than regex-matched to the next ``}``, because
    the dark block is nested inside an ``@media`` rule.
    """
    start = css.index(opener) + len(opener)
    depth = 1
    for i, ch in enumerate(css[start:], start):
        if ch == "{":
            depth += 1
        elif ch == "}":
            depth -= 1
            if depth == 0:
                return css[start:i]
    raise AssertionError(f"unterminated CSS block for {opener!r}")


def _css_tokens(block: str) -> dict[str, str]:
    return {
        m.group(1): m.group(2).strip().lower()
        for m in re.finditer(r"--label-([a-z0-9-]+):\s*([^;]+);", block)
    }


@pytest.fixture(scope="module")
def css() -> str:
    return APP_CSS.read_text()


def test_every_theme_block_defines_exactly_the_palette(css: str) -> None:
    """No block is missing a token, and no block defines a token Python doesn't know.

    The second half matters as much as the first: a ``--label-lime`` left in the CSS
    after the token was dropped from Python is dead weight that reads, to the next
    person, as a hue they may use.
    """
    for opener in THEME_BLOCKS:
        assert opener in css, f"theme block not found: {opener!r}"
        found = set(_css_tokens(_block(css, opener)))
        assert found == set(LABEL_PALETTE), (
            f"block {opener!r} defines {sorted(found)}, "
            f"palette.py says {sorted(LABEL_PALETTE)}"
        )


def test_css_hexes_match_the_recorded_light_dark_pairs(css: str) -> None:
    """The light block carries the light value and both dark blocks the dark one.

    This is the assertion that catches a light hex pasted into the dark block — a
    copy-paste that a names-only check waves straight through, and that nothing else
    would notice until a label turned unreadable in one theme.
    """
    light = _css_tokens(_block(css, THEME_BLOCKS[0]))
    media_dark = _css_tokens(_block(css, THEME_BLOCKS[1]))
    forced_dark = _css_tokens(_block(css, THEME_BLOCKS[2]))

    for token, (want_light, want_dark) in PALETTE_HEX.items():
        assert light[token] == want_light.lower(), f"--label-{token} light value"
        assert media_dark[token] == want_dark.lower(), f"--label-{token} @media dark"
        assert forced_dark[token] == want_dark.lower(), f"--label-{token} forced dark"

    # The in-app toggle must land a viewer on exactly the same colours as the OS
    # preference would. These two blocks exist only because CSS has no way to say
    # "or", so they drifting apart is a live possibility rather than a theoretical one.
    assert media_dark == forced_dark


def _lab(hex_colour: str) -> tuple[float, float, float]:
    """sRGB hex -> CIE L*a*b*. Small enough to inline; no dependency added for it."""
    h = hex_colour.lstrip("#")
    if len(h) == 3:
        h = "".join(c * 2 for c in h)
    r, g, b = (int(h[i : i + 2], 16) / 255 for i in (0, 2, 4))

    def linear(c: float) -> float:
        return c / 12.92 if c <= 0.04045 else ((c + 0.055) / 1.055) ** 2.4

    r, g, b = linear(r), linear(g), linear(b)
    x = r * 0.4124 + g * 0.3576 + b * 0.1805
    y = r * 0.2126 + g * 0.7152 + b * 0.0722
    z = r * 0.0193 + g * 0.1192 + b * 0.9505

    def f(t: float) -> float:
        return t ** (1 / 3) if t > 0.008856 else 7.787 * t + 16 / 116

    fx, fy, fz = f(x / 0.95047), f(y), f(z / 1.08883)
    return (116 * fy - 16, 500 * (fx - fy), 200 * (fy - fz))


def _delta_e(a: str, b: str) -> float:
    """CIE76 ΔE. Crude next to CIEDE2000, and entirely good enough to separate
    "different colour" from "the same colour with a different name"."""
    return sum((x - y) ** 2 for x, y in zip(_lab(a), _lab(b))) ** 0.5


def _status_colours(css: str, block: str) -> set[str]:
    """The colours a label must not be mistaken for, in one theme.

    Includes ``Card.svelte``'s hardcoded priority dots as well as the semantic tokens,
    because priority renders as a coloured dot + text — the *same* visual primitive as
    a label dot, on the same card — so it is exactly as confusable.
    """
    found = {
        m.group(2).lower()
        for m in re.finditer(
            r"--(accent|agent|danger|success|warning|muted):\s*(#[0-9a-fA-F]{3,6});",
            _block(css, block),
        )
    }
    return found | {"#d97706", "#ea580c"}


#: Minimum ΔE between a palette colour and any status colour, per theme.
#: 18 is not a standards figure; it is the floor the shipped palette clears, chosen so
#: the test fails on a genuine collision rather than encoding one. For scale: the
#: rejected `slate` measured 6.9 against --muted, and `indigo` 14.4 against --agent.
MIN_STATUS_DELTA_E = 18.0

#: Minimum ΔE between two palette colours. Lower than the status floor on purpose —
#: two labels being similar is a mild annoyance, a label reading as "done" is a bug.
MIN_MUTUAL_DELTA_E = 20.0


def test_palette_is_perceptually_clear_of_every_status_colour(css: str) -> None:
    """The disjointness decision (SHAPING Q5), measured rather than eyeballed.

    An exact-hex comparison — which is what this test did first — passes any colour
    that is merely *near* a status colour, and that is precisely how a mid-grey
    `slate` (ΔE 6.9 from --muted, which priority "low" paints) and an `indigo`
    (ΔE 14.4 from --agent) got as far as a rendered screenshot before anyone noticed
    they were the status colours wearing different names.
    """
    for theme_index, block in ((0, THEME_BLOCKS[0]), (1, THEME_BLOCKS[2])):
        status = _status_colours(css, block)
        for token, pair in PALETTE_HEX.items():
            colour = pair[theme_index]
            worst = min((_delta_e(colour, s), s) for s in status)
            assert worst[0] >= MIN_STATUS_DELTA_E, (
                f"--label-{token} ({colour}) is only ΔE {worst[0]:.1f} from {worst[1]} "
                f"in the {'light' if theme_index == 0 else 'dark'} theme"
            )


def test_palette_colours_are_distinguishable_from_each_other(css: str) -> None:
    """Nine hues could not do this — mutual ΔE fell to 11.2, because excluding green,
    violet, red, orange and grey leaves only blues and magentas to choose from. Seven
    can. That trade is the reason the shape's "~12" is not what shipped."""
    for theme_index in (0, 1):
        for a, b in itertools.combinations(PALETTE_HEX, 2):
            d = _delta_e(PALETTE_HEX[a][theme_index], PALETTE_HEX[b][theme_index])
            assert d >= MIN_MUTUAL_DELTA_E, (
                f"--label-{a} and --label-{b} are only ΔE {d:.1f} apart "
                f"in the {'light' if theme_index == 0 else 'dark'} theme"
            )


def test_typescript_palette_matches(css: str) -> None:
    """``api.ts`` offers the grid, so it must offer exactly what the server accepts.

    A token here but not in Python is a swatch that 422s when clicked; a token in
    Python but not here is a colour the CLI can set and the picker cannot.
    """
    ts = API_TS.read_text()
    block = re.search(r"export const LABEL_PALETTE = \[(.*?)\] as const;", ts, re.S)
    assert block, "LABEL_PALETTE not found in api.ts"
    assert tuple(re.findall(r'"([a-z0-9-]+)"', block.group(1))) == LABEL_PALETTE

    # The default must agree too, or a label made in the browser and one made from the
    # CLI start different colours — which is the exact drift this slice found and
    # fixed (the CLI had #64748b, the SPA #94a3b8, each claiming to match the other).
    ts_default = re.search(
        r'export const DEFAULT_LABEL_COLOR: LabelPaletteToken = "([a-z0-9-]+)";', ts
    )
    assert ts_default and ts_default.group(1) == DEFAULT_LABEL_COLOR


def test_default_is_itself_a_palette_token() -> None:
    assert DEFAULT_LABEL_COLOR in LABEL_PALETTE


def test_cli_palette_matches() -> None:
    """The CLI carries a fourth copy, and it has to be right for a reason that is not
    obvious: it exists only for ``--help``.

    The CLI deliberately does NOT validate the colour (the server does), so a stale
    list here fails silently — it does not reject anything, it just PRINTS the wrong
    palette to the one audience that cannot see the swatch grid. That is the worst
    kind of drift, so it is pinned like the others."""
    cli = CLI_PY.read_text()
    block = re.search(r"LABEL_PALETTE = \((.*?)\)", cli, re.S)
    assert block, "LABEL_PALETTE not found in pandan_cli/cli.py"
    assert tuple(re.findall(r'"([a-z0-9-]+)"', block.group(1))) == LABEL_PALETTE

    default = re.search(r'DEFAULT_LABEL_COLOR = "([a-z0-9-]+)"', cli)
    assert default and default.group(1) == DEFAULT_LABEL_COLOR


@pytest.mark.parametrize(
    "value",
    ["sky", "blue", "ink", "mulberry", "#0ea5e9", "#abc", "#ABCDEF", "#000000"],
)
def test_accepts_tokens_and_well_formed_hex(value: str) -> None:
    assert is_valid_label_color(value)


@pytest.mark.parametrize(
    "value",
    [
        "banana",  # the value issue #278 named: valid before V62, renders as nothing
        "red",  # a CSS colour keyword is still not a palette token
        "Sky",  # tokens are identifiers, not free text — one spelling only
        "0ea5e9",  # missing the hash
        "#0ea5e",  # five digits
        "#0ea5e9ff",  # #rrggbbaa: a translucent dot composites against its surface,
        # which is the dual-theme unreadability this slice removes
        "var(--danger)",  # no indirection: it would smuggle a status colour back in
        "",
    ],
)
def test_rejects_everything_else(value: str) -> None:
    assert not is_valid_label_color(value)


def test_error_message_names_every_token() -> None:
    """The 422 detail is the palette's only discovery path for an agent.

    Neither the API, the CLI nor MCP gains a "list the palette" verb in this slice
    (the MCP surface is frozen at 49 tools by ADR 0019), so this message is how a
    caller that guessed wrong finds out what is allowed.
    """
    msg = label_color_error()
    for token in LABEL_PALETTE:
        assert token in msg, f"{token} missing from the 422 detail"


def test_hex_re_is_anchored() -> None:
    """A trailing-garbage guard, because an unanchored pattern would accept it.

    ``re.match`` anchors only the start, so without the ``$`` the value
    ``"#0ea5e9; background: url(...)"`` — a stored string that lands straight in a
    ``style`` attribute — would validate.
    """
    assert not HEX_RE.match("#0ea5e9 ")
    assert not HEX_RE.match("#0ea5e9;")
    assert not HEX_RE.match("#0ea5e9) drop")
