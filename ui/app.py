"""DDW UI v0.2 (Streamlit) — Guided workflow, Notes toggle, Debug JSON only.

Constraints:
- UI talks ONLY to the HTTP API (no DB access).
- Every API request MUST send X-Tenant-Id.
- Expected errors: 404 / 409 / 422 only.
- Notes/Vault are optional and hidden by default (Notes mode toggle).

Run:
  uvicorn api.main:app --reload
  streamlit run ui/app.py
"""

from __future__ import annotations

from dataclasses import dataclass
from datetime import date, datetime, time
from pathlib import Path
from typing import Any

import requests  # type: ignore[import-untyped]
import streamlit as st  # type: ignore[import-not-found]

DEFAULT_BASE_URL = "http://127.0.0.1:8000"
DEFAULT_TENANT_ID = "tenantA"
TIMEOUT_S = 15

# Keep in sync with docs/state_machine.md (UI contract).
ALLOWED_TRANSITIONS: dict[str, list[tuple[str, str]]] = {
    "hypothesis": [
        ("draft", "active"),
        ("active", "testing"),
        ("testing", "supported"),
        ("testing", "refuted"),
    ],
    "action": [
        ("draft", "proposed"),
        ("proposed", "approved"),
        ("approved", "in_progress"),
        ("in_progress", "done"),
        ("draft", "cancelled"),
        ("proposed", "cancelled"),
        ("approved", "cancelled"),
        ("in_progress", "cancelled"),
    ],
    # Potentials: API v1 has no /transition, only /archive.
}


# ----------------------------
# Helpers (safe UI)
# ----------------------------

def _norm_base_url(url: str) -> str:
    url = (url or "").strip()
    if not url:
        return DEFAULT_BASE_URL
    return url[:-1] if url.endswith("/") else url


def _now_iso() -> str:
    return datetime.now().strftime("%Y-%m-%d %H:%M:%S")


def _split_lines(text: str) -> list[str]:
    items: list[str] = []
    for line in (text or "").splitlines():
        s = line.strip()
        if s:
            items.append(s)
    return items


def _parse_kv_lines(text: str) -> dict[str, str]:
    out: dict[str, str] = {}
    for line in _split_lines(text):
        if "=" not in line:
            continue
        k, v = line.split("=", 1)
        k = k.strip()
        v = v.strip()
        if k and v:
            out[k] = v
    return out


def _safe_json(resp: requests.Response) -> Any:
    try:
        return resp.json()
    except Exception:
        return None


def _show_api_error(resp: requests.Response) -> None:
    status = resp.status_code
    payload = _safe_json(resp)

    detail: Any = None
    if isinstance(payload, dict):
        detail = payload.get("detail")

    if status in (404, 409):
        msg = detail if isinstance(detail, str) else (resp.text or "Request failed")
        st.error(f"{status}: {msg}")
        return

    if status == 422:
        st.warning("422: validation / missing tenant header")
        if isinstance(detail, list):
            rows = []
            for e in detail:
                if isinstance(e, dict):
                    rows.append(
                        {
                            "loc": " / ".join(str(x) for x in e.get("loc", [])),
                            "msg": e.get("msg"),
                            "type": e.get("type"),
                        }
                    )
                else:
                    rows.append({"loc": "", "msg": str(e), "type": ""})
            st.dataframe(rows, use_container_width=True)
        elif isinstance(detail, str):
            st.write(detail)
        else:
            st.write(resp.text)
        return

    st.error(f"Unexpected HTTP {status}. Response: {resp.text[:500]}")


def _escape_html(text: str) -> str:
    return (
        (text or "")
        .replace("&", "&amp;")
        .replace("<", "&lt;")
        .replace(">", "&gt;")
        .replace('"', "&quot;")
        .replace("'", "&#39;")
    )


def _wow_card(title: str, lines: list[str], *, footer: str | None = None) -> None:
    st.markdown(
        """
        <style>
        .ddw-card {border: 1px solid rgba(255,255,255,0.12); border-radius: 16px; padding: 16px;}
        .ddw-title {font-size: 18px; font-weight: 700; margin-bottom: 8px;}
        .ddw-line {font-size: 14px; opacity: 0.95; margin: 4px 0;}
        .ddw-footer {font-size: 12px; opacity: 0.65; margin-top: 10px;}
        </style>
        """,
        unsafe_allow_html=True,
    )
    body = "".join([f'<div class="ddw-line">{_escape_html(line)}</div>' for line in lines])
    foot = f'<div class="ddw-footer">{_escape_html(footer)}</div>' if footer else ""
    st.markdown(
        f'<div class="ddw-card"><div class="ddw-title">{_escape_html(title)}</div>{body}{foot}</div>',
        unsafe_allow_html=True,
    )


def _md(text: str) -> None:
    st.markdown(text or "—")


def _next_statuses(entity: str, current: str) -> list[str]:
    curr = (current or "").strip()
    pairs = ALLOWED_TRANSITIONS.get(entity, [])
    return [to for (frm, to) in pairs if frm == curr]


def _dt_iso(d: date, t: time) -> str:
    return datetime.combine(d, t).isoformat(timespec="seconds")


# ----------------------------
# Local Vault (Notes mode)
# ----------------------------

def _vault_root() -> Path:
    return Path(__file__).resolve().parent / ".vault"


def _note_path(tenant_id: str, entity: str, entity_id: str) -> Path:
    safe_tenant = (tenant_id or "tenant").strip() or "tenant"
    safe_entity = entity.strip() or "entity"
    safe_id = (entity_id or "unknown").strip() or "unknown"
    return _vault_root() / safe_tenant / safe_entity / f"{safe_id}.md"


def _load_note(tenant_id: str, entity: str, entity_id: str) -> str:
    p = _note_path(tenant_id, entity, entity_id)
    if not p.exists():
        return ""
    try:
        return p.read_text(encoding="utf-8")
    except Exception:
        return ""


def _save_note(tenant_id: str, entity: str, entity_id: str, content: str) -> bool:
    p = _note_path(tenant_id, entity, entity_id)
    try:
        p.parent.mkdir(parents=True, exist_ok=True)
        p.write_text(content or "", encoding="utf-8")
        return True
    except Exception:
        return False


