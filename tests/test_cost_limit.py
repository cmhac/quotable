"""The cost limit, estimates and messages through the whole pipeline (spec 017)."""

import asyncio
import copy
import json
from decimal import Decimal
from pathlib import Path

import pytest

from quotable.errors import BudgetExceededError, CostLimitExceededError
from quotable.estimate import estimate_discovery
from quotable.llm.answers import CellRecheck, Omissions, PageRecheck
from quotable.llm.client import CachedClient
from quotable.meter import CostModel, RunMeter
from quotable.pipeline import CostContext, run_metered
from quotable.progress import NullSink, Reporter
from tests.conftest import DATA, FakeClient, PricedClient, load_sample, replay
from tests.test_progress import RecordingSink

D = Decimal
PDF = DATA / "fy22_ag_house_original.pdf"  # four pages, one table
SAMPLE = load_sample("fy22_ag_house_original")
CENT = D("0.01")


def corrupted() -> tuple[dict, dict]:
    """The recorded rows with one wrong word in row 1 of every page, and the true values."""
    pages = copy.deepcopy(SAMPLE["pages"])
    truth = {}
    for page, rows in pages.items():
        column = max(SAMPLE["columns"], key=lambda c: len(rows[0][c].split()))
        words = rows[0][column].split()
        truth[page] = (1, column, rows[0][column])
        words[1] = "Zzyzx"
        rows[0][column] = " ".join(words)
    return pages, truth


def model_handler(*, flagged: bool = False):
    """A model that answers every stage; ``flagged`` makes the recheck run on every page."""
    pages, truth = corrupted() if flagged else (SAMPLE["pages"], {})
    base = replay(SAMPLE["columns"], pages).handler

    def handler(request):
        if request.stage == "recheck":
            if request.page not in truth:
                return PageRecheck(cells=[])
            row, column, value = truth[request.page]
            return PageRecheck(cells=[CellRecheck(row=row, column=column, value=value)])
        if request.stage == "audit":
            return Omissions(missing_rows=[], filled_cells=[])
        return base(request)

    return handler


class Run:
    """One metered run with a priced fake model; ``go`` can be called again on the same cache."""

    def __init__(  # noqa: PLR0913, PLR0917
        self, tmp_path: Path, limit=None, cost=CENT, no_usage=(), flagged=False, sink=None
    ):
        self.cache = tmp_path / "cache"
        self.cache.mkdir(parents=True, exist_ok=True)
        self.limit = limit
        self.cost = cost
        self.no_usage = no_usage
        self.handler = model_handler(flagged=flagged)
        self.sink = sink or RecordingSink()
        self.model = CostModel(
            "fake:model",
            lambda i, o: D(i + o) / 1_000_000,
            lambda w, h, detail: 1000,
            image_basis="a fixed 1000 tokens an image",
        )

    def go(self, limit="same", **options):
        limit = self.limit if limit == "same" else limit
        self.meter = RunMeter(limit)
        self.fake = FakeClient(self.handler)
        self.priced = PricedClient(self.fake, self.meter, self.cost, self.no_usage)
        self.client = CachedClient(self.priced, self.cache, None, self.meter)
        self.reporter = Reporter(self.sink, self.meter)
        self.ctx = CostContext(self.meter, self.reporter, self.model, self.client.peek)
        options = {"audit": True, "recheck": True, "discovery_pages": 2, **options}
        return asyncio.run(run_metered(PDF, self.client, self.ctx, **options))


# --- story 5: the limit stops the run the moment it is passed -----------------------------------
def test_the_limit_crossed_in_the_middle_of_extraction_stops_the_run(tmp_path):
    run = Run(tmp_path, limit=D("0.035"))  # discovery 2 requests, then extraction
    with pytest.raises(CostLimitExceededError) as caught:
        run.go()
    error = caught.value
    assert error.reason == "spent"
    assert error.stage in ("extract", "audit", "recheck")
    # no request was started after the total went above the limit
    assert all(total <= error.limit for _, total in run.priced.started)


