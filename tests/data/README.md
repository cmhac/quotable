# Test data

Sample PDFs from the House Appropriations Committee's community project funding
"included projects" tables (public documents):

| File | Pages | Notes |
|---|---|---|
| `fy22_milcon_house_original.pdf` | 1 | Rotated page (`/Rotate 90`); every recorded cell is printed verbatim. |
| `fy24_milcon_house_original.pdf` | 2 | Rotated; a different column set. |
| `fy22_ag_house_original.pdf` | 4 | Upright; shared (merged) cells repeated down rows, some real model misses. |
| `senate_expenditures_garbled.pdf` | 3 | Rotated pages from the Secretary of the Senate's expenditure report (printed pages B-41 to B-43, a public document). The pages render correctly but the embedded text layer is garbled by a font-encoding problem (`0.00` is stored as `4$44`). Negative fixture for the text-layer check: it must be rejected with `TextLayerError`. Has no `.rows.json`. |
| `senate_expenditures_paddleocr.pdf` | 3 | The same three pages after OCR with PaddleOCR 3.7.0 (PP-OCRv6 medium models, 300 dpi): each page is the rasterized image plus an invisible word-level text layer. The layer is readable (scores like the House fixtures) but has real OCR errors, notably every thousands comma read as a period (`68.027.74`) and a few misread names (`MARESE`, `BOLIEK`). Positive fixture for the text-layer check, and the document for exercising the recheck's deference to the text layer. Has no `.rows.json`. |

`<name>.rows.json` holds the rows a vision model returned for each PDF in the original
project (final values after its recheck), keyed by page: `{"columns": [...], "pages": {"1": [row, ...]}}`.
The offline tests replay these as the "model" answers. They are recorded outputs, not a
ground truth: a few cells in the ag sample are known to be wrong, which the tests allow for.
