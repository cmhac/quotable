# 010 - App shell, runs list and run screen

Spec: `../spec.md` (Requirements B4, B7, C1, C2, C6; Visual design: Layout, Type, Colour,
Statuses, Controls). Depends on: tasks 007 and 009.

## Goal

The browser side starts: plain HTML, CSS and JavaScript modules in
`quotable/review/static/`, no framework, no build step, no file from the internet. The first two
screens look like the mockup's "Runs list" and "Run screen" boards (and the "PDF missing or
changed" board).

## Steps

1. `app.css`: the colours of "Visual design / Colour" as CSS custom properties, the system font
   stacks of "Type", tabular figures for numbers, the header bar, cards, buttons, inputs,
   keycaps, focus ring, the seven status badges of "Statuses" (glyph + word), the alert. Copy
   sizes and spacing from the boards.
2. `app.js` (module): hash routes (`#/`, `#/run/<id>`, `#/run/<id>/table/<n>?...`,
   `#/run/<id>/table/<n>/cell/...?...`, `#/queue?...`) so reload, back and a copied link
   return to the same place (C6); a `fetch` helper that shows API errors in the page; and
   `el(tag, attrs, ...children)`, the only way the app builds DOM: strings become text nodes
   (`textContent`), never markup (B4).
3. `screens/runs.js`: C1 (groups, filters, the run table, flagged chips, cost styles, progress
   bar and "done", the note on costs, the "no runs yet" message with how to make one).
4. `screens/run.js`: C2 (heading line, "Review this run" with progress, Run and Document cards,
   settings chips, extra fields, table cards with their four numbers and the note, the two
   alerts).
5. A test `tests/review/test_static.py`: no file in `static/` contains `innerHTML`,
   `outerHTML`, `insertAdjacentHTML`, `document.write`, `eval(`, `new Function`, `http://` or
   `https://`; every file `index.html` references exists.
6. Check in a browser (the `playwright-cli` skill) on `just review-demo` (task 009):
   both screens, both alerts, a value containing `<img src=x onerror=alert(1)>` shown as text,
   keyboard focus visible on every control. Screenshots side by side with the boards.
7. `ruff check`, `ruff format`, `ty check`, `just test`.

## Done when

The two screens match their boards with real data, nothing is loaded from outside the app,
and the static-file guard test passes.
