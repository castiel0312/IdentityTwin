"""Simulation and calibration read models."""

from datetime import datetime
from typing import Any

from pydantic import BaseModel, Field


class SimulationScenario(BaseModel):
    id: str
    name: str
    description: str
    attack_type: str
    expected_trust_state: str
    expected_min_score: float
    expected_outcomes: list[str] = Field(default_factory=list)
    endpoint: str
    method: str = "POST"
    safety: list[str] = Field(default_factory=list)
    parameters: dict[str, Any] = Field(default_factory=dict)


class SimulationScenariosResponse(BaseModel):
    environment: str
    scenarios: list[SimulationScenario] = Field(default_factory=list)
    limitations: list[str] = Field(default_factory=list)


class SplitMetricsView(BaseModel):
    name: str
    identities: int
    sessions: int
    flagged_sessions: int
    benign_sessions: int
    benign_flagged_sessions: int
    false_positive_rate: float
    events: int
    flagged_events: int
    benign_identities: int
    compromised_identities: int
    detected: int
    detection_rate: float
    mean_session_score: float
    max_score: float
    per_cohort: dict[str, dict[str, Any]] = Field(default_factory=dict)
    per_attack_type: dict[str, dict[str, Any]] = Field(default_factory=dict)


class CalibrationReportResponse(BaseModel):
    synthetic_dataset: bool = True
    seed: int
    generated_at: datetime
    overall: SplitMetricsView
    calibration: SplitMetricsView
    holdout: SplitMetricsView
    methodology: list[str] = Field(default_factory=list)
    limitations: list[str] = Field(default_factory=list)
