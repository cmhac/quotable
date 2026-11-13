# Feature Specification: A table that fails validation no longer stops the run

**Feature Branch**: `019-tolerate-failed-tables`

**Created**: 2026-11-12

**Status**: Draft. Partly built: only the window-answer retry of FR-005 (discovery asks again once, naming the problem, when a table has no columns, a blank column name or a repeated one). Failed tables (FR-001 to FR-004, FR-006 to FR-013), OCR of every empty page (FR-014 to FR-017) and the cache record (FR-019, FR-020) are not built. The empty answers could not be reproduced with the real model: the exact windows were asked again 6 times and all answers had columns, so the retry is tested with the two recorded bad answers (`tests/data/discovery_empty_columns/`).

**Input**: User description: "I ran quotable on the Trump annual report and it errored: one or more tables don't have columns. The model should not be able to provide a table with no columns, and we need to understand what happened. Some pages in the document do not contain tables. An issue that affects one table in validation should not kill the whole run, because then we lose the tables that did work. Instead we should warn where we currently fail, and still return the table object for users to inspect. We should also warn, not error, when a user accesses the data of a table that failed validation. Understand why the error occurred first, then build a new spec for this error handling and anything else that comes out of the investigation."

Terms used in this spec:

- **Failed table**: a `Table` that `extract_tables` returns although one of its checks failed. It records what failed and keeps whatever the run had produced for it. A table that passed every check is a **sound table**.
- **Check that can fail a table**: the checks that today end the whole call with `ExtractionError` and that concern one table: (a) the columns discovery reports for it are unusable (none, a blank name, or a repeated name), (b) the rows the model gives for one of its pages are still invalid after the one retry, (c) its first or last row cannot be found in the text layer of a page it shares with another table, or its band overlaps another table's band.
- **Document-level failure**: a problem that is not about one table, so no table can carry it. These keep raising and are listed under "Not changed".
- **Window**: the group of consecutive pages (4 by default) shown to the model in one discovery request.

## Clarifications

### Session 2026-11-13

- Q: Should the OCR story (Story 5) stay in spec 019 or move to its own spec? -> A: It stays; all six stories remain in spec 019.
- Q: When discovery fails a table, should later windows still be shown it in the "Known tables" list? -> A: No; failed tables are left out of that list (FR-006, Story 3 scenario 6).
- Approved by the user the same day: OCR as a default dependency. The constitution is amended to 1.1.0 (Technology and Security Constraints). The other proposed amendment, the wording of Principle II about warnings and errors, is not approved and not made.

## What the investigation found

The failed call was `extract_tables` on `President-Donald-J.-Trump-2025-Annual-Report.pdf` (927 pages, `openai:gpt-5.6-luna`), run from a notebook in the `2026-11-12-senate-expenditures` project. The cache and the cost log of that run were read; no model request was made for this investigation.

1. **What the model returned.** Discovery made 234 requests (232 windows and 2 retries for a wrong page count), cost $0.9465 and took 34 minutes (21:05 to 21:39 UTC). The 234 cached answers report 933 tables on 931 page entries. 16 of those tables, one on each page of four windows, list **no columns**: pages 357-360 ("Investment Account #6 transactions"), 421-424 and 545-548 ("Investment Account #7 transactions") and 889-892 ("Trademark registrations"). The ones with no columns on 889-892 also have an empty first and last row.
2. **It was a wrong answer, not a missing header.** The pages were looked at. Page 357 prints the header row (`#`, `Description`, `Type`, `Date`, `Amount`) and 1257 QUALCOMM as the first row; the neighbouring pages 356 and 361 got the same five columns from the model. Page 889 prints a six-column trademark table with its header. The model returned `columns: []` for all four pages of a window at once, three times for pages that continue a long table and once for a dense page of small print.
3. **Nothing stops an empty column list.** The answer format accepts an empty list. The check for columns runs only once, after the last window, and only raises. The one retry in discovery covers a wrong page count and wrong extra-field names, not an unusable schema. So the model is never told, and 34 minutes and $0.95 of discovery end in an error.
4. **A rerun fails the same way, for free.** The bad answers are cached, so the next call replays them and raises the same error without spending anything. There is no way out for the user short of deleting cache files by hand.
5. **Different tables were mixed.** Tables are grouped by their column names. Every table with no columns has the same (empty) names, so the 16 entries, from three different tables and four different places in the document, became one table of 16 pages.
6. **A second problem, found on the way.** Only 26 of the 927 pages have a text layer (the first is page 848); the other 901 are scans. The text-layer check still passed, because it rejects a document only when no page has text, or when more than 10% of the pages that have text are garbled. Pages with no words are listed as bad but do not count. So OCR was not tried (and PaddleOCR is not installed in that project), and had discovery succeeded, 901 pages of values would have been checked against nothing. The decision recorded in Story 5 is to OCR every page that has no text, rather than to refuse such a document.
7. **The cache says too little about its own entries.** A cache file is the model's bare answer, named by a hash of the request. It does not say which pages the request covered, which stage asked, which model answered, when, in which run, or whether it was a retry (and of what). The stage and page are on the in-memory request but are not written, and for discovery the page is empty. To find the four bad windows I had to sort the 234 files by modification time, count 4 pages per window, skip the two answers with a wrong page count, and then check the result by looking at page 357. Anyone debugging a long run will have to do the same.

