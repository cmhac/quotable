"""The messages of a run and where they are shown (spec 017)."""

import sys
from decimal import Decimal
from types import ModuleType, SimpleNamespace

from pydantic import BaseModel

from quotable.errors import ExtractionError
from quotable.llm.client import Request
from quotable.meter import RunMeter, make_error
from quotable.progress import (
    CLEAR_LINE,
    NotebookSink,
    NullSink,
    PlainSink,
    Reporter,
    TerminalSink,
    choose_sink,
)

D = Decimal


class RecordingSink:
    """Records what a reporter shows."""

    def __init__(self) -> None:
        self.events: list[tuple[str, str]] = []

    def phase(self, name: str) -> None:
        self.events.append(("phase", name))

    def fixed(self, text: str) -> None:
        self.events.append(("fixed", text))

    def live(self, text: str, *, milestone: bool, final: bool = False) -> None:
        kind = "live-final" if final else ("live-milestone" if milestone else "live")
        self.events.append((kind, text))


def paid(meter: RunMeter, stage: str, cost: str = "0.01") -> None:
    meter.add(
        Request(stage, "", BaseModel, []),
        SimpleNamespace(input_tokens=1, output_tokens=1),
        D(cost),
    )  # type: ignore[arg-type]
    meter.tick(stage)


# --- the sinks ----------------------------------------------------------------------------------
def test_the_plain_sink_writes_whole_lines_to_stderr(capsys):
    sink = PlainSink()
    sink.fixed("one\ntwo")
    sink.live("status", milestone=False)
    sink.live("start", milestone=True)
    captured = capsys.readouterr()
    assert captured.out == ""
    assert captured.err == "one\ntwo\nstart\n"


def test_the_null_sink_writes_nothing(capsys):
    sink = NullSink()
    sink.phase("x")
    sink.fixed("a")
    sink.live("b", milestone=True)
    captured = capsys.readouterr()
    assert captured.out == captured.err == ""


# --- the closing messages -----------------------------------------------------------------------
def test_a_limit_error_is_shown_with_its_headline_and_its_figures():
    sink = RecordingSink()
    reporter = Reporter(sink, RunMeter(D("25")))
    error = make_error(
        "spent", limit=D("25"), spent=D("25.0412"), stage="audit", done=41, total=180
    )
    reporter.closing(error)
    (kind, text) = sink.events[-1]
    assert kind == "fixed"
    assert text.startswith("quotable: stopped, the cost limit was passed")
    assert "over by $0.0412" in text
    assert "raise max_cost by at least" in text
    assert "Everything already answered is in the cache" in text


def test_each_reason_has_its_own_headline():
    sink = RecordingSink()
    reporter = Reporter(sink, RunMeter(D("5")))
    for reason, headline in (
        ("estimate", "estimate is over the cost limit"),
        ("unpriced", "not started"),
        ("unmetered", "reported no token usage"),
    ):
        kwargs = {"estimate": D("6")} if reason == "estimate" else {}
        reporter.closing(make_error(reason, limit=D("5"), spent=D("1"), model="m", **kwargs))
        assert headline in sink.events[-1][1]


def test_another_failure_says_where_it_stopped_and_what_was_spent():
    sink = RecordingSink()
    meter = RunMeter()
    reporter = Reporter(sink, meter)
    paid(meter, "extract", "12.03")
    meter.stage("extract", 10)
    reporter.start_stage("extract")
    reporter.closing(ExtractionError("boom"))
    assert sink.events[-1] == ("fixed", "quotable: stopped in the extraction stage after $12.03")


# --- the status line ----------------------------------------------------------------------------
def test_a_stage_prints_a_line_at_its_start_and_its_end_and_none_between(capsys):
    meter = RunMeter()
    reporter = Reporter(PlainSink(), meter, clock=lambda: 0.0)  # the clock never advances
    meter.stage("schema", 3)
    reporter.start_stage("schema", "about $0.0300")
    for _ in range(3):
        paid(meter, "schema")
    reporter.end_stage()
    lines = capsys.readouterr().err.splitlines()
    assert len(lines) == 2
    assert lines[0].strip().startswith("discovery") and "0 of 3 windows" in lines[0]
    assert "3 of 3 windows" in lines[1] and "$0.0300 so far (about $0.0300)" in lines[1]


def test_the_status_line_for_audit_says_of_up_to():
    meter = RunMeter()
    reporter = Reporter(RecordingSink(), meter)
    meter.phase = "rest"
    meter.stage("audit", 177, upper_bound=True)
    reporter.stage = "audit"
    assert "0 of up to 177 pages" in reporter.line()
    assert reporter.line().strip().startswith("audit")


def test_sample_stages_are_labelled_as_the_sample():
    meter = RunMeter()
    reporter = Reporter(RecordingSink(), meter)
    meter.phase = "sample"
    meter.stage("extract", 3)
    reporter.stage = "extract"
    assert reporter.line().strip().startswith("sample extraction")


def test_a_stage_answered_from_the_cache_says_so_and_adds_no_cost():
    meter = RunMeter()
    reporter = Reporter(RecordingSink(), meter)
    meter.stage("schema", 2)
    reporter.stage = "schema"
    meter.hit("k1", "schema")
    meter.hit("k2", "schema")
    assert "(from the cache)" in reporter.line()
    assert meter.total == 0


