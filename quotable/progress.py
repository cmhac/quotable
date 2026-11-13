"""
Messages while a run goes (spec 017): estimates, progress, cost and the final summary.

``Reporter`` turns what the run meter knows into text and hands it to one sink. A sink decides
how the text looks where it is shown: plain lines for a file or a pipe, one rewritten line in a
terminal, one block updated in place per phase in a notebook, nothing at all when progress is
off. A sink that fails is replaced by the plain one and the run carries on: a display must never
break an extraction. Messages go to standard error or the cell output, never to standard output,
and never contain a prompt, an answer, an extracted value or a file path.
"""

import importlib
import sys
import time
import uuid
from collections.abc import Callable
from decimal import Decimal
from typing import Protocol

from quotable.errors import CostLimitExceededError
from quotable.estimate import Estimate
from quotable.meter import HEADLINES, PHASES, STAGE_NAMES, RunMeter, dollars
from quotable.table import Table

REDRAWS_PER_SECOND = 4
SECONDS_A_MINUTE = 60
SECONDS_AN_HOUR = 3600
UNITS = {"schema": "windows", "extract": "pages", "audit": "pages", "recheck": "pages"}


def duration(seconds: float) -> str:
    """Return a time as "45 s", "6 min 12 s" or "1 h 02 min"."""
    whole = round(seconds)
    if whole < SECONDS_A_MINUTE:
        return f"{whole} s"
    if whole < SECONDS_AN_HOUR:
        return f"{whole // SECONDS_A_MINUTE} min {whole % SECONDS_A_MINUTE:02d} s"
    return f"{whole // SECONDS_AN_HOUR} h {whole % SECONDS_AN_HOUR // SECONDS_A_MINUTE:02d} min"


def _phase_cost(name: str, cost: Decimal, estimate: Estimate | None) -> str:
    text = f"{name} {dollars(cost)}"
    if estimate is not None and estimate.cost is not None:
        text += f" (estimated {dollars(estimate.cost)})"
    return text


class Sink(Protocol):
    """Where the text goes."""

    def phase(self, name: str) -> None:
        """Start the block of a phase (a notebook shows one block per phase)."""
        ...

    def fixed(self, text: str) -> None:
        """Show lines that stay."""
        ...

    def live(self, text: str, *, milestone: bool, final: bool = False) -> None:
        """Show the status line; a plain sink writes it only at a ``milestone``."""
        ...


class NullSink:
    """Show nothing (``progress=False``)."""

    def phase(self, name: str) -> None:
        """Ignore."""

    def fixed(self, text: str) -> None:
        """Ignore."""

    def live(self, text: str, *, milestone: bool, final: bool = False) -> None:
        """Ignore."""


class PlainSink:
    """Whole lines on standard error: no carriage returns, no escape codes."""

    def phase(self, name: str) -> None:
        """Ignore: plain lines have no blocks."""

    def fixed(self, text: str) -> None:
        """Write the lines."""
        print(text, file=sys.stderr, flush=True)

    def live(self, text: str, *, milestone: bool, final: bool = False) -> None:
        """Write the status line only when a stage starts or ends."""
        if milestone:
            print(text, file=sys.stderr, flush=True)


CLEAR_LINE = "\r\x1b[2K"


class TerminalSink:
    """A terminal: the status line is one line rewritten in place; fixed lines stay."""

    def __init__(self) -> None:
        """Start with no status line on screen."""
        self._live = False

    def phase(self, name: str) -> None:
        """Ignore: a terminal has no blocks."""

    def _clear(self) -> None:
        if self._live:
            sys.stderr.write(CLEAR_LINE)
            self._live = False

    def fixed(self, text: str) -> None:
        """Write the lines, below a status line if there is one (which is cleared first)."""
        self._clear()
        print(text, file=sys.stderr, flush=True)

    def live(self, text: str, *, milestone: bool, final: bool = False) -> None:
        """Rewrite the status line; the last state of a stage is kept as a line of its own."""
        sys.stderr.write(f"{CLEAR_LINE}{text}")
        self._live = not final
        if final:
            sys.stderr.write("\n")
        sys.stderr.flush()