def test_the_error_figures_agree_with_the_meter_and_with_the_limit(tmp_path):
    run = Run(tmp_path, limit=D("0.035"))
    with pytest.raises(CostLimitExceededError) as caught:
        run.go()
    error = caught.value
    assert error.spent == run.meter.total
    assert error.over == error.spent - error.limit
    assert error.limit + error.raise_by >= error.spent
    assert "raise max_cost by at least" in str(error)


def test_requests_in_flight_when_the_limit_is_crossed_are_billed_and_counted(tmp_path):
    run = Run(tmp_path, limit=D("0.025"))
    with pytest.raises(CostLimitExceededError) as caught:
        run.go(discovery_pages=4)  # one discovery request, then four extraction requests together
    error = caught.value
    paid = sum(t.requests for t in run.meter.tallies.values())
    # the sample runs three pages together: the second extraction crossed the limit, the third was
    # in flight
    assert paid == 4
    assert error.spent == CENT * 4  # and is billed and counted
    assert error.in_flight == 1
    assert "1 requests were in flight" in str(error)


def test_a_rerun_with_the_limit_raised_takes_what_was_paid_from_the_cache(tmp_path):
    run = Run(tmp_path, limit=D("0.035"))
    with pytest.raises(CostLimitExceededError) as caught:
        run.go()
    paid_before = len(run.fake.requests)
    tables = run.go(limit=caught.value.limit + caught.value.raise_by + D("1"))
    assert len(tables) == 1
    assert run.meter.tally("schema", "discovery").cache_hits >= 1
    assert paid_before > 0
    asked_again = [r for r in run.fake.requests if r.stage == "schema"]
    assert asked_again == []


def test_a_request_with_no_usage_stops_a_limited_run(tmp_path):
    run = Run(tmp_path, limit=D("100"), no_usage=("extract",))
    with pytest.raises(CostLimitExceededError) as caught:
        run.go()
    assert caught.value.reason == "unmetered"
    assert caught.value.stage == "extract"
    assert "without usage figures" in str(caught.value)


def test_without_a_limit_nothing_is_stopped_whatever_it_costs(tmp_path):
    run = Run(tmp_path, limit=None, cost=D("1000"), no_usage=("extract",))
    (table,) = run.go()
    assert table.columns == SAMPLE["columns"]


def test_the_limit_crossed_by_the_very_last_request_still_raises(tmp_path):
    first = Run(tmp_path, limit=None)
    first.go()
    total = first.meter.total
    # a fresh cache makes the same requests again; the last paid request crosses the limit
    second = Run(tmp_path / "again", limit=total - D("0.001"))
    with pytest.raises(CostLimitExceededError):
        second.go()


def test_a_request_cap_stops_the_run_with_the_older_error(tmp_path):
    meter = RunMeter(D("100"))
    cache = tmp_path / "capped"
    cache.mkdir()
    client = CachedClient(PricedClient(FakeClient(model_handler()), meter), cache, 1, meter)
    model = CostModel("m", lambda i, o: D(0))
    ctx = CostContext(meter, Reporter(NullSink(), meter), model, client.peek)
    with pytest.raises(BudgetExceededError) as caught:
        asyncio.run(run_metered(PDF, client, ctx))
    assert not isinstance(caught.value, CostLimitExceededError)


def test_another_failure_gets_a_closing_message_and_is_raised_unchanged(tmp_path):
    run = Run(tmp_path, limit=D("100"))
    base = run.handler

    def handler(request):
        if request.stage == "extract":
            raise RuntimeError("boom")
        return base(request)

    run.handler = handler
    with pytest.raises(RuntimeError, match="boom"):
        run.go()
    closings = [text for kind, text in run.sink.events if text.startswith("quotable: stopped")]
    assert len(closings) == 1
    assert "after $" in closings[0]


def test_the_cost_log_total_matches_the_error(tmp_path):
    """The meter total and the sum a cost log would hold for the same requests are the same."""
    run = Run(tmp_path, limit=D("0.035"))
    with pytest.raises(CostLimitExceededError) as caught:
        run.go()
    paid = sum(t.requests for t in run.meter.tallies.values())
    assert caught.value.spent == CENT * paid


