# Quickstart: checking spec 017

## Offline (no network, no key, no cost)

```bash
just test tests/test_meter.py tests/test_estimate.py tests/test_progress.py tests/test_cost_limit.py
just test tests/llm/test_cached_client_meter.py
just test            # the whole suite: nothing existing changes (SC-007)
just check           # hooks (ruff, ty), then tests
```

What each file proves:

| File | Proves |
|---|---|
| `tests/test_meter.py` | Totals; stop at "strictly above"; unmetered request stops the run; settled total includes in-flight requests; `raise_by` rounded up; money formatting never prints a total over the limit as equal to it |
| `tests/test_estimate.py` | Image rules reproduce the examples in the providers' documentation; a model outside the table gives "no estimate"; cached windows are left out; the estimate for the rest equals measured cost per page times pages left |
| `tests/test_progress.py` | A file gets no control codes and no repeated line (at most 30 lines for 100 pages); a terminal gets one rewritten line; a fake notebook gets one display per phase and only updates after that; `progress=False` prints nothing; a failing sink falls back |
| `tests/test_cost_limit.py` | Every acceptance scenario of stories 1 to 5 on a generated PDF with a fake model that charges a fixed price per request |
| `tests/llm/test_cached_client_meter.py` | No request starts after the meter trips; the crossing answer is cached; cache keys are the same with and without a meter |

## By hand, in a notebook, with a real model (needs your go-ahead; costs money)

1. Pick a 10 to 20 page PDF. In a notebook cell:

   ```python
   from quotable import extract_tables_async

   tables = await extract_tables_async("report.pdf", model="openai:<model>", max_cost=2.00)
   ```

2. Expected: a discovery block with the estimate and a status line that updates in place (no new row per update), then a sample block, then the rest, then one final block. The cell's output has 4 blocks.
3. Run it again unchanged: every request comes from the cache, the estimates say 0 requests to make, the total is $0.
4. Run with `max_cost=0.05`: stops with a message that names the total, the limit and the amount to raise it by.
5. Run `quotable cost-report` and compare its total with the final message (SC-006). Compare the estimates with the final cost (SC-003); the live test `tests/live/test_live_cost_estimate.py` records the same figures.
6. Repeat step 2 in a terminal, and with the output redirected to a file (`2> run.log`): the file must hold plain lines only.

Not yet checked anywhere: the in-place update in JupyterLab, VS Code and Colab (research 1).
