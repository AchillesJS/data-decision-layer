# State machine rules (v1)

This document is a *contract* for UI/API. Core models enforce only minimal invariants.
Persistence/use-case layer must enforce referential integrity and audit.

## ErrorStatus
- observed -> triaged -> archived
- observed -> archived

Rules:
- We intentionally do NOT model a separate `resolved` state in Core.
- Whether an error pattern is “addressed” is tracked via DecisionRecords (links/outcomes) in the store layer.

## HypothesisStatus
- draft -> active -> testing -> supported | refuted -> archived
- draft -> archived
Rules:
- Non-DRAFT must have (statement) and at least one grounding: arguments OR evidence_error_ids OR scope.
- SUPPORTED/REFUTED must have evidence_error_ids or scope.

## ActionStatus
- draft -> proposed -> approved -> in_progress -> done
- draft -> cancelled
- proposed/approved/in_progress -> cancelled
Rules:
- `hypothesis_id` may be null ONLY in DRAFT (exploratory action).
- DONE requires completed_at; CANCELLED requires cancel_reason.

## DecisionType
- proceed / reject / defer
Rules:
- PROCEED requires action_ids.
- REJECT forbids action_ids.
- DEFER should include rationale explaining what is missing (uncertainty gaps, missing evidence).

## DataPotentialStatus
- draft -> estimated -> stale
- estimated -> stale
Rules:
- ESTIMATED requires: upper_bound_range, limiting_factors, assumptions, sample_size>0.
- upper_bound_range: 0<=low<=high<=1 and high>=current (low may be < current).