def test_json_cost_logging_is_not_part_of_the_error():
    # the error text names stages and amounts only: no prompt, value or path
    from quotable.meter import make_error  # noqa: PLC0415

    text = str(make_error("spent", limit=D("1"), spent=D("1.5"), stage="extract", done=2, total=9))
    assert json.dumps(text).count("/") == 0


# --- story 1: an estimate for discovery, before anything is sent --------------------------------
PAGE_SIZES = [(612.0, 792.0)] * 4


def messages(run: Run, containing: str) -> list[str]:
    return [text for kind, text in run.sink.events if kind == "fixed" and containing in text]


def test_the_discovery_estimate_is_printed_before_the_first_request(tmp_path):
    run = Run(tmp_path, limit=D("50"))
    seen: list[int] = []
    original = run.sink.fixed

    def stamp(text):
        seen.append(len(run.fake.requests))
        original(text)

    run.sink.fixed = stamp  # ty: ignore[invalid-assignment]
    run.go()
    (text,) = messages(run, "estimate before discovery")
    assert seen[0] == 0  # nothing had been sent when the first message was shown
    assert "4 pages, 2 discovery requests of 2 pages (0 already in the cache)" in text
    assert "estimated cost $" in text
    assert "based on: page images at 150 dpi (a fixed 1000 tokens an image)" in text
    assert "cost limit: $50.00" in text


def test_a_limit_below_the_estimate_stops_the_run_before_any_request(tmp_path):
    run = Run(tmp_path)
    estimate = estimate_discovery(PAGE_SIZES, run.model, discovery_pages=2)
    assert estimate.cost is not None
    run.limit = estimate.cost - D("0.0000001")
    with pytest.raises(CostLimitExceededError) as caught:
        run.go()
    error = caught.value
    assert (error.reason, error.spent, error.estimate) == ("estimate", D(0), estimate.cost)
    assert run.fake.requests == []
    assert "Nothing has been requested" in str(error)
    assert "estimate for discovery is" in str(error)


def test_a_limit_equal_to_the_estimate_does_not_stop_the_run(tmp_path):
    run = Run(tmp_path)
    estimate = estimate_discovery(PAGE_SIZES, run.model, discovery_pages=2)
    run.limit = D("50")
    run.go()
    assert estimate.cost is not None and estimate.cost < D("50")
    run2 = Run(tmp_path / "x", limit=estimate.cost)
    # equal to the estimate passes the estimate check (the actual cost check may still stop it)
    try:
        run2.go()
    except CostLimitExceededError as err:
        assert err.reason != "estimate"


def test_no_limit_still_prints_the_estimate_and_runs_without_waiting(tmp_path):
    run = Run(tmp_path, limit=None)
    (table,) = run.go()
    assert table.columns == SAMPLE["columns"]
    (text,) = messages(run, "estimate before discovery")
    assert "cost limit" not in text


def test_discovery_answers_in_the_cache_are_left_out_and_counted(tmp_path):
    first = Run(tmp_path, limit=None)
    first.go()
    again = Run(tmp_path, limit=None)
    again.go()
    (text,) = messages(again, "estimate before discovery")
    assert "0 discovery requests" in text and "(2 already in the cache)" in text
    assert "estimated cost $0.0000" in text


def test_an_unknown_image_rule_says_no_estimate_and_the_run_goes_on_with_a_limit(tmp_path):
    run = Run(tmp_path, limit=D("50"))
    run.model = CostModel("fake:model", lambda i, o: D(i + o) / 1_000_000)
    run.go()
    (text,) = messages(run, "estimate before discovery")
    assert 'no estimate: no image-size rule is known for "fake:model"' in text
    assert "checked against actual cost after every request" in text


def test_an_unknown_price_without_a_limit_shows_tokens_and_goes_on(tmp_path):
    run = Run(tmp_path, limit=None)
    run.model = CostModel("fake:model", lambda i, o: None, lambda w, h, d: 1000)
    run.go()
    (text,) = messages(run, "estimate before discovery")
    assert "tokens; no price is known" in text and "dollars are not" in text


