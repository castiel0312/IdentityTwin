"""Operational analytics computed from complete, bounded record sets.

The service never derives a global metric from a paginated page. If the
requested range exceeds the server-side scan cap the response is flagged as
truncated and the console must label the metrics as partial.
"""

from collections import Counter, defaultdict
from datetime import datetime, timedelta, timezone

from sqlalchemy import func, select
from sqlalchemy.orm import Session

from app.core.security import AuthenticatedPrincipal
from app.models.agent import AgenticCommerceAudit
from app.models.event import SecurityEvent
from app.models.evidence import IncidentSeal
from app.models.idempotency import IdempotencyRecord
from app.models.incident import IncidentRecord
from app.models.payout import PayoutRequestRecord
from app.models.risk import RiskDecisionRecord
from app.models.session import SessionRecord
from app.schemas.analytics import (
    AnalyticsBucket,
    AnalyticsOverviewResponse,
    AnalyticsRange,
    AnalyticsTotals,
    ProviderOutcome,
    RecentActivityItem,
    RiskBucket,
)
from app.schemas.sessions import SessionStatus
from app.services.payout_query_service import (
    PROVIDER_FAILURE_STATUSES,
    RECONCILIATION_STATUSES,
)

SCAN_CAP = 50_000


def _as_utc(value: datetime) -> datetime:
    return value if value.tzinfo else value.replace(tzinfo=timezone.utc)


def _floor_hour(value: datetime) -> datetime:
    return value.replace(minute=0, second=0, microsecond=0)


def _floor_day(value: datetime) -> datetime:
    return value.replace(hour=0, minute=0, second=0, microsecond=0)