def _entity_to_note_template(entity: str, obj: dict[str, Any]) -> str:
    if entity == "hypothesis":
        return (
            f"# Hypothesis\n\n"
            f"**id:** `{obj.get('id','')}`\n\n"
            f"## Snapshot\n"
            f"- status: **{obj.get('status','')}**\n"
            f"- uncertainty: **{obj.get('uncertainty','')}**\n"
            f"- tags: {', '.join(obj.get('tags') or []) or '—'}\n\n"
            f"## Statement\n"
            f"{obj.get('statement') or ''}\n\n"
            f"## Arguments\n"
            + "\n".join([f"- {x}" for x in (obj.get("arguments") or [])])
            + "\n\n"
            "## Alternatives\n"
            + "\n".join([f"- {x}" for x in (obj.get("alternatives") or [])])
            + "\n\n"
            "## Evidence (error_ids)\n"
            + "\n".join([f"- `{x}`" for x in (obj.get("evidence_error_ids") or [])])
            + "\n"
        )
    if entity == "action":
        cost = obj.get("cost") or {}
        cost_line = ""
        if isinstance(cost, dict):
            bits = []
            if cost.get("time_hours") is not None:
                bits.append(f"{cost.get('time_hours')}h")
            if cost.get("money") is not None:
                bits.append(f"${cost.get('money')}")
            if bits:
                cost_line = ", ".join(bits)
        return (
            f"# Action\n\n"
            f"**id:** `{obj.get('id','')}`\n\n"
            f"## Snapshot\n"
            f"- status: **{obj.get('status','')}**\n"
            f"- risk_if_false: **{obj.get('risk_if_false','')}**\n"
            f"- hypothesis_id: `{obj.get('hypothesis_id','')}`\n"
            f"- cost: {cost_line or '—'}\n\n"
            f"## Description\n"
            f"{obj.get('description') or ''}\n\n"
            f"## Expected artifacts\n"
            + "\n".join([f"- {x}" for x in (obj.get("expected_artifacts") or [])])
            + "\n"
        )
    if entity == "potential":
        ubr = obj.get("upper_bound_range")
        ubr_s = "—"
        if isinstance(ubr, list) and len(ubr) == 2:
            ubr_s = f"({ubr[0]}, {ubr[1]})"
        return (
            f"# Potential\n\n"
            f"**id:** `{obj.get('id','')}`\n\n"
            f"## Snapshot\n"
            f"- status: **{obj.get('status','')}**\n"
            f"- metric: **{obj.get('metric_name','')}**\n"
            f"- current: **{obj.get('current','')}**\n"
            f"- upper_bound_range: **{ubr_s}**\n"
            f"- confidence: **{obj.get('confidence','')}**\n"
            f"- sample_size: **{obj.get('sample_size','')}**\n\n"
            f"## Limiting factors\n"
            + "\n".join([f"- {x}" for x in (obj.get("limiting_factors") or [])])
            + "\n\n"
            "## Assumptions\n"
            + "\n".join([f"- {x}" for x in (obj.get("assumptions") or [])])
            + "\n\n"
            "## Evidence (error_ids)\n"
            + "\n".join([f"- `{x}`" for x in (obj.get("evidence_error_ids") or [])])
            + "\n\n"
            f"## Notes\n"
            f"{obj.get('notes') or ''}\n"
        )
    return "# Note\n\n"


def _render_note_panel(api: ApiClient, entity: str, obj: dict[str, Any]) -> None:
    tenant_id = (api.tenant_id or "").strip()
    entity_id = obj.get("id", "")

    st.caption(f"Vault: `{_vault_root()}`")
    key = f"note::{tenant_id}::{entity}::{entity_id}"
    if key not in st.session_state:
        st.session_state[key] = _load_note(tenant_id, entity, entity_id)

    tab_edit, tab_preview = st.tabs(["Edit", "Preview"])
    with tab_edit:
        st.session_state[key] = st.text_area(
            "Markdown note (local)",
            value=st.session_state[key],
            height=260,
            placeholder="Write notes here…",
        )
        c1, c2, c3 = st.columns([1, 1, 2])
        with c1:
            if st.button("Save", key=f"save_{key}"):
                ok = _save_note(tenant_id, entity, entity_id, st.session_state[key])
                st.success("Saved") if ok else st.error("Save failed")
        with c2:
            if st.button("Template", key=f"tpl_{key}"):
                st.session_state[key] = _entity_to_note_template(entity, obj)
        with c3:
            st.caption(f"File: `{_note_path(tenant_id, entity, entity_id)}`")

    with tab_preview:
        _md(st.session_state[key] or "—")


# ----------------------------
# API Client
# ----------------------------

@dataclass
class ApiClient:
    base_url: str
    tenant_id: str

    def _headers(self) -> dict[str, str]:
        return {
            "X-Tenant-Id": self.tenant_id,
            "Content-Type": "application/json",
        }

    def request(
        self,
        method: str,
        path: str,
        *,
        params: dict[str, Any] | None = None,
        json: dict[str, Any] | None = None,
        allow_error_ui: bool = True,
    ) -> tuple[bool, Any | None, requests.Response | None]:
        url = f"{self.base_url}{path}"
        try:
            resp = requests.request(
                method=method,
                url=url,
                headers=self._headers(),
                params=params,
                json=json,
                timeout=TIMEOUT_S,
            )
        except requests.RequestException:
            if allow_error_ui:
                st.error("API is unreachable. Check BASE_URL and that uvicorn is running.")
                st.caption(f"{_now_iso()} — {method} {url}")
            return False, None, None

        if resp.status_code in (200, 201):
            return True, _safe_json(resp), resp
        if resp.status_code == 204:
            return True, None, resp

        if allow_error_ui:
            _show_api_error(resp)
        return False, None, resp

    def get_list(
        self,
        path: str,
        *,
        params: dict[str, Any] | None = None,
    ) -> tuple[bool, list[dict[str, Any]], int | None]:
        ok, data, resp = self.request("GET", path, params=params)
        if not ok or resp is None:
            return False, [], None

        total = resp.headers.get("X-Total-Count")
        try:
            total_i = int(total) if total is not None else None
        except Exception:
            total_i = None

        if isinstance(data, list):
            return True, [d for d in data if isinstance(d, dict)], total_i
        return True, [], total_i


# ----------------------------
# Capability / endpoint detection (optional)
# ----------------------------

def _openapi_spec(base_url: str) -> dict[str, Any] | None:
    key = f"openapi::{base_url}"
    if key in st.session_state:
        cached = st.session_state[key]
        return cached if isinstance(cached, dict) else None

    url = f"{base_url}/openapi.json"
    try:
        resp = requests.get(url, timeout=TIMEOUT_S)
        if resp.status_code != 200:
            st.session_state[key] = None
            return None
        spec = resp.json()
        parsed = spec if isinstance(spec, dict) else None
        st.session_state[key] = parsed
        return parsed
    except Exception:
        st.session_state[key] = None
        return None


def _supports(spec: dict[str, Any] | None, method: str, path: str) -> bool:
    if not spec:
        return False
    paths = spec.get("paths") if isinstance(spec, dict) else None
    if not isinstance(paths, dict):
        return False
    p = paths.get(path)
    if not isinstance(p, dict):
        return False
    return method.lower() in p


# ----------------------------
# App State
# ----------------------------

def _init_state() -> None:
    st.session_state.setdefault("base_url", DEFAULT_BASE_URL)
    st.session_state.setdefault("tenant_id", DEFAULT_TENANT_ID)
    st.session_state.setdefault("page", "Workflow")

    st.session_state.setdefault("notes_mode", False)

    st.session_state.setdefault("selected_hypothesis_id", "")
    st.session_state.setdefault("selected_action_id", "")
    st.session_state.setdefault("selected_potential_id", "")

    # Workflow state
    st.session_state.setdefault("wf_step", 1)
    st.session_state.setdefault("wf_hypothesis_id", "")
    st.session_state.setdefault("wf_action_ids", [])
    st.session_state.setdefault("wf_potential_id", "")
    st.session_state.setdefault("wf_last_decision_id", "")

    st.session_state.setdefault("quick_query", "")
    st.session_state.setdefault("refresh_token", 0)


def _client() -> ApiClient:
    return ApiClient(
        base_url=_norm_base_url(st.session_state["base_url"]),
        tenant_id=(st.session_state["tenant_id"] or "").strip(),
    )