# --- story 2: progress and running cost during discovery -----------------------------------------
def live_lines(run: Run, stage: str) -> list[str]:
    return [text for kind, text in run.sink.events if kind.startswith("live") and stage in text]


def test_discovery_shows_windows_done_of_total_and_the_cost_so_far(tmp_path):
    run = Run(tmp_path, limit=None)
    run.go(audit=False, recheck=False)
    lines = live_lines(run, "discovery")
    assert "0 of 2 windows" in lines[0]
    assert "2 of 2 windows" in lines[-1] and "$0.0200 so far (about $" in lines[-1]
    finals = [t for kind, t in run.sink.events if kind == "live-final" and "windows" in t]
    assert finals == [lines[-1]]  # the last state is the one line that stays


def test_discovery_answered_from_the_cache_says_so_and_adds_no_cost(tmp_path):
    Run(tmp_path, limit=None).go(audit=False, recheck=False)
    again = Run(tmp_path, limit=None)
    again.go(audit=False, recheck=False)
    assert "(from the cache)" in live_lines(again, "discovery")[-1]
    assert again.meter.tally("schema").cost == D(0)


# --- story 3: a sample run, then a better estimate for extraction --------------------------------
def test_with_a_cost_context_the_tables_are_the_same_as_without(tmp_path):
    from quotable.pipeline import run_pipeline  # noqa: PLC0415

    plain_client = FakeClient(model_handler(flagged=True))
    plain = asyncio.run(run_pipeline(PDF, plain_client, audit=True, discovery_pages=2))
    run = Run(tmp_path, limit=None, flagged=True)
    metered = run.go()
    assert len(plain) == len(metered) == 1
    for a, b in zip(plain, metered, strict=True):
        assert a.records() == b.records()
        assert a.position == b.position
        assert [vars(p) for p in a.proposals] == [vars(p) for p in b.proposals]
        assert [vars(i) for i in a.audit] == [vars(i) for i in b.audit]


def test_the_sample_is_announced_with_its_pages_and_covers_the_full_process(tmp_path):
    run = Run(tmp_path, limit=None, flagged=True)
    run.go()
    (text,) = messages(run, "quotable: sample run")
    assert "found 1 tables on 4 table pages" in text
    assert "3 table pages" in text and "table 1 page 1, table 1 page 3, table 1 page 4" in text
    assert "extraction, audit, recheck" in text
    sample = {
        stage for (phase, stage), t in run.meter.tallies.items() if phase == "sample" and t.requests
    }
    assert {"extract", "audit", "recheck"} <= sample


def test_the_extraction_answers_of_the_sample_are_cache_hits_in_the_rest(tmp_path):
    run = Run(tmp_path, limit=None)
    run.go()
    rest = run.meter.tally("extract", "rest")
    assert rest.cache_hits == 3 and rest.requests == 1  # three sample pages reused, one new
    assert run.meter.tally("extract", "sample").requests == 3


def test_the_estimate_for_the_rest_is_printed_after_the_sample(tmp_path):
    run = Run(tmp_path, limit=D("50"))
    run.go()
    (text,) = messages(run, "estimate for the rest of the run")
    assert "sample: 3 table pages cost $" in text
    assert "rest: 1 table pages, about $" in text
    assert "expected total $" in text and "cost limit $50.00" in text
    estimate = run.ctx.estimates["rest"]
    assert estimate.expected_total == run.meter.estimate_total


def test_a_limit_between_the_sample_and_the_expected_total_stops_after_the_sample(tmp_path):
    first = Run(tmp_path, limit=None)
    first.go()
    expected = first.ctx.estimates["rest"].expected_total
    sample_end = first.meter.tally("extract", "sample").cost  # at least this much was spent
    assert sample_end > 0
    second = Run(tmp_path / "limited", limit=expected - D("0.0001"))
    with pytest.raises(CostLimitExceededError) as caught:
        second.go()
    assert caught.value.reason == "estimate"
    assert caught.value.estimate == expected
    assert caught.value.spent > 0  # the sample was paid for
    extractions = [r for r in second.fake.requests if r.stage == "extract"]
    assert len(extractions) == 3  # only the sample's; none of the rest


