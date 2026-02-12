from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime, timedelta, time
from zoneinfo import ZoneInfo


@dataclass
class Recommendation:
    recommended_time_utc: str
    confidence_score: float
    reasoning_summary: str
    fallback_used: bool


def _is_weekday(dt: datetime) -> bool:
    return dt.weekday() < 5


def recommend_post_time(
    audience_timezone: str,
    now_utc: datetime | None = None,
    has_history: bool = False,
) -> Recommendation:
    """
    Balanced heuristic (engagement + reliability) for v1.
    Falls back to 09:30 local with explicit low-confidence signal.
    """
    if now_utc is None:
        now_utc = datetime.utcnow()

    tz = ZoneInfo(audience_timezone)
    local_now = now_utc.replace(tzinfo=ZoneInfo("UTC")).astimezone(tz)

    # Candidate slots over next 7 days.
    candidates: list[datetime] = []
    for delta in range(0, 7):
        day = (local_now + timedelta(days=delta)).date()
        for hh, mm in ((9, 30), (12, 0), (17, 30), (19, 0)):
            candidate = datetime.combine(day, time(hour=hh, minute=mm), tz)
            if candidate <= local_now:
                continue
            candidates.append(candidate)

    if not candidates:
        fallback_local = local_now + timedelta(hours=1)
        fallback_local = fallback_local.replace(minute=30, second=0, microsecond=0)
        return Recommendation(
            recommended_time_utc=fallback_local.astimezone(ZoneInfo("UTC")).isoformat(),
            confidence_score=0.3,
            reasoning_summary="No future slot candidates found; using safe fallback.",
            fallback_used=True,
        )

    # Score: balanced, deterministic, with weekday preference.
    def score(dt_local: datetime) -> float:
        hour = dt_local.hour + dt_local.minute / 60
        # Soft preference around mid-morning and early evening.
        engagement = max(0.0, 1.0 - min(abs(hour - 9.5), abs(hour - 19.0)) / 12)
        reliability = 1.0 if 8 <= hour <= 20 else 0.6
        weekday_bonus = 0.1 if _is_weekday(dt_local) else 0.0
        history_bonus = 0.1 if has_history else 0.0
        return (0.5 * engagement) + (0.5 * reliability) + weekday_bonus + history_bonus

    scored = sorted(((c, score(c)) for c in candidates), key=lambda x: x[1], reverse=True)
    best_score = scored[0][1]
    top = [c for c, s in scored if abs(s - best_score) < 1e-9]

    # Tie-break: earliest -> weekday -> earliest (historical best day not yet tracked in v1 data).
    top.sort(key=lambda d: (d, 0 if _is_weekday(d) else 1))
    chosen = top[0]

    fallback_used = not has_history
    confidence = 0.75 if has_history else 0.45
    reasoning = "Balanced heuristic based on day/hour reliability and engagement windows."
    if fallback_used:
        reasoning += " Limited history; confidence is lower."

    return Recommendation(
        recommended_time_utc=chosen.astimezone(ZoneInfo("UTC")).isoformat(),
        confidence_score=confidence,
        reasoning_summary=reasoning,
        fallback_used=fallback_used,
    )