# ----------------------------
# Quick Switcher
# ----------------------------

def _quick_switcher(api: ApiClient) -> None:
    st.sidebar.subheader("Quick Switcher")
    q = st.sidebar.text_input("Search (title/name/metric)", key="quick_query", placeholder="type to filter…")

    ok_h, hyps, _ = api.get_list("/api/v1/hypotheses", params={"limit": 50, "offset": 0})
    ok_a, acts, _ = api.get_list("/api/v1/actions", params={"limit": 50, "offset": 0})
    ok_p, pots, _ = api.get_list("/api/v1/potentials", params={"limit": 50, "offset": 0})

    if not (ok_h and ok_a and ok_p):
        st.sidebar.caption("Quick switcher unavailable (API error).")
        return

    ql = (q or "").strip().lower()

    def match(s: str) -> bool:
        return ql in (s or "").lower()

    items: list[tuple[str, str, str]] = []
    for h in hyps:
        label = f"H · {h.get('title','(no title)')} · {h.get('status','')} · {h.get('id','')}"
        if not ql or match(h.get("title", "")) or match(h.get("id", "")) or match(h.get("status", "")):
            items.append((label, "hypothesis", h.get("id", "")))
    for a in acts:
        label = f"A · {a.get('name','(no name)')} · {a.get('status','')} · {a.get('id','')}"
        if not ql or match(a.get("name", "")) or match(a.get("id", "")) or match(a.get("status", "")):
            items.append((label, "action", a.get("id", "")))
    for p in pots:
        label = f"P · {p.get('metric_name','(metric)')} · {p.get('status','')} · {p.get('id','')}"
        if not ql or match(p.get("metric_name", "")) or match(p.get("id", "")) or match(p.get("status", "")):
            items.append((label, "potential", p.get("id", "")))

    items = items[:120]
    pick = st.sidebar.selectbox("Jump to…", [""] + [x[0] for x in items], index=0)
    if pick:
        entity = None
        entity_id = None
        for label, e, i in items:
            if label == pick:
                entity, entity_id = e, i
                break
        if entity and entity_id:
            if entity == "hypothesis":
                st.session_state["page"] = "Hypotheses → Actions"
                st.session_state["selected_hypothesis_id"] = entity_id
            elif entity == "action":
                st.session_state["page"] = "Hypotheses → Actions"
                st.session_state["selected_action_id"] = entity_id
            else:
                st.session_state["page"] = "Potentials"
                st.session_state["selected_potential_id"] = entity_id
            st.session_state["refresh_token"] += 1


# ----------------------------
# Pages
# ----------------------------

def _dashboard_page(api: ApiClient) -> None:
    st.header("Dashboard")

    def count(path: str, *, status: str | None = None) -> int | None:
        params: dict[str, Any] = {"limit": 1, "offset": 0}
        if status is not None:
            params["status"] = status
        ok, _rows, total = api.get_list(path, params=params)
        return total if ok else None

    total_h = count("/api/v1/hypotheses")
    arch_h = count("/api/v1/hypotheses", status="archived")
    open_h = (total_h - arch_h) if (total_h is not None and arch_h is not None) else None

    total_a = count("/api/v1/actions")
    arch_a = count("/api/v1/actions", status="archived")
    open_a = (total_a - arch_a) if (total_a is not None and arch_a is not None) else None

    total_p = count("/api/v1/potentials")
    arch_p = count("/api/v1/potentials", status="archived")
    open_p = (total_p - arch_p) if (total_p is not None and arch_p is not None) else None

    ok_d, decisions, total_d = api.get_list("/api/v1/decision-records", params={"limit": 10, "offset": 0})
    last10 = len(decisions) if ok_d else None

    c1, c2, c3, c4 = st.columns(4)
    c1.metric("Hypotheses (≠ archived)", open_h if open_h is not None else "—")
    c2.metric("Actions (≠ archived)", open_a if open_a is not None else "—")
    c3.metric("Potentials (≠ archived)", open_p if open_p is not None else "—")
    c4.metric("Decisions (last 10)", last10 if last10 is not None else "—")

    _wow_card(
        "DDW Pulse",
        [
            f"Open hypotheses: {open_h if open_h is not None else '—'}",
            f"Open actions: {open_a if open_a is not None else '—'}",
            f"Open potentials: {open_p if open_p is not None else '—'}",
            f"Total decision records: {total_d if total_d is not None else '—'}",
        ],
        footer="Counts via X-Total-Count + status='archived'.",
    )

    st.subheader("Latest DecisionRecords")
    if not ok_d:
        return
    if not decisions:
        st.info("No decision records yet.")
        return

    st.dataframe(
        [
            {
                "id": r.get("id"),
                "created_at": r.get("created_at"),
                "decision": r.get("decision"),
                "confidence": r.get("confidence"),
                "made_by": r.get("made_by"),
                "actions": len(r.get("action_ids") or []),
                "hypotheses": len(r.get("hypothesis_ids") or []),
                "errors": len(r.get("error_ids") or []),
            }
            for r in decisions
        ],
        use_container_width=True,
    )

    ids = [r.get("id") for r in decisions if r.get("id")]
    pick = st.selectbox("Open decision record", [""] + ids, index=0)
    if pick:
        ok, data, _ = api.request("GET", f"/api/v1/decision-records/{pick}")
        if ok and isinstance(data, dict):
            _wow_card(
                f"DecisionRecord · {pick}",
                [
                    f"Decision: {data.get('decision','')}",
                    f"Confidence: {data.get('confidence','')}",
                    f"Made by: {data.get('made_by','')}",
                    f"Actions: {len(data.get('action_ids') or [])}",
                    f"Hypotheses: {len(data.get('hypothesis_ids') or [])}",
                    f"Errors: {len(data.get('error_ids') or [])}",
                ],
                footer="Decision record snapshot.",
            )
            tabs = st.tabs(["Details", "Debug JSON"])
            with tabs[0]:
                st.subheader("Rationale")
                _md(data.get("rationale") or "—")
                st.subheader("Notes")
                _md(data.get("notes") or "—")
            with tabs[1]:
                st.json(data)


