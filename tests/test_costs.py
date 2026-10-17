"""The cost record and the cost log: what is written, where, and that it never raises."""

import asyncio
import json
import shutil
import threading
from decimal import Decimal
from pathlib import Path
from types import SimpleNamespace

import pytest
from pydantic import BaseModel
from pydantic_ai.messages import ModelResponse
from pydantic_ai.models.function import FunctionModel
from pydantic_ai.models.test import TestModel
from pydantic_ai.usage import RequestUsage

from quotable import BudgetExceededError, extract_tables
from quotable._model import PydanticAIClient, _price
from quotable.costs import (
    CostLog,
    CostRecord,
    CostSummary,
    ModelTotals,
    format_report,
    summarize,
)
from quotable.llm import Request, request_key
from tests.test_entrypoint import PDF, Calls

FIELDS = [
    "v",
    "time",
    "run",
    "stage",
    "model",
    "input_tokens",
    "output_tokens",
    "cache_read_tokens",
    "cache_write_tokens",
    "cost_usd",
]


def cost_file() -> Path:
    return Path.cwd() / ".quotable" / "cost" / "requests.jsonl"


def records() -> list[dict]:
    return [json.loads(line) for line in cost_file().read_text().splitlines()]


def record(log: CostLog, stage: str = "extract", cost: Decimal | None = Decimal("0.0125")) -> None:
    log.record(
        stage,
        "openai:gpt-test",
        input_tokens=1000,
        output_tokens=200,
        cache_read_tokens=50,
        cache_write_tokens=7,
        cost=cost,
    )


def line(**changes: object) -> str:
    base: dict[str, object] = {
        "v": 1,
        "time": "2026-10-17T10:00:00+00:00",
        "run": "r1",
        "stage": "extract",
        "model": "m",
        "input_tokens": 1,
        "output_tokens": 2,
        "cache_read_tokens": 3,
        "cache_write_tokens": 4,
        "cost_usd": 0.5,
    }
    return json.dumps({**base, **changes})


# --- CostRecord ---------------------------------------------------------------------------


def test_a_record_line_round_trips():
    original = CostRecord.from_line(line())
    assert CostRecord.from_line(original.to_line()) == original
    assert original.cost_usd == 0.5
    assert CostRecord.from_line(line(cost_usd=None)).cost_usd is None


def test_a_record_line_is_one_compact_json_line_with_the_spec_keys_in_order():
    text = CostRecord.from_line(line()).to_line()
    assert text.endswith("\n")
    assert text.count("\n") == 1
    assert list(json.loads(text)) == FIELDS


@pytest.mark.parametrize(
    "bad",
    [
        "",
        "{not json",
        "[1, 2]",
        "3",
        line(v=2),
        line(v="1"),
        line(input_tokens="1"),
        line(input_tokens=True),
        line(input_tokens=1.5),
        line(cost_usd="0.5"),
        line(cost_usd=True),
        line(stage=None),
        json.dumps({"v": 1}),
    ],
)
def test_a_malformed_line_raises_value_error(bad):
    with pytest.raises(ValueError, match=r"."):
        CostRecord.from_line(bad)


def test_an_integer_cost_is_accepted():
    assert CostRecord.from_line(line(cost_usd=1)).cost_usd == 1


# --- CostLog ------------------------------------------------------------------------------


def test_nothing_is_created_until_the_first_record():
    CostLog()
    assert list(Path.cwd().iterdir()) == []


def test_a_record_has_exactly_the_spec_keys_and_the_values_passed_in():
    record(CostLog(run_id="abc"))
    (written,) = records()
    assert list(written) == FIELDS
    assert written["v"] == 1
    assert written["run"] == "abc"
    assert written["stage"] == "extract"
    assert written["model"] == "openai:gpt-test"
    assert (written["input_tokens"], written["output_tokens"]) == (1000, 200)
    assert (written["cache_read_tokens"], written["cache_write_tokens"]) == (50, 7)
    assert written["cost_usd"] == 0.0125
    assert written["time"].endswith("+00:00")


