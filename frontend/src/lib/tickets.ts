// Ordering ticket references the way a human reads them (KAN-986).
//
// `"KAN-100".localeCompare("KAN-9")` is negative: a string comparison reaches the
// `1` against the `9` in the fifth character and stops there, so every ticket that
// crosses a digit width lands in the wrong place. That was already wrong on a
// sparse board, and M8's board-local refs (V54) make it impossible to miss — a
// 77-card board goes from `KAN-530…971` to a solid `1…77`, where the misordering
// is the first thing you see.
//
// The parse is structural rather than a `KAN-`/`EPIC-` special case: split off the
// *trailing digit run*, compare what precedes it as text and the digits as a
// number. That covers every form the product mints or plans to — `KAN-9`,
// `EPIC-7`, the board-local `ENG-14`, and the epic variant `ENG-E7`, whose `E`
// stays in the prefix and therefore groups epics apart from cards rather than
// interleaving them by number.

const TRAILING_DIGITS = /^(.*?)(\d+)$/;

export function parseTicketRef(ref: string): { prefix: string; number: number } {
  const match = TRAILING_DIGITS.exec(ref);
  // No trailing digits at all — an empty string, or a value that is not a ticket
  // ref. Treat the whole thing as prefix and give it a number no real ref can
  // have, so it sorts ahead of `KAN-0` instead of colliding with it.
  if (!match) return { prefix: ref, number: -1 };
  return { prefix: match[1], number: Number(match[2]) };
}

export function compareTicketRefs(a: string, b: string): number {
  const left = parseTicketRef(a);
  const right = parseTicketRef(b);
  if (left.prefix !== right.prefix) return left.prefix.localeCompare(right.prefix);
  if (left.number !== right.number) return left.number - right.number;
  // Same prefix and same number: only reachable through leading zeros
  // (`KAN-007` against `KAN-7`). Fall back to the raw strings so the order is
  // total and the sort stays deterministic.
  return a.localeCompare(b);
}

// What a human sees for a card or epic's ticket (M8 V54, KAN-975, issue #280).
// The board-local `ref` (`ENG-14`) is the display form; the canonical
// `ticket_number` (`KAN-955`) is the fallback for the rare case the API hasn't
// attached one (a board with no key, which cannot happen post-migration, or a
// read path that doesn't resolve it). Every *display* site should go through this.
//
// **Sorting follows the displayed form, and searching matches both.** A user sorts
// the column they can see, so a table showing `ENG-14` that ordered itself by a
// hidden `KAN-955` would look unsorted; within one board the two agree anyway (both
// track creation order), so this only bites across boards — which is exactly where
// it would otherwise be inexplicable. Searching accepts either form too — see
// `CommandPalette.svelte`, whose `keywords` carry the canonical ticket alongside the
// ref, since that stays the address the rest of the product takes.
export function displayRef(entity: { ref?: string | null; ticket_number: string }): string {
  // `||` rather than `??`: an empty-string ref is as unusable as a missing one, and a
  // read path that renders "" would otherwise put a blank where the ticket goes.
  return entity.ref || entity.ticket_number;
}
