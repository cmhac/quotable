"""The cost record and the cost log: what is written, where, and that it never raises."""

import asyncio
import json
import threading
from decimal import Decimal
from pathlib import Path

import pytest

from quotable.costs import CostLog, CostRecord

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
