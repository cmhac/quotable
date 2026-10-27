// "Your verdict" (spec 013 D4, D6): three choices, the right value and why, a note, drafts.
// What the server refuses to save it says in its own words; nothing is checked twice here.

import { ApiError } from "./api.js";
import { el } from "./dom.js";
import { settingsQuery } from "./queue.js";

export const CATEGORIES = [
  ["misspelling", "Letters wrong"],
  ["spacing", "Spaces or line breaks wrong"],
  ["dropped_word", "Words of the cell left out"],
  [
    "added_word",
    "Words added that the cell does not have (often from a neighbouring cell)",
  ],
  ["hallucination", "A value that is not on the page at all"],
  ["wrong_cell", "The value of another row or column"],
  ["wrong_number", "Digits, sign or decimal point wrong"],
  [
    "corrected_source",
    "The model fixed an error that is printed in the PDF; the PDF’s text is the right value",
  ],
  ["other", "Anything else; the note should say what"],
];

const CHOICES = [
  ["correct", "C", "Correct"],
  ["changed", "X", "Change value"],
  ["unsure", "U", "Can’t tell"],
];
const LABELS = { correct: "Correct", changed: "Changed", unsure: "Can’t tell" };
const MAX_NOTE = 5000;
const PAUSE = 600;
const pad = (n) => String(n).padStart(2, "0");
const clock = (iso) => {
  const d = new Date(iso);
  return `${pad(d.getHours())}:${pad(d.getMinutes())}`;
};

export function prefill(cell) {
  const matched = cell.matched_text;
  return matched && matched !== cell.value ? matched : cell.value;
}

export function startState(cell) {
  const draft = cell.review.draft;
  const changing = Boolean(draft && (draft.value !== null || draft.category));
  return {
    choice: changing ? "changed" : null,
    value: draft?.value ?? prefill(cell),
    category: draft?.category ?? null,
    note: draft?.note ?? "",
  };
}

export function savedText(cell) {
  const { state, verdict } = cell.review;
  if (state === "stale" && verdict)
    return `Stale verdict · judged “${verdict.extracted}” · now “${cell.value}”`;
  if (!verdict) return "Not reviewed yet";
  return `${LABELS[verdict.verdict] ?? verdict.verdict} · ${clock(verdict.time)}`;
}

export function payload(state, cell, settings) {
  const body = { key: cell.review.key, run: cell.run, verdict: state.choice };
  if (state.choice === "changed") {
    body.value = state.value;
    body.category = state.category;
  }
  body.note = state.note;
  if (settings) body.queue = settingsQuery(settings);
  return body;
}

