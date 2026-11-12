"""The public function's cost limit and progress arguments (spec 017)."""

from decimal import Decimal

import pytest

from quotable import CostLimitExceededError, extract_tables
from quotable.meter import CostModel
from quotable.pipeline import _limit
from tests.test_entrypoint import PDF, SAMPLE, Calls


@pytest.mark.parametrize("bad", [0, -1, "abc", float("nan"), float("inf"), "0", True])
def test_a_limit_that_is_not_a_number_above_zero_is_refused_before_any_request(bad):
    calls = Calls()
    with pytest.raises(ValueError, match="max_cost"):
        extract_tables(PDF, calls.model(), max_cost=bad, recheck=False, audit=False)
    assert calls.count == 0


def test_the_limit_is_kept_as_decimal_dollars():
    assert _limit(0.1) == Decimal("0.1")
    assert _limit("2.50") == Decimal("2.50")
    assert _limit(3) == Decimal(3)
    assert _limit(None) is None


def test_a_limit_with_a_model_that_has_no_known_price_is_refused_before_any_request(capsys):
    calls = Calls()
    with pytest.raises(CostLimitExceededError) as caught:
        extract_tables(PDF, calls.model(), max_cost=1, recheck=False, audit=False)
    assert caught.value.reason == "unpriced"
    assert calls.count == 0
    assert "not started" in capsys.readouterr().err


def test_the_new_arguments_change_nothing_about_the_result_or_the_cache_keys(
    tmp_path, monkeypatch, capsys
):
    monkeypatch.setattr(
        "quotable.pipeline.CostModel.for_model",
        classmethod(lambda cls, model: CostModel("fake:m", lambda i, o: Decimal(i + o) / 10**6)),
    )
    monkeypatch.setattr("quotable.llm.client._price", lambda result: Decimal("0.001"))
    plain_calls, limited_calls = Calls(), Calls()
    (plain,) = extract_tables(
        PDF, plain_calls.model(), cache_dir=tmp_path / "a", recheck=False, audit=False
    )
    (limited,) = extract_tables(
        PDF,
        limited_calls.model(),
        cache_dir=tmp_path / "b",
        max_cost=5,
        progress=False,
        recheck=False,
        audit=False,
    )
    assert [r.values for r in plain.rows()] == [r.values for r in limited.rows()]
    assert [r.values for r in limited.page_rows(1)] == SAMPLE["pages"][1]
    assert sorted(p.name for p in (tmp_path / "a").iterdir()) == sorted(
        p.name for p in (tmp_path / "b").iterdir()
    )
    assert plain_calls.count == limited_calls.count == 2


def test_progress_false_prints_nothing_and_the_limit_still_applies(tmp_path, monkeypatch, capsys):
    monkeypatch.setattr(
        "quotable.pipeline.CostModel.for_model",
        classmethod(lambda cls, model: CostModel("fake:m", lambda i, o: Decimal(i + o) / 10**6)),
    )
    monkeypatch.setattr("quotable.llm.client._price", lambda result: Decimal("0.01"))
    with pytest.raises(CostLimitExceededError) as caught:
        extract_tables(
            PDF,
            Calls().model(),
            cache_dir=tmp_path,
            max_cost="0.015",
            progress=False,
            recheck=False,
            audit=False,
        )
    assert caught.value.reason == "spent"
    captured = capsys.readouterr()
    assert captured.out == captured.err == ""


def test_the_final_message_total_equals_the_cost_log_sum(tmp_path, monkeypatch, capsys):
    import json  # noqa: PLC0415
    import re  # noqa: PLC0415
    from pathlib import Path  # noqa: PLC0415

    monkeypatch.setattr(
        "quotable.pipeline.CostModel.for_model",
        classmethod(lambda cls, model: CostModel("fake:m", lambda i, o: Decimal(i + o) / 10**6)),
    )
    monkeypatch.setattr("quotable.llm.client._price", lambda result: Decimal("0.0123"))
    extract_tables(PDF, Calls().model(), cache_dir=tmp_path, max_cost=5, recheck=False, audit=False)
    err = capsys.readouterr().err
    (total,) = re.findall(r"total cost \$([\d,.]+)", err)
    log = Path.cwd() / ".quotable" / "cost" / "requests.jsonl"
    records = [json.loads(line) for line in log.read_text().splitlines()]
    assert round(sum(Decimal(str(r["cost_usd"])) for r in records), 2) == round(Decimal(total), 2)
    assert err.count("quotable: done in ") == 1
    assert capsys.readouterr().out == ""