## User Scenarios & Testing *(mandatory)*

### User Story 1 - One bad table does not cost me the others (Priority: P1)

An analyst runs `extract_tables` on a long report with many tables. Discovery or extraction cannot produce a valid result for one table. The call finishes, returns every sound table as before, and also returns the failed table. A warning at the moment of the failure says which table (its label), which pages, and what was wrong. The closing progress message lists the failed tables.

**Why this priority**: it is the request. Today one table out of dozens, found after a 34-minute, $0.95 stage, discards all the others.

**Independent Test**: drive the pipeline with a scripted model that gives one table of a generated three-table PDF an empty column list (and again, on the retry). The call returns three tables, two sound and one failed, with exactly one failure warning, and the two sound tables equal what the same call returns when the third table is left out.

**Acceptance Scenarios**:

1. **Given** discovery reports a table with no columns on its pages, even after the one retry, **When** the call runs, **Then** it does not raise, it returns a failed table for those pages, and it emits one warning that names the table's label, its pages and the problem.
2. **Given** a document with 3 tables of which 1 fails, **When** the call ends, **Then** the other 2 tables have the rows, grounding, positions, rechecks and audit results they would have without the failure.
3. **Given** every table fails, **When** the call ends, **Then** it returns the failed tables and does not raise.
4. **Given** a failed table, **When** the call ends, **Then** the closing progress message names it and the number of failed tables, and the saved run (`.quotable/runs/`) records it as failed with its problems.
5. **Given** a call with no failure, **When** it ends, **Then** its tables, messages and saved run are what they were before this change, apart from the new "failed" field being false.

---

### User Story 2 - Reading a failed table warns instead of raising (Priority: P1)

A user looks at the returned tables in a notebook. A failed table may hold nothing, or only some of its pages. Every way of reading its data (`rows()`, `page_rows()`, `records()`, `to_pandas()`, `to_polars()`, `flagged()`) still works and returns what the table holds, and each call emits a warning that the table failed, why, and that the data may be incomplete or wrong.

**Why this priority**: the second half of the request. The point of returning a failed table is to let the user inspect it, so reading it must work.

**Independent Test**: read each accessor of a failed table under a warnings recorder. Each returns without raising and records exactly one warning of the failure category that names the table's label and problems. The same accessors on a sound table record none.

**Acceptance Scenarios**:

1. **Given** a failed table, **When** the user calls `records()`, **Then** the call returns a list (possibly empty) and one warning is emitted.
2. **Given** a failed table, **When** the user reads its descriptive fields (`label`, `columns`, `pages`, the problems, the failed flag), **Then** no warning is emitted, so a user can test the flag without noise.
3. **Given** a sound table, **When** any accessor is used, **Then** no warning is emitted.
4. **Given** a user who turns the failure warning into an error with Python's warning filters, **When** they read a failed table, **Then** it raises, because the filters decide, not the library.

---

### User Story 3 - A table with no columns is not accepted from the model (Priority: P1)

When the model says a table has no columns, that answer is not taken as a table. The model is asked the same question again once, with the problem named (as is already done for a wrong page count), and the answer to that is used. An empty list, a blank column name and a repeated column name are all treated this way, because all three are unusable. If the second answer is still unusable, that table becomes a failed table (Story 1). Failed pages are never grouped with pages whose problem is different.