def _hypotheses_actions_page(api: ApiClient, spec: dict[str, Any] | None) -> None:
    st.header("Hypotheses → Actions")

    left, right = st.columns([1.15, 1.35], gap="large")

    with left:
        st.subheader("Hypotheses")

        status_filter = st.selectbox(
            "Status",
            ["(all)", "draft", "active", "testing", "supported", "refuted", "archived"],
            index=1,
        )
        search = st.text_input("Search title/id", placeholder="type…")
        params: dict[str, Any] = {"limit": 50, "offset": 0}
        if status_filter != "(all)":
            params["status"] = status_filter

        ok, hyps, _ = api.get_list("/api/v1/hypotheses", params=params)
        if not ok:
            return

        s = (search or "").strip().lower()
        if s:
            hyps = [
                h
                for h in hyps
                if s in (h.get("title", "") or "").lower() or s in (h.get("id", "") or "").lower()
            ]

        if not hyps:
            st.info("No hypotheses for this filter/search.")
        else:
            st.dataframe(
                [
                    {
                        "id": h.get("id"),
                        "status": h.get("status"),
                        "title": h.get("title"),
                        "uncertainty": h.get("uncertainty"),
                    }
                    for h in hyps
                ],
                use_container_width=True,
                height=280,
            )

        options = [""] + [
            f"{h.get('title','(no title)')} · {h.get('status','')} · {h.get('id','')}" for h in hyps
        ]
        default_idx = 0
        sid = st.session_state.get("selected_hypothesis_id") or ""
        if sid:
            for i, h in enumerate(hyps, start=1):
                if h.get("id") == sid:
                    default_idx = i
                    break

        pick = st.selectbox("Open hypothesis", options, index=default_idx)
        if pick:
            st.session_state["selected_hypothesis_id"] = pick.split(" · ")[-1].strip()
        else:
            st.session_state["selected_hypothesis_id"] = ""

        with st.expander("Create hypothesis", expanded=False):
            with st.form("create_hypothesis_form"):
                title = st.text_input("Title", placeholder="Short & concrete")
                statement = st.text_area("Statement (markdown ok)", height=120)
                status = st.selectbox("Initial status", ["draft", "active", "testing"], index=0)
                uncertainty = st.slider("Uncertainty (0..1)", 0.0, 1.0, 0.6, 0.05)
                tags = st.text_input("Tags (comma-separated)", placeholder="mvp, test")
                arguments = st.text_area("Arguments (one per line)", height=90)
                alternatives = st.text_area("Alternatives (one per line)", height=90)
                evidence_error_ids = st.text_area("Evidence Error IDs (one per line)", height=90)

                st.caption("Optional scope (ErrorScope)")
                scope_y_true = st.text_input("scope.y_true")
                scope_y_pred = st.text_input("scope.y_pred")
                cmin = st.number_input("scope.confidence_min", 0.0, 1.0, 0.0, 0.01)
                cmax = st.number_input("scope.confidence_max", 0.0, 1.0, 1.0, 0.01)
                min_count = st.number_input("scope.min_count", min_value=1, value=1, step=1)
                filters_kv = st.text_area("scope.filters (key=value per line)", height=90)

                submitted = st.form_submit_button("Create")

            if submitted:
                payload: dict[str, Any] = {
                    "title": title,
                    "statement": statement,
                    "status": status,
                    "uncertainty": float(uncertainty),
                    "tags": [t.strip() for t in (tags or "").split(",") if t.strip()],
                    "arguments": _split_lines(arguments),
                    "alternatives": _split_lines(alternatives),
                    "evidence_error_ids": _split_lines(evidence_error_ids),
                }

                scope_filters = _parse_kv_lines(filters_kv)
                scope: dict[str, Any] = {
                    "filters": scope_filters or None,
                    "y_true": scope_y_true.strip() or None,
                    "y_pred": scope_y_pred.strip() or None,
                    "confidence_min": float(cmin) if cmin > 0.0 else None,
                    "confidence_max": float(cmax) if cmax < 1.0 else None,
                    "min_count": int(min_count),
                }
                if any(v is not None for k, v in scope.items() if k != "min_count") or scope.get("min_count", 1) != 1:
                    payload["scope"] = scope

                okc, data, _ = api.request("POST", "/api/v1/hypotheses", json=payload)
                if okc and isinstance(data, dict):
                    st.success("Hypothesis created")
                    st.session_state["selected_hypothesis_id"] = data.get("id", "")
                    st.session_state["refresh_token"] += 1

    with right:
        hid = st.session_state.get("selected_hypothesis_id") or ""
        if not hid:
            st.info("Select a hypothesis on the left.")
            return

        ok, hyp, _ = api.request("GET", f"/api/v1/hypotheses/{hid}")
        if not ok or not isinstance(hyp, dict):
            return

        _wow_card(
            f"Hypothesis · {hyp.get('title','')}",
            [
                f"Status: {hyp.get('status','—')}",
                f"Uncertainty: {hyp.get('uncertainty','—')}",
                f"Evidence errors: {len(hyp.get('evidence_error_ids') or [])}",
                f"Tags: {', '.join(hyp.get('tags') or []) or '—'}",
            ],
            footer="Snapshot.",
        )

        tabs_labels = ["Fields"]
        if st.session_state.get("notes_mode"):
            tabs_labels = ["Notes", "Fields"]
        tabs_labels.append("Debug JSON")
        tabs = st.tabs(tabs_labels)

        idx = 0
        if st.session_state.get("notes_mode"):
            with tabs[idx]:
                _render_note_panel(api, "hypothesis", hyp)
            idx += 1

        with tabs[idx]:
            st.subheader("Statement")
            _md(hyp.get("statement") or "—")
            c1, c2 = st.columns(2)
            with c1:
                st.subheader("Arguments")
                _md("\n".join([f"- {a}" for a in (hyp.get("arguments") or [])]) or "—")
            with c2:
                st.subheader("Alternatives")
                _md("\n".join([f"- {a}" for a in (hyp.get("alternatives") or [])]) or "—")

            st.subheader("Transitions")
            nexts = _next_statuses("hypothesis", hyp.get("status", ""))
            if not nexts:
                st.caption("No forward transitions from this status.")
            else:
                cols = st.columns(min(len(nexts), 4))
                for i, to_status in enumerate(nexts):
                    with cols[i % len(cols)]:
                        if st.button(f"→ {to_status}", key=f"hyp_tr_{hid}_{to_status}"):
                            ok2, _d2, _ = api.request(
                                "POST",
                                f"/api/v1/hypotheses/{hid}/transition",
                                json={"to_status": to_status},
                            )
                            if ok2:
                                st.success(f"Transitioned to {to_status}")
                                st.session_state["refresh_token"] += 1

            if st.button("Archive hypothesis", type="secondary"):
                ok3, _d3, _ = api.request("POST", f"/api/v1/hypotheses/{hid}/archive")
                if ok3:
                    st.success("Archived")
                    st.session_state["refresh_token"] += 1

        with tabs[-1]:
            st.json(hyp)

        st.divider()

        st.subheader("Actions linked")
        ok_a, acts, _ = api.get_list(
            "/api/v1/actions", params={"limit": 50, "offset": 0, "hypothesis_id": hid}
        )
        if not ok_a:
            return

        if not acts:
            st.info("No actions linked yet.")
        else:
            st.dataframe(
                [
                    {
                        "id": a.get("id"),
                        "status": a.get("status"),
                        "risk": a.get("risk_if_false"),
                        "name": a.get("name"),
                    }
                    for a in acts
                ],
                use_container_width=True,
                height=220,
            )

        aopts = [""] + [
            f"{a.get('status','')} · {a.get('name','(no name)')} · {a.get('id','')}" for a in acts
        ]
        apick = st.selectbox("Open action", aopts, index=0)
        if apick:
            st.session_state["selected_action_id"] = apick.split(" · ")[-1].strip()

        aid = st.session_state.get("selected_action_id") or ""
        if aid:
            okd, act, _ = api.request("GET", f"/api/v1/actions/{aid}")
            if okd and isinstance(act, dict):
                cost = act.get("cost") or {}
                cost_bits = []
                if isinstance(cost, dict):
                    if cost.get("time_hours") is not None:
                        cost_bits.append(f"{cost.get('time_hours')}h")
                    if cost.get("money") is not None:
                        cost_bits.append(f"${cost.get('money')}")

                _wow_card(
                    f"Action · {act.get('name','')}",
                    [
                        f"Status: {act.get('status','')}",
                        f"Risk if false: {act.get('risk_if_false','')}",
                        f"Cost: {', '.join(cost_bits) or '—'}",
                        f"Expected artifacts: {', '.join(act.get('expected_artifacts') or []) or '—'}",
                    ],
                    footer="Snapshot.",
                )

                tabs_labels = ["Fields"]
                if st.session_state.get("notes_mode"):
                    tabs_labels = ["Notes", "Fields"]
                tabs_labels.append("Debug JSON")
                t = st.tabs(tabs_labels)

                j = 0
                if st.session_state.get("notes_mode"):
                    with t[j]:
                        _render_note_panel(api, "action", act)
                    j += 1

                with t[j]:
                    st.subheader("Description")
                    _md(act.get("description") or "—")

                    st.subheader("Transitions")

                    # DONE/CANCELLED require completed_at / cancel_reason.
                    # If backend doesn't provide minimal endpoints to set those, we HIDE those transitions.
                    has_complete_ep = _supports(spec, "post", "/api/v1/actions/{id}/complete") or _supports(
                        spec, "post", "/api/v1/actions/{action_id}/complete"
                    )
                    has_cancel_ep = _supports(spec, "post", "/api/v1/actions/{id}/cancel") or _supports(
                        spec, "post", "/api/v1/actions/{action_id}/cancel"
                    )

                    curr = act.get("status", "")
                    nexts_a = _next_statuses("action", curr)

                    filtered: list[str] = []
                    for to_s in nexts_a:
                        if to_s == "done" and not has_complete_ep:
                            continue
                        if to_s == "cancelled" and not has_cancel_ep:
                            continue
                        filtered.append(to_s)

                    if not filtered:
                        st.caption("No available transitions (or DONE/CANCELLED require extra fields).")
                    else:
                        cols = st.columns(min(len(filtered), 4))
                        for i, to_s in enumerate(filtered):
                            with cols[i % len(cols)]:
                                if to_s not in ("done", "cancelled"):
                                    if st.button(f"→ {to_s}", key=f"act_tr_{aid}_{to_s}"):
                                        okx, _dx, _ = api.request(
                                            "POST",
                                            f"/api/v1/actions/{aid}/transition",
                                            json={"to_status": to_s},
                                        )
                                        if okx:
                                            st.success(f"Transitioned to {to_s}")
                                            st.session_state["refresh_token"] += 1

                    # Minimal modal-like UX via expander blocks (Streamlit-compatible)
                    if has_complete_ep and "done" in nexts_a:
                        with st.expander("Mark as DONE (requires completed_at)", expanded=False):
                            d = st.date_input("completed_at date", value=date.today(), key=f"done_d_{aid}")
                            t_ = st.time_input("completed_at time", value=time(12, 0), key=f"done_t_{aid}")
                            if st.button("Set completed_at + transition to DONE", key=f"done_go_{aid}"):
                                payload = {"completed_at": _dt_iso(d, t_)}
                                ok1, _d1, _ = api.request("POST", f"/api/v1/actions/{aid}/complete", json=payload)
                                if ok1:
                                    ok2, _d2, _ = api.request(
                                        "POST", f"/api/v1/actions/{aid}/transition", json={"to_status": "done"}
                                    )
                                    if ok2:
                                        st.success("Action marked DONE")
                                        st.session_state["refresh_token"] += 1

                    if has_cancel_ep and "cancelled" in nexts_a:
                        with st.expander("Cancel action (requires cancel_reason)", expanded=False):
                            reason = st.text_area(
                                "cancel_reason", key=f"cancel_r_{aid}", height=80, placeholder="Why cancelled?"
                            )
                            if st.button("Set cancel_reason + transition to CANCELLED", key=f"cancel_go_{aid}"):
                                payload = {"cancel_reason": (reason or "").strip()}
                                ok1, _d1, _ = api.request("POST", f"/api/v1/actions/{aid}/cancel", json=payload)
                                if ok1:
                                    ok2, _d2, _ = api.request(
                                        "POST",
                                        f"/api/v1/actions/{aid}/transition",
                                        json={"to_status": "cancelled"},
                                    )
                                    if ok2:
                                        st.success("Action cancelled")
                                        st.session_state["refresh_token"] += 1

                    if st.button("Archive action", key=f"act_arch_{aid}", type="secondary"):
                        okx, _dx, _ = api.request("POST", f"/api/v1/actions/{aid}/archive")
                        if okx:
                            st.success("Archived")
                            st.session_state["refresh_token"] += 1

                with t[-1]:
                    st.json(act)

        st.divider()
        st.subheader("Create action")
        with st.form("create_action_form"):
            status_a = st.selectbox("Initial status", ["draft", "proposed", "approved", "in_progress"], index=0)
            name = st.text_input("Name", placeholder="Relabel slice")
            description = st.text_area("Description (markdown ok)", height=120)
            risk = st.selectbox("Risk if false", ["low", "medium", "high", "critical"], index=0)

            st.caption("Cost (at least one of time_hours or money)")
            c1, c2, c3 = st.columns(3)
            with c1:
                time_hours = st.number_input("time_hours", min_value=0.0, value=1.0, step=0.5)
            with c2:
                money = st.number_input("money", min_value=0.0, value=0.0, step=10.0)
            with c3:
                cost_note = st.text_input("note", placeholder="optional")

            expected = st.text_area("Expected artifacts (one per line)", height=90)

            submitted = st.form_submit_button("Create action")

        if submitted:
            cost_payload: dict[str, Any] = {"note": cost_note.strip() or None}
            if time_hours > 0.0:
                cost_payload["time_hours"] = float(time_hours)
            if money > 0.0:
                cost_payload["money"] = float(money)

            payload = {
                "status": status_a,
                "hypothesis_id": hid,
                "name": name,
                "description": description,
                "risk_if_false": risk,
                "cost": cost_payload,
                "expected_artifacts": _split_lines(expected),
            }
            okc, data, _ = api.request("POST", "/api/v1/actions", json=payload)
            if okc and isinstance(data, dict):
                st.success("Action created")
                st.session_state["selected_action_id"] = data.get("id", "")
                st.session_state["refresh_token"] += 1


