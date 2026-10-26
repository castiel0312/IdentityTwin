from datetime import datetime, timezone
from functools import lru_cache

from fastapi import APIRouter, Depends

from app.core.config import settings
from app.core.security import AuthenticatedPrincipal, get_current_principal
from app.risk.calibration import CalibrationReport, SplitMetrics, run_calibration
from app.schemas.simulation import (
    CalibrationReportResponse,
    SimulationScenario,
    SimulationScenariosResponse,
    SplitMetricsView,
)

router = APIRouter(prefix="/simulate", tags=["Attack Simulation & Calibration"])


def _split(metrics: SplitMetrics) -> SplitMetricsView:
    return SplitMetricsView(
        name=metrics.name,
        identities=metrics.identities,
        sessions=metrics.sessions,
        flagged_sessions=metrics.flagged_sessions,
        benign_sessions=metrics.benign_sessions,
        benign_flagged_sessions=metrics.benign_flagged_sessions,
        false_positive_rate=round(metrics.false_positive_rate * 100, 4),
        events=metrics.events,
        flagged_events=metrics.flagged_events,
        benign_identities=metrics.benign_identities,
        compromised_identities=metrics.compromised_identities,
        detected=metrics.detected,
        detection_rate=round(metrics.detection_rate * 100, 4),
        mean_session_score=round(metrics.mean_session_score, 2),
        max_score=round(metrics.max_score, 2),
        per_cohort=metrics.per_cohort,
        per_attack_type=metrics.per_attack_type,
    )


@lru_cache(maxsize=4)
def _cached_report(seed: int) -> CalibrationReport:
    return run_calibration(seed)


@router.get(
    "/scenarios",
    response_model=SimulationScenariosResponse,
    summary="List supported, server-implemented simulation scenarios",
    description=(
        "Only scenarios that exist in the running backend are returned. "
        "The console must not invent additional attack types."
    ),
)
def list_scenarios(
    principal: AuthenticatedPrincipal = Depends(get_current_principal),
) -> SimulationScenariosResponse:
    scenarios = [
        SimulationScenario(
            id="account_takeover_canary_drill",
            name="Account Takeover → Canary Containment",
            description=(
                "Creates a synthetic session, records a login, payee registration and "
                "payout, issues scoped canaries, triggers one canary hit and runs containment."
            ),
            attack_type="account_takeover",
            expected_trust_state="ISOLATED",
            expected_min_score=90.0,
            expected_outcomes=[
                "Canary interaction forces isolation.",
                "Session is revoked.",
                "Incident is opened and sealed.",
                "Evidence chain verification runs.",
            ],
            endpoint="/v1/simulate/attack",
            safety=[
                "Creates synthetic records only; no real payout is executed.",
                "The mock provider never contacts an external payment network.",
                "The run is rejected when the backend is in production mode.",
            ],
            parameters={},
        )
    ]
    return SimulationScenariosResponse(
        environment=settings.ENVIRONMENT,
        scenarios=scenarios,
        limitations=[
            "This is the only adversarial scenario implemented by the running backend.",
            "A successful drill is not evidence of production fraud prevention.",
        ],
    )


@router.get(
    "/calibration",
    response_model=CalibrationReportResponse,
    summary="Run the committed synthetic calibration and holdout evaluation",
    description=(
        "Replays the committed synthetic dataset through the shipped engine. "
        "Results are cached per seed for the life of the process."
    ),
)
def calibration_report(
    principal: AuthenticatedPrincipal = Depends(get_current_principal),
) -> CalibrationReportResponse:
    report = _cached_report(settings.RISK_SYNTHETIC_SEED)
    return CalibrationReportResponse(
        seed=report.seed,
        generated_at=datetime.now(timezone.utc),
        overall=_split(report.overall),
        calibration=_split(report.calibration),
        holdout=_split(report.holdout),
        methodology=[
            "Identities are split deterministically into calibration and held-out cohorts.",
            "Signal weights are not tuned by this harness; thresholds come from configuration.",
            "False-positive rate uses benign sessions only as the denominator.",
            "Detection rate uses compromised identities as the denominator.",
        ],
        limitations=[
            "All metrics come from a synthetic dataset, not production traffic.",
            "slow_and_low fraud is not detected by the current behavioural contract.",
            "A simulation or calibration pass does not prove production fraud prevention.",
        ],
    )