**Why this priority**: the first half of the request, and it is the repair: in the investigation the model had the information it needed and a second chance might give a valid answer. Without this, Story 1 only softens the loss.

**Independent Test**: script the model to answer a window with an empty column list the first time and a correct list the second time. The call returns one sound table that includes those pages, the second request names the problem, and the answer is cached. Then script both answers empty: a failed table with those pages is returned.

**Acceptance Scenarios**:

1. **Given** a window answer where one table has no columns, **When** discovery handles it, **Then** it sends the window once more with the problem named and uses the new answer.
2. **Given** the retry still has an unusable table, **When** discovery finishes, **Then** only that table fails; tables in the same window that were valid are kept.
3. **Given** failed entries of different labels, **When** they are collected, **Then** they are separate failed tables, never one table of unrelated pages.
4. **Given** the cache from the failed Trump run, **When** the call is repeated, **Then** it neither raises the old error nor repeats the bad answers: the cached bad answers are read, the unusable one is seen, and the retry is made (new request, or cached if it was made before).
5. **Given** a page that really has no table, **When** the model gives an empty list of tables for it, **Then** nothing is reported or warned: that answer is valid.
6. **Given** a table that failed in discovery, **When** later windows are asked, **Then** the "Known tables" list they are shown does not include it, so the model cannot copy its unusable columns.

---

### User Story 4 - Later-stage failures of one table are tolerated too (Priority: P2)

The same applies to the other checks that can fail a table: rows still invalid for a page after the retry, a first or last row that cannot be found in a shared page's text layer, and overlapping bands. The table is a failed table. It keeps the pages that did extract (readable with the warning of Story 2) and lists the pages that did not. Later stages (merge, recheck, audit, extra fields) skip a failed table and work on the sound ones.

**Why this priority**: the request says "an issue that affects one table in validation", not only the one seen. Without it the fix covers one door of three.

**Independent Test**: script the model to give invalid rows twice for one page of one table: the call returns that table failed (pages before and after the bad page present), the other tables sound, one warning.

**Acceptance Scenarios**:

1. **Given** a page whose rows are still invalid after the retry, **When** the call ends, **Then** its table is failed, the problem names the page, and the table's other pages are in it.
2. **Given** two tables whose bands overlap on a page, **When** the call runs, **Then** both are failed tables that name each other, and a third table elsewhere is sound.
3. **Given** a failed table, **When** merge, recheck, audit and the extra-field stages run, **Then** none of them reads, changes or raises on it, and none of them spends a request on it.

---

### User Story 5 - Every page without text is OCR'd, and OCR comes with quotable (Priority: P2)

Every page whose text layer has no words is sent to OCR, whatever share of the document it is, and the run continues with the OCR text as that page's text layer. OCR needs no extra install: PaddleOCR and the CPU build of PaddlePaddle are installed with quotable on the platforms that have a wheel for them.

**Why this priority**: it was found in the same run. It does not cause the error, but a run that got past it would have spent for 901 pages that cannot be verified, and the user's own fix is to read those pages instead of refusing them. It is independent of Stories 1-4 in behavior, but it ships in this spec.

**Independent Test**: with the OCR engine replaced by a fake that returns known words, build a 20-page PDF with text on 2 pages and nothing on 18. The call OCRs exactly the 18 pages and carries on, and `Table.ocr_pages` lists them. A 20-page PDF whose only empty page is blank OCRs that one page and finds nothing on it, without an error. With the real engine, one scanned page of the Trump report is OCR'd and its table rows are found in the text (opt-in, no model cost).

**Acceptance Scenarios**:

1. **Given** a document in which some pages have no words, **When** the call starts, **Then**, whatever their share, those pages and only those are OCR'd before any model request, and the text layer used for checking contains their OCR text.
2. **Given** a page where OCR finds no words (a blank page), **When** OCR ends, **Then** the page stays empty and there is no error; **but** if the document still has no words on any page, `TextLayerError` is raised as today.
3. **Given** the Trump annual report, **When** the call starts, **Then** its 901 pages without text are OCR'd, and a rerun reads their OCR text from the cache.
4. **Given** `ocr=False` and more than 10% of the pages have no words, **When** the call starts, **Then** `TextLayerError` is raised before any request, naming how many pages have no text. With 10% or fewer, the document is accepted as today.
5. **Given** `pip install quotable` on a platform that has a PaddlePaddle wheel, **When** a document needs OCR, **Then** it runs with no extra. **Given** a platform without one (Intel Mac, Linux ARM, Python 3.14), **When** quotable is installed, **Then** the install succeeds, and a document that needs OCR raises `OcrUnavailableError` before any request, as today.
6. **Given** OCR of many pages, **When** it runs, **Then** progress messages show the pages done so far, in the way the model stages do (spec 017), so a long OCR is not silent.

---

### User Story 6 - A cache entry says what it is (Priority: P2)

Someone debugging a long run opens the cache and can tell, for any entry, which pages it covers, which stage asked, which model answered, when, in which run (the id the cost log uses), and, for a retry, which request it retried and what problem it named. Nothing about how entries are found or reused changes.

**Why this priority**: the investigation needed this and had to rebuild it by hand (finding 7). It is also what lets a future tool answer "which windows came back unusable" without guessing. It is independent of the other stories.

**Independent Test**: run a small generated PDF through the pipeline with a scripted model that gives one unusable answer. Every cache file written has the details above, the retry's entry points to the original request and names the problem, and the original's key is the same as before this change. Then put an entry written by the previous version in the cache: it is read and used.

**Acceptance Scenarios**:

1. **Given** a discovery request for pages 357-360, **When** its answer is cached, **Then** the entry records pages 357-360, the stage, the model name, the time written and the run id.
2. **Given** a retry made because an answer was unusable, **When** its answer is cached, **Then** the entry records the key of the request it retried and the problem named.
3. **Given** a cache written before this change, **When** a call reads it, **Then** every old entry is used as it was, and no entry is rewritten just to add details.
4. **Given** the cache of any call, **When** it is searched, **Then** no entry holds a prompt, an image, a file path or a credential.

---

### Edge Cases

- A **cache entry written by this version and read by an older one** is not required to work; the older reader may ignore it. Entries written by older versions MUST keep working here.
- A **failed table with no pages that extracted** returns empty rows. `records()` returns an empty list and `to_pandas()` an empty frame, with the warning.
- **Document-level failures keep raising**: no table in the whole document; a window answer that is wrong (page count, extra-field names) after its retry; a page too large for the image policy; the cost limit and the request cap; a bad text layer. A scripted test pins each, so this spec does not turn them into warnings by accident.
- A **window with a valid table and an unusable one** keeps the valid table; only the unusable one retries and, if still bad, fails.
- A **failed table whose pages another sound table also uses** (two tables on one page): the sound table is unaffected; its band is found from its own first and last rows as today.
- The **merge step** must not merge a failed table into another or another into it, and a failed table's lack of columns must not count as "the same columns".
- **Warnings are not repeated per row**: one warning per accessor call, however many rows the call returns.
- A failed table in a **saved run** is read back by the review app without error and shown as failed. How richly it is shown is not decided here.
- A **rerun** of a call that had a failed table reads the same answers from the cache and fails the same table for free, unless the retry in Story 3 now produces a valid answer.

## Requirements *(mandatory)*

### Functional Requirements