export function createVerdictPanel({
  cell,
  ctx,
  settings,
  onSaved,
  pause = PAUSE,
}) {
  const state = startState(cell);
  const reviewable = cell.review.reviewable;
  const choices = el("div", {
    class: "choices",
    role: "radiogroup",
    "aria-label": "Your verdict",
  });
  const changeSlot = el("div", { class: "change-slot" });
  const refusal = el("div", { class: "refusal-slot" });
  const draftState = el("span", { class: "draft-state" });
  let timer = null;
  let saving = false;

  const note = el("textarea", {
    class: "input note-box",
    rows: 3,
    maxlength: MAX_NOTE,
    value: state.note,
    "aria-label": "Note",
    oninput: (event) => {
      state.note = event.target.value;
      later();
    },
    onblur: () => flush(),
  });

  async function flush() {
    clearTimeout(timer);
    timer = null;
    if (!reviewable) return;
    state.note = note.value;
    const body = {
      key: cell.review.key,
      note: state.note,
      value: state.choice === "changed" ? state.value : null,
      category: state.choice === "changed" ? state.category : null,
    };
    try {
      const answer = await ctx.sendJson("PUT", "/api/drafts", body);
      draftState.replaceChildren(`Draft saved ${clock(answer.saved_at)}`);
    } catch (error) {
      draftState.replaceChildren(
        `The draft could not be saved: ${error.message}`,
      );
    }
  }
  const later = () => {
    clearTimeout(timer);
    timer = setTimeout(flush, pause);
  };

  function paint() {
    choices.replaceChildren(
      ...CHOICES.map(([value, key, label]) =>
        el(
          "button",
          {
            class: "btn choice",
            type: "button",
            role: "radio",
            "aria-checked": String(state.choice === value),
            onclick: () => choose(value),
          },
          el("span", { class: "key" }, key),
          label,
        ),
      ),
    );
    changeSlot.replaceChildren(
      ...(state.choice === "changed" ? [changePanel()] : []),
    );
  }

  function changePanel() {
    const chosen = CATEGORIES.find(([name]) => name === state.category);
    return el(
      "div",
      { class: "change-panel" },
      el(
        "label",
        { class: "field" },
        el("span", { class: "label" }, "Right value"),
        el("input", {
          class: "input mono",
          name: "right_value",
          type: "text",
          value: state.value,
          maxlength: MAX_NOTE,
          oninput: (event) => {
            state.value = event.target.value;
            later();
          },
          onblur: () => flush(),
        }),
        el("span", { class: "note" }, "blank means the cell should be empty"),
      ),
      el("div", { class: "label" }, "Why was the model wrong?"),
      el(
        "div",
        { class: "categories-pick" },
        CATEGORIES.map(([name], i) =>
          el(
            "button",
            {
              class: "btn category",
              type: "button",
              "aria-pressed": String(state.category === name),
              onclick: () => pick(i),
            },
            el("span", { class: "key" }, String(i + 1)),
            name,
          ),
        ),
      ),
      chosen ? el("p", { class: "note description" }, chosen[1]) : null,
    );
  }

  function choose(value) {
    state.choice = value;
    refusal.replaceChildren();
    paint();
    flush();
  }

  function pick(i) {
    state.category = CATEGORIES[i][0];
    paint();
    flush();
  }

  async function save() {
    if (!state.choice || saving) return;
    saving = true;
    refusal.replaceChildren();
    state.note = note.value;
    try {
      const answer = await ctx.sendJson(
        "POST",
        "/api/verdicts",
        payload(state, cell, settings),
      );
      clearTimeout(timer);
      onSaved(answer);
    } catch (error) {
      if (!(error instanceof ApiError)) console.error(error);
      refusal.replaceChildren(
        el("div", { class: "refusal", role: "alert" }, error.message),
      );
    } finally {
      saving = false;
    }
  }

  function cancel() {
    state.choice = null;
    refusal.replaceChildren();
    paint();
  }

  function act(action) {
    if (!reviewable) return false;
    if (action === "correct") choose("correct");
    else if (action === "change") choose("changed");
    else if (action === "unsure") choose("unsure");
    else if (action === "save") save();
    else if (action === "cancel") cancel();
    else if (action.startsWith("category:")) {
      if (state.choice !== "changed") return false;
      pick(Number(action.slice(9)) - 1);
    } else return false;
    return true;
  }

  paint();
  const node = el(
    "section",
    { class: "card verdict" },
    el(
      "div",
      { class: "verdict-head" },
      el("h3", { class: "label" }, "Your verdict"),
      el(
        "span",
        { class: `saved ${cell.review.state === "stale" ? "stale" : ""}` },
        savedText(cell),
      ),
    ),
    reviewable
      ? [choices, changeSlot]
      : el("p", { class: "note" }, "This cell cannot be reviewed."),
    el(
      "label",
      { class: "field" },
      el("span", { class: "label" }, "Note"),
      el("span", { class: "note" }, "optional · up to 5,000 characters"),
      note,
    ),
    el(
      "div",
      { class: "actions" },
      reviewable
        ? el(
            "button",
            {
              class: "btn primary save",
              type: "button",
              onclick: () => save(),
            },
            "Save ",
            el("span", { class: "key" }, "⌘↵"),
          )
        : null,
      reviewable
        ? el(
            "button",
            { class: "btn cancel", type: "button", onclick: () => cancel() },
            "Cancel ",
            el("span", { class: "key" }, "Esc"),
          )
        : null,
      draftState,
    ),
    refusal,
  );
  return { node, act };
}