def build_overview(
    db: Session,
    principal: AuthenticatedPrincipal,
    start: datetime,
    end: datetime,
) -> AnalyticsOverviewResponse:
    start = _as_utc(start)
    end = _as_utc(end)
    if end <= start:
        end = start + timedelta(hours=1)

    bucket_mode = "hour" if (end - start) <= timedelta(hours=48) else "day"
    now = datetime.now(timezone.utc)

    payout_rows = db.execute(
        select(PayoutRequestRecord, RiskDecisionRecord)
        .join(
            RiskDecisionRecord,
            RiskDecisionRecord.decision_id == PayoutRequestRecord.decision_id,
        )
        .where(
            PayoutRequestRecord.merchant_id == principal.merchant_id,
            PayoutRequestRecord.created_at >= start,
            PayoutRequestRecord.created_at <= end,
        )
        .order_by(PayoutRequestRecord.created_at.asc())
        .limit(SCAN_CAP + 1)
    ).all()
    truncated = len(payout_rows) > SCAN_CAP
    payout_rows = payout_rows[:SCAN_CAP]

    incident_rows = list(
        db.scalars(
            select(IncidentRecord).where(
                IncidentRecord.merchant_id == principal.merchant_id,
                IncidentRecord.created_at >= start,
                IncidentRecord.created_at <= end,
            )
        ).all()
    )

    agent_payout_ids = set(
        db.scalars(
            select(AgenticCommerceAudit.payout_id).where(
                AgenticCommerceAudit.merchant_id == principal.merchant_id,
                AgenticCommerceAudit.payout_id.is_not(None),
            )
        ).all()
    )

    status_counts: Counter[str] = Counter()
    trust_counts: Counter[str] = Counter()
    amount_by_currency: defaultdict[str, float] = defaultdict(float)
    amount_total = 0.0
    step_up = 0
    decoy = 0
    isolated = 0
    provider_failures = 0
    agent_initiated = 0

    timeline_map: dict[str, AnalyticsBucket] = {}
    histogram_counts = [0] * 10

    for payout, decision in payout_rows:
        status_counts[payout.status] += 1
        trust_counts[decision.trust_level] += 1
        amount_total += float(payout.amount or 0.0)
        amount_by_currency[payout.currency] += float(payout.amount or 0.0)
        if decision.action == "REQUIRE_STEP_UP":
            step_up += 1
        if decision.action == "DECOY_FORWARD":
            decoy += 1
        if decision.action == "BLOCK":
            isolated += 1
        if payout.status in PROVIDER_FAILURE_STATUSES:
            provider_failures += 1
        if payout.payout_id in agent_payout_ids:
            agent_initiated += 1

        score = max(0.0, min(100.0, float(decision.risk_score or 0.0)))
        index = min(9, int(score // 10))
        histogram_counts[index] += 1

        occurred = _as_utc(payout.created_at)
        bucket_start = _floor_hour(occurred) if bucket_mode == "hour" else _floor_day(occurred)
        key = bucket_start.isoformat()
        bucket = timeline_map.get(key)
        if bucket is None:
            bucket = AnalyticsBucket(
                bucket=key,
                label=bucket_start.strftime("%Y-%m-%d %H:%M" if bucket_mode == "hour" else "%Y-%m-%d"),
            )
            timeline_map[key] = bucket
        bucket.payouts += 1
        bucket.amount += float(payout.amount or 0.0)
        level = decision.trust_level
        if level == "NORMAL":
            bucket.normal += 1
        elif level == "RESTRICTED":
            bucket.restricted += 1
        elif level == "DECOY":
            bucket.decoy += 1
        elif level == "ISOLATED":
            bucket.isolated += 1

    for incident in incident_rows:
        occurred = _as_utc(incident.created_at)
        bucket_start = _floor_hour(occurred) if bucket_mode == "hour" else _floor_day(occurred)
        key = bucket_start.isoformat()
        bucket = timeline_map.get(key)
        if bucket is None:
            bucket = AnalyticsBucket(
                bucket=key,
                label=bucket_start.strftime("%Y-%m-%d %H:%M" if bucket_mode == "hour" else "%Y-%m-%d"),
            )
            timeline_map[key] = bucket
        bucket.incidents += 1

    # Fill empty buckets so charts do not silently compress quiet periods.
    cursor = _floor_hour(start) if bucket_mode == "hour" else _floor_day(start)
    step = timedelta(hours=1) if bucket_mode == "hour" else timedelta(days=1)
    final_bucket = _floor_hour(end) if bucket_mode == "hour" else _floor_day(end)
    while cursor <= final_bucket:
        key = cursor.isoformat()
        if key not in timeline_map:
            timeline_map[key] = AnalyticsBucket(
                bucket=key,
                label=cursor.strftime("%Y-%m-%d %H:%M" if bucket_mode == "hour" else "%Y-%m-%d"),
            )
        cursor += step
    timeline = sorted(timeline_map.values(), key=lambda item: item.bucket)

    reconciliation_required = (
        db.scalar(
            select(func.count())
            .select_from(IdempotencyRecord)
            .where(
                IdempotencyRecord.merchant_id == principal.merchant_id,
                IdempotencyRecord.updated_at >= start,
                IdempotencyRecord.updated_at <= end,
                IdempotencyRecord.status.in_(RECONCILIATION_STATUSES),
            )
        )
        or 0
    )
    incidents_open = (
        db.scalar(
            select(func.count())
            .select_from(IncidentRecord)
            .where(
                IncidentRecord.merchant_id == principal.merchant_id,
                IncidentRecord.status == "OPEN",
            )
        )
        or 0
    )
    sessions_active = (
        db.scalar(
            select(func.count())
            .select_from(SessionRecord)
            .where(
                SessionRecord.merchant_id == principal.merchant_id,
                SessionRecord.status == SessionStatus.ACTIVE.value,
            )
        )
        or 0
    )
    evidence_seals = (
        db.scalar(
            select(func.count())
            .select_from(IncidentSeal)
            .where(IncidentSeal.merchant_id == principal.merchant_id)
        )
        or 0
    )

    provider_counts: Counter[tuple[str, str]] = Counter(
        (payout.provider_name or "none", payout.status) for payout, _ in payout_rows
    )
    provider_outcomes = [
        ProviderOutcome(provider=provider, status=status, count=count)
        for (provider, status), count in sorted(
            provider_counts.items(), key=lambda item: (-item[1], item[0])
        )
    ]

    risk_histogram = [
        RiskBucket(
            bucket=(
                "100" if index == 9 else f"{index * 10}-{index * 10 + 9}"
            ),
            min_score=float(index * 10),
            max_score=100.0 if index == 9 else float(index * 10 + 9),
            count=histogram_counts[index],
        )
        for index in range(10)
    ]

    recent_activity = _recent_activity(
        db, principal, payout_rows, list(incident_rows)
    )

    return AnalyticsOverviewResponse(
        range=AnalyticsRange(start=start, end=end, bucket=bucket_mode),
        generated_at=now,
        totals=AnalyticsTotals(
            payouts_total=len(payout_rows),
            amount_total=round(amount_total, 2),
            amount_by_currency={
                currency: round(amount, 2)
                for currency, amount in sorted(amount_by_currency.items())
            },
            payouts_by_status=dict(sorted(status_counts.items())),
            payouts_by_trust_level=dict(sorted(trust_counts.items())),
            payouts_requiring_step_up=step_up,
            decoy_routed=decoy,
            isolated_actions=isolated,
            reconciliation_required=int(reconciliation_required),
            provider_failures=provider_failures,
            agent_initiated=agent_initiated,
            incidents_open=int(incidents_open),
            incidents_in_range=len(incident_rows),
            sessions_active=int(sessions_active),
            evidence_seals=int(evidence_seals),
        ),
        timeline=timeline,
        risk_histogram=risk_histogram,
        provider_outcomes=provider_outcomes,
        recent_activity=recent_activity,
        truncated=truncated,
    )


def _recent_activity(
    db: Session,
    principal: AuthenticatedPrincipal,
    payout_rows: list[tuple[PayoutRequestRecord, RiskDecisionRecord]],
    incident_rows: list[IncidentRecord],
) -> list[RecentActivityItem]:
    items: list[RecentActivityItem] = []

    for payout, decision in payout_rows[-15:]:
        items.append(
            RecentActivityItem(
                activity_id=f"payout:{payout.payout_id}",
                kind="payout",
                occurred_at=_as_utc(payout.created_at),
                title=f"{payout.amount:.2f} {payout.currency} payout",
                summary=f"{payout.status} · {payout.recipient_email}",
                risk_score=decision.risk_score,
                trust_level=decision.trust_level,
                session_id=payout.session_id,
                payout_id=payout.payout_id,
            )
        )

    for incident in incident_rows[-15:]:
        items.append(
            RecentActivityItem(
                activity_id=f"incident:{incident.incident_id}",
                kind="incident",
                occurred_at=_as_utc(incident.created_at),
                title=incident.title,
                summary=incident.trigger_reason,
                severity=incident.severity,
                risk_score=incident.risk_score,
                session_id=incident.session_id,
                incident_id=incident.incident_id,
            )
        )

    events = list(
        db.scalars(
            select(SecurityEvent)
            .where(SecurityEvent.merchant_id == principal.merchant_id)
            .order_by(SecurityEvent.occurred_at.desc())
            .limit(15)
        ).all()
    )
    for event in events:
        items.append(
            RecentActivityItem(
                activity_id=f"event:{event.event_id}",
                kind="event",
                occurred_at=_as_utc(event.occurred_at),
                title=event.action.replace(".", " ").replace("_", " ").title(),
                summary=f"{event.event_type} · {event.action}",
                event_type=event.event_type,
                session_id=event.session_id,
            )
        )

    items.sort(key=lambda item: item.occurred_at, reverse=True)
    return items[:20]
