"""Configurable earnings-result screening thresholds."""

from pathlib import Path
from typing import Any

import yaml

PROJECT_ROOT = Path(__file__).resolve().parents[1]
DEFAULT_SCENARIOS_PATH = PROJECT_ROOT / "config" / "scenarios.yaml"


def load_scenario_config(path: str | Path = DEFAULT_SCENARIOS_PATH) -> dict[str, Any]:
    with Path(path).open(encoding="utf-8") as scenario_file:
        config = yaml.safe_load(scenario_file) or {}
    thresholds = config.get("screening_thresholds")
    labels = config.get("scenario_labels")
    views = config.get("screening_views")
    if not isinstance(thresholds, dict) or not isinstance(labels, dict) or not isinstance(views, dict):
        raise ValueError("Scenario config must define screening_thresholds, scenario_labels, and screening_views")
    return config


def classify_scenario(
    pat_surprise_pct: float | None,
    ebitda_surprise_pct: float | None,
    guidance_status: str | None,
    margins_stable: bool | None,
    config: dict[str, Any] | None = None,
) -> dict[str, str]:
    """Classify verified results using configured screening thresholds, not forecasts."""
    scenario_config = config or load_scenario_config()
    thresholds = scenario_config["screening_thresholds"]
    labels = scenario_config["scenario_labels"]
    views = scenario_config["screening_views"]
    earnings = [value for value in (pat_surprise_pct, ebitda_surprise_pct) if value is not None]
    if not earnings:
        key = "insufficient"
    elif (
        pat_surprise_pct is not None
        and ebitda_surprise_pct is not None
        and pat_surprise_pct >= thresholds["strong_beat_pct"]
        and ebitda_surprise_pct >= thresholds["strong_beat_pct"]
        and guidance_status == "raised"
    ):
        key = "strong_beat"
    elif any(value < -thresholds["major_miss_pct"] for value in earnings) and guidance_status == "cut":
        key = "major_miss"
    elif (
        all(value >= -thresholds["in_line_abs_pct"] for value in earnings)
        and any(thresholds["moderate_beat_min_pct"] < value <= thresholds["moderate_beat_max_pct"] for value in earnings)
        and margins_stable is True
    ):
        key = "moderate_beat"
    elif all(abs(value) <= thresholds["in_line_abs_pct"] for value in earnings):
        key = "in_line"
    elif (
        all(value <= thresholds["in_line_abs_pct"] for value in earnings)
        and any(
            thresholds["moderate_miss_min_pct"] < abs(value) <= thresholds["moderate_miss_max_pct"] and value < 0
            for value in earnings
        )
    ):
        key = "moderate_miss"
    else:
        key = "insufficient"

    return {
        "label": str(labels[key]),
        "view": str(views[key]),
        "basis": "Screening thresholds only; not a return prediction.",
    }