def test_the_first_record_creates_the_folder_and_a_gitignore():
    record(CostLog())
    assert (Path.cwd() / ".quotable" / ".gitignore").read_text() == "*\n"
    assert cost_file().is_file()


def test_an_existing_project_folder_gets_no_gitignore():
    (Path.cwd() / ".quotable").mkdir()
    record(CostLog())
    assert not (Path.cwd() / ".quotable" / ".gitignore").exists()


def test_a_run_shares_one_id_and_two_runs_differ():
    first, second = CostLog(), CostLog()
    record(first)
    record(first, stage="recheck")
    record(second)
    runs = [r["run"] for r in records()]
    assert runs[0] == runs[1] != runs[2]
    assert len(runs[0]) == 32


def test_an_unpriced_request_writes_null_and_keeps_the_tokens():
    record(CostLog(), cost=None)
    (written,) = records()
    assert written["cost_usd"] is None
    assert written["input_tokens"] == 1000


def test_a_record_holds_only_the_fixed_keys():
    # The only free text is the model name; prompts, answers and paths have no field to go in.
    record(CostLog())
    assert set(records()[0]) == set(FIELDS)


def test_records_append_to_what_is_already_there():
    record(CostLog())
    record(CostLog())
    assert len(records()) == 2


def test_an_unwritable_folder_warns_once_and_never_raises(capsys):
    folder = Path.cwd() / ".quotable"
    folder.mkdir()
    (folder / "cost").write_text("a file where the folder should be")
    log = CostLog()
    for _ in range(5):
        record(log)
    log.skip("the model reported no usage")
    err = capsys.readouterr().err
    assert err.count("\n") == 1
    assert "cost" in err


def test_a_skip_warns_once_and_a_later_write_failure_adds_nothing(capsys):
    log = CostLog()
    log.skip("the model reported no usage")
    log.skip("again")
    assert capsys.readouterr().err.count("\n") == 1
    assert not cost_file().exists()


def test_concurrent_tasks_leave_whole_lines_and_the_exact_count():
    log = CostLog()

    async def many() -> None:
        async def one() -> None:
            record(log)

        await asyncio.gather(*(one() for _ in range(200)))

    asyncio.run(many())
    assert len(records()) == 200


def test_two_logs_writing_from_threads_leave_whole_lines():
    first, second = CostLog(), CostLog()
    (Path.cwd() / ".quotable").mkdir()  # so the threads do not race to create the folder

    def work(log: CostLog) -> None:
        for _ in range(100):
            record(log)

    threads = [threading.Thread(target=work, args=(log,)) for log in (first, second)]
    for thread in threads:
        thread.start()
    for thread in threads:
        thread.join()
    written = records()
    assert len(written) == 200
    assert {r["run"] for r in written} == {first.run_id, second.run_id}


# --- summarize and format_report ----------------------------------------------------------


def write_lines(tmp_path: Path, *lines: str) -> Path:
    path = tmp_path / "requests.jsonl"
    path.write_text("".join(f"{text}\n" for text in lines), encoding="utf-8")
    return path


def test_the_totals_are_the_sum_of_the_stored_costs_by_model(tmp_path):
    path = write_lines(
        tmp_path,
        line(run="a", model="m1", cost_usd=0.25, input_tokens=100, output_tokens=10),
        line(run="a", model="m2", cost_usd=1.5, input_tokens=200, output_tokens=20),
        line(run="b", model="m1", cost_usd=0.25, input_tokens=300, output_tokens=30),
    )
    summary = summarize(path)
    assert (summary.runs, summary.requests, summary.unpriced, summary.skipped) == (2, 3, 0, 0)
    assert (summary.input_tokens, summary.output_tokens) == (600, 60)
    assert summary.total == Decimal("2.0")
    assert [m.model for m in summary.models] == ["m2", "m1"]  # most expensive first
    m2, m1 = summary.models
    assert (m1.requests, m1.input_tokens, m1.output_tokens, m1.cost) == (2, 400, 40, Decimal("0.5"))
    assert (m2.requests, m2.cost) == (1, Decimal("1.5"))


