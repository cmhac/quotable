"""
The run meter (spec 017): what a run has cost so far, and the cost limit.

One ``RunMeter`` belongs to one ``extract_tables_async`` call and is used on the event-loop thread
only, so it takes no locks. ``PydanticAIClient`` reports every paid request to it (``add``);
``CachedClient`` asks it before starting a request and after storing an answer (``check``), which
is how a limit stops the run: nothing is started once the meter has tripped. Money is ``Decimal``
dollars. The messages for the limit errors are built here too, so the text is in one place.
"""

import asyncio
import time
from collections import defaultdict
from collections.abc import Callable
from dataclasses import dataclass
from decimal import ROUND_CEILING, Decimal
from typing import Any

from pydantic_ai.exceptions import UserError
from pydantic_ai.messages import ModelResponse
from pydantic_ai.models import Model, infer_model
from pydantic_ai.usage import RequestUsage

from quotable.errors import CostLimitExceededError
from quotable.llm.client import model_name

STAGE_NAMES = {
    "schema": "discovery",
    "extract": "extraction",
    "audit": "audit",
    "recheck": "recheck",
    "extras": "extra-field",
}
PHASES = ("discovery", "sample", "rest")
MIN_PAIR_PLACES = 4
MAX_PAIR_PLACES = 6


# --- money ------------------------------------------------------------------------------------
def dollars(amount: Decimal) -> str:
    """Return ``amount`` as dollars: 2 decimals from $1 up, 4 below."""
    places = 2 if abs(amount) >= 1 else MIN_PAIR_PLACES
    return f"${amount:,.{places}f}"


def exact(amount: Decimal) -> str:
    """Return ``amount`` with 4 decimals, for a limit someone is asked to set."""
    return f"${amount:,.{MIN_PAIR_PLACES}f}"


def dollars_pair(a: Decimal, b: Decimal) -> tuple[str, str]:
    """Return two amounts with enough decimals (4 to 6) that they do not print the same."""
    for places in range(MIN_PAIR_PLACES, MAX_PAIR_PLACES + 1):
        first, second = f"{a:,.{places}f}", f"{b:,.{places}f}"
        if first != second:
            break
    return f"${first}", f"${second}"


def round_up(amount: Decimal, places: int = MIN_PAIR_PLACES) -> Decimal:
    """Round up (never down) to ``places`` decimals, so an amount raised by it is enough."""
    return amount.quantize(Decimal(1).scaleb(-places), rounding=ROUND_CEILING)


# --- the cost model ---------------------------------------------------------------------------
def _no_image_rule(width: int, height: int, detail: str) -> int | None:  # noqa: ARG001
    return None


@dataclass
class CostModel:
    """What the estimates need to know about the model: its price and its image-token rule."""

    name: str  # provider:model-name, as the cost log writes it
    price: Callable[[int, int], Decimal | None]  # input and output tokens -> dollars
    image_tokens: Callable[[int, int, str], int | None] = _no_image_rule
    why_unpriced: str = ""
    image_basis: str = ""  # a sentence naming the image-token rule, for the estimate message

    @classmethod
    def for_model(cls, model: Model | str) -> "CostModel":
        """
        Build the cost model of ``model``; the price comes from pydantic-ai's own pricing.

        The price of a token count is worked out the way the price of an answer is
        (``ModelResponse.cost``), so estimates and the cost log use one source. A model that
        cannot be built (for example no API key in the environment) or has no known price
        gets a price of ``None`` and the cause in ``why_unpriced``.
        """
        from quotable.estimate import image_rule  # noqa: PLC0415 (estimate imports this module)

        name = model_name(model)
        try:
            built = model if isinstance(model, Model) else infer_model(model)
        except (UserError, ImportError, ValueError) as err:
            return cls(name, lambda _i, _o: None, why_unpriced=str(err).splitlines()[0])

        def price(input_tokens: int, output_tokens: int) -> Decimal | None:
            response = ModelResponse(
                parts=[],
                usage=RequestUsage(input_tokens=input_tokens, output_tokens=output_tokens),
                model_name=built.model_name,
                provider_name=built.system,
            )
            try:
                return response.cost().total_price
            except (LookupError, AssertionError):  # genai-prices does not know the model
                return None

        why = "" if price(1000, 100) is not None else "no price is known for this model"
        rule, basis = image_rule(built.system, built.model_name)
        return cls(name, price, rule, why, basis)


# --- the meter --------------------------------------------------------------------------------
@dataclass
class Tally:
    """What one stage of one phase has used."""

    requests: int = 0
    cache_hits: int = 0
    input_tokens: int = 0
    output_tokens: int = 0
    cost: Decimal = Decimal(0)
    unpriced: int = 0


