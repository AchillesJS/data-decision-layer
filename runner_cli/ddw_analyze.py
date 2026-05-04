"""DDW single-run diagnostics — local CLI.

Reads a JSONL file of metric points and prints a v1 diagnostic report.
Runs entirely locally; does not contact a DDW server.

Usage:
    python -m runner_cli.ddw_analyze \\
        --metrics-jsonl ./logs/metrics.jsonl \\
        --metric-name accuracy \\
        --format text

Exit code:
    0 — no warn/critical findings
    1 — at least one warn or critical finding
"""

from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path
from typing import Any

from analytics_engine.diagnostics_schemas import DiagnosisReport, DiagnosticsInput
from analytics_engine.diagnostics_v1 import diagnose


def _read_jsonl(path: str) -> list[dict[str, Any]]:
    rows: list[dict[str, Any]] = []
    text = Path(path).read_text(encoding="utf-8")
    for line in text.splitlines():
        stripped = line.strip()
        if not stripped:
            continue
        rows.append(json.loads(stripped))
    return rows


def _build_input(rows: list[dict[str, Any]], metric_name: str, run_id: str) -> DiagnosticsInput:
    by_series: dict[str, list[tuple[float, float]]] = {}
    for row in rows:
        series = str(row.get("series_name", ""))
        try:
            x = float(row["x_value"])
            y = float(row["y_value"])
        except (KeyError, TypeError, ValueError):
            continue
        by_series.setdefault(series, []).append((x, y))

    val = sorted(by_series.get("val", []), key=lambda t: t[0])
    train = sorted(by_series.get("train", []), key=lambda t: t[0])

    return DiagnosticsInput(
        run_id=run_id,
        metric_name=metric_name,
        val_series=val,
        train_series=train,
    )


def _format_text(report: DiagnosisReport) -> str:
    lines: list[str] = [
        "DDW diagnostics report",
        f"  run_id: {report.run_id}",
        f"  metric_name: {report.metric_name}",
        f"  n_val_points: {report.n_val_points}",
        f"  n_train_points: {report.n_train_points}",
        "",
        f"Findings ({len(report.findings)}):",
    ]
    if not report.findings:
        lines.append("  (none)")
    for f in report.findings:
        lines.append(f"  [{f.severity.upper()}] {f.kind}: {f.title}")
        lines.append(f"    {f.description}")
        if f.epoch_range is not None:
            lines.append(f"    range: {f.epoch_range.start} -> {f.epoch_range.end}")
        if f.evidence:
            evidence = ", ".join(f"{k}={v}" for k, v in f.evidence.items())
            lines.append(f"    evidence: {evidence}")
        if f.suggested_checks:
            lines.append("    Possible checks:")
            for c in f.suggested_checks:
                lines.append(f"      - {c}")
    lines.append("")
    lines.append("Assumptions:")
    for a in report.assumptions:
        lines.append(f"  - {a}")
    return "\n".join(lines)


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(
        prog="ddw_analyze",
        description="DDW single-run diagnostics (local, no server).",
    )
    parser.add_argument("--metrics-jsonl", required=True, help="path to a JSONL file of metric points")
    parser.add_argument("--metric-name", required=True, help="quality-score metric name (higher is better)")
    parser.add_argument("--run-id", default="local", help="run identifier to embed in the report")
    parser.add_argument(
        "--format",
        choices=("text", "json"),
        default="text",
        help="output format (default: text)",
    )
    args = parser.parse_args(argv)

    rows = _read_jsonl(args.metrics_jsonl)
    inp = _build_input(rows, args.metric_name, args.run_id)
    report = diagnose(inp)

    if args.format == "json":
        sys.stdout.write(json.dumps(report.model_dump(), ensure_ascii=False, indent=2))
        sys.stdout.write("\n")
    else:
        sys.stdout.write(_format_text(report))
        sys.stdout.write("\n")

    severities = {f.severity for f in report.findings}
    return 1 if ("critical" in severities or "warn" in severities) else 0


if __name__ == "__main__":  # pragma: no cover
    sys.exit(main())
