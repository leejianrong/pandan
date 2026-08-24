import { readFileSync } from "node:fs";
import { expect, test } from "@playwright/test";

import { compareTicketRefs, parseTicketRef } from "../src/lib/tickets";

// Ticket ordering (KAN-986). `KAN-100` used to sort ahead of `KAN-9` in both
// places the SPA orders by ticket: the dashboard's per-assignee buckets and the
// board table's Ticket column.
//
// **Why a pure-logic test lives in the e2e suite.** The frontend has no unit-test
// runner — only `svelte-check` and Playwright — and adding one (vitest, a script,
// a CI job) would be a larger change than the bug it is guarding. Playwright
// already compiles TypeScript and already runs in CI, and a spec that navigates to
// nothing costs milliseconds. So this imports the comparator directly and asserts
// on it; nothing here needs a browser. If a frontend unit runner ever arrives,
// this file moves there unchanged.

const sorted = (refs: string[]) => [...refs].sort(compareTicketRefs);

test("orders by the numeric tail, not the string", () => {
  expect(sorted(["KAN-100", "KAN-9", "KAN-10", "KAN-1"])).toEqual([
    "KAN-1",
    "KAN-9",
    "KAN-10",
    "KAN-100",
  ]);
});

test("the exact pair from the bug report reverses the string comparison", () => {
  // Both halves matter: the second line is the defect, stated as an assertion so
  // this test still describes the bug once the fix is old news.
  expect(compareTicketRefs("KAN-100", "KAN-9")).toBeGreaterThan(0);
  expect("KAN-100".localeCompare("KAN-9")).toBeLessThan(0);
});

test("board-local refs order numerically too (M8 V54)", () => {
  expect(sorted(["ENG-14", "ENG-2", "ENG-77", "ENG-9"])).toEqual([
    "ENG-2",
    "ENG-9",
    "ENG-14",
    "ENG-77",
  ]);
});

test("the epic form groups apart from cards instead of interleaving", () => {
  // `ENG-E7`'s `E` stays in the prefix, so epics sort as their own run rather
  // than mixing into the card numbers.
  expect(sorted(["ENG-E7", "ENG-3", "ENG-E2", "ENG-11"])).toEqual([
    "ENG-3",
    "ENG-11",
    "ENG-E2",
    "ENG-E7",
  ]);
});

test("a differing prefix still decides, and does so as text", () => {
  expect(sorted(["KAN-1", "EPIC-2"])).toEqual(["EPIC-2", "KAN-1"]);
  expect(compareTicketRefs("KAN-5", "KAN-5")).toBe(0);
});

test("a malformed ref sorts deterministically instead of throwing", () => {
  expect(parseTicketRef("")).toEqual({ prefix: "", number: -1 });
  expect(parseTicketRef("KAN-")).toEqual({ prefix: "KAN-", number: -1 });
  // A prefix with no number comes before that prefix's zeroth ticket, so it can
  // never collide with a real ref.
  expect(sorted(["KAN-0", "KAN-"])).toEqual(["KAN-", "KAN-0"]);
  // Leading zeros: same prefix, same number, so the raw-string fallback decides
  // and the order is total rather than arbitrary.
  expect(sorted(["KAN-7", "KAN-007"])).toEqual(["KAN-007", "KAN-7"]);
});

test("the comparator is antisymmetric over every pair it will see", () => {
  const refs = ["KAN-1", "KAN-9", "KAN-100", "EPIC-2", "ENG-14", "ENG-E7", "KAN-", ""];
  for (const a of refs) {
    for (const b of refs) {
      // The two signs must cancel. Summing rather than negating one side on
      // purpose: `-Math.sign(0)` is `-0`, and `toBe` is `Object.is`, so the
      // equal-pairs case would fail on a sign of zero and say nothing true.
      const signs =
        Math.sign(compareTicketRefs(a, b)) + Math.sign(compareTicketRefs(b, a));
      expect(signs, `${a} vs ${b}`).toBe(0);
    }
  }
});

test("both sort sites go through the comparator", () => {
  // A change-detector, and named as one: it catches a call site reverting to a
  // raw string compare, which is the regression that actually happened. It cannot
  // catch every way a sort could go wrong — the assertions above are what pin the
  // ordering itself.
  const sources = ["../src/lib/dashboard.svelte.ts", "../src/lib/components/BoardTable.svelte"];
  for (const path of sources) {
    const source = readFileSync(new URL(path, import.meta.url), "utf8");
    expect(source, `${path} should sort tickets via compareTicketRefs`).toContain(
      "compareTicketRefs(",
    );
    expect(source, `${path} must not compare ticket_number as a string`).not.toContain(
      "ticket_number.localeCompare",
    );
  }
});
