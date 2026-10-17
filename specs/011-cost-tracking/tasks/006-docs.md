# 006 - Docs

Spec: `../spec.md` (Docs). Depends on: tasks 001 to 005.

## Goal

The README, AGENTS.md and the `llm.py` docstring describe the new folder layout, the cost log
and the command, and agree with the code.

## Steps

1. `README.md`:
   - every place that says the cache is `.quotable/` (the opening example comment and the cache
     section) now says `.quotable/cache/`;
   - the `.quotable/` layout (`cache/`, `cost/requests.jsonl`, `.gitignore`) and how to clear the
     cache without losing the costs (`rm -rf .quotable/cache`);
   - a short "Cost" section: costs are recorded for every request that reaches the model, kept
     in `.quotable/cost/requests.jsonl` apart from the cache; `quotable cost-report` with the
     example output; `--dir`; cached answers cost nothing and are not counted; the figure is an
     estimate from pydantic-ai's price data, stored when the request was made; the file holds
     tokens and costs, no prompts, answers or paths;
   - one sentence that a `cache_dir` the caller names is used as given and costs still go to
     `.quotable/cost/`, and that pointing `cache_dir` at `.quotable` itself puts the cache next
     to the cost folder (clearing it then needs care);
   - "Not carried over yet": keep "dollar-based cost caps"; drop nothing else (there is still no
     extraction CLI).
2. `src/quotable/llm.py` module docstring: "dollar pricing and a cost cap" is no longer
   entirely true. Say that cost is recorded (see `quotable.costs`) and a cost cap is still
   left out.
3. `AGENTS.md`: project state (spec 011 implemented: the folder layout, the cost log, the
   command, the one-time move of an old cache; the "dollar-based cost caps" item in "Not yet
   ported" says tracking exists and the cap does not), the file tree (`costs.py`, `cli.py`,
   `__main__.py`, `tests/test_costs.py`, `tests/test_cli.py`, the `cache.py` line), the
   `quotable cost-report` command in the commands section (it is a command for users, not a
   `just` recipe, so it goes in a sentence rather than the recipe table), the test count (run
   `just test`, use the printed number), and, in the `just test-live` row, one line: after an
   opt-in live run, compare `quotable cost-report` with the provider's dashboard; this is the
   only check that the prices are right and it spends money, so it is the owner's to run.
4. Set `specs/011-cost-tracking/spec.md` Status to `implemented` only after the user approves
   the change.
5. `just check` (stage new files first so the hooks see them).

## Done when

`just check` passes and README.md, AGENTS.md and the docstrings agree with the code.