def test_redraws_are_limited_to_a_few_a_second_but_the_last_state_is_always_drawn():
    now = [0.0]
    sink = RecordingSink()
    meter = RunMeter()
    reporter = Reporter(sink, meter, clock=lambda: now[0])
    meter.stage("extract", 100)
    reporter.start_stage("extract")
    for _ in range(99):
        paid(meter, "extract")
    drawn = [e for e in sink.events if e[0].startswith("live")]
    assert len(drawn) == 1  # only the start: the clock stood still
    now[0] += 0.3
    paid(meter, "extract")  # the 100th: the stage is done, and drawn at once
    assert sink.events[-1][0] == "live" and "100 of 100" in sink.events[-1][1]
    reporter.end_stage()
    assert sink.events[-1][0] == "live-final" and "100 of 100" in sink.events[-1][1]


def test_a_long_run_prints_few_lines_to_a_file(capsys):
    meter = RunMeter()
    reporter = Reporter(PlainSink(), meter, clock=lambda: 0.0)
    for stage, total in (("schema", 25), ("extract", 100), ("audit", 100), ("recheck", 100)):
        meter.stage(stage, total)
        reporter.start_stage(stage)
        for _ in range(total):
            paid(meter, stage, "0.001")
        reporter.end_stage()
    assert len(capsys.readouterr().err.splitlines()) <= 30


def test_a_sink_that_fails_is_replaced_by_the_plain_one(capsys):
    class Broken:
        def phase(self, name):
            raise RuntimeError

        def fixed(self, text):
            raise RuntimeError

        def live(self, text, *, milestone, final=False):
            raise RuntimeError

    reporter = Reporter(Broken(), RunMeter())
    reporter.fixed("hello")
    reporter.fixed("again")
    assert capsys.readouterr().err == "hello\nagain\n"


# --- where the messages are shown ---------------------------------------------------------------
class FakeTty:
    """A stream that says it is a terminal."""

    def __init__(self) -> None:
        self.parts: list[str] = []

    def write(self, text: str) -> int:
        self.parts.append(text)
        return len(text)

    def flush(self) -> None:
        pass

    def isatty(self) -> bool:
        return True

    @property
    def text(self) -> str:
        return "".join(self.parts)


def test_the_terminal_sink_rewrites_one_line_and_keeps_the_last_state(monkeypatch):
    tty = FakeTty()
    monkeypatch.setattr("sys.stderr", tty)
    sink = TerminalSink()
    sink.live("status 1", milestone=True)
    sink.live("status 2", milestone=False)
    sink.fixed("a message")
    sink.live("status 3", milestone=True)
    sink.live("status 3 done", milestone=True, final=True)
    out = tty.text
    assert out.count(CLEAR_LINE) >= 4 and "\n" in out
    assert out.endswith("status 3 done\n")
    # a fixed message clears the status line before it, so it never lands on the same line
    assert f"{CLEAR_LINE}a message\n" in out


def test_the_notebook_sink_shows_one_display_per_phase_and_updates_it(fake_ipython):
    sink = NotebookSink()
    sink.phase("discovery")
    sink.fixed("estimate line 1\nestimate line 2")
    sink.live("status 1", milestone=True)
    sink.live("status 2", milestone=False)
    sink.live("status 2", milestone=True, final=True)
    sink.phase("sample")
    sink.fixed("announcement")
    calls = fake_ipython.calls
    assert [c[0] for c in calls] == ["display", "update", "update", "update", "display"]
    ids = [c[2] for c in calls]
    assert ids[0] == ids[1] == ids[2] == ids[3] != ids[4]
    assert calls[3][1] == {"text/plain": "estimate line 1\nestimate line 2\nstatus 2"}
    assert calls[1][1]["text/plain"].endswith("status 1")


def test_a_whole_run_leaves_four_notebook_blocks(fake_ipython):
    meter = RunMeter()
    reporter = Reporter(NotebookSink(), meter, clock=lambda: 0.0)
    for phase, stage in (("discovery", "schema"), ("sample", "extract"), ("rest", "extract")):
        reporter.phase(phase)
        meter.phase = phase
        reporter.fixed(f"{phase} message")
        meter.stage(stage, 100)
        reporter.start_stage(stage)
        for _ in range(100):
            paid(meter, stage, "0.001")
        reporter.end_stage()
    reporter.phase("final")
    reporter.fixed("done")
    displays = {c[2] for c in fake_ipython.calls}
    assert len(displays) == 4  # discovery, sample, rest, final (SC-004: at most 5)
    assert sum(1 for c in fake_ipython.calls if c[0] == "display") == 4


def test_choose_sink_picks_by_where_the_run_is(monkeypatch, fake_ipython):
    assert isinstance(choose_sink(progress=False), NullSink)
    assert isinstance(choose_sink(progress=True), NotebookSink)
    monkeypatch.delitem(sys.modules, "IPython")
    assert isinstance(choose_sink(progress=True), PlainSink)  # captured stderr is not a tty
    monkeypatch.setattr("sys.stderr", FakeTty())
    assert isinstance(choose_sink(progress=True), TerminalSink)


def test_ipython_is_never_imported_by_quotable(monkeypatch):
    monkeypatch.delitem(sys.modules, "IPython", raising=False)
    choose_sink(progress=True)
    assert "IPython" not in sys.modules


def test_a_loaded_ipython_that_is_not_a_kernel_gives_a_plain_sink(monkeypatch):
    module = ModuleType("IPython")
    vars(module).update(get_ipython=lambda: None)
    monkeypatch.setitem(sys.modules, "IPython", module)
    assert isinstance(choose_sink(progress=True), PlainSink)


def test_a_notebook_whose_display_fails_falls_back_to_plain_lines(fake_ipython, capsys):
    def explode(*args, **kwargs):
        raise RuntimeError

    vars(sys.modules["IPython.display"])["display"] = explode
    reporter = Reporter(NotebookSink(), RunMeter())
    reporter.phase("discovery")
    reporter.fixed("hello")
    reporter.fixed("again")
    assert capsys.readouterr().err == "hello\nagain\n"