def test_a_small_table_is_run_as_it_is_with_no_sample(tmp_path):
    small = load_sample("fy22_milcon_house_original")
    run = Run(tmp_path, limit=None)
    run.handler = replay(small["columns"], small["pages"]).handler
    asyncio.run(
        run_metered(
            small["pdf"],
            _client_for(run),
            run.ctx,
            audit=False,
            recheck=False,
        )
    )
    texts = messages(run, "small enough to run as it is")
    assert len(texts) == 1 and "on 1 table pages" in texts[0]
    assert not any(phase == "sample" for phase, _ in run.meter.tallies)
    assert messages(run, "estimate for the rest") == []


def _client_for(run: Run) -> CachedClient:
    run.meter = RunMeter(run.limit)
    run.fake = FakeClient(run.handler)
    run.priced = PricedClient(run.fake, run.meter, run.cost, run.no_usage)
    run.client = CachedClient(run.priced, run.cache, None, run.meter)
    run.reporter = Reporter(run.sink, run.meter)
    run.ctx = CostContext(run.meter, run.reporter, run.model, run.client.peek)
    return run.client


def test_a_page_shared_by_two_tables_runs_through_the_sample_and_gives_the_same_tables(tmp_path):
    from quotable.pipeline import run_pipeline  # noqa: PLC0415
    from tests.test_senate_tables import PDF as SENATE  # noqa: PLC0415
    from tests.test_senate_tables import recorded_model  # noqa: PLC0415

    plain = asyncio.run(run_pipeline(SENATE, recorded_model(), recheck=False))
    meter = RunMeter(None)
    fake = recorded_model()
    client = CachedClient(PricedClient(fake, meter), tmp_path, None, meter)
    ctx = CostContext(
        meter, Reporter(RecordingSink(), meter), CostModel("m", lambda i, o: D(0)), client.peek
    )
    metered = asyncio.run(run_metered(SENATE, client, ctx, recheck=False))
    assert [t.records() for t in plain] == [t.records() for t in metered]
    assert [len(t.layers[1].words) for t in plain] == [len(t.layers[1].words) for t in metered]
    assert {phase for phase, _ in meter.tallies} == {"discovery", "sample", "rest"}


# --- story 4: progress while extracting, and a final summary -------------------------------------
def final_message(run: Run) -> str:
    (text,) = [
        t for kind, t in run.sink.events if kind == "fixed" and t.startswith("quotable: done")
    ]
    return text


def test_extraction_audit_and_recheck_show_their_stage_and_progress(tmp_path):
    run = Run(tmp_path, limit=None, flagged=True)
    run.go()
    rest = [t for kind, t in run.sink.events if kind.startswith("live")]
    assert any("sample extraction" in t and "3 of 3 pages" in t for t in rest)
    assert any(t.strip().startswith("extraction") and "4 of 4 pages" in t for t in rest)
    assert any(t.strip().startswith("audit") and "of up to 4 pages" in t for t in rest)
    assert any(t.strip().startswith("recheck") and "of up to 4 pages" in t for t in rest)
    assert any("(about $" in t and "for the rest)" in t for t in rest)


def test_exactly_one_final_message_with_the_totals_and_the_counts(tmp_path):
    run = Run(tmp_path, limit=D("50"), flagged=True)
    (table,) = run.go()
    text = final_message(run)
    assert text.count("quotable: done in ") == 1
    paid = sum(t.requests for t in run.meter.tallies.values())
    assert f"total cost {dollars_for(run.meter.total)} (limit $50.00)" in text
    assert (
        "discovery $" in text and "(estimated $" in text and "sample $" in text and "rest $" in text
    )
    hits = sum(t.cache_hits for t in run.meter.tallies.values())
    assert f"{hits} answered from the cache" in text
    assert "4 pages, 1 tables, 4 table pages" in text
    assert paid == sum(t.requests for t in run.meter.tallies.values())
    assert len(table.pages) == 4