@dataclass
class Progress:
    """How far a stage is: ``total`` is exact unless ``upper_bound`` (audit and recheck)."""

    done: int = 0
    total: int | None = None
    upper_bound: bool = False


class RunMeter:
    """Adds up the cost of a run and stops it when the limit is passed."""

    def __init__(self, limit: Decimal | None = None) -> None:
        """Start a meter with an optional cost ``limit`` in dollars."""
        self.limit = limit
        self.total = Decimal(0)
        self.phase = "discovery"
        self.tallies: dict[tuple[str, str], Tally] = defaultdict(Tally)
        self.in_flight = 0
        self.stopped: str | None = None  # None | "spent" | "unmetered"
        self.stop_stage: str | None = None
        self.stop_in_flight = 0
        self.progress: dict[str, Progress] = {}
        self.estimate_total: Decimal | None = None  # the expected cost of the whole run, once known
        self.sample_paid: dict[str, Decimal] = {}
        self.sample_reused = Decimal(0)
        self.started = time.perf_counter()
        self.listener: Callable[[], None] | None = None
        self._costs: dict[int, Decimal | None] = {}
        self._idle = asyncio.Event()
        self._idle.set()

    # reporting what happened
    def tally(self, stage: str, phase: str | None = None) -> Tally:
        """Return the tally of ``stage`` in ``phase`` (the current one by default)."""
        return self.tallies[phase or self.phase, stage]

    def add(self, request: Any, usage: Any, cost: Decimal | None) -> None:  # noqa: ANN401
        """Record one paid request (the ``on_usage`` callback of ``PydanticAIClient``)."""
        stage = request.stage
        tally = self.tally(stage)
        inputs, outputs = (getattr(usage, n, 0) or 0 for n in ("input_tokens", "output_tokens"))
        tally.requests += 1
        tally.input_tokens += inputs
        tally.output_tokens += outputs
        self._costs[id(request)] = cost
        if cost is None:
            tally.unpriced += 1
        else:
            tally.cost += cost
            self.total += cost
        if self.limit is not None and self.stopped is None:
            if cost is None or not (inputs or outputs):
                self._stop("unmetered", stage)
            elif self.total > self.limit:
                self._stop("spent", stage)
        self._changed()

    def _stop(self, reason: str, stage: str) -> None:
        self.stopped = reason
        self.stop_stage = stage
        self.stop_in_flight = max(self.in_flight - 1, 0)  # the others, not the request itself

    def begin(self) -> None:
        """Mark a paid request as about to be sent."""
        self.in_flight += 1
        self._idle.clear()

    def end(self) -> None:
        """Mark a paid request as finished (answered or failed)."""
        self.in_flight -= 1
        if self.in_flight == 0:
            self._idle.set()

    async def settled(self) -> None:
        """Wait until no paid request is in flight."""
        await self._idle.wait()

    def check(self) -> None:
        """Raise the limit error if the meter has tripped."""
        if self.stopped is not None:
            raise self.error()

    def paid(self, key: str, request: Any) -> None:  # noqa: ANN401
        """Note that a paid answer is stored under ``key``; the sample remembers what it cost."""
        cost = self._costs.pop(id(request), None)
        if self.phase == "sample" and cost is not None:
            self.sample_paid[key] = cost
        self.tick(request.stage)

    def hit(self, key: str, stage: str) -> None:
        """Note that an answer came from the cache."""
        self.tally(stage).cache_hits += 1
        if self.phase == "rest" and key in self.sample_paid:
            self.sample_reused += self.sample_paid.pop(key)
        self.tick(stage)

    def stage(self, name: str, total: int | None, *, upper_bound: bool = False) -> None:
        """Start tracking a stage with ``total`` units to do."""
        self.progress[name] = Progress(0, total, upper_bound)
        self._changed()

    def tick(self, name: str) -> None:
        """One more unit of ``name`` is done."""
        if name in self.progress:
            self.progress[name].done += 1
        self._changed()

    def _changed(self) -> None:
        if self.listener is not None:
            self.listener()

    # building the errors
    def error(self) -> CostLimitExceededError:
        """Return the error for the recorded stop, with the numbers as they are now."""
        assert self.limit is not None
        stage = self.stop_stage
        progress = self.progress.get(stage or "")
        return make_error(
            self.stopped or "spent",
            limit=self.limit,
            spent=self.total,
            estimate=self.estimate_total,
            stage=stage,
            done=progress.done if progress else None,
            total=progress.total if progress else None,
            in_flight=self.stop_in_flight,
        )


