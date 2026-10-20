# 013 - Queue screen, queue bar, verdicts and keyboard

Spec: `../spec.md` (Requirements D1 to D9, E; Visual design). Depends on: tasks 008 and 012.

## Goal

The review flow in the browser: `screens/queue.js` matching the "Review — queue, sample &
statistics" board, and the queue bar and verdict panel of the "Review — cell on the page"
board added to the cell screen.

## Steps

1. Queue screen, left: Statuses (check boxes with badges and counts, `exact` apart), Scope (run,
   table, column, include extra fields), the big matching count, Sampling (review all or
   sample, slider and number kept in step, confidence radio group, target margin with
   "suggests n cells", seed and New seed), and "Start review" / "Resume review". Settings are
   kept in `localStorage` and in the URL.
2. Queue screen, right: "How good is this extraction?", the headline numbers, the interval chart
   (with its text equivalent), the three counts, the two margin tiles with $p$, $n$ and the
   correction written out, the by-status table with "All" and its note, the error-category
   bars and the note on `verdicts.jsonl`. Numbers formatted as "Type" says.
3. Queue bar on the cell screen (only in a queue): description, Edit queue, reviewed count,
   changed share with interval, the progress strip (mark shapes of D3, hover text, click to
   jump, narrowing to 3 px then scrolling with the current mark in view) and its legend.
4. Verdict panel: "Your verdict" with the saved state (or the stale line of D8), the three
   choices as a radio group, the Change value panel (right value prefilled as D4 says,
   categories with keys 1-9 and the chosen one's description), the note, Save and Cancel,
   "Draft saved HH:MM". A refused save shows the server's message next to Save. After a save
   in a queue, go to the next unreviewed item.
5. Drafts: note and right value saved to the API after a short pause and on blur, restored when
   the cell opens.
6. Keyboard: the D7 table, plus the "Shortcuts ?" dialog (focus trapped while open, Esc
   closes). Single keys are ignored in text boxes; ⌘↵ / Ctrl+Enter and Esc work there.
7. Check in a browser with the demo project: a full pass over a sample of 20 with every verdict
   kind, a refused save, a reload mid-draft, a stale verdict after re-running the demo with a
   changed answer, the statistics matching a recount from `verdicts.jsonl`, keyboard only.
   Screenshots next to both boards.

## Done when

A reviewer can go from the run screen through a sampled queue to final statistics with the
keyboard alone, and every number on the queue screen matches task 005's functions.
