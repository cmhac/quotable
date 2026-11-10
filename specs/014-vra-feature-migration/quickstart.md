# Quickstart: checking the feature works

Run from the repository root. Steps 1 to 4 are offline and free. Step 5 calls a real model and
costs money; run it only with the user's go-ahead.

## 1. The existing suite still passes

```console
$ just check
```

Expect ruff, ty and every offline test to pass. The tests that count requests through the public
function pass `audit=False` (see the plan); nothing else about them changes.

## 2. The new offline tests

```console
$ just test tests/llm/test_images.py tests/steps/test_audit.py tests/test_audit_pipeline.py tests/test_audit_output.py
```

They show, in order of the spec:

- the audit asks only about pages that have unexplained words, once each, and keeps only
  proposals the text layer confirms (FR-002 to FR-009, SC-002, SC-003);
- an added row is in page order, marked in `audit_added`, grounded `exact` (FR-008, FR-010);
- `audit=False` makes no audit request (FR-001);
- the image of each stage and provider is the one in the table of `contracts/public-api.md`
  (FR-021, FR-022, SC-004), and `sharp_images=False` gives the keys recorded before this change
  (FR-020, SC-001);
- a page too large stops the run before any request (FR-023, SC-006);
- a cell of only dots or dashes comes through unchanged (FR-030, SC-007);
- a run saved before this change still loads (FR-012).

## 3. Defaults through the public function

```console
$ uv run python - <<'EOF'
import inspect, quotable
sig = inspect.signature(quotable.extract_tables)
print(sig.parameters["audit"].default, sig.parameters["sharp_images"].default)
EOF
```

Expect `True True`.

## 4. The columns of a result

```python
tables = quotable.extract_tables("report.pdf", "openai:<model>")
tables[0].records()[0]["audit_added"]      # "", "row" or "cells: <columns>"
tables[0].audit                            # every proposal and its outcome
```

## 5. Live check (opt-in, costs money)

```console
$ just test-live tests/live/test_live_audit.py
```

Needs `OPENAI_API_KEY` and `QUOTABLE_LIVE_TEST_MODEL` (see `.env.example`). It runs a real
multi-page document with the audit off and on, and with sharp images off and on, and prints the
numbers SC-005 asks for: pages audited out of pages, audit requests, rows and cells kept and
rejected, flagged cells and tokens. Copy the numbers into the spec. Then run
`uv run quotable cost-report` and compare it with the provider's dashboard (the prices have never
been compared).
