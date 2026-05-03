from __future__ import annotations

from analytics_engine.engine_v1 import analyze_saturation


def _rp(
    run_id: str,
    x: float,
    y: float,
    *,
    x_kind: str = "dataset_size",
    seed: int | None = None,
    model_tag: str = "m1",
    metric_name: str = "acc",
    dataset_version: str | None = "v1",
    split: str | None = "val",
):
    return {
        "run_id": run_id,
        "x_kind": x_kind,
        "x_value": x,
        "y_value": y,
        "seed": seed,
        "model_tag": model_tag,
        "dataset_version": dataset_version,
        "metric_name": metric_name,
        "split": split,
    }


def test_insufficient_data_returns_unknown():
    pts = [
        _rp("r1", 100, 0.60, seed=1),
        _rp("r2", 200, 0.62, seed=2),
    ]
    sat, regime, draft = analyze_saturation(pts, n_boot=50, rng_seed=0)
    assert sat.fit.fit_quality == "insufficient_data"
    assert regime.regime == "UNKNOWN"
    assert 0.0 <= sat.confidence <= 0.6
    assert draft.confidence == sat.confidence


def test_high_never_below_current():
    pts = [
        _rp("r1", 100, 0.55),
        _rp("r2", 200, 0.60),
        _rp("r3", 400, 0.64),
        _rp("r4", 800, 0.66),
    ]
    sat, _, draft = analyze_saturation(pts, n_boot=80, rng_seed=0)
    assert sat.ceiling_range[1] >= draft.current
    assert sat.ceiling_range[0] >= draft.current - 1e-9


def test_evidence_run_ids_present():
    pts = [
        _rp("r1", 100, 0.50),
        _rp("r2", 200, 0.57),
        _rp("r3", 400, 0.61),
    ]
    sat, regime, draft = analyze_saturation(pts, n_boot=60, rng_seed=0)
    assert sat.evidence_run_ids
    assert set(sat.evidence_run_ids) == {"r1", "r2", "r3"}
    assert set(regime.evidence_run_ids) == {"r1", "r2", "r3"}
    assert set(draft.evidence["run_ids"]) == {"r1", "r2", "r3"}


def test_confidence_increases_with_more_points():
    pts3 = [
        _rp("a1", 100, 0.55),
        _rp("a2", 200, 0.60),
        _rp("a3", 400, 0.63),
    ]
    pts6 = [
        _rp("b1", 50, 0.50),
        _rp("b2", 100, 0.55),
        _rp("b3", 200, 0.60),
        _rp("b4", 400, 0.63),
        _rp("b5", 800, 0.65),
        _rp("b6", 1600, 0.66),
    ]
    sat3, _, _ = analyze_saturation(pts3, n_boot=40, rng_seed=0)
    sat6, _, _ = analyze_saturation(pts6, n_boot=40, rng_seed=0)
    assert sat6.confidence > sat3.confidence


def test_noise_limited_when_variance_high():
    noisy = [
        _rp("n1", 100, 0.55, seed=1),
        _rp("n2", 200, 0.60, seed=1),
        _rp("n3", 400, 0.62, seed=1),
        # high variance at max-x
        _rp("n4", 800, 0.45, seed=1),
        _rp("n5", 800, 0.90, seed=2),
    ]
    clean = [
        _rp("c1", 100, 0.55, seed=1),
        _rp("c2", 200, 0.60, seed=1),
        _rp("c3", 400, 0.62, seed=1),
        _rp("c4", 800, 0.64, seed=1),
        _rp("c5", 800, 0.65, seed=2),
    ]
    sat_noisy, regime_noisy, _ = analyze_saturation(noisy, n_boot=60, rng_seed=0)
    sat_clean, _, _ = analyze_saturation(clean, n_boot=60, rng_seed=0)

    assert regime_noisy.regime in {"NOISE_LIMITED", "UNKNOWN"}
    assert sat_noisy.confidence <= sat_clean.confidence
    signal_names = {s.name for s in regime_noisy.signals}
    assert "std_at_max_x" in signal_names or "std_mean" in signal_names


def test_gain_ranges_non_negative_reasonable():
    pts = [
        _rp("g1", 100, 0.55),
        _rp("g2", 200, 0.60),
        _rp("g3", 400, 0.64),
        _rp("g4", 800, 0.66),
        _rp("g5", 1600, 0.67),
    ]
    sat, _, _ = analyze_saturation(pts, n_boot=80, rng_seed=0)
    for r in (sat.marginal_gain_p20_range, sat.marginal_gain_p50_range):
        lo, hi = r
        assert lo >= -0.02
        assert hi >= lo
        assert hi <= 1.0


def test_no_oracle_through_regime_signals() -> None:
    pts = [
        _rp("o1", 100, 0.55),
        _rp("o2", 200, 0.60),
        _rp("o3", 400, 0.64),
    ]
    _, regime, _ = analyze_saturation(pts, n_boot=40, rng_seed=0)

    forbidden = {"ceiling_point_estimate", "slope_gain_at_max_x_+20%"}
    names = {s.name for s in regime.signals}
    assert names.isdisjoint(forbidden)

    # If a transparency band is present, it must be non-numeric.
    band = next((s for s in regime.signals if s.name == "marginal_gain_band_+20pct"), None)
    if band is not None:
        assert isinstance(band.value, str)
        assert band.value in {"LOW", "MEDIUM", "HIGH"}


def test_determinism_fixed_rng_seed():
    pts = [
        _rp("d1", 50, 0.50, seed=1),
        _rp("d2", 100, 0.55, seed=2),
        _rp("d3", 200, 0.60, seed=3),
        _rp("d4", 400, 0.63, seed=4),
        _rp("d5", 800, 0.65, seed=5),
        _rp("d6", 1600, 0.66, seed=6),
        # replicate at max-x to exercise variance paths
        _rp("d7", 1600, 0.67, seed=7),
    ]
    sat1, regime1, draft1 = analyze_saturation(pts, n_boot=200, rng_seed=123)
    sat2, regime2, draft2 = analyze_saturation(pts, n_boot=200, rng_seed=123)

    assert sat1.model_dump() == sat2.model_dump()
    assert regime1.model_dump() == regime2.model_dump()
    assert draft1.model_dump() == draft2.model_dump()
