import assert from "node:assert/strict";
import { test } from "node:test";

import { byClass, byTag, findAll, installDom } from "./fake_dom.mjs";

installDom();
const STATIC = "../../../quotable/review/static/";
const V = await import(`${STATIC}verdict.js`);
const { ApiError } = await import(`${STATIC}api.js`);

function words(node) {
  if (node.nodeType === 3) return node.data;
  return node.childNodes.map(words).join(" ");
}
const text = (node) => words(node).replace(/\s+/g, " ").trim();
const click = (node) => node.listeners.click[0]({ preventDefault() {} });
const settle = () => new Promise((resolve) => setImmediate(resolve));
const KEY = { sha256: "a", columns: ["A"], page: 1, row: 2, column: "A" };

function cell(over = {}) {
  return {
    run: "run1",
    value: "1,204",
    matched_text: "1,294",
    status: "fuzzy",
    review: {
      state: "none",
      verdict: null,
      draft: null,
      reviewable: true,
      key: KEY,
    },
    ...over,
  };
}

function fakeCtx(over = {}) {
  const sent = [];
  return {
    sent,
    sendJson: async (method, path, body) => {
      sent.push([method, path, body]);
      return path === "/api/drafts"
        ? { saved_at: "2026-10-20T14:05:00Z" }
        : { next: null, verdict: {} };
    },
    ...over,
  };
}

const make = (c = cell(), ctx = fakeCtx(), extra = {}) => {
  const saved = [];
  const panel = V.createVerdictPanel({
    cell: c,
    ctx,
    settings: null,
    onSaved: (r) => saved.push(r),
    ...extra,
  });
  return { ctx, saved, ...panel };
};

test("the right value starts as the matched text when it differs, else the extracted value", () => {
  assert.equal(V.prefill(cell()), "1,294");
  assert.equal(V.prefill(cell({ matched_text: "1,204" })), "1,204");
  assert.equal(V.prefill(cell({ matched_text: null })), "1,204");
  assert.equal(V.prefill(cell({ matched_text: "" })), "1,204");
});

test("a saved draft comes back, a fresh cell starts empty", () => {
  const s = V.startState(
    cell({
      review: {
        ...cell().review,
        draft: { note: "n", value: "9", category: "spacing" },
      },
    }),
  );
  assert.deepEqual(s, {
    choice: "changed",
    value: "9",
    category: "spacing",
    note: "n",
  });
  assert.deepEqual(V.startState(cell()), {
    choice: null,
    value: "1,294",
    category: null,
    note: "",
  });
  const noteOnly = V.startState(
    cell({
      review: {
        ...cell().review,
        draft: { note: "n", value: null, category: null },
      },
    }),
  );
  assert.equal(noteOnly.choice, null);
  assert.equal(noteOnly.note, "n");
});

test("the saved state: none, a verdict with its time, or stale with both values", () => {
  assert.equal(V.savedText(cell()), "Not reviewed yet");
  const saved = cell({
    review: {
      state: "correct",
      verdict: {
        verdict: "correct",
        time: "2026-10-20T14:05:00Z",
        extracted: "1,204",
      },
      draft: null,
    },
  });
  assert.match(V.savedText(saved), /^Correct · /);
  const stale = cell({
    value: "FY2026",
    review: {
      state: "stale",
      verdict: {
        verdict: "correct",
        time: "2026-10-20T14:05:00Z",
        extracted: "FY2025",
      },
      draft: null,
    },
  });
  assert.equal(
    V.savedText(stale),
    "Stale verdict · judged “FY2025” · now “FY2026”",
  );
});

test("three choices as a radio group with their keys; nothing selected at first", () => {
  const { node } = make();
  const group = byClass(node, "choices")[0];
  assert.equal(group.getAttribute("role"), "radiogroup");
  const radios = byTag(group, "button");
  assert.deepEqual(radios.map(text), [
    "C Correct",
    "X Change value",
    "U Can’t tell",
  ]);
  assert.ok(
    radios.every(
      (r) =>
        r.getAttribute("role") === "radio" &&
        r.getAttribute("aria-checked") === "false",
    ),
  );
  assert.equal(byClass(node, "change-panel").length, 0);
});

test("Change value opens the panel with the prefilled value and nine categories", () => {
  const p = make();
  p.act("change");
  const panel = byClass(p.node, "change-panel")[0];
  const input = findAll(
    panel,
    (e) => e.getAttribute("name") === "right_value",
  )[0];
  assert.equal(input.value, "1,294");
  assert.match(text(panel), /blank means the cell should be empty/);
  const cats = byClass(panel, "category");
  assert.equal(cats.length, 9);
  assert.match(text(cats[0]), /^1 misspelling/);
  assert.match(text(cats[8]), /^9 other/);
});

test("a category key chooses it and shows its description", () => {
  const p = make();
  p.act("change");
  p.act("category:5");
  assert.match(
    text(byClass(p.node, "change-panel")[0]),
    /A value that is not on the page at all/,
  );
  assert.equal(
    byClass(p.node, "category").find(
      (c) => c.getAttribute("aria-pressed") === "true",
    ) !== undefined,
    true,
  );
});

