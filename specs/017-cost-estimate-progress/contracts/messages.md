# Contract: messages

The text of every message, and how each sink shows it. The wording is a contract for tests (they match on the figures and on a few fixed phrases, not on every character). The figures below are examples.

## Money

- A single amount: 2 decimals from $1 up, 4 decimals below $1 (`$21.87`, `$0.0412`).
- When two amounts are compared (spent against the limit), enough decimals (up to 6) that the two do not print the same.
- "Raise by" amounts are rounded **up** at the number of decimals shown, so raising `max_cost` by exactly that is enough to pass the point.
- Dollars only. A model with no known price shows token counts and the words "no price known".
- Never in a message: a prompt, an answer, a value from a table, a file path (FR-021). The PDF is named by its page count only.

## Fixed messages (printed once each)

**1. Discovery estimate** (before the first request)

```text
quotable: estimate before discovery
  300 pages, 75 discovery requests of 4 pages (0 already in the cache)
  about 1,240,000 input and 22,500 output tokens: estimated cost $4.12
  based on: page images at 150 dpi (OpenAI patch rule, 1.2 tokens a patch, for gpt-5.6-luna),
  the instructions, and an allowance of 300 output tokens a page
  cost limit: $25.00
```

No rule or no price:

```text
quotable: estimate before discovery
  300 pages, 75 discovery requests of 4 pages (0 already in the cache)
  no estimate: no image-size rule is known for "provider:model". The limit, if set, is still
  checked against actual cost after every request.
```

```text
  no price known for "provider:model" (set OPENAI_API_KEY): tokens are counted, dollars are not
```

**2. Sample announcement** (after discovery)

```text
quotable: sample run
  discovery found 2 tables on 180 table pages; spent so far $3.98
  running the full process (extraction, audit, recheck) on 3 table pages to measure what a page
  costs: table 1 page 1, table 1 page 90, table 2 page 180
  their extraction answers are reused afterwards
```

Small document (3 or fewer table pages):

```text
quotable: discovery found 2 tables on 3 table pages; small enough to run as it is, no sample
```

**3. Estimate for the rest of the run** (after the sample)

```text
quotable: estimate for the rest of the run
  sample: 3 table pages cost $0.3100 ($0.1033 a page: extraction $0.0600, audit $0.0233, recheck $0.0200)
  rest: 177 table pages, about $18.33 (counting the sample pages' audit and recheck again, in case
  they are not reused)
  expected total $22.62; spent so far $4.29; cost limit $25.00
```

Added when part of the sample came from the cache: `  note: 2 of the 9 sample requests were already in the cache, so this may be low`.

**4. Final message**

```text
quotable: done in 6 min 12 s
  total cost $21.87 (limit $25.00)
  discovery $3.98 (estimated $4.12) | sample $0.31 | rest $17.58 (estimated $18.33)
  new requests: 75 discovery, 184 extraction, 180 audit, 41 recheck; 12 answered from the cache
  300 pages, 2 tables, 180 table pages; $0.02 of the sample could not be reused
```

No limit: the `(limit ...)` part is left out. No price: `total cost: no price known (3,204,118 input and 188,430 output tokens)`.

**5. Closing message** (the run stopped; also the text of the error)

`reason == "spent"`:

```text
quotable: stopped, the cost limit was passed
  The run has cost $25.0412 and the limit is $25.0000: over by $0.0412.
  It stopped in the audit stage (page 41 of up to 180); 3 requests were in flight and are included.
  To get past this point, raise max_cost by at least $0.0412 (to $25.0412).
  The whole run is estimated at $26.80: max_cost=26.80 would finish it.
  Everything already answered is in the cache. Run again with the higher limit and it is not paid for twice.
```

The estimate line is left out when there is no estimate or it is below the limit.

`reason == "estimate"`:

```text
quotable: stopped before spending more, the estimate is over the cost limit
  The estimate for the whole run is $26.80 and max_cost is $25.00. Spent so far: $4.29.
  Raise max_cost by about $1.80 (to $26.80) to run it. Nothing more has been requested.
  Everything already answered is in the cache.
```

Before discovery the "spent so far" line reads `Nothing has been requested.`

`reason == "unpriced"`:

```text
quotable: not started
  max_cost is set but the price of "provider:model" is not known (set OPENAI_API_KEY), so the
  cost cannot be added up and the limit could not be kept. Nothing was requested.
  Remove max_cost to run without a limit.
```

`reason == "unmetered"`:

```text
quotable: stopped, a request reported no token usage
  A request in the extraction stage came back without usage figures, so its cost cannot be checked
  against max_cost=25.00. Spent so far, without it: $12.0300.
  Everything already answered is in the cache.
```

Any other failure prints: `quotable: stopped in the extraction stage after $12.03 ...` then the error is raised as usual.

## Live status line

```text
  discovery   12 of 75 windows   $0.84 so far (about $4.12)
  sample      6 of 9 requests    $0.20 so far
  extraction  96 of 177 pages    $11.40 so far (about $18.33 for the rest)
  audit       12 of up to 177    $12.10 so far
  recheck     0 of up to 177     $12.10 so far
```

"of up to" is used for audit and recheck, whose pages are not known until the stage begins. A stage served from the cache reads `... windows (from the cache)` and adds no cost.

## Sinks

| Sink | Chosen when | Fixed messages | Live status line |
|---|---|---|---|
| Notebook | `IPython` is loaded and the shell is a `ZMQInteractiveShell` | In the phase's block, `text/plain` | The last line of the same block, updated in place with `update_display`. Four blocks in a run: discovery, sample, rest, final |
| Terminal | `sys.stderr.isatty()` | Printed to stderr | One line rewritten with `\r` and a clear-line code; cleared before any fixed message |
| Plain | anything else (file, pipe, scheduled job) | Printed to stderr, each once | Written at the start and the end of each stage only. No `\r`, no escape codes |
| Null | `progress=False` | nothing | nothing |

Redraws are limited to 4 a second, except that a stage's last state is always drawn. A sink that raises is replaced by the plain sink for the rest of the run, and the run continues (FR-020). In a notebook where the richer display is unavailable the plain sink is used.

Several calls at the same time in one notebook each keep their own display ids.