def _potentials_page(api: ApiClient) -> None:
    st.header("Potentials")

    left, right = st.columns([1.15, 1.35], gap="large")

    with left:
        st.subheader("List")
        status_filter = st.selectbox("Status", ["(all)", "draft", "estimated", "stale", "archived"], index=0)
        search = st.text_input("Search metric/id", placeholder="type…")

        params: dict[str, Any] = {"limit": 50, "offset": 0}
        if status_filter != "(all)":
            params["status"] = status_filter

        ok, pots, _ = api.get_list("/api/v1/potentials", params=params)
        if not ok:
            return

        s = (search or "").strip().lower()
        if s:
            pots = [
                p
                for p in pots
                if s in (p.get("metric_name", "") or "").lower() or s in (p.get("id", "") or "").lower()
            ]

        if not pots:
            st.info("No potentials for this filter/search.")
        else:
            rows = []
            for p in pots:
                ubr = p.get("upper_bound_range")
                ubr_s = "—"
                if isinstance(ubr, list) and len(ubr) == 2:
                    ubr_s = f"({ubr[0]}, {ubr[1]})"
                rows.append(
                    {
                        "id": p.get("id"),
                        "status": p.get("status"),
                        "metric": p.get("metric_name"),
                        "current": p.get("current"),
                        "upper_bound": ubr_s,
                        "confidence": p.get("confidence"),
                    }
                )
            st.dataframe(rows, use_container_width=True, height=280)

        options = [""] + [
            f"{p.get('metric_name','(metric)')} · {p.get('status','')} · {p.get('id','')}" for p in pots
        ]
        pick = st.selectbox("Open potential", options, index=0)
        if pick:
            st.session_state["selected_potential_id"] = pick.split(" · ")[-1].strip()
        else:
            st.session_state["selected_potential_id"] = ""

        with st.expander("Create potential", expanded=False):
            with st.form("create_potential_form"):
                metric_name = st.text_input("Metric name", placeholder="accuracy / F1 / CER")
                current = st.slider("Current (0..1)", 0.0, 1.0, 0.70, 0.01)
                status = st.selectbox("Status", ["draft", "estimated", "stale"], index=0)

                st.caption("Upper bound range (0..1)")
                lo = st.slider("low", 0.0, 1.0, min(0.85, max(0.0, current)), 0.01)
                hi_default = max(float(current), 0.92)
                hi = st.slider("high", 0.0, 1.0, float(min(hi_default, 1.0)), 0.01)

                confidence = st.slider("Confidence (0..1)", 0.0, 1.0, 0.40, 0.05)
                sample_size = st.number_input("Sample size", min_value=0, value=0, step=10)

                limiting = st.text_area("Limiting factors (one per line)", height=100)
                assumptions = st.text_area("Assumptions (one per line)", height=100)
                evidence = st.text_area("Evidence Error IDs (one per line)", height=90)
                notes = st.text_area("Notes (markdown ok)", height=90)

                if status == "estimated":
                    st.info("Estimated обычно требует sample_size>0 + limiting_factors + assumptions + upper_bound_range.")
                submitted = st.form_submit_button("Create")

            if submitted:
                payload: dict[str, Any] = {
                    "metric_name": metric_name,
                    "current": float(current),
                    "status": status,
                    "upper_bound_range": [float(lo), float(hi)],
                    "confidence": float(confidence),
                    "sample_size": int(sample_size),
                    "limiting_factors": _split_lines(limiting),
                    "assumptions": _split_lines(assumptions),
                    "evidence_error_ids": _split_lines(evidence),
                    "notes": notes.strip() or None,
                }

                okc, data, _ = api.request("POST", "/api/v1/potentials", json=payload)
                if okc and isinstance(data, dict):
                    st.success("Potential created")
                    st.session_state["selected_potential_id"] = data.get("id", "")
                    st.session_state["refresh_token"] += 1

    with right:
        pid = st.session_state.get("selected_potential_id") or ""
        if not pid:
            st.info("Select a potential on the left.")
            return

        ok, pot, _ = api.request("GET", f"/api/v1/potentials/{pid}")
        if not ok or not isinstance(pot, dict):
            return

        ubr = pot.get("upper_bound_range")
        ubr_s = "—"
        if isinstance(ubr, list) and len(ubr) == 2:
            ubr_s = f"({ubr[0]}, {ubr[1]})"

        _wow_card(
            f"Potential · {pot.get('metric_name','')}",
            [
                f"Status: {pot.get('status','')}",
                f"Current: {pot.get('current')}",
                f"Upper bound range: {ubr_s}",
                f"Confidence: {pot.get('confidence')}",
                f"Evidence refs: {len(pot.get('evidence_error_ids') or [])}",
            ],
            footer="Upper bound estimate (honest).",
        )

        tabs_labels = ["Fields"]
        if st.session_state.get("notes_mode"):
            tabs_labels = ["Notes", "Fields"]
        tabs_labels.append("Debug JSON")
        tabs = st.tabs(tabs_labels)

        k = 0
        if st.session_state.get("notes_mode"):
            with tabs[k]:
                _render_note_panel(api, "potential", pot)
            k += 1

        with tabs[k]:
            st.subheader("Limiting factors")
            _md("\n".join([f"- {x}" for x in (pot.get("limiting_factors") or [])]) or "—")
            st.subheader("Assumptions")
            _md("\n".join([f"- {x}" for x in (pot.get("assumptions") or [])]) or "—")
            st.subheader("Evidence")
            _md("\n".join([f"- `{x}`" for x in (pot.get("evidence_error_ids") or [])]) or "—")
            st.subheader("Notes")
            _md(pot.get("notes") or "—")

            if st.button("Archive potential", type="secondary"):
                ok2, _d2, _ = api.request("POST", f"/api/v1/potentials/{pid}/archive")
                if ok2:
                    st.success("Archived")
                    st.session_state["refresh_token"] += 1

        with tabs[-1]:
            st.json(pot)


