"""Unit tests for app.emoji — single-grapheme validation (M8 V64, KAN-985).

Pins the whole reason this module exists rather than a bare ``len(value) == 1``:
several common emoji are ONE grapheme cluster built from MULTIPLE codepoints, and
a naive length check would reject every one of them.
"""
from __future__ import annotations

import pytest

from app.emoji import is_single_grapheme, label_emoji_error


@pytest.mark.parametrize(
    "value",
    [
        "😀",  # a plain single-codepoint emoji
        "a",  # any single grapheme is accepted, not just emoji
        "5",
        "🇺🇸",  # a flag: 2 codepoints (regional indicators U+1F1FA U+1F1F8)
        "👨‍👩‍👧‍👦",  # a ZWJ family sequence: 7 codepoints, one grapheme
        "👍🏽",  # a skin-tone modifier: base emoji + Fitzpatrick modifier
        "3️⃣",  # a keycap: digit + variation selector + combining keycap
        "🏴󠁧󠁢󠁳󠁣󠁴󠁿",  # a tag-sequence subdivision flag (Scotland): 7 codepoints
    ],
)
def test_accepts_a_single_grapheme_cluster(value):
    assert is_single_grapheme(value) is True


@pytest.mark.parametrize(
    "value",
    [
        "",  # zero clusters
        "ab",  # two plain characters
        "😀😀",  # two separate emoji (no joiner between them)
        "bug",  # a whole word
    ],
)
def test_rejects_anything_but_exactly_one_cluster(value):
    assert is_single_grapheme(value) is False


def test_error_message_is_stable_text():
    # Not asserting exact wording forever, just that it names the requirement —
    # the 422 detail is the discovery path for an agent with no picker to look at.
    assert "one character" in label_emoji_error()
