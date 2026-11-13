# Contract: messages and error texts

Wording is fixed here so tests can pin it. `<...>` is filled in. None of these contains a prompt, a model answer, an extracted value or a file path. Spec: [../spec.md](../spec.md).

## 1. Warning at failure (`TableFailedWarning`)

One per failed table, from the full pass only.

```text
table 'Investment Account #6 transactions' failed (pages 357-360): no columns. The table is returned with the problem recorded; read it with table.problems.
```

- `table '<label>'`: the table's label. If the label is empty, `table 'unnamed'`.
- `(pages <list>)`: the pages of all its problems, as ranges.
- After the colon, the problems of that stage, joined with `; `. Each is a `Problem.message`.

## 2. Warning on reading a failed table

One per call of `rows()`, `page_rows()`, `records()`, `to_pandas()`, `to_polars()` or `flagged()`.

```text
table 'Investment Account #6 transactions' failed: no columns. The data returned by records() may be incomplete or wrong.
```

`records()` is the name of the accessor that was called.

## 3. Closing message (FR-010)

Only when at least one table failed, one extra line after the summary line of the final message (spec 017):

```text
quotable: done in 6 min 12 s
  total cost $0.4812 (limit $20.00)
  discovery $0.4812 (estimated $0.42) | rest $0.0000
  new requests: 120 discovery; 0 answered from the cache
  927 pages, 14 tables, 120 table pages
  2 tables failed: 'Investment Account #6 transactions' (pages 357-360), 'Trademark registrations' (pages 889-892)
```

With no failed table the message is exactly what it is today. (The figures above are an example.)

## 4. Window retry text

The retry's text names each problem, the page and the table (built in PR #5, kept):

```text
Your previous answer was invalid:
- page 357, table 'Investment Account #6 transactions': schema discovery returned an unusable schema: no columns. Give the column names printed in the table's header row, or, if the page continues a known table without printing its header, that table's listed column names
```

## 5. OCR progress (Story 5; shown only with `progress=True` and more than 5 pages to OCR)

```text
quotable: OCR of 901 pages without text (0 already in the cache)
quotable: OCR 90 of 901 pages
...
quotable: OCR done, 901 pages in 41 min 05 s
```

A line at each 10% done. Plain lines in every sink.

## 6. Text-layer errors

| Case | Exception | Text |
|---|---|---|
| `ocr=False`, more than 10% of the pages have no words | `TextLayerError` | `The PDF has no text on <n> of <m> pages (more than 10%).` followed by the existing `REMEDY_OCR_OFF` |
| `ocr=False`, no page has words | `TextLayerError` | unchanged: `The PDF has no text layer (it looks like a scan without OCR).` + `REMEDY_OCR_OFF` |
| OCR needed, PaddleOCR cannot be imported | `OcrUnavailableError` | says OCR is installed with quotable only on macOS arm64, Linux x86_64 and Windows x86_64 with Python 3.11 to 3.13, and what to do (reinstall on a supported platform, or OCR the PDF yourself) |
| OCR needed, PaddlePaddle missing but PaddleOCR present | `OcrUnavailableError` | says to install a PaddlePaddle build (CPU: `pip install paddlepaddle==3.3.1`; NVIDIA: see the README) |

The messages stop mentioning `quotable[ocr]` and `quotable[ocr-core]`.
