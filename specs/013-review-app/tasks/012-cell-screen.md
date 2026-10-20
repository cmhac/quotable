# 012 - Cell screen: page view and cell view

Spec: `../spec.md` (Requirements C4, C5, C6; Visual design: Layout, Page highlights). Depends
on: task 011.

## Goal

`screens/cell.js`, matching the "Review — cell on the page" board without the queue bar and
the verdict panel (task 013 adds them).

## Steps

1. Layout: page view and cell view side by side, the cell view below on narrow windows.
2. Page view toolbar: view mode (Highlights / Browser PDF viewer), previous page, page box,
   next page, zoom out, zoom %, zoom in, Fit width, Text layer toggle, "Open full PDF at p. n"
   (new tab).
3. Highlights row: the six toggles (seven with Table band when the page holds another table),
   each with its swatch, struck through when off, header off by default. The choice is kept
   in `localStorage` (a display preference, not review state).
4. Page: the PNG scaled to the zoom, highlights drawn as absolutely positioned boxes from the
   page's point coordinates (scale = image width / page width), each with its label on the page
   as in "Page highlights"; for `misplaced`, cell area and matched words together. The text
   layer overlay dims the image and lays the words at their boxes as selectable text. The view
   scrolls to matched words, else cell area, else row window. Clicking inside a cell area
   selects that cell (the API of task 007 gives every row window and column range of the page).
   Other pages show their text layer, header and band, without cell highlights.
5. Browser PDF viewer: an `<iframe>` on `/api/runs/<id>/pdf#page=n` with a line saying it has
   no highlights.
6. PDF missing or changed: the page drawn from the stored words on a blank page of the stored
   size, with the highlights, under the notice; the viewer mode and full-PDF link disabled.
7. Cell view: heading ("Cell n of N", column, page, row) with the five navigation buttons and
   their keys, status badge and explanation, value card, the row table, and the collapsible
   Recheck history, OCR, Merge and Extra field sections, each only when it applies.
8. Check in a browser with the demo project: a `fuzzy`, a `misplaced` (both boxes), an
   `ungrounded` (no matched box), an extra field carried from an earlier page, a shared page
   with the band, an OCR'd page, a missing PDF; zoom and fit; text layer copy. Screenshot next
   to the board.

## Done when

Every C4 and C5 element is on screen with real data, highlights sit on the right words at
every zoom, and the missing-PDF page still shows text and highlights.