def test_many_small_costs_add_up_without_float_drift(tmp_path):
    path = write_lines(tmp_path, *[line(cost_usd=0.1) for _ in range(1000)])
    assert summarize(path).total == Decimal(100)  # float addition would give 99.9999999999986


def test_models_with_the_same_cost_are_ordered_by_name(tmp_path):
    path = write_lines(tmp_path, line(model="b", cost_usd=1), line(model="a", cost_usd=1))
    assert [m.model for m in summarize(path).models] == ["a", "b"]


def test_unpriced_requests_count_but_add_nothing(tmp_path):
    path = write_lines(tmp_path, line(cost_usd=None), line(cost_usd=2.0))
    summary = summarize(path)
    assert (summary.requests, summary.unpriced, summary.total) == (2, 1, Decimal("2.0"))


def test_a_missing_file_and_an_empty_file_are_both_an_empty_summary(tmp_path):
    for summary in (summarize(tmp_path / "nope.jsonl"), summarize(write_lines(tmp_path))):
        assert (summary.requests, summary.skipped, summary.models) == (0, 0, ())
        assert summary.total == 0


def test_a_damaged_line_is_counted_and_the_others_still_sum(tmp_path):
    path = write_lines(tmp_path, line(cost_usd=1.0), "{not json", "", line(v=9), line(cost_usd=2.0))
    path.write_bytes(path.read_bytes() + b"\xff\xfe broken bytes\n")
    summary = summarize(path)
    assert (summary.requests, summary.skipped, summary.total) == (2, 3, Decimal("3.0"))


def test_a_directory_in_the_way_raises_oserror(tmp_path):
    folder = tmp_path / "requests.jsonl"
    folder.mkdir()
    with pytest.raises(OSError, match="requests.jsonl"):
        summarize(folder)


def test_summarize_never_creates_anything(tmp_path):
    summarize(tmp_path / "missing" / "requests.jsonl")
    assert not (tmp_path / "missing").exists()


EXAMPLE = """\
Cost report for .quotable/cost/requests.jsonl

Runs:      7
Requests:  412 paid, 0 unpriced
Tokens:    3,204,118 in, 188,430 out
Total:     $9.87

By model            Requests      In tokens    Out tokens        Cost
openai:gpt-5.1           400      3,100,000       180,000       $9.40
openai:gpt-5-mini         12        104,118         8,430       $0.47
"""


def example_summary() -> CostSummary:
    return CostSummary(
        runs=7,
        requests=412,
        unpriced=0,
        input_tokens=3_204_118,
        output_tokens=188_430,
        total=Decimal("9.87"),
        models=(
            ModelTotals("openai:gpt-5.1", 400, 3_100_000, 180_000, Decimal("9.40")),
            ModelTotals("openai:gpt-5-mini", 12, 104_118, 8_430, Decimal("0.47")),
        ),
        skipped=0,
    )


def test_the_report_matches_the_example_in_the_spec():
    path = Path(".quotable/cost/requests.jsonl")
    assert format_report(example_summary(), path) == EXAMPLE


def test_the_example_comes_out_of_a_real_file(tmp_path):
    rows = [
        line(run=str(n), model="openai:gpt-5.1", cost_usd=1.0, input_tokens=1000) for n in range(3)
    ]
    path = write_lines(tmp_path, *rows)
    text = format_report(summarize(path), path)
    assert "Requests:  3 paid, 0 unpriced" in text
    assert "$3.00" in text


def test_a_path_inside_the_working_directory_is_shown_relative():
    inside = Path.cwd() / ".quotable" / "cost" / "requests.jsonl"
    assert format_report(example_summary(), inside).startswith(
        "Cost report for .quotable/cost/requests.jsonl\n"
    )