- **FR-001**: `extract_tables` and `extract_tables_async` MUST NOT raise because of a check that can fail a table; they MUST return a failed table for it and every sound table as they would without the failure.
- **FR-002**: A failed table MUST record that it failed and every problem found, each with the pages it concerns and the stage it came from, and MUST keep every result the run produced for it (label, pages found, extracted pages).
- **FR-003**: At the moment a table fails, the library MUST emit one warning of a dedicated category (exported from `quotable`) that gives the table's label, its pages and the problems. It MUST NOT emit the warning again for the same failure.
- **FR-004**: Every way to read a failed table's data (`rows()`, `page_rows()`, `records()`, `to_pandas()`, `to_polars()`, `flagged()`) MUST return what the table holds without raising, and MUST emit one warning of the same category per call that says the table failed and why. Reading descriptive fields and the failure record MUST NOT warn. A sound table MUST never warn.
- **FR-005**: A discovery answer in which a table has no columns, a blank column name or a repeated column name MUST be treated as invalid: the window is sent once more with the problem named, in the way an answer with a wrong page count already is. Only the tables that are still unusable after that become failed tables.
- **FR-006**: Failed discovery entries MUST be grouped by their label and never with entries of a different label, and MUST NOT be grouped with a sound table or matched to one by their (empty) column names. A table that failed in discovery MUST NOT appear in the "Known tables" list shown to later windows.
- **FR-007**: A page of a table whose rows are still invalid after the existing retry MUST fail that table only; the table MUST keep the pages that extracted and list the pages that did not.
- **FR-008**: A table whose first or last row cannot be found on a shared page, or whose band overlaps another table's, MUST fail only the tables concerned (both, for an overlap).
- **FR-009**: Merge, recheck, audit and the extra-field stages MUST skip a failed table, send no request for it, and MUST NOT raise because of it. A failed table MUST NOT take part in a merge in either direction.
- **FR-010**: The closing progress message MUST state how many tables failed and name them. A call with none MUST print what it printed before.
- **FR-011**: A saved run MUST record, for each table, whether it failed and its problems, and a run saved before this change MUST still be read (no failure). The review app MUST open a run with a failed table without error.
- **FR-012**: A call with no failed table MUST return tables equal to those it returned before this change, and MUST send the same requests (same prompts and cache keys), so existing caches stay valid. The one exception is a request whose input includes the text of a page that is now OCR'd (FR-014): the recheck and audit requests for those pages differ, and only those.
- **FR-013**: Document-level failures listed in "Not changed" MUST still raise their present errors.
- **FR-014**: Every page whose text layer has no words MUST be OCR'd before any model request, whatever their share of the document, and the OCR text MUST replace that page's layer. A page OCR finds nothing on stays empty without error. Garbled pages keep today's rule (OCR'd only when the document is rejected for too many of them). The check afterwards stays as today: a document with no words at all is rejected.
- **FR-015**: With OCR turned off (`ocr=False`), a document in which more than 10% of the pages have no words MUST be rejected with `TextLayerError` before any request, naming how many pages have no text; at most 10% is accepted as today.
- **FR-016**: PaddleOCR and the CPU build of PaddlePaddle MUST be installed with quotable (no extra), only on platforms and Python versions for which a PaddlePaddle wheel exists; elsewhere installation MUST still succeed and a document that needs OCR MUST raise `OcrUnavailableError` as today. The `ocr` and `ocr-core` extras MUST be removed or kept as harmless aliases (decided in the plan). PaddleOCR MUST still be imported only when a page misses the OCR cache.
- **FR-017**: OCR of more than a handful of pages MUST report its progress with the same kind of messages as the model stages.
- **FR-018**: Each change of behavior MUST come with offline tests that drive the pipeline with scripted models, including one that replays the four empty-column windows of the failed run's cached answers.
- **FR-019**: Each cache entry written MUST record, besides the answer: the stage; the pages the request covered (for every stage, discovery windows included); the model name and settings identity; the time written; the run id shared with the cost log; and, for a retry, the key of the request it retried and the problem named. It MUST NOT record prompts, images, file paths or credentials.
- **FR-020**: Request keys MUST NOT change, and the answer MUST be read and validated as before. An entry written before this change MUST still be read and used unchanged and MUST NOT be rewritten to add details. The format change MUST be stated in the plan together with how old entries are told apart from new ones (Constitution IV).

### Key Entities

- **Failed table**: a returned table with a failed flag and a list of problems. Descriptive fields stay readable without a warning; data access warns.
- **Problem**: what went wrong for one table: the stage (discovery, extraction, location in the text layer), the pages, and a message a person can act on.
- **Failure warning**: the warning category for a failed table, used at the moment of failure and on each data access, so a user can silence it, show it or turn it into an error with Python's warning filters.
- **Cache entry**: the stored answer to one request, with the details of FR-019 beside it. Its name is still the request's key.

### Not changed

- The cost limit, the request cap, the page-size check, a text layer that is still unusable after OCR, "no table found in the document", and a window answer that is wrong after its retry still raise.
- Grounding, the position check, the recheck, the audit and the merge rules for sound tables.
- Prompts and cache keys of every request that exists today. The retry in Story 3 is a new request; it exists only where an answer was unusable. The model's answer inside each cache entry is also unchanged (Story 6 adds details beside it).

