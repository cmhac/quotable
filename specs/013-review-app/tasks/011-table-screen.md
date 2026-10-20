# 011 - Table screen

Spec: `../spec.md` (Requirement C3; Visual design: Statuses, Review labels). Depends on: task 010.

## Goal

`screens/table.js`, matching the "Table screen" board, plus the Review column the board
prepares but does not draw.

## Steps

1. Heading line, label, "Review flagged cells" (to the queue screen scoped to this table) and
   "Download N rows as CSV" (a link to `rows.csv` with the current filters).
2. Summary card: the stacked status bar (with a text equivalent), the counts under it,
   position check and recheck numbers.
3. Filters card: the seven status toggles (`aria-pressed`) with counts, search, column, page,
   review state, the four check boxes, "N of M rows match", "Clear filters", the sort line.
   Every change updates the URL (C6) and refetches; typing in search waits for a short pause.
4. Grid: sortable headings with ▲ / ▼ / ↕, numeric columns right-aligned, extra fields after a
   heavier divider with "extra", the "By status" heading row, each cell's value and badge
   (`exact` quiet, `ungrounded` underlined), the Review column last with the label styles of
   "Review labels", the open row highlighted. A cell is a link to the cell screen with the
   current filter in its URL (so "Cell n of N" and previous / next follow it).
5. Pager: "Rows a-b of N", previous, page box, next.
6. Check in a browser with the demo project: every filter, sort, paging, CSV download, a table
   of a few rows and one of several thousand (the demo of task 009 has one), keyboard only.
   Screenshot next to the board.

## Done when

The screen matches its board with real data, every C3 control works, and a large table stays
responsive.