@pytest.mark.parametrize(
    ("total", "shown"),
    [
        ("1.00", "$1.00"),
        ("0.9999", "$0.9999"),
        ("0.99995", "$1.0000"),
        ("1234.565", "$1,234.57"),
        ("0", "$0.0000"),
    ],
)
def test_money_has_two_decimals_from_a_dollar_and_four_below(total, shown):
    summary = CostSummary(1, 1, 0, 0, 0, Decimal(total), (), 0)
    assert f"Total:     {shown}\n" in format_report(summary, Path("x"))


def test_the_rows_use_the_precision_of_the_total():
    summary = CostSummary(
        1, 2, 0, 0, 0, Decimal("0.0030"),
        (ModelTotals("m", 2, 0, 0, Decimal("0.0030")),), 0,
    )  # fmt: skip
    text = format_report(summary, Path("x"))
    assert "$0.0030" in text.splitlines()[-1]


def test_unpriced_requests_and_damaged_lines_are_reported():
    summary = CostSummary(1, 5, 2, 10, 10, Decimal("1.5"), (), 3)
    text = format_report(summary, Path("x"))
    assert "Requests:  5 paid, 2 unpriced" in text
    assert "Total leaves out 2 unpriced requests." in text
    assert text.endswith("Skipped 3 unreadable lines.\n")
    one = CostSummary(1, 5, 1, 10, 10, Decimal("1.5"), (), 1)
    assert "Total leaves out 1 unpriced request." in format_report(one, Path("x"))
    assert format_report(one, Path("x")).endswith("Skipped 1 unreadable line.\n")


def test_no_records_prints_the_one_line_message():
    empty = summarize(Path("/does/not/exist/requests.jsonl"))
    assert format_report(empty, Path(".quotable/cost/requests.jsonl")) == (
        "No cost records found in .quotable/cost/requests.jsonl. "
        "Costs are recorded when quotable sends a request to a model.\n"
    )


def test_only_damaged_lines_is_not_no_records(tmp_path):
    path = write_lines(tmp_path, "{broken")
    text = format_report(summarize(path), path)
    assert text.startswith("Cost report for ")
    assert "Requests:  0 paid, 0 unpriced" in text
    assert text.endswith("Skipped 1 unreadable line.\n")


# --- recording requests -------------------------------------------------------------------


class Answer(BaseModel):
    x: int


def make_request(stage: str = "extract") -> Request:
    return Request(stage=stage, instructions="Read it.", output_type=Answer, parts=["page"])


def test_the_request_cache_key_is_unchanged():
    # Computed with the code as it was before spec 011; a change here would orphan every cache.
    key = request_key("openai:gpt-test:{}", make_request())
    assert key == "a653881a7d523b5d03f0e828f96bf253fb454d0d5cde7e24d92690ee01004354"


def test_the_callback_is_not_part_of_the_identity():
    plain = PydanticAIClient(TestModel())
    watched = PydanticAIClient(TestModel(), on_usage=lambda *args: None)
    assert plain.identity == watched.identity


def test_the_client_reports_each_ask_once_with_the_model_usage_and_an_unpriced_cost():
    seen = []
    client = PydanticAIClient(TestModel(), on_usage=lambda *args: seen.append(args))
    request = make_request("recheck")
    asyncio.run(client.ask(request))
    ((got_request, model, usage, cost),) = seen
    assert got_request is request
    assert model == "test:test"
    assert usage.input_tokens > 0
    assert cost is None  # genai-prices does not know the "test" provider


def test_a_known_price_is_passed_on(monkeypatch):
    monkeypatch.setattr("quotable._model._price", lambda result: Decimal("0.5"))
    seen = []
    asyncio.run(
        PydanticAIClient(TestModel(), on_usage=lambda *args: seen.append(args)).ask(make_request())
    )
    assert seen[0][3] == Decimal("0.5")


def test_a_client_without_a_callback_just_answers():
    answer = asyncio.run(PydanticAIClient(TestModel()).ask(make_request()))
    assert isinstance(answer, Answer)