def _workflow_page(api: ApiClient) -> None:
    st.header("Workflow")

    step = int(st.session_state.get("wf_step", 1))
    step = 1 if step < 1 else 4 if step > 4 else step
    st.session_state["wf_step"] = step
    st.progress((step - 1) / 3)

    labels = {
        1: "1) Pick hypothesis",
        2: "2) Pick / create actions",
        3: "3) Create decision record",
        4: "4) (Optional) Potential link",
    }

    cols = st.columns(4)
    for i in range(1, 5):
        with cols[i - 1]:
            st.caption(labels[i] + (" ✅" if i < step else ""))

    st.divider()

    nav = st.radio(
        "Step",
        [1, 2, 3, 4],
        index=step - 1,
        format_func=lambda x: labels[x],
        horizontal=True,
    )
    st.session_state["wf_step"] = int(nav)
    step = int(nav)

    if step == 1:
        st.subheader("Step 1 — Choose hypothesis")

        status_filter = st.selectbox(
            "Status filter",
            ["(all)", "draft", "active", "testing", "supported", "refuted", "archived"],
            index=0,
        )
        search = st.text_input("Search title/id", placeholder="type…", key="wf_h_search")
        params: dict[str, Any] = {"limit": 50, "offset": 0}
        if status_filter != "(all)":
            params["status"] = status_filter

        ok, hyps, _ = api.get_list("/api/v1/hypotheses", params=params)
        if not ok:
            return

        s = (search or "").strip().lower()
        if s:
            hyps = [
                h
                for h in hyps
                if s in (h.get("title", "") or "").lower() or s in (h.get("id", "") or "").lower()
            ]

        options = [""] + [
            f"{h.get('title','(no title)')} · {h.get('status','')} · {h.get('id','')}" for h in hyps
        ]
        cur = st.session_state.get("wf_hypothesis_id") or ""
        idx = 0
        if cur:
            for i, h in enumerate(hyps, start=1):
                if h.get("id") == cur:
                    idx = i
                    break
        pick = st.selectbox("Hypothesis", options, index=idx)
        if pick:
            st.session_state["wf_hypothesis_id"] = pick.split(" · ")[-1].strip()
        else:
            st.session_state["wf_hypothesis_id"] = ""

        hid = st.session_state.get("wf_hypothesis_id") or ""
        if hid:
            okd, hyp, _ = api.request("GET", f"/api/v1/hypotheses/{hid}")
            if okd and isinstance(hyp, dict):
                _wow_card(
                    f"Selected · {hyp.get('title','')}",
                    [
                        f"Status: {hyp.get('status','')}",
                        f"Uncertainty: {hyp.get('uncertainty','')}",
                        f"Evidence errors: {len(hyp.get('evidence_error_ids') or [])}",
                    ],
                    footer="This is your workflow anchor.",
                )

        with st.expander("Or create a new hypothesis (quick)", expanded=False):
            with st.form("wf_create_hypothesis"):
                title = st.text_input("Title", placeholder="Short & concrete", key="wf_h_title")
                statement = st.text_area("Statement", height=120, key="wf_h_stmt")
                uncertainty = st.slider("Uncertainty (0..1)", 0.0, 1.0, 0.6, 0.05, key="wf_h_unc")
                tags = st.text_input("Tags (comma-separated)", placeholder="mvp, test", key="wf_h_tags")
                submit = st.form_submit_button("Create (draft)")

            if submit:
                payload = {
                    "title": title,
                    "statement": statement,
                    "status": "draft",
                    "uncertainty": float(uncertainty),
                    "tags": [t.strip() for t in (tags or "").split(",") if t.strip()],
                    "arguments": [],
                    "alternatives": [],
                    "evidence_error_ids": [],
                }
                okc, data, _ = api.request("POST", "/api/v1/hypotheses", json=payload)
                if okc and isinstance(data, dict):
                    st.success("Created")
                    st.session_state["wf_hypothesis_id"] = data.get("id", "")
                    st.session_state["wf_step"] = 2

        b1, b2 = st.columns([1, 3])
        with b1:
            if st.button("Next →", disabled=not bool(st.session_state.get("wf_hypothesis_id"))):
                st.session_state["wf_step"] = 2
                st.rerun()
        with b2:
            st.caption("Pick a hypothesis to continue.")

    if step == 2:
        st.subheader("Step 2 — Choose / create actions")

        hid = st.session_state.get("wf_hypothesis_id") or ""
        if not hid:
            st.warning("No hypothesis selected. Go back to Step 1.")
            if st.button("← Back to Step 1"):
                st.session_state["wf_step"] = 1
                st.rerun()
            return

        ok_a, acts, _ = api.get_list("/api/v1/actions", params={"limit": 50, "offset": 0, "hypothesis_id": hid})
        if not ok_a:
            return

        options_map: dict[str, str] = {}
        labels_list = []
        for a in acts:
            label = f"{a.get('name','(no name)')} · {a.get('status','')} · {a.get('id','')}"
            labels_list.append(label)
            options_map[label] = a.get("id", "")

        default_ids = set(st.session_state.get("wf_action_ids") or [])
        default_labels = [lbl for lbl in labels_list if options_map.get(lbl) in default_ids]

        picked = st.multiselect("Select actions", labels_list, default=default_labels)
        st.session_state["wf_action_ids"] = [options_map[x] for x in picked if options_map.get(x)]

        _wow_card(
            "Selection",
            [
                f"Hypothesis: {hid}",
                f"Selected actions: {len(st.session_state.get('wf_action_ids') or [])}",
            ],
            footer="You can create actions below.",
        )

        with st.expander("Create a new action (quick)", expanded=False):
            with st.form("wf_create_action"):
                name = st.text_input("Name", placeholder="Relabel slice", key="wf_a_name")
                description = st.text_area("Description", height=120, key="wf_a_desc")
                risk = st.selectbox(
                    "Risk if false", ["low", "medium", "high", "critical"], index=0, key="wf_a_risk"
                )

                c1, c2 = st.columns(2)
                with c1:
                    time_hours = st.number_input("time_hours", min_value=0.0, value=1.0, step=0.5, key="wf_a_th")
                with c2:
                    money = st.number_input("money", min_value=0.0, value=0.0, step=10.0, key="wf_a_money")

                expected = st.text_area("Expected artifacts (one per line)", height=80, key="wf_a_exp")
                submit = st.form_submit_button("Create (draft)")

            if submit:
                cost_payload: dict[str, Any] = {}
                if time_hours > 0.0:
                    cost_payload["time_hours"] = float(time_hours)
                if money > 0.0:
                    cost_payload["money"] = float(money)

                payload = {
                    "status": "draft",
                    "hypothesis_id": hid,
                    "name": name,
                    "description": description,
                    "risk_if_false": risk,
                    "cost": cost_payload or {"time_hours": 1},
                    "expected_artifacts": _split_lines(expected),
                }
                okc, data, _ = api.request("POST", "/api/v1/actions", json=payload)
                if okc and isinstance(data, dict):
                    st.success("Created")
                    new_id = data.get("id", "")
                    if new_id:
                        st.session_state["wf_action_ids"] = list(
                            dict.fromkeys((st.session_state.get("wf_action_ids") or []) + [new_id])
                        )
                    st.session_state["refresh_token"] += 1

        b1, b2, b3 = st.columns([1, 1, 3])
        with b1:
            if st.button("← Back"):
                st.session_state["wf_step"] = 1
                st.rerun()
        with b2:
            if st.button("Next →"):
                st.session_state["wf_step"] = 3
                st.rerun()
        with b3:
            st.caption("You can proceed even with 0 actions, but DecisionRecords are better with links.")

    if step == 3:
        st.subheader("Step 3 — Create DecisionRecord")

        hid = st.session_state.get("wf_hypothesis_id") or ""
        action_ids = st.session_state.get("wf_action_ids") or []
        if not hid:
            st.warning("No hypothesis selected. Go back to Step 1.")
            return

        ok_e, errors, _ = api.get_list("/api/v1/errors", params={"limit": 50, "offset": 0})
        error_labels: list[str] = []
        error_map: dict[str, str] = {}
        if ok_e:
            for e in errors:
                lbl = f"{e.get('y_true','')}→{e.get('y_pred','')} · {e.get('status','')} · {e.get('id','')}"
                error_labels.append(lbl)
                error_map[lbl] = e.get("id", "")

        with st.form("wf_decision_form"):
            made_by = st.text_input("made_by", value="ui", help="Used for filtering in API.")
            decision = st.selectbox("decision", ["proceed", "defer", "reject"], index=0)
            confidence = st.slider("confidence (0..1)", 0.0, 1.0, 0.8, 0.01)
            rationale = st.text_area("rationale (short)", height=100, placeholder="Why this decision?")
            notes = st.text_area(
                "notes (markdown ok; include links here)",
                height=140,
                placeholder="- link: ...\n- observation: ...",
            )

            picked_errors = st.multiselect("Link errors (optional; last 50)", error_labels, default=[])
            extra_error_ids = st.text_area("Or paste error_ids (one per line)", height=80)

            submit = st.form_submit_button("Create DecisionRecord")

        error_ids = [error_map[x] for x in picked_errors if error_map.get(x)]
        error_ids += _split_lines(extra_error_ids)
        error_ids = list(dict.fromkeys([x for x in error_ids if x]))

        potential_id = st.session_state.get("wf_potential_id") or ""
        if potential_id:
            notes = (notes or "") + f"\n\nLinked potential: `{potential_id}`\n"

        _wow_card(
            "Will create DecisionRecord",
            [
                f"Hypothesis: {hid}",
                f"Actions: {len(action_ids)}",
                f"Errors: {len(error_ids)}",
                f"Potential: {potential_id or '—'}",
            ],
            footer="DecisionRecord fields are persisted in backend.",
        )

        if submit:
            payload = {
                "made_by": (made_by or "").strip() or "ui",
                "decision": decision,
                "confidence": float(confidence),
                "rationale": (rationale or "").strip(),
                "notes": (notes or "").strip(),
                "hypothesis_ids": [hid],
                "action_ids": action_ids,
                "error_ids": error_ids,
            }
            okc, data, _ = api.request("POST", "/api/v1/decision-records", json=payload)
            if okc and isinstance(data, dict):
                st.success("DecisionRecord created")
                st.session_state["wf_last_decision_id"] = data.get("id", "")
                st.session_state["wf_step"] = 4
                st.rerun()

        b1, b2 = st.columns([1, 4])
        with b1:
            if st.button("← Back"):
                st.session_state["wf_step"] = 2
                st.rerun()
        with b2:
            last_id = st.session_state.get("wf_last_decision_id") or ""
            if last_id:
                st.caption(f"Last DecisionRecord: `{last_id}`")

    if step == 4:
        st.subheader("Step 4 — Optional: create/link a Potential")

        ok_p, pots, _ = api.get_list("/api/v1/potentials", params={"limit": 50, "offset": 0})
        if not ok_p:
            return

        options = [""] + [
            f"{p.get('metric_name','(metric)')} · {p.get('status','')} · {p.get('id','')}" for p in pots
        ]
        cur = st.session_state.get("wf_potential_id") or ""
        idx = 0
        if cur:
            for i, p in enumerate(pots, start=1):
                if p.get("id") == cur:
                    idx = i
                    break
        pick = st.selectbox("Potential", options, index=idx)
        if pick:
            st.session_state["wf_potential_id"] = pick.split(" · ")[-1].strip()
        else:
            st.session_state["wf_potential_id"] = ""

        pid = st.session_state.get("wf_potential_id") or ""
        if pid:
            okd, pot, _ = api.request("GET", f"/api/v1/potentials/{pid}")
            if okd and isinstance(pot, dict):
                ubr = pot.get("upper_bound_range")
                ubr_s = "—"
                if isinstance(ubr, list) and len(ubr) == 2:
                    ubr_s = f"({ubr[0]}, {ubr[1]})"
                _wow_card(
                    f"Selected · {pot.get('metric_name','')}",
                    [
                        f"Status: {pot.get('status','')}",
                        f"Current: {pot.get('current')}",
                        f"Upper bound: {ubr_s}",
                        f"Confidence: {pot.get('confidence')}",
                    ],
                    footer="Link is stored in DecisionRecord notes (Step 3).",
                )

        with st.expander("Or create a new potential (quick)", expanded=False):
            with st.form("wf_create_potential"):
                metric_name = st.text_input("metric_name", placeholder="accuracy / F1 / CER")
                current = st.slider("current (0..1)", 0.0, 1.0, 0.7, 0.01)
                lo = st.slider("upper_bound low", 0.0, 1.0, 0.85, 0.01)
                hi = st.slider("upper_bound high", 0.0, 1.0, 0.95, 0.01)
                confidence = st.slider("confidence (0..1)", 0.0, 1.0, 0.4, 0.05)
                sample_size = st.number_input("sample_size", min_value=0, value=100, step=10)
                limiting = st.text_area("limiting_factors (one per line)", height=90)
                assumptions = st.text_area("assumptions (one per line)", height=90)
                evidence = st.text_area("evidence_error_ids (one per line)", height=90)
                notes = st.text_area("notes", height=80)
                submit = st.form_submit_button("Create (estimated)")

            if submit:
                payload = {
                    "metric_name": metric_name,
                    "current": float(current),
                    "status": "estimated",
                    "upper_bound_range": [float(lo), float(hi)],
                    "confidence": float(confidence),
                    "sample_size": int(sample_size),
                    "limiting_factors": _split_lines(limiting),
                    "assumptions": _split_lines(assumptions),
                    "evidence_error_ids": _split_lines(evidence),
                    "notes": (notes or "").strip() or None,
                }
                okc, data, _ = api.request("POST", "/api/v1/potentials", json=payload)
                if okc and isinstance(data, dict):
                    st.success("Created")
                    st.session_state["wf_potential_id"] = data.get("id", "")

        st.divider()
        last_id = st.session_state.get("wf_last_decision_id") or ""
        _wow_card(
            "Workflow summary",
            [
                f"Hypothesis: {st.session_state.get('wf_hypothesis_id') or '—'}",
                f"Actions: {len(st.session_state.get('wf_action_ids') or [])}",
                f"DecisionRecord: {last_id or '—'}",
                f"Potential: {st.session_state.get('wf_potential_id') or '—'}",
            ],
            footer="Strict linking Potential↔DecisionRecord requires backend field/endpoint.",
        )

        b1, b2, b3 = st.columns([1, 1, 2])
        with b1:
            if st.button("← Back"):
                st.session_state["wf_step"] = 3
                st.rerun()
        with b2:
            if st.button("Restart workflow"):
                st.session_state["wf_step"] = 1
                st.session_state["wf_hypothesis_id"] = ""
                st.session_state["wf_action_ids"] = []
                st.session_state["wf_potential_id"] = ""
                st.session_state["wf_last_decision_id"] = ""
                st.rerun()
        with b3:
            if st.button("Go to Dashboard"):
                st.session_state["page"] = "Dashboard"
                st.rerun()