class NotebookSink:
    """
    A notebook: one output block per phase, updated in place (research 1 of spec 017).

    The block holds the phase's fixed lines, the finished stages and the status line of the
    stage that is running, as ``text/plain`` through IPython's display handle.
    """

    def __init__(self) -> None:
        """Start with no block."""
        self.lines: list[str] = []
        self.live_text = ""
        self.display_id: str | None = None
        self._shown = False

    def phase(self, name: str) -> None:
        """Start a new block."""
        self.lines, self.live_text, self._shown = [], "", False
        self.display_id = f"quotable-{uuid.uuid4().hex}"

    def _push(self) -> None:
        display_module = importlib.import_module("IPython.display")  # only a kernel has it
        display, update_display = display_module.display, display_module.update_display
        if self.display_id is None:
            self.phase("")
        data = {
            "text/plain": "\n".join([*self.lines, *([self.live_text] if self.live_text else [])])
        }
        if self._shown:
            update_display(data, raw=True, display_id=self.display_id)
        else:
            display(data, raw=True, display_id=self.display_id)
            self._shown = True

    def fixed(self, text: str) -> None:
        """Add the lines to the block."""
        self.lines.extend(text.splitlines())
        self._push()

    def live(self, text: str, *, milestone: bool, final: bool = False) -> None:
        """Update the status line; a finished stage's last state becomes a line of the block."""
        if final:
            self.lines.append(text)
            self.live_text = ""
        else:
            self.live_text = text
        self._push()


def choose_sink(*, progress: bool) -> Sink:
    """Pick where the messages go: nothing, a notebook block, a terminal line or plain lines."""
    if not progress:
        return NullSink()
    ipython = sys.modules.get("IPython")  # never imported here: only a kernel has loaded it
    if ipython is not None:
        try:
            if type(ipython.get_ipython()).__name__ == "ZMQInteractiveShell":
                return NotebookSink()
        except Exception:  # noqa: BLE001, S110 (not a kernel after all)
            pass
    if sys.stderr is not None and sys.stderr.isatty():
        return TerminalSink()
    return PlainSink()


