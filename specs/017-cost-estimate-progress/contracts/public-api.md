# Contract: public API changes

## `extract_tables` and `extract_tables_async`

Two new keyword-only arguments, added after `extra_fields`:

```python
def extract_tables(
    pdf, model, *,
    ...,
    max_cost: float | int | Decimal | str | None = None,
    progress: bool = True,
) -> list[Table]: ...
```

| Argument | Meaning |
|---|---|
| `max_cost` | A limit in US dollars on the total actual cost of this call. `None`: no limit; estimates and progress are still shown. Must be greater than 0; anything else raises `ValueError` before any work. It is compared with the total at every request (FR-011) and with the two estimates (FR-004, FR-008). It is separate from `max_requests` |
| `progress` | `True`: print the estimates, phase messages, progress and the final message. `False`: print nothing. The limit applies either way |

Names were proposed in the spec's Assumptions and are settled here. `max_cost` is converted with `Decimal(str(value))`, so `0.1` means one tenth of a dollar and not a binary float.

Nothing else about the call changes: the same requests in the same order for the same inputs, the same cache keys, the same returned tables, the same saved run (checked by a test that compares the request keys of a run with and without the new arguments).

## `CostLimitExceededError`

```python
class CostLimitExceededError(BudgetExceededError):
    reason: Literal["spent", "estimate", "unpriced", "unmetered"]
    limit: Decimal
    spent: Decimal              # actual cost so far, in-flight requests included
    over: Decimal               # spent - limit; Decimal(0) unless reason == "spent"
    raise_by: Decimal           # round_up(smallest amount that gets past this point)
    estimate: Decimal | None    # the expected cost of the whole run, when one exists
    finish_by: Decimal | None   # round_up(estimate - limit), when estimate exists and exceeds the limit
    stage: str | None           # "schema", "extract", "audit", "recheck", "extras"
    done: int | None            # progress in that stage
    total: int | None
    in_flight: int              # requests that were in flight when it tripped
    # str(error) is the full message described in contracts/messages.md
```

It subclasses `BudgetExceededError`, so existing `except BudgetExceededError` handlers also catch it. It is exported from `quotable`.

| `reason` | Raised | `spent` |
|---|---|---|
| `unpriced` | Before any work, when a limit is set and the model's price is unknown | 0 |
| `estimate` | Before the first request (discovery estimate above the limit) or after the sample (expected total above the limit) | what has been paid so far |
| `spent` | After the request that took the total above the limit (or the last in-flight request that did) | the settled total |
| `unmetered` | After a request that reported no usage, when a limit is set | the total so far |

`raise_by` is the amount to add to `limit` so that `limit + raise_by >= spent` (rounded up, never down). For `reason == "estimate"` it is `estimate - limit` rounded up.

## Behavior that callers can rely on

- With a limit set, no model request is started after the meter has tripped. Requests already sent finish and are billed, and `spent` includes them.
- Every answer received before the stop is in the cache, the one that crossed the limit included. A rerun with a higher limit pays nothing for them.
- A call that raises `CostLimitExceededError` returns no tables and saves no run (as for any failed call).
- `progress=False` changes only what is printed.

## Unchanged

`BudgetExceededError` from `max_requests` keeps its message and meaning. `Table`, `records()`, the frames, the cost log, `quotable cost-report`, the saved run and the review app are untouched.
