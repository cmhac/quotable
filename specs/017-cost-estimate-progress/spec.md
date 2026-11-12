# Feature Specification: Cost estimates and progress messages

**Feature Branch**: `017-cost-estimate-progress`

**Created**: 2026-11-12

**Status**: Implemented (offline tests; live accuracy and notebook frontends not yet checked)

**Input**: User description: "Estimate the cost of discovery from the size of the page images and print a message explaining the cost before it starts; no approval step. If the estimate exceeds the cap, error. During discovery print progress and cost. When run in Jupyter notebooks it should look nice and not fill the output with duplicate rows (do web research for the best way). When discovery is done, run a few pages to get a better cost estimate, say that this is what it is doing, and print progress and cost again. When that is done, print a new estimate for extraction, and error if it exceeds the limit. Then run extraction with the same notebook-friendly progress and cost messages, and at the very end print one final status message with the total cost and everything that was done."

Terms used in this spec:

- **Cost limit**: a new maximum, in US dollars, that the user may pass to `extract_tables`. It limits the total actual cost of the run, at every moment of the run, and the estimates before it. It is separate from `max_requests`, which counts requests and stays as it is.
- **Discovery**: the first model stage, which finds the tables (`quotable/steps/discover.py`).
- **Table page**: one page of one table. Extraction, the omission audit and the recheck each make up to one request per table page.
- **Sample run** (the user's "run a few pages"): the full process on a handful of table pages, done before the rest, to measure what a table page actually costs: extraction, then the omission audit and the recheck (and the extra-field checks, if on), each as it is configured for the run.
- **Rest of the run**: the same stages for the remaining table pages.
- **Estimate**: a figure computed before the money is spent. **Actual cost**: what the provider's usage figures say was spent (the figure the cost log already records).

## Clarifications

### Session 2026-11-12

- Q: Should the cost limit also stop the run during extraction if the actual spend passes it, or only be checked against the two estimates? -> A: Always stop if the total cost exceeds the limit at any time, immediately and loudly, with the total so far and how much to raise the limit by (story 5, FR-011, FR-012).
- Q: Should the sample run include the audit and the recheck for its pages, or only extraction? -> A: The full process, audit and recheck included (story 3, FR-006 to FR-008).

## User Scenarios & Testing *(mandatory)*

### User Story 1 - A cost estimate for discovery, before anything is sent (Priority: P1)

A reporter points `extract_tables` at a 300-page PDF. Before the first request, quotable prints a short message: how many pages and discovery requests there will be, the estimated cost, and what the estimate is based on. There is no prompt and no pause. If the user set a cost limit and the estimate is above it, the run stops with an error that states the estimate and the limit, having sent nothing.

**Why this priority**: discovery is the first spend. The user finds out, and is stopped, before it.

**Independent Test**: run on a generated PDF with a fake model and a known price table. The message appears before the first request, the figure matches the expected token count times the price, and a limit set just below the estimate raises the error with no request made.

**Acceptance Scenarios**:

1. **Given** a PDF and a model with a known price, **When** the run starts, **Then** before any model request one message gives the page count, the number of discovery requests, the estimated cost in dollars, and how it was worked out (page image size, text of the instructions, an allowance for the answer).
2. **Given** a cost limit and an estimate above it, **When** the run starts, **Then** it raises an error naming both numbers and sends no model request.
3. **Given** no cost limit, **When** the run starts, **Then** the estimate is still printed and the run continues without waiting for anyone.
4. **Given** discovery answers already in the cache, **When** the estimate is made, **Then** requests whose answers are cached are left out of the figure and the message says how many were left out.
5. **Given** a provider whose image size rule quotable does not know, **When** the run starts, **Then** the message says that no estimate can be made for this model and why, shows what it can (pages and requests), and the run continues, with or without a cost limit, because the limit is still enforced on the actual cost of every request (story 5).
6. **Given** a model whose price quotable does not know and no cost limit, **When** the run starts, **Then** the message says so and shows token counts in place of dollars, and the run continues. **Given** the same model and a cost limit, **Then** the run stops before any request, saying that the limit cannot be enforced because the model has no known price.

---

### User Story 2 - Progress and running cost during discovery (Priority: P1)

While discovery runs, the user sees which window of pages is done, out of how many, and the cost so far, updated as each request finishes. In a terminal this is one line that rewrites itself. In a Jupyter notebook it is one block that updates in place, so the cell's output does not grow a new row for every update.

**Why this priority**: discovery can take minutes on a long PDF with no sign of life today.

**Independent Test**: run discovery on 20 pages with a fake model. Collect what is shown. In the notebook mode there is exactly one output block after the run, and its last state shows 100% and the total. In a non-interactive stream (a redirected file) there is one line per milestone, not one per update.

**Acceptance Scenarios**:

1. **Given** discovery is running, **When** each window's answer arrives, **Then** the display shows windows done of total, and the cost so far.
2. **Given** a notebook, **When** the display updates, **Then** it replaces the previous state instead of adding another, and no row is repeated.
3. **Given** output going to a file or a pipe, **When** discovery runs, **Then** no line-rewriting control codes are written, and a line is written only at the start, at milestones and at the end.
4. **Given** discovery answered from the cache, **When** it runs, **Then** the display says that the windows were cached and shows no cost for them.

---

### User Story 3 - A sample run, then a better estimate for extraction (Priority: P1)

When discovery is done, quotable knows how many tables and table pages there are. It prints a message saying what it will do next: run the full process (extraction, audit and recheck) on a few table pages to see what a page really costs. It shows progress and cost as in story 2. When the sample is done it prints a new estimate for the rest of the run, now based on the measured cost per table page, all stages included. If a cost limit is set and the expected total is above it, the run stops with an error stating the numbers (see story 5). Otherwise it continues, with no pause.

**Why this priority**: the discovery estimate says nothing about extraction, which is most of the spend. The sample turns a guess into a measurement.

**Independent Test**: run a generated 30-page table with a fake model that charges a known amount per request. After the sample, the printed estimate for the rest equals the measured cost per table page times the pages left, within the tolerance the message states. A limit between the sample's cost and the estimate stops the run after the sample.

**Acceptance Scenarios**:

1. **Given** discovery is done and the table has more table pages than the sample size, **When** the sample starts, **Then** a message says that a sample of N table pages is being extracted to measure the real cost per page, and which pages.
2. **Given** the sample is done, **When** the estimate is printed, **Then** it gives the measured cost per table page, the number of table pages left, the estimated cost of the rest, the total expected for the whole run, and the spend so far.
3. **Given** a cost limit and an estimate for the whole run above it, **When** the sample is done, **Then** the run stops with an error naming the estimate, the spent amount and the limit.
4. **Given** the pages of the sample, **When** the rest of the run starts, **Then** their extraction answers are reused and not paid for again. The audit and recheck answers are reused when the rest of the run asks the same question, and the final message shows how much of the sample's cost was not reused.
5. **Given** a document with no more table pages than the sample size, **When** discovery is done, **Then** there is no separate sample, a message says that the document is small enough to run as it is, and the run continues.

---

### User Story 4 - Progress and cost while extracting, and a final summary (Priority: P1)

The rest of the run shows the same kind of display: the current stage (extraction, audit, recheck), pages or requests done of total, and cost so far, with an estimated total. When the run finishes, one final message sums it up: the total actual cost, the estimates it can be compared with, the requests made and the ones served from the cache, the pages and tables handled, and the time taken. If the run fails or stops, the same kind of message says what was spent up to that point.

**Why this priority**: the user needs to see what a run is costing as it goes, and a record at the end that they can paste into a note.

**Independent Test**: run the whole pipeline on a generated PDF with a fake model. The final message appears once, its total equals the sum of the cost records written for the run, and its counts equal the counts in the saved run.

**Acceptance Scenarios**:

1. **Given** extraction is running, **When** a request finishes, **Then** the display shows the stage, progress in that stage, and the cost so far, without adding a new line or row.
2. **Given** the run is complete, **When** the result is returned, **Then** exactly one final message is printed with: total cost; the discovery, sample and full-run estimates beside what was actually spent; new requests and cache hits; pages, tables and table pages; time.
3. **Given** a model with no known price, **When** the final message is printed, **Then** it gives token counts and says no price is known.
4. **Given** a run that stops with an error, **When** the error is raised, **Then** a closing message states how much was spent and in which stage it stopped.

---

### User Story 5 - The limit stops the run the moment it is passed (Priority: P1)

An analyst sets a cost limit of $20 on a long run. Whatever the estimates said, if the total actual cost of the run ever goes above $20, at any stage and on any request, quotable stops at once. No further model request is started. The error is loud and says what the user needs to know: what the run has cost so far, what the limit was, how far over it is, how much to raise the limit by to get past this point, and how to carry on without paying again for what is done.

**Why this priority**: the limit is the user's protection against a bill. Estimates can be wrong; a limit that only guards the estimates is not a limit.

**Independent Test**: run a generated table with a fake model that charges a fixed price per request and a limit that falls in the middle of extraction. The run raises the error after the request that crossed the limit; the count of requests started after that moment is zero; the error contains the total, the limit, the overshoot and the suggested new limit, and the numbers agree with the cost log.

**Acceptance Scenarios**:

1. **Given** a cost limit and a run whose total actual cost passes it at any point (discovery, the sample, extraction, audit, recheck, or the extra-field checks), **When** the request that crosses it finishes, **Then** no new model request is started and the run raises an error at once.
2. **Given** the error, **When** the user reads it, **Then** it states the total cost so far, the limit, the amount over the limit, the amount to raise the limit by to pass this point, and, when an estimate for the whole run exists, the amount to raise it by to finish the run.
3. **Given** the error, **When** the user runs again with a higher limit, **Then** every request already answered comes from the cache and costs nothing, and the message says so.
4. **Given** requests that were already in flight when the limit was crossed, **When** the error is raised, **Then** the total in the error includes those that finished, so the figure shown is what the provider will bill, and the message says that up to that many requests were in flight.
5. **Given** the run is stopped by the limit, **When** the closing message is printed, **Then** it names the stage, the pages done and the total, and nothing is returned as if the run had finished.

---

### User Story 6 - Output that fits where it is shown (Priority: P2)

The messages are the same in content wherever they are shown, but their form fits the place: a notebook gets one block per phase that updates in place; a terminal gets a single rewriting line; a log file or pipe gets plain separate lines with no control codes. The user can turn all of this off.

**Why this priority**: the notebook case is the stated pain; the terminal and file cases keep the library usable in scripts and scheduled jobs.

**Independent Test**: run the same extraction in a plain process with output captured to a file, with a terminal, and in a notebook kernel. The file has no control codes and no repeated lines. The notebook has no more output blocks than phases. Passing the off switch produces no output in any of them.

**Acceptance Scenarios**:

1. **Given** output to a file, **When** the run finishes, **Then** the file has the estimates, the phase messages and the final message, each once.
2. **Given** the off switch, **When** the run is made, **Then** nothing is printed, and the cost limit still applies.
3. **Given** a notebook where the richer display is not available, **When** the run is made, **Then** the output degrades to the plain form of scenario 1 and nothing fails.

---

### Edge Cases

- A PDF with no table pages after discovery: discovery already raises its error; no sample and no estimate for extraction.
- The cost limit is lower than the discovery estimate by a hair: the comparison uses the same numbers the message prints, so the user is never told "$4.20 against a limit of $4.25" and then stopped.
- A cost limit passed with the price unknown: refuses to start, as in story 1, scenario 6.
- A request that comes back with no usage figures while a cost limit is set: its cost cannot be worked out, so the run stops at once with an error saying which stage it happened in, instead of carrying on unchecked (the library fails closed when in doubt). Without a cost limit this request only produces the existing one-time warning.
- Amounts are shown in dollars with enough decimals that an amount over the limit never looks equal to it (requests often cost a fraction of a cent), and any "raise the limit by" amount is rounded up so that raising by exactly that amount is enough to pass this point.
- `max_requests` and the cost limit are both set: either may stop the run; the error says which.
- Several requests in flight when the limit is crossed: they finish and are billed; the error total includes them (FR-012).
- The limit is crossed by the very last request of the run: the run still raises the error, and the result is not returned, because the user asked for a limit and was over it. Everything is cached, so a rerun with a higher limit costs nothing.
- The sample's pages are chosen so that a re-run chooses the same ones (so their cached answers are found again).
- A table that continues onto a page with no header, or a page shared by two tables: the sample counts table pages, so a shared page counts once for each table on it.
- The PDF needs OCR: OCR happens before discovery and is out of scope for these messages (see Assumptions).
- Several `extract_tables_async` calls at once in one notebook: each keeps its own block; they do not overwrite each other.
- A notebook that is saved after the run: the saved output holds the final state of each block, not every update.
- An estimate that turns out wrong: the final message shows the estimate beside the actual cost, so the gap is visible.

## Requirements *(mandatory)*

### Functional Requirements

**Cost limit and estimates**

- **FR-001**: `extract_tables` and `extract_tables_async` MUST accept an optional cost limit in US dollars. Without it, nothing is ever stopped for cost; estimates and progress are still printed. `max_requests` keeps its meaning.
- **FR-002**: Before the first model request, quotable MUST print the discovery estimate: page count, number of discovery requests, estimated input tokens, estimated cost, and the basis of the figure. Requests whose answers are already cached MUST be left out and counted in the message.
- **FR-003**: The discovery estimate MUST come from the size of the page images as they will be sent (including the image settings the run uses), the text of the instructions, and a stated allowance for the answer. It MUST be labelled an estimate.
- **FR-004**: If a cost limit is set and the discovery estimate is above it, quotable MUST raise an error before any model request. The error MUST state the estimate and the limit.
- **FR-005**: There MUST be no confirmation step: no prompt, no pause, no key to press.
- **FR-006**: After discovery, quotable MUST announce the sample run in a message before it starts: why it is done, how many table pages, which ones, and that it covers the full process (extraction, audit and recheck).
- **FR-007**: The sample MUST run the full process on N table pages, N defaulting to 3 (see Assumptions), chosen deterministically and spread through the table pages (first, middle, last for N = 3). The rest of the run MUST NOT request again any question the sample has already had answered.
- **FR-008**: After the sample, quotable MUST print the estimate for the rest of the run, from the measured cost per table page across all stages, and the expected total. If a cost limit is set and the expected total is above it, quotable MUST raise the limit error of FR-011, stating the estimate, the amount already spent and the limit, before the rest of the run starts.
- **FR-009**: If the image-size rule for the model's provider is not known, quotable MUST say that no estimate is available for it, in place of the figure, and carry on; the limit is still enforced on actual cost (FR-011), and the sample later gives a measured estimate. If the model's price is not known, quotable MUST say so, show token counts in place of dollars, and carry on when no cost limit is set; with a cost limit set it MUST stop before any request, because actual cost could not be worked out.
- **FR-010**: Estimates MUST NOT change what is requested, the prompts, the cache keys or the saved-run format.
- **FR-011**: When a cost limit is set, quotable MUST check the run's total actual cost after every request that reaches a model, in every stage, and MUST stop the run at once if the total is above the limit: no new model request is started after that point, and the run raises a typed error from `quotable.errors`. This applies in addition to the two estimate checks, which stop the run earlier when they can.
- **FR-012**: The limit error MUST state, in plain words: the total actual cost so far; the limit; how much the total is over the limit; the smallest amount to raise the limit by to get past this point; the estimate for the whole run and the amount to raise the limit by to finish it, if an estimate exists; the stage and the pages done; and that a run with a higher limit will take every answer already paid for from the cache. The total MUST include requests that were in flight and finished after the limit was crossed.
- **FR-012a**: The amounts in the error MUST be computed from the same cost figures as the cost log and the final message, so the three agree to the cent.
- **FR-012b**: With a cost limit set, a request that reports no usage figures MUST stop the run with an error naming the stage (the cost could not be checked against the limit).

**Progress and cost display**

- **FR-013**: During discovery, the sample and the rest of the run, quotable MUST show the current stage, progress within it (units done of total) and the cost so far, updated as requests finish.
- **FR-014**: In a notebook, the display MUST update one output block in place per phase and MUST NOT add a new row for each update. The final state of a block MUST remain after the run.
- **FR-015**: In a terminal, the display MUST be one line that rewrites itself. When output is not a terminal (a file, a pipe, a scheduled job), it MUST write plain lines with no control codes, only at the start, at milestones and at the end.
- **FR-016**: Estimates, phase announcements and the final message MUST be printed in every form, once each.
- **FR-017**: One final message MUST be printed when the run ends, with the total actual cost, the estimates beside it, new requests and cache hits, pages, tables and table pages, how much of the sample's cost the rest of the run could not reuse, and time. After a failure, a closing message MUST state the spend so far and the stage it stopped in.
- **FR-018**: The total in the final message MUST equal the sum of the run's records in the cost log. A cache hit costs nothing and is counted separately.
- **FR-019**: The user MUST be able to turn all of these messages off with one setting. The cost limit MUST still apply with messages off.
- **FR-020**: A failure to draw the display MUST NOT break an extraction. It falls back to plain lines.
- **FR-021**: Messages MUST NOT contain prompts, model answers, extracted values or file paths (the same rule as the cost log).

### Key Entities

- **Cost estimate**: a figure with its basis (what was counted), the number of requests it covers, the number it left out because they were cached, and whether it is complete or missing a price or image rule.
- **Spend so far**: actual cost of the requests made in this run, read from the usage the provider reported for each one.
- **Phase**: discovery, sample, rest of the run (with its stages: extraction, audit, recheck, extra-field checks).
- **Run summary**: the content of the final message: totals, estimates, counts, time.

## Success Criteria *(mandatory)*

### Measurable Outcomes

- **SC-001**: With a cost limit set below the discovery estimate, 100% of runs stop before any model request, and the error contains both numbers.
- **SC-002**: With a cost limit between the cost of the sample and the expected total, 100% of runs stop after the sample and before the rest of the run, and no table-page extraction beyond the sample has been requested.
- **SC-002a**: With a cost limit that the run crosses at any stage, 100% of runs raise the limit error after the request that crossed it, with zero requests started after that moment. The error's total equals the cost log's sum for the run to the cent, and its "raise by" figure, added to the limit, is at least the total.
- **SC-003**: On the offline fixture with a fake model that charges a fixed price per request, the sample-based estimate for the rest of the run is within 5% of the actual cost of the rest (a test of the arithmetic). On the real-model live check (opt-in) the estimates are recorded beside the actual cost; the target is the discovery estimate within 25% and the whole-run estimate within 25% of actual. These targets are to be checked against that live run and revised if the real numbers say otherwise.
- **SC-004**: In a notebook, a 100-page run leaves one output block per phase, with no more than 5 blocks in total, instead of one row per update.
- **SC-005**: When output goes to a file, the file holds no control codes, no line repeated, and at most 40 lines however many pages the PDF has (the count is set by the number of messages and stages, not by pages).
- **SC-006**: The final message's total equals the cost log's sum for the run to the cent, in every offline test that checks it.
- **SC-007**: With messages off, a run prints nothing, and the existing offline suite passes unchanged except for tests that read the new messages.
- **SC-008**: A user who has never seen the tool can read the first message and say how much the discovery step is expected to cost and what it is based on.

## Assumptions

- The cost limit's argument name is proposed as `max_cost`, in US dollars, and the off switch as `progress=False`. Names are settled in the plan.
- The sample size is 3 table pages, with the first, middle and last table pages chosen. A small constant is enough; it is not an option.
- Prices come from the genai-prices data already used by the cost log. A price is also used for estimates before any request is made, calculated from token counts, which that package supports without calling a model.
- Image token rules differ by provider and by model, and change between model generations; they are not a single formula. The estimate therefore uses the rules quotable knows for the providers `images.py` already tells apart, and says so when it does not know the rule (FR-009). The accuracy targets in SC-003 are unmeasured and must be checked on a live run, which needs the user's go-ahead.
- Discovery output is small compared with its input. The allowance for the answer is a stated constant; reasoning models can produce many more output tokens than the answer, and the estimate does not predict them.
- Text-layer checking and OCR run before discovery and are not covered by these messages. OCR can take about a minute per page on a CPU; messages for it are a separate piece of work.
- The extra-field requests are part of discovery and the rest of the run, and are included in the same counts when extra fields are used.
- Messages go to the cell output in notebooks and to standard error in a terminal, so standard output stays free for the caller's own use.
- The display approach for notebooks is chosen in the plan. The research recorded in `research.md` recommends updating a single output block in place through IPython, and not using `rich` live displays (open reports of double rendering and of breaking with ipykernel 7). That choice has not been tried in JupyterLab, VS Code or Colab.
- The spec changes no existing behavior of the extraction, the cache, the saved runs or the cost log; it adds output and one new limit.
- Out of scope: a dry run that prints an estimate and stops, a confirmation prompt, estimates for the review app and the gold check, and progress for OCR.
- The check in FR-011 happens when a request's usage is known, so requests already in flight at that moment (at most 4, the run's existing limit on concurrent requests) finish and are paid for. The limit can therefore be passed by at most the cost of those requests, and the error says so. Holding back a request whose estimated cost would cross the limit is a stricter rule that this spec does not require; the plan may add it.
- The sample's audit and recheck are measured on the sample pages alone. The position check and the audit's furniture rule use the whole table, so on a few pages they can flag more or fewer cells than on the full table. The estimate is labelled accordingly, and the final message compares it with the actual cost.