# ----------------------------
# Main
# ----------------------------

def main() -> None:
    st.set_page_config(page_title="DDW UI", layout="wide")
    _init_state()

    st.sidebar.title("DDW UI")
    st.sidebar.caption("HTTP-only UI · tenant required")

    st.sidebar.text_input("BASE_URL", value=st.session_state["base_url"], key="base_url")
    st.sidebar.text_input("TENANT_ID", value=st.session_state["tenant_id"], key="tenant_id")

    # Notes mode toggle (default OFF)
    st.sidebar.checkbox("Notes mode", value=bool(st.session_state.get("notes_mode")), key="notes_mode")
    st.sidebar.caption("Notes/Vault are hidden by default.")

    st.sidebar.divider()
    st.sidebar.radio(
        "Navigation",
        ["Workflow", "Dashboard", "Hypotheses → Actions", "Potentials"],
        key="page",
    )
    if st.sidebar.button("Refresh data"):
        st.session_state["refresh_token"] += 1

    base_url = _norm_base_url(st.session_state["base_url"])
    tenant_id = (st.session_state["tenant_id"] or "").strip()
    if not tenant_id:
        st.warning("TENANT_ID is empty — API will respond 422.")

    api = _client()
    spec = _openapi_spec(api.base_url)

    _ = st.session_state["refresh_token"]

    st.sidebar.divider()
    _quick_switcher(api)
    st.sidebar.divider()
    st.sidebar.caption(f"Now: {_now_iso()}")
    st.sidebar.caption(f"Using: {base_url}")
    if st.session_state.get("notes_mode"):
        st.sidebar.caption(f"Vault: {_vault_root()}")

    if st.session_state["page"] == "Workflow":
        _workflow_page(api)
    elif st.session_state["page"] == "Dashboard":
        _dashboard_page(api)
    elif st.session_state["page"] == "Hypotheses → Actions":
        _hypotheses_actions_page(api, spec)
    else:
        _potentials_page(api)


if __name__ == "__main__":
    main()
