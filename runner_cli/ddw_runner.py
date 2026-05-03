from __future__ import annotations

import argparse
import json
import subprocess
import sys
import time
from pathlib import Path
from typing import Any
from urllib.error import HTTPError
from urllib.request import Request, urlopen


def _request(
    method: str,
    url: str,
    *,
    tenant: str,
    body: dict[str, Any] | None = None,
    headers: dict[str, str] | None = None,
) -> tuple[int, dict[str, Any] | None]:
    payload = None if body is None else json.dumps(body).encode("utf-8")
    req_headers = {"X-Tenant-Id": tenant, "Content-Type": "application/json"}
    req_headers.update(headers or {})
    req = Request(url, data=payload, headers=req_headers, method=method)
    try:
        with urlopen(req, timeout=30) as resp:  # noqa: S310 - local/admin CLI target is user supplied.
            data = resp.read().decode("utf-8")
            return resp.status, (json.loads(data) if data else None)
    except HTTPError as exc:
        data = exc.read().decode("utf-8")
        raise RuntimeError(f"HTTP {exc.code}: {data}") from exc


def _register(args: argparse.Namespace) -> int:
    tags = [tag.strip() for tag in args.tags.split(",") if tag.strip()]
    _, data = _request(
        "POST",
        f"{args.url.rstrip('/')}/api/v1/runners/register",
        tenant=args.tenant,
        body={"name": args.name, "tags": tags},
    )
    print(json.dumps(data, indent=2, ensure_ascii=False))
    return 0


def _read_jsonl_metrics(path: str | None) -> list[dict[str, Any]]:
    if not path:
        return [{"series_name": "val", "x_kind": "epoch", "x_value": 1, "y_value": 0.0}]
    points: list[dict[str, Any]] = []
    for line in Path(path).read_text(encoding="utf-8").splitlines():
        if not line.strip():
            continue
        row = json.loads(line)
        points.append(
            {
                "series_name": str(row.get("series_name", "val")),
                "x_kind": str(row.get("x_kind", "epoch")),
                "x_value": float(row["x_value"]),
                "y_value": float(row["y_value"]),
            }
        )
    return points


def _build_run_report(job: dict[str, Any], exit_code: int, metrics_jsonl: str | None) -> dict[str, Any]:
    metric_points = _read_jsonl_metrics(metrics_jsonl)
    final = metric_points[-1]["y_value"] if metric_points else 0.0
    status = "SUCCEEDED" if exit_code == 0 else "FAILED"
    return {
        "schema_version": 1,
        "external_run_id": f"job:{job['id']}:attempt:1",
        "run": {
            "model_tag": "local_process",
            "dataset_version": None,
            "dataset_size": 1,
            "seed": None,
            "budget_kind": "steps",
            "budget_value": max(1, len(metric_points)),
            "metric_name": "score",
            "split": "val",
            "metric_final": final,
            "status": status,
            "config_hash": None,
            "git_commit": None,
        },
        "metric_points": metric_points,
    }


def _append_log(args: argparse.Namespace, job_id: str, lease_token: str, seq: int, stream: str, chunk: str) -> None:
    _request(
        "POST",
        f"{args.url.rstrip('/')}/api/v1/jobs/{job_id}/logs:append",
        tenant=args.tenant,
        headers={
            "X-Runner-Id": args.runner_id,
            "X-Runner-Token": args.runner_token,
            "X-Lease-Token": lease_token,
        },
        body={"chunks": [{"seq": seq, "stream": stream, "chunk": chunk}]},
    )


def _execute_job(args: argparse.Namespace, claim: dict[str, Any]) -> None:
    job = claim["job"]
    lease_token = claim["lease_token"]
    seq = 0
    proc = subprocess.Popen(
        job["command"],
        cwd=job.get("workdir") or None,
        shell=True,
        stdout=subprocess.PIPE,
        stderr=subprocess.STDOUT,
        text=True,
        env=None,
    )
    assert proc.stdout is not None
    for line in proc.stdout:
        _append_log(args, job["id"], lease_token, seq, "stdout", line)
        seq += 1
    exit_code = proc.wait(timeout=job.get("timeout_sec"))
    report = _build_run_report(job, exit_code, args.metrics_jsonl)
    _request(
        "POST",
        f"{args.url.rstrip('/')}/api/v1/jobs/{job['id']}/complete",
        tenant=args.tenant,
        headers={
            "X-Runner-Id": args.runner_id,
            "X-Runner-Token": args.runner_token,
            "X-Lease-Token": lease_token,
        },
        body={
            "status": "SUCCEEDED" if exit_code == 0 else "FAILED",
            "exit_code": exit_code,
            "error_message": None if exit_code == 0 else "local_process failed",
            "run_report": report,
        },
    )


def _start(args: argparse.Namespace) -> int:
    headers = {"X-Runner-Id": args.runner_id, "X-Runner-Token": args.runner_token}
    while True:
        _request(
            "POST",
            f"{args.url.rstrip('/')}/api/v1/runners/{args.runner_id}/heartbeat",
            tenant=args.tenant,
            headers={"X-Runner-Token": args.runner_token},
        )
        status_code, claim = _request(
            "POST",
            f"{args.url.rstrip('/')}/api/v1/jobs/claim",
            tenant=args.tenant,
            headers=headers,
            body={"tags_filter": None},
        )
        if status_code == 204 or claim is None:
            time.sleep(args.poll_interval)
            continue
        _execute_job(args, claim)


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(prog="ddw-runner")
    sub = parser.add_subparsers(dest="cmd", required=True)

    reg = sub.add_parser("register")
    reg.add_argument("--url", required=True)
    reg.add_argument("--tenant", required=True)
    reg.add_argument("--name", default=None)
    reg.add_argument("--tags", default="")
    reg.set_defaults(func=_register)

    start = sub.add_parser("start")
    start.add_argument("--url", required=True)
    start.add_argument("--tenant", required=True)
    start.add_argument("--runner-id", required=True)
    start.add_argument("--runner-token", required=True)
    start.add_argument("--poll-interval", type=float, default=2.0)
    start.add_argument("--metrics-jsonl", default=None)
    start.set_defaults(func=_start)

    args = parser.parse_args(argv)
    return int(args.func(args))


if __name__ == "__main__":
    raise SystemExit(main(sys.argv[1:]))
