from __future__ import annotations

import json
from pathlib import Path
from typing import Any

import pytest

from runner_cli.ddw_analyze import main


def _write_jsonl(path: Path, rows: list[dict[str, Any]]) -> str:
    text = "\n".join(json.dumps(r) for r in rows) + "\n"
    path.write_text(text, encoding="utf-8")
    return str(path)


def _overfitting_rows() -> list[dict[str, Any]]:
    val = [(1, 0.50), (2, 0.55), (3, 0.58), (4, 0.59), (5, 0.59), (6, 0.59), (7, 0.59), (8, 0.59)]
    train = [(1, 0.52), (2, 0.60), (3, 0.68), (4, 0.78), (5, 0.84), (6, 0.88), (7, 0.91), (8, 0.93)]
    rows: list[dict[str, Any]] = []
    for x, y in val:
        rows.append({"series_name": "val", "x_kind": "epoch", "x_value": x, "y_value": y})
    for x, y in train:
        rows.append({"series_name": "train", "x_kind": "epoch", "x_value": x, "y_value": y})
    return rows


def _learning_rows() -> list[dict[str, Any]]:
    rows: list[dict[str, Any]] = []
    for i, y in enumerate([0.30, 0.45, 0.55, 0.62, 0.66, 0.69, 0.71, 0.72, 0.73, 0.735], start=1):
        rows.append({"series_name": "val", "x_kind": "epoch", "x_value": i, "y_value": y})
    return rows


def test_cli_text_output_on_overfitting_curve(tmp_path: Path, capsys: pytest.CaptureFixture[str]) -> None:
    metrics = _write_jsonl(tmp_path / "m.jsonl", _overfitting_rows())
    rc = main(["--metrics-jsonl", metrics, "--metric-name", "accuracy", "--format", "text"])
    out = capsys.readouterr().out
    assert "overfitting_divergence" in out
    assert "Possible checks:" in out
    assert rc == 1


def test_cli_json_output_schema_valid(tmp_path: Path, capsys: pytest.CaptureFixture[str]) -> None:
    metrics = _write_jsonl(tmp_path / "m.jsonl", _overfitting_rows())
    main(["--metrics-jsonl", metrics, "--metric-name", "accuracy", "--format", "json"])
    out = capsys.readouterr().out
    data = json.loads(out)
    assert "run_id" in data
    assert "metric_name" in data and data["metric_name"] == "accuracy"
    assert "findings" in data and isinstance(data["findings"], list)
    assert "assumptions" in data and isinstance(data["assumptions"], list)


def test_cli_exit_code_1_on_warn_or_critical(tmp_path: Path) -> None:
    metrics = _write_jsonl(tmp_path / "m.jsonl", _overfitting_rows())
    rc = main(["--metrics-jsonl", metrics, "--metric-name", "accuracy", "--format", "text"])
    assert rc == 1


def test_cli_text_uses_possible_checks_not_try(tmp_path: Path, capsys: pytest.CaptureFixture[str]) -> None:
    metrics = _write_jsonl(tmp_path / "m.jsonl", _overfitting_rows())
    main(["--metrics-jsonl", metrics, "--metric-name", "accuracy", "--format", "text"])
    out = capsys.readouterr().out
    forbidden = ["Try:", "Recommendation:", "You should", "root cause", "the reason is"]
    for token in forbidden:
        assert token not in out
    assert "Possible checks:" in out
    assert "Check whether" in out