class Reporter:
    """Builds the messages of a run from the meter and shows them through a sink."""

    def __init__(
        self,
        sink: Sink,
        meter: RunMeter,
        clock: Callable[[], float] = time.monotonic,
    ) -> None:
        """Show ``meter``'s figures through ``sink``; ``clock`` is a parameter for tests."""
        self.sink = sink
        self.meter = meter
        self.clock = clock
        self.stage: str | None = None
        self.last_stage: str | None = None  # the latest stage started, for the closing message
        self.expected: str | None = None  # "about $4.12": the estimate the status line shows
        self._last_draw = float("-inf")
        self._last_text = ""
        meter.listener = self.refresh

    def _show(self, method: str, *args: object, **kwargs: object) -> None:
        try:
            getattr(self.sink, method)(*args, **kwargs)
        except Exception:  # noqa: BLE001 (a display must never break an extraction)
            self.sink = PlainSink()
            getattr(self.sink, method)(*args, **kwargs)

    # fixed messages
    def phase(self, name: str) -> None:
        """Start the block of a phase."""
        self.stage = None
        self.expected = None
        self._last_text = ""
        self._show("phase", name)

    def fixed(self, text: str) -> None:
        """Show lines that stay."""
        self._show("fixed", text)

    def closing(self, error: Exception | None) -> None:
        """Say that the run stopped, and how much it had cost."""
        if isinstance(error, CostLimitExceededError):
            body = "\n".join(f"  {line}" for line in str(error).splitlines())
            self.fixed(f"quotable: {HEADLINES[error.reason]}\n{body}")
            return
        name = STAGE_NAMES.get(self.last_stage or "", self.last_stage or "starting")
        self.fixed(f"quotable: stopped in the {name} stage after {dollars(self.meter.total)}")

    def estimate_discovery(
        self, estimate: Estimate, discovery_pages: int, limit: Decimal | None
    ) -> None:
        """Show the estimate for discovery (contracts/messages.md, section 1)."""
        lines = [
            "quotable: estimate before discovery",
            f"  {estimate.pages} pages, {estimate.requests} discovery requests of "
            f"{discovery_pages} pages ({estimate.cached} already in the cache)",
        ]
        if estimate.input_tokens is None:
            lines.append(
                f"  no estimate: {estimate.unavailable}. The limit, if set, is still checked "
                "against actual cost after every request."
            )
        elif estimate.cost is None:
            lines.append(
                f"  about {estimate.input_tokens:,} input and {estimate.output_tokens:,} output "
                f"tokens; {estimate.unavailable}: tokens are counted, dollars are not"
            )
            lines.append(f"  based on: {estimate.basis}")
        else:
            lines.append(
                f"  about {estimate.input_tokens:,} input and {estimate.output_tokens:,} output "
                f"tokens: estimated cost {dollars(estimate.cost)}"
            )
            lines.append(f"  based on: {estimate.basis}")
        if limit is not None:
            lines.append(f"  cost limit: {dollars(limit)}")
        self.fixed("\n".join(lines))

    def announce_sample(
        self, tables: int, jobs: int, picked: list[tuple[int, int]], spent: Decimal
    ) -> None:
        """Say that a sample run is next, and which pages it covers (messages.md, section 2)."""
        pages = ", ".join(f"table {index + 1} page {page}" for index, page in picked)
        self.fixed(
            "quotable: sample run\n"
            f"  discovery found {tables} tables on {jobs} table pages; "
            f"spent so far {dollars(spent)}\n"
            f"  running the full process (extraction, audit, recheck) on {len(picked)} table pages "
            f"to measure what a page costs: {pages}\n"
            "  their extraction answers are reused afterwards"
        )

    def estimate_rest(self, estimate: Estimate, limit: Decimal | None) -> None:
        """Show the estimate for the rest of the run (messages.md, section 3)."""
        lines = ["quotable: estimate for the rest of the run"]
        if estimate.expected_total is None or estimate.per_page is None:
            lines.append(f"  no estimate: {estimate.unavailable}")
        else:
            rest_cost = estimate.cost or Decimal(0)
            stages = ", ".join(
                f"{STAGE_NAMES.get(stage, stage)} {dollars(cost)}"
                for stage, cost in (estimate.by_stage or {}).items()
            )
            lines.append(
                f"  sample: {estimate.sample_pages} table pages cost "
                f"{dollars(estimate.per_page * estimate.sample_pages)} "
                f"({dollars(estimate.per_page)} a page: {stages})\n"
                f"  rest: {estimate.pages} table pages, about {dollars(rest_cost)} "
                "(counting the sample pages' audit and recheck again, in case they are not reused)"
            )
            spent = estimate.expected_total - rest_cost
            tail = (
                f"  expected total {dollars(estimate.expected_total)}; "
                f"spent so far {dollars(spent)}"
            )
            if limit is not None:
                tail += f"; cost limit {dollars(limit)}"
            lines.append(tail)
            self.expected = f"about {dollars(rest_cost)} for the rest"
        if estimate.possibly_low:
            lines.append(
                f"  note: {estimate.cached} sample requests were already in the cache, "
                "so this may be low"
            )
        self.fixed("\n".join(lines))

    def final(self, tables: list[Table], estimates: dict[str, Estimate], pdf_pages: int) -> None:
        """Show the one summary message of a finished run (messages.md, section 4)."""
        meter = self.meter
        by_phase = {
            phase: sum((t.cost for (p, _), t in meter.tallies.items() if p == phase), Decimal(0))
            for phase in PHASES
        }
        elapsed = time.perf_counter() - meter.started
        lines = [f"quotable: done in {duration(elapsed)}"]
        unpriced = sum(t.unpriced for t in meter.tallies.values())
        if unpriced:
            tokens_in = sum(t.input_tokens for t in meter.tallies.values())
            tokens_out = sum(t.output_tokens for t in meter.tallies.values())
            lines.append(
                "  total cost: no price known "
                f"({tokens_in:,} input and {tokens_out:,} output tokens)"
            )
        else:
            limit = f" (limit {dollars(meter.limit)})" if meter.limit is not None else ""
            lines.append(f"  total cost {dollars(meter.total)}{limit}")
            parts = [_phase_cost("discovery", by_phase["discovery"], estimates.get("discovery"))]
            if any(p == "sample" for p, _ in meter.tallies):
                parts.append(f"sample {dollars(by_phase['sample'])}")
            parts.append(_phase_cost("rest", by_phase["rest"], estimates.get("rest")))
            lines.append("  " + " | ".join(parts))
        new: dict[str, int] = {}
        for (_, stage), tally in meter.tallies.items():
            new[stage] = new.get(stage, 0) + tally.requests
        hits = sum(t.cache_hits for t in meter.tallies.values())
        listed = ", ".join(f"{n} {STAGE_NAMES.get(stage, stage)}" for stage, n in new.items() if n)
        lines.append(f"  new requests: {listed or 'none'}; {hits} answered from the cache")
        summary = (
            f"  {pdf_pages} pages, {len(tables)} tables, "
            f"{sum(len(t.pages) for t in tables)} table pages"
        )
        lost = sum(meter.sample_paid.values(), Decimal(0))
        if lost:
            summary += f"; {dollars(lost)} of the sample could not be reused"
        lines.append(summary)
        failed = [t for t in tables if t.failed]
        if failed:
            named = ", ".join(
                f"'{t.label or 'unnamed'}' (pages {t.problem_pages()})" for t in failed
            )
            noun = "table" if len(failed) == 1 else "tables"
            lines.append(f"  {len(failed)} {noun} failed: {named}")
        self.phase("final")
        self.fixed("\n".join(lines))

    # the status line
    def start_stage(self, stage: str, expected: str | None = None) -> None:
        """Show that ``stage`` has begun (the status line is written at once)."""
        self.stage = self.last_stage = stage
        if expected is not None:
            self.expected = expected
        self._draw(milestone=True)

    def end_stage(self) -> None:
        """Show the last state of the current stage; later changes do not redraw it."""
        self._draw(milestone=True, final=True)
        self.stage = None

    def refresh(self) -> None:
        """Redraw the status line, at most a few times a second; a finished stage always."""
        progress = self.meter.progress.get(self.stage or "")
        if progress is None:
            return
        done = progress.total is not None and progress.done >= progress.total
        if done or self.clock() - self._last_draw >= 1 / REDRAWS_PER_SECOND:
            self._draw(milestone=False)

    def line(self) -> str:
        """Return the status line of the current stage."""
        stage = self.stage or ""
        progress = self.meter.progress[stage]
        name = STAGE_NAMES.get(stage, stage)
        label = name if self.meter.phase == "rest" or stage == "schema" else f"sample {name}"
        of = "of up to" if progress.upper_bound else "of"
        total = f" {of} {progress.total}" if progress.total is not None else ""
        shown = min(progress.done, progress.total) if progress.total is not None else progress.done
        text = f"  {label:<18} {shown}{total} {UNITS.get(stage, 'pages')}"
        tally = self.meter.tally(stage)
        if tally.requests == 0 and tally.cache_hits > 0 and progress.done:
            return f"{text}   (from the cache)"
        expected = f" ({self.expected})" if self.expected else ""
        return f"{text}   {dollars(self.meter.total)} so far{expected}"

    def _draw(self, *, milestone: bool, final: bool = False) -> None:
        if self.stage is None or self.stage not in self.meter.progress:
            return
        text = self.line()
        if text == self._last_text and not milestone:
            return
        self._last_draw, self._last_text = self.clock(), text
        self._show("live", text, milestone=milestone, final=final)