# --- the messages -----------------------------------------------------------------------------
HEADLINES = {
    "spent": "stopped, the cost limit was passed",
    "estimate": "stopped before spending more, the estimate is over the cost limit",
    "unpriced": "not started",
    "unmetered": "stopped, a request reported no token usage",
}
CACHED = "Everything already answered is in the cache."
RERUN = "Run again with the higher limit and it is not paid for twice."


def make_error(  # noqa: PLR0913
    reason: str,
    *,
    limit: Decimal,
    spent: Decimal,
    estimate: Decimal | None = None,
    stage: str | None = None,
    done: int | None = None,
    total: int | None = None,
    in_flight: int = 0,
    what: str = "the whole run",
    model: str = "",
    cause: str = "",
) -> CostLimitExceededError:
    """Build the limit error of ``reason`` with its figures and message (contracts/messages.md)."""
    over = max(spent - limit, Decimal(0)) if reason == "spent" else Decimal(0)
    if reason == "spent":
        raise_by = round_up(over)
    elif reason == "estimate" and estimate is not None:
        raise_by = round_up(max(estimate - limit, Decimal(0)))
    else:
        raise_by = Decimal(0)
    finish_by = round_up(estimate - limit) if estimate is not None and estimate > limit else None
    if reason in ("spent", "unmetered"):
        lines = _lines(
            reason, limit, spent, over, raise_by, estimate, finish_by, stage, done, total, in_flight
        )
    else:
        lines = _early_lines(reason, limit, spent, estimate, raise_by, what, model, cause)
    return CostLimitExceededError(
        "\n".join(lines),
        reason=reason,
        limit=limit,
        spent=spent,
        over=over,
        raise_by=raise_by,
        estimate=estimate,
        finish_by=finish_by,
        stage=stage,
        done=done,
        total=total,
        in_flight=in_flight,
    )


def _where(stage: str | None, done: int | None, total: int | None, in_flight: int) -> str:
    text = f"It stopped in the {STAGE_NAMES.get(stage or '', stage or 'run')} stage"
    if done is not None:
        of = "of up to" if stage in ("audit", "recheck") else "of"
        text += f" ({done} {of} {total})" if total else f" ({done} done)"
    if in_flight:
        text += f"; {in_flight} requests were in flight and are included"
    return text + "."


def _lines(  # noqa: PLR0913, PLR0917
    reason: str,
    limit: Decimal,
    spent: Decimal,
    over: Decimal,
    raise_by: Decimal,
    estimate: Decimal | None,
    finish_by: Decimal | None,
    stage: str | None,
    done: int | None,
    total: int | None,
    in_flight: int,
) -> list[str]:
    if reason == "unmetered":
        name = STAGE_NAMES.get(stage or "", stage or "a")
        return [
            f"A request in the {name} stage came back without usage figures, so its cost cannot "
            f"be checked against max_cost={limit:f}. Spent so far, without it: {dollars(spent)}.",
            CACHED,
        ]
    shown_spent, shown_limit = dollars_pair(spent, limit)
    lines = [
        f"The run has cost {shown_spent} and the limit is {shown_limit}: over by {dollars(over)}.",
        _where(stage, done, total, in_flight),
        f"To get past this point, raise max_cost by at least {dollars(raise_by)} "
        f"(to {exact(limit + raise_by)}).",
    ]
    if estimate is not None and finish_by is not None:
        lines.append(
            f"The whole run is estimated at {dollars(estimate)}: "
            f"max_cost={round_up(estimate, 2):f} would finish it."
        )
    return [*lines, f"{CACHED} {RERUN}"]


def _early_lines(  # noqa: PLR0913, PLR0917
    reason: str,
    limit: Decimal,
    spent: Decimal,
    estimate: Decimal | None,
    raise_by: Decimal,
    what: str,
    model: str,
    cause: str,
) -> list[str]:
    if reason == "unpriced":
        because = f" ({cause})" if cause else ""
        return [
            f'max_cost is set but the price of "{model}" is not known{because}, so the cost '
            "cannot be added up and the limit could not be kept. Nothing was requested.",
            "Remove max_cost to run without a limit.",
        ]
    assert estimate is not None
    shown_estimate, shown_limit = dollars_pair(estimate, limit)
    before = f"Spent so far: {dollars(spent)}." if spent > 0 else "Nothing has been requested."
    return [
        f"The estimate for {what} is {shown_estimate} and max_cost is {shown_limit}. {before}",
        f"Raise max_cost by about {dollars(raise_by)} (to {exact(limit + raise_by)}) to run it."
        + (" Nothing more has been requested." if spent > 0 else ""),
        CACHED if spent > 0 else "Estimates for the later steps come after discovery.",
    ]