## Success Criteria *(mandatory)*

### Measurable Outcomes

- **SC-001**: Replaying the cached discovery answers of the failed run offline, with a scripted model answering the retries (no network, no real model), the call returns instead of raising, and every table the model described validly is returned.
- **SC-002**: In a generated document of 3 tables where one fails, the 2 sound tables are identical (rows, grounding statuses, positions, flags) to the result of the same document with the failing table removed.
- **SC-003**: Each failure produces exactly 1 warning when it happens, and each data-reading call on a failed table produces exactly 1 warning; across the whole offline suite, a sound table produces 0.
- **SC-004**: With the real model on the four windows that failed (pages 357-360, 421-424, 545-548, 889-892), each ends as a table or a failed table, never as an error. This is a live check, run only with your go-ahead; its cost is about $0.02 for 16 pages plus retries.
- **SC-005**: In the Trump annual report, all 901 pages without text are OCR'd before any model request, and a second call reads them from the cache without running the OCR engine. With `ocr=False` the same report is refused before any model request, with a message that names 901 pages without text. (The real-engine run takes no model requests, but its time has not been measured.)
- **SC-006**: The existing offline suite passes with only the changes to tests that expected an error from a check that now fails a table; every other test is unchanged.
- **SC-007**: For 100% of cache entries written in a test run, the stage, pages, model, time and run id can be read without the pipeline; every retry entry names its original; the tests that pin request keys pass unchanged; and a cache from before this change (a fixture of old-format entries) gives the same results as before.

## Assumptions

- A failed table is returned in the same list as sound tables, in order of first appearance; the user tells them apart by its flag.
- There is no switch to restore the old raising behavior. If wanted later, it is a small addition; it is left out because nothing asked for it.
- The new warning category and the failure fields are public API, so they are exported from `quotable`; their names are for the plan to decide.
- One retry of a window for an unusable schema is enough, as it is for a wrong page count; more attempts would multiply cost on a model that has already answered the same way.
- The cache needs no change to find an entry: the retry request differs from the original request (it names the problem), so a bad cached answer is read once, found unusable, and the retry takes over. Story 6 changes only what an entry records, not how it is found.
- Details are written only for new entries. The failed run's 234 entries stay without them; for those, the cost log and the file times remain the only clues, which is why the investigation rebuilt them by hand.
- Principle II of the constitution ("failures MUST be loud and typed", "MUST NOT swallow errors that change results") is met by the typed warning at the failure, the flag and the problems on the table, the warning on each read and the closing message: nothing is hidden. It does say failures are typed in `quotable.errors`, so the plan proposes a wording amendment (per-table failures as warnings, document-level failures as errors) for you to approve with `speckit-constitution`; this spec does not make it.
- The 10% limit applies only when OCR is off. It is the share the check already uses for garbled pages and is not tuned on data. The Trump report is 97% scanned, far from any sensible limit.
- Making OCR a default dependency changed the constitution's rule that OCR "MUST stay optional extras"; the user approved the amendment on 2026-11-13 and the constitution is now 1.1.0 (OCR is a default dependency, still imported only when used). The README and AGENTS.md change with the implementation.
- The CPU build of PaddlePaddle is the default. NVIDIA users must replace it with their GPU build, as `ocr-core` users did, so the README's GPU section changes to say so. Which platforms get the dependency is a plan decision (environment markers); the README lists today Apple Silicon Macs, Linux x86_64 and Windows x86_64 on Python 3.11 to 3.13.
- Installing quotable gets larger by about 100 to 200 MB plus OpenCV (README's figure for the CPU build), for everyone, including users whose PDFs never need OCR. This is the cost of the request and is accepted here.
- OCR of 901 pages on a CPU is slow. Nobody has measured it for this report, so the spec sets no time target; Story 5 asks for progress messages instead.
- A page that was empty now has OCR text, and the recheck sends the page's whole text layer (spec 002), so those pages' recheck requests, and any audit request that lists the page's words, differ from before (FR-012). Whether either stage treated an empty page differently before was not checked here; the plan should.
- Spec 018 (one configurable concurrency limit) touches discovery and the pipeline's request gate too. The two are independent in behavior; whichever lands second merges the other's changes.