test("a category key does nothing unless the change panel is open", () => {
  const p = make();
  assert.equal(p.act("category:1"), false);
});

test("Correct saves a verdict with the key, the run and no value", async () => {
  const ctx = fakeCtx();
  const p = make(cell(), ctx);
  p.act("correct");
  p.act("save");
  await settle();
  const [method, path, body] = ctx.sent.find(
    ([, path]) => path === "/api/verdicts",
  );
  assert.equal(method, "POST");
  assert.deepEqual(body, {
    key: KEY,
    run: "run1",
    verdict: "correct",
    note: "",
  });
});

test("a changed verdict sends the right value and the category; the queue settings go too", async () => {
  const ctx = fakeCtx();
  const p = make(cell(), ctx, {
    settings: {
      statuses: ["fuzzy"],
      run: "",
      table: "",
      column: "",
      extra_fields: true,
      mode: "all",
      sample_size: 100,
      confidence: 95,
      margin: 8,
      seed: 1,
    },
  });
  p.act("change");
  p.act("category:1");
  p.act("save");
  await settle();
  const body = ctx.sent.find(([, path]) => path === "/api/verdicts")[2];
  assert.equal(body.verdict, "changed");
  assert.equal(body.value, "1,294");
  assert.equal(body.category, "misspelling");
  assert.equal(body.queue.statuses, "fuzzy");
});

test("saving with nothing chosen sends nothing", async () => {
  const ctx = fakeCtx();
  const p = make(cell(), ctx);
  assert.equal(p.act("save"), true);
  await settle();
  assert.equal(ctx.sent.length, 0);
});

test("a refused save shows the server's message and keeps the choice", async () => {
  const ctx = fakeCtx({
    sendJson: async () => {
      throw new ApiError("Choose why the model was wrong.", 400);
    },
  });
  const p = make(cell(), ctx);
  p.act("change");
  p.act("save");
  await settle();
  const alert = byClass(p.node, "refusal")[0];
  assert.equal(alert.getAttribute("role"), "alert");
  assert.equal(text(alert), "Choose why the model was wrong.");
  assert.equal(byClass(p.node, "change-panel").length, 1);
});

test("a saved verdict tells the screen, with the server's answer", async () => {
  const ctx = fakeCtx();
  const p = make(cell(), ctx);
  p.act("unsure");
  p.act("save");
  await settle();
  assert.equal(p.saved.length, 1);
});

test("Cancel drops the unsaved choice", () => {
  const p = make();
  p.act("change");
  p.act("cancel");
  assert.equal(byClass(p.node, "change-panel").length, 0);
  assert.ok(
    byTag(byClass(p.node, "choices")[0], "button").every(
      (b) => b.getAttribute("aria-checked") === "false",
    ),
  );
});

test("leaving the note box saves a draft and says when", async () => {
  const ctx = fakeCtx();
  const p = make(cell(), ctx);
  const note = byTag(p.node, "textarea")[0];
  note.value = "check page 4";
  note.listeners.blur[0]({ target: note });
  await settle();
  const [method, path, body] = ctx.sent[0];
  assert.equal(method, "PUT");
  assert.equal(path, "/api/drafts");
  assert.deepEqual(body, {
    key: KEY,
    note: "check page 4",
    value: null,
    category: null,
  });
  assert.match(
    text(byClass(p.node, "draft-state")[0]),
    /^Draft saved \d\d:\d\d$/,
  );
});

test("a failed draft save is said, not hidden", async () => {
  const ctx = fakeCtx({
    sendJson: async () => {
      throw new ApiError("disk full", 500);
    },
  });
  const p = make(cell(), ctx);
  const note = byTag(p.node, "textarea")[0];
  note.value = "x";
  note.listeners.blur[0]({ target: note });
  await settle();
  assert.match(text(byClass(p.node, "draft-state")[0]), /could not be saved/i);
});

test("the note is limited to 5,000 characters and says it is optional", () => {
  const { node } = make();
  assert.equal(byTag(node, "textarea")[0].getAttribute("maxlength"), "5000");
  assert.match(text(node), /optional · up to 5,000 characters/);
});

test("a cell that cannot be reviewed has no choices", () => {
  const { node } = make(
    cell({ review: { ...cell().review, reviewable: false, key: null } }),
  );
  assert.equal(byClass(node, "choices").length, 0);
  assert.match(text(node), /cannot be reviewed/i);
});

test("a note restored from a draft fills the box", () => {
  const { node } = make(
    cell({
      review: {
        ...cell().review,
        draft: { note: "old", value: null, category: null },
      },
    }),
  );
  assert.equal(byTag(node, "textarea")[0].value, "old");
});

test("values are text, never markup", () => {
  const { node } = make(cell({ matched_text: "<img src=x onerror=alert(1)>" }));
  assert.equal(findAll(node, (e) => e.tagName === "IMG").length, 0);
});