def test_the_cost_log_writes_what_the_client_reports(monkeypatch):
    monkeypatch.setattr("quotable._model._price", lambda result: Decimal("0.0125"))
    log = CostLog(run_id="r")
    asyncio.run(
        PydanticAIClient(TestModel(), on_usage=log.record_usage).ask(make_request("schema"))
    )
    (written,) = records()
    assert (written["run"], written["stage"], written["model"]) == ("r", "schema", "test:test")
    assert written["cost_usd"] == 0.0125
    assert written["input_tokens"] > 0
    assert written["output_tokens"] > 0


def test_an_unpriced_model_is_recorded_with_a_null_cost():
    log = CostLog()
    asyncio.run(PydanticAIClient(TestModel(), on_usage=log.record_usage).ask(make_request()))
    assert records()[0]["cost_usd"] is None


def test_a_request_that_fails_writes_nothing():
    def explode(messages, info):
        msg = "provider down"
        raise RuntimeError(msg)

    log = CostLog()
    client = PydanticAIClient(FunctionModel(explode), on_usage=log.record_usage)
    with pytest.raises(RuntimeError, match="provider down"):
        asyncio.run(client.ask(make_request()))
    assert not cost_file().exists()


def test_a_model_that_reports_no_usage_writes_nothing_and_warns_once(capsys):
    nothing = SimpleNamespace(
        input_tokens=0, output_tokens=0, cache_read_tokens=0, cache_write_tokens=0
    )
    log = CostLog()
    log.record_usage(make_request(), "m", nothing, None)
    log.record_usage(make_request(), "m", nothing, None)
    assert not cost_file().exists()
    assert capsys.readouterr().err.count("\n") == 1


def test_every_paid_request_of_a_run_is_recorded_and_cache_hits_are_not():
    extract_tables(PDF, Calls().model(), recheck=False)
    first = records()
    assert len(first) == 2  # discovery, then the one page
    assert {r["stage"] for r in first} <= {"schema", "extract", "recheck"}
    assert len({r["run"] for r in first}) == 1
    assert {r["model"] for r in first} == {"function:entrypoint-test"}

    extract_tables(PDF, Calls().model(), recheck=False)  # all cache hits
    assert len(records()) == 2


def test_clearing_the_cache_keeps_the_costs_and_the_next_run_adds_to_them():
    extract_tables(PDF, Calls().model(), recheck=False)
    shutil.rmtree(Path.cwd() / ".quotable" / "cache")
    extract_tables(PDF, Calls().model(), recheck=False)
    written = records()
    assert len(written) == 4
    assert len({r["run"] for r in written}) == 2


def test_a_named_cache_dir_holds_no_costs(tmp_path):
    named = tmp_path / "named"
    extract_tables(PDF, Calls().model(), cache_dir=named, recheck=False)
    assert len(records()) == 2
    assert not any("cost" in p.name or p.suffix == ".jsonl" for p in named.rglob("*"))


def test_an_unwritable_cost_folder_does_not_stop_the_extraction(capsys):
    project = Path.cwd() / ".quotable"
    project.mkdir()
    (project / "cost").write_text("in the way")
    (table,) = extract_tables(PDF, Calls().model(), recheck=False)
    assert table.columns
    warnings = [x for x in capsys.readouterr().err.splitlines() if "cost" in x]
    assert len(warnings) == 1


def test_a_refused_request_over_the_cap_writes_no_record():
    with pytest.raises(BudgetExceededError):
        extract_tables(PDF, Calls().model(), max_requests=1, recheck=False)
    assert len(records()) == 1


def test_the_price_of_a_known_model_comes_from_genai_prices():
    response = ModelResponse(
        parts=[],
        usage=RequestUsage(input_tokens=1_000_000, output_tokens=0),
        model_name="gpt-4o",
        provider_name="openai",
    )
    price = _price(SimpleNamespace(response=response))  # ty: ignore[invalid-argument-type]
    assert isinstance(price, Decimal)
    assert price > 0
