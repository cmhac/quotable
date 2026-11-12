# Research: notebook-friendly progress display, image token rules and design decisions

Gathered 2026-11-12 for spec 017. Sections 1 and 2 are findings; section 3 lists the decisions the plan took.

## 1. Showing progress in a notebook without repeated rows

The usual cause of repeated rows is a terminal-style progress bar (carriage returns, ANSI codes) written to a notebook's output, which treats each write as new text. Three ways to avoid it:

| Approach | How it avoids duplicates | Needs | Known problems |
|---|---|---|---|
| IPython display handle: `display(obj, display_id=True)` returns a handle; `handle.update(obj)` or `update_display(obj, display_id=...)` rewrites that one output | The notebook replaces the output with that id | `IPython`, which is present wherever a notebook kernel runs. No widgets | JupyterLab has had inconsistent display behavior in some cases (a Jupyter discourse thread suggests wrapping in an `Output` widget as a workaround). Not tried here in JupyterLab, VS Code or Colab |
| `tqdm.auto` / `tqdm.notebook` | Draws an `ipywidgets` progress bar widget and updates it | `ipywidgets` and a frontend that supports widgets | Without a working `ipywidgets` it warns ("IProgress not found") and falls back to a console bar, which is the repeated-rows case. Adds a dependency. The bar is created in the cell that makes it |
| `rich` `Progress` / `Live` | Rewrites a display | `rich` | Open issues: live bars rendering twice in Jupyter (Textualize/rich #1737), and the live display not refreshing with ipykernel 7 (Textualize/rich #3868, reported October 2025). Status of both not checked |

Chosen: the IPython display handle with a `text/plain` payload, so there is no HTML to escape and no theme to match. `tqdm.auto` is the fallback if the in-place update fails in a frontend we care about, at the cost of a dependency on `ipywidgets`.

Sources:

- IPython display API (`display`, `display_id`, `DisplayHandle.update`, `update_display`): https://ipython.readthedocs.io/en/stable/api/generated/IPython.display.html
- tqdm, notebook integration and `tqdm.auto`: https://github.com/tqdm/tqdm
- tqdm "IProgress not found" fallback behaviour (secondary): https://errors.standardbeagle.com/tqdm/tqdm/iprogress-not-found-please-update-jupyter-and-ipy-3b7baf/
- rich, double rendering in Jupyter: https://github.com/Textualize/rich/issues/1737
- rich, live display with ipykernel 7: https://github.com/Textualize/rich/issues/3868
- JupyterLab display inconsistency, `Output` widget workaround: https://discourse.jupyter.org/t/jlab-or-ipython-issue-inconsistency-in-ipython-display-behavior-between-jlab-and-classic-notebook-or-google-colab/14765/2

## 2. Estimating image tokens from image size

The rules are published and can be implemented. They differ by provider and model and change between generations, so they are a table in the code, not one formula, and a model that is not in the table gets "no estimate available". Read from the providers' documentation on 2026-11-12.

### OpenAI (https://developers.openai.com/api/docs/guides/images-vision)

Patch models cover the image with 32 px squares: `patches = ceil(w/32) * ceil(h/32)`, after resizing to the model's and detail level's limits. Tokens are `ceil(patches * multiplier)`; the multiplier applies to the image tokens only.

- Multipliers: 1.2 for `gpt-6-astra`, `gpt-5.6-sol/-terra/-luna`, `gpt-5.5`, `gpt-5.4` (and `-mini`, `-nano`), `gpt-5.2`; 1.62 for `gpt-4.1-mini` (2025-04-14 snapshot). The deprecated `gpt-5-mini` (1.2), `gpt-5-nano` (1.5), `gpt-4.1-nano` and `o4-mini` are left out of the table, which makes them "no rule known".
- Sizing by detail level, per model (`high` is what discovery sends; `original` is what the sharp-image policy sends for extraction, audit and recheck):
  - `gpt-6-astra`: `high` up to 2,500 patches and 65,535 px; `original` keeps the size (rejected above 30,000 patches).
  - `gpt-5.6-*`: `high` fits 2048 x 2048 px and 2,500 patches; `original` keeps the size (rejected above 30,000 patches).
  - `gpt-5.5`: `high` 2,500 patches and 2048 px; `original` 10,000 patches and 6000 px.
  - `gpt-5.4*`: `high` 2,500 patches and 2048 px; `original` 10,000 patches and 6000 px.
  - `gpt-5.2`, `gpt-4.1-mini`: 6,144 patches and 2048 px; no `original`.
- When a patch budget applies the image is scaled down by the formula in the documentation (a shrink factor that is then adjusted so the scaled size lands on whole patches).
- Tile models (`gpt-5.1`, `gpt-4.1`, `gpt-4o`): fit in 2048 x 2048, shortest side to 768, count 512 px tiles; tokens are base + tiles x per-tile (70 and 140 for `gpt-5.1`, 85 and 170 for `gpt-4o` and `gpt-4.1`).
- Documentation examples to pin in tests, `gpt-6-astra` with `detail: high`: 1024 x 1024 gives 1,229 tokens; 2048 x 2048 gives 3,000; 4096 x 512 gives 2,458.

### Anthropic (https://platform.claude.com/docs/en/build-with-claude/vision)

An image costs `ceil(w/28) * ceil(h/28)` visual tokens, after downscaling to the tier's limits: standard tier 1,568 px long edge and 1,568 tokens; high-resolution tier (Claude 4.7 and later) 2,576 px and 4,784 tokens. Which tier a model is on depends on its generation, and the model name alone is not a reliable way to tell. The estimate therefore uses the high-resolution tier for every Anthropic model, which can only overestimate, and says "upper bound". Documentation examples to pin: 1000 x 1000 gives 1,296 tokens on both tiers; 1920 x 1080 gives 2,691 on the high tier; 3840 x 2160 gives 4,784 on the high tier.

### Other providers

No rule is known. The estimate says so (FR-009). The limit still works, because it is enforced on actual cost.

### Counting calls

Both providers also offer a call that counts tokens for a request before it is made. Whether it is free, rate limited, and reachable through pydantic-ai has not been checked, and it would make a network request before the first paid one. Not used.

## 3. Decisions

1. **Pricing a token count without a request.** Build a `ModelResponse(parts=[], usage=RequestUsage(...), model_name=..., provider_name=...)` and call `.cost()`. This is the same path the cost log uses after a request, so estimates and actual cost use one price source. Checked with pydantic-ai 2.54.0 for `openai:gpt-5.6-luna` (1,000 input and 100 output tokens price at $0.00032), `openai-responses:gpt-5.5`, `anthropic:claude-sonnet-4-5` and `openai:gpt-4o`. The model is built with `infer_model`, which needs the provider's API key in the environment (it raises `UserError` without it); in that case the price is reported unknown, with the cause in the message.
2. **Where the limit is checked.** In `CachedClient`, which every stage already goes through, so no step module changes. It checks before starting a request and after storing a paid answer. Checking before starting also stops tasks that were waiting for the run's gate of 4.
3. **In-flight requests.** `asyncio.gather` does not cancel the other tasks when one fails, so requests already sent finish and are counted. The entry point waits for them (`RunMeter.settled`) before it builds the error, so the total in the error is what the provider will bill.
4. **The crossing answer is cached.** The cache write comes before the final check, so a rerun with a higher limit takes it from the cache.
5. **Finding cached discovery windows.** Run the real `discover` against a client that answers only from the cache and raises on a miss. It reproduces exactly how windows depend on earlier answers, without a second implementation. The requests it answers are the cached ones.
6. **The sample runs the same code as the rest.** The code after discovery becomes a function over a set of (table, page) jobs. Bands and layouts come from the full discovery and are filtered, so a sample page is grounded as it will be in the full run. Merge is skipped in the sample (no requests); the sample's tables are discarded.
7. **Choosing the sample pages.** Table pages in order of (table, page); positions `round(i * (T - 1) / 2)` for i = 0, 1, 2. Deterministic, so a rerun finds its cached answers. A document with 3 or fewer table pages skips the sample.
8. **Estimate for the rest.** `(T - N) * c + N * (c - e)`, where `c` is the sample's cost per table page and `e` its extraction share. The second term counts the sample pages' audit and recheck again, because those requests depend on the whole table and may not be reused. It errs high, which is the safe side for a limit.
9. **Progress totals.** Discovery (windows) and extraction (jobs) have exact totals. Audit and recheck do not know which pages need a request until they run, so they show "n of up to T" with T the table pages.
10. **Unmetered requests.** `PydanticAIClient` calls `on_usage` for every answer, with whatever usage the provider reported. A request with no token counts, or with no price, trips the meter as `unmetered` when a limit is set.
11. **Notebook detection.** `"IPython" in sys.modules` and `type(get_ipython()).__name__ == "ZMQInteractiveShell"`. IPython is never imported by quotable.
