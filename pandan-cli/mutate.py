"""Scratch mutation-test harness for V45 (KAN-428). Deleted before commit.

Each mutation is a (file, old, new) literal replacement applied to a COMMITTED
tree, so the restore is `git checkout --` of a file whose index copy is authoritative
(nothing uncommitted can be lost). Runs the suite, records red/green, restores, and
verifies the tree is clean again before moving on.
"""
from __future__ import annotations

import subprocess
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parent
CLI = ROOT / "pandan_cli" / "cli.py"
CFG = ROOT / "pandan_cli" / "config.py"

MUTATIONS: list[tuple[str, Path, str, str]] = [
    (
        "1. hint total reports the KEPT length, not the original",
        CLI,
        "return text[:limit], len(text)",
        "return text[:limit], len(text[:limit])",
    ),
    (
        "2. truncate by BYTES instead of characters",
        CLI,
        "    return text[:limit], len(text)",
        '    return text.encode()[:limit].decode("utf-8", "replace"), len(text.encode())',
    ),
    (
        "3. off-by-one: a string exactly at the limit gets cut",
        CLI,
        "if limit <= 0 or len(text) <= limit:",
        "if limit <= 0 or len(text) < limit:",
    ),
    (
        "4. _truncate_inline drops the hint",
        CLI,
        'return f"{kept}… {_truncation_hint(total)}"',
        "return kept",
    ),
    (
        "5. --full is ignored (limit never collapses to 0)",
        CLI,
        "return 0 if full else limit",
        "return limit",
    ),
    (
        "6. _truncate_payload does not recurse into lists",
        CLI,
        "        return [_truncate_payload(item, limit) for item in value]",
        "        return value",
    ),
    (
        "7. truncate ANY long string, not just the allow-list",
        CLI,
        "                if key in _TEXT_FIELDS and isinstance(item, str)",
        "                if isinstance(item, str)",
    ),
    (
        "8. attach V44's summary BEFORE truncating instead of after",
        CLI,
        "    payload = _truncate_payload(result, _text_limit(full=full, limit=limit))\n"
        "    # Computed from the untruncated ``result``: the numbers describe the rows the API\n"
        "    # returned, and cannot be perturbed by how much of a body we chose to print.\n"
        "    found = _summary_for(result)\n"
        "    if found is None:\n"
        "        return payload\n"
        "    _, summary = found\n",
        "    found = _summary_for(result)\n"
        "    if found is None:\n"
        "        return _truncate_payload(result, _text_limit(full=full, limit=limit))\n"
        "    _, summary = found\n"
        "    payload = _truncate_payload(\n"
        "        {**result, 'summary': summary}, _text_limit(full=full, limit=limit)\n"
        "    )\n",
    ),
    (
        "9. an empty-string description still emits a block",
        CLI,
        "    if not description:\n        return head",
        "    if description is None:\n        return head",
    ),
    (
        "10. single-card render goes back to _card_line (no description at all)",
        CLI,
        "        return _card_block(result, limit=limit)",
        "        return _card_line(result)",
    ),
    (
        "11. --fields projection stops truncating",
        CLI,
        "        if resolved in _TEXT_FIELDS:\n            cell = _truncate_inline(cell, limit)",
        "        if False:\n            cell = _truncate_inline(cell, limit)",
    ),
    (
        "12. a negative PANDAN_MAX_TEXT_CHARS is accepted",
        CFG,
        "    if value < 0:",
        "    if False:",
    ),
    (
        "13. the config-file merge forgets max_text_chars again",
        CFG,
        "                    k: str(table[k]) for k in _CONFIG_KEYS if table.get(k) is not None",
        '                    k: str(table[k])\n'
        '                    for k in ("api_url", "token", "board_id")\n'
        "                    if table.get(k) is not None",
    ),
    (
        "14. _comment_line stops truncating",
        CLI,
        '            _truncate_inline(str(comment.get("body", "")), limit),',
        '            str(comment.get("body", "")),',
    ),
    (
        "15. run() ignores the configured limit and hardcodes the default",
        CLI,
        "            limit=config.max_text_chars,",
        "            limit=DEFAULT_MAX_TEXT_CHARS,",
    ),
    (
        "16. _emit's structured branch drops full/limit",
        CLI,
        "print(_render_structured(_structured_payload(result, full=full, limit=limit), fmt))",
        "print(_render_structured(_structured_payload(result), fmt))",
    ),
    (
        "17. _notification_line stops truncating",
        CLI,
        '            _truncate_inline(str(n.get("body", "")), limit),',
        '            str(n.get("body", "")),',
    ),
    (
        "18. single-epic render goes back to _epic_line",
        CLI,
        "            _epic_block(result, limit=limit)",
        "            _epic_line(result)",
    ),
    (
        "19. list ROWS grow a description block too",
        CLI,
        "        lines = [_card_line(c) for c in cards]",
        "        lines = [_card_block(c, limit=limit) for c in cards]",
    ),
    (
        "20. config show stops reporting the limit",
        CLI,
        '        "max_text_chars": resolved.get("max_text_chars") or str(DEFAULT_MAX_TEXT_CHARS),',
        "",
    ),
]


def git(*args: str) -> str:
    return subprocess.run(
        ["git", *args], cwd=ROOT, capture_output=True, text=True, check=True
    ).stdout


def clean() -> bool:
    return git("status", "--porcelain", "--", "pandan_cli").strip() == ""


def main() -> int:
    green: list[str] = []
    for name, path, old, new in MUTATIONS:
        assert clean(), f"tree dirty before {name}"
        src = path.read_text(encoding="utf-8")
        count = src.count(old)
        if count != 1:
            print(f"ANCHOR MISS ({count} matches) — {name}")
            green.append(f"{name} [anchor miss]")
            continue
        path.write_text(src.replace(old, new), encoding="utf-8")
        proc = subprocess.run(
            [sys.executable, "-m", "pytest", "-q", "-x", "--no-header", "-p", "no:cacheprovider"],
            cwd=ROOT,
            capture_output=True,
            text=True,
        )
        git("checkout", "--", str(path.relative_to(ROOT)))
        assert clean(), f"tree dirty after restoring {name}"
        tail = proc.stdout.strip().splitlines()[-1] if proc.stdout.strip() else "(no output)"
        verdict = "RED  " if proc.returncode != 0 else "GREEN"
        if proc.returncode == 0:
            green.append(name)
        print(f"{verdict} {name}\n      {tail}")
    print("\n=== mutations that came back GREEN (blind guards) ===")
    print("\n".join(green) if green else "(none)")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