def dollars_for(amount: D) -> str:
    from quotable.meter import dollars  # noqa: PLC0415

    return dollars(amount)


def test_the_final_total_is_the_sum_of_the_paid_requests_to_the_cent(tmp_path):
    run = Run(tmp_path, limit=None, flagged=True)
    run.go()
    paid = sum(t.requests for t in run.meter.tallies.values())
    assert run.meter.total == CENT * paid
    assert f"total cost {dollars_for(CENT * paid)}" in final_message(run)


def test_the_sample_cost_that_could_not_be_reused_is_reported(tmp_path):
    run = Run(tmp_path, limit=None, flagged=True)
    run.go()
    lost = sum(run.meter.sample_paid.values(), D(0))
    if lost:
        assert f"{dollars_for(lost)} of the sample could not be reused" in final_message(run)
    else:
        assert "could not be reused" not in final_message(run)
    # the sample's extraction requests were all asked for again, so they are reused
    assert run.meter.sample_reused >= CENT * 3


def test_a_model_with_no_price_gets_token_counts_in_the_final_message(tmp_path):
    run = Run(tmp_path, limit=None)
    run.model = CostModel("fake:model", lambda i, o: None, lambda w, h, d: 1000)
    run.cost = None  # PricedClient reports no price
    run.go(audit=False, recheck=False)
    assert "total cost: no price known (" in final_message(run)
    assert "input and" in final_message(run)


def test_a_run_with_no_limit_leaves_the_limit_out_of_the_final_message(tmp_path):
    run = Run(tmp_path, limit=None)
    run.go(audit=False, recheck=False)
    assert "(limit" not in final_message(run)
    assert "total cost $" in final_message(run)


def test_a_run_that_stops_gets_no_final_message(tmp_path):
    run = Run(tmp_path, limit=D("0.035"))
    with pytest.raises(CostLimitExceededError):
        run.go()
    assert not [t for kind, t in run.sink.events if t.startswith("quotable: done")]
    assert messages(run, "quotable: stopped, the cost limit was passed")


# --- story 6: output that fits where it is shown -------------------------------------------------
def test_a_file_gets_the_messages_once_each_with_no_control_codes(tmp_path, capsys):
    from quotable.progress import PlainSink  # noqa: PLC0415

    run = Run(tmp_path, limit=D("50"), flagged=True, sink=PlainSink())
    run.go()
    captured = capsys.readouterr()
    assert captured.out == ""
    assert "\r" not in captured.err and "\x1b" not in captured.err
    lines = captured.err.splitlines()
    assert len(lines) <= 40  # SC-005: set by the messages and stages, not by the pages
    for phrase in (
        "estimate before discovery",
        "quotable: sample run",
        "estimate for the rest",
        "quotable: done in",
    ):
        assert sum(phrase in line for line in lines) == 1
    # each stage prints its status line at the start and at the end, and nowhere in between
    extraction = [line for line in lines if line.strip().startswith("extraction")]
    assert len(extraction) == 2


def test_the_run_in_a_notebook_makes_one_block_per_phase(tmp_path, fake_ipython):
    from quotable.progress import NotebookSink  # noqa: PLC0415

    run = Run(tmp_path, limit=None, flagged=True, sink=NotebookSink())
    run.go()
    blocks = {c[2] for c in fake_ipython.calls}
    assert len(blocks) == 4  # discovery, sample, rest, final
    last = fake_ipython.calls[-1][1]["text/plain"]
    assert last.startswith("quotable: done in ")
    first = next(c for c in fake_ipython.calls if c[0] == "display")[1]["text/plain"]
    assert first.startswith("quotable: estimate before discovery")


def test_progress_off_prints_nothing_but_the_limit_still_stops_the_run(
    tmp_path, capsys, fake_ipython
):
    run = Run(tmp_path, limit=D("0.035"), sink=NullSink())
    with pytest.raises(CostLimitExceededError):
        run.go()
    captured = capsys.readouterr()
    assert captured.out == captured.err == ""
    assert fake_ipython.calls == []
