import base64
import uuid
from datetime import date, datetime, timedelta, timezone

from fastapi import APIRouter, Depends, HTTPException, Query
from sqlalchemy import case, func, or_, select
from sqlalchemy.ext.asyncio import AsyncSession

from app.auth import get_current_user
from app.database import get_db
from app.usage_events import publisher
from app.models import BudgetAlert, RequestLog, User
from app.schemas import BudgetIn

router = APIRouter(prefix="/api/usage", tags=["usage"])

DEFAULT_RANGE_DAYS = 30
MAX_RANGE_DAYS = 366
UNTAGGED = "untagged"


def _as_utc(value: datetime) -> datetime:
    return value.replace(tzinfo=timezone.utc) if value.tzinfo is None else value.astimezone(timezone.utc)


def _resolve_range(from_: datetime | None, to: datetime | None) -> tuple[datetime, datetime | None]:
    end = _as_utc(to) if to else None
    start = _as_utc(from_) if from_ else (end or datetime.now(timezone.utc)) - timedelta(days=DEFAULT_RANGE_DAYS)
    if end and end <= start:
        raise HTTPException(status_code=400, detail="'to' must be after 'from'")
    if (end or datetime.now(timezone.utc)) - start > timedelta(days=MAX_RANGE_DAYS):
        raise HTTPException(status_code=400, detail=f"Range can be at most {MAX_RANGE_DAYS} days")
    return start, end


def _filters(user: User, start: datetime, end: datetime | None, feature: str | None, with_feature: bool = True):
    conditions = [RequestLog.user_id == user.id, RequestLog.created_at >= start]
    if end:
        conditions.append(RequestLog.created_at < end)
    if with_feature and feature:
        conditions.append(RequestLog.feature_tag.is_(None) if feature == UNTAGGED else RequestLog.feature_tag == feature)
    return conditions


def _round_cost(value) -> float:
    return round(float(value or 0), 6)


@router.get("/summary")
async def usage_summary(
    feature: str | None = Query(default=None, max_length=50),
    from_: datetime | None = Query(default=None, alias="from"),
    to: datetime | None = Query(default=None),
    user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
):
    start, end = _resolve_range(from_, to)
    where = _filters(user, start, end, feature)

    cache_hits = func.coalesce(func.sum(case((RequestLog.cache_hit.is_(True), 1), else_=0)), 0)
    fallbacks = func.coalesce(func.sum(case((RequestLog.fallback_used.is_(True), 1), else_=0)), 0)
    errors = func.coalesce(func.sum(case((RequestLog.error.is_not(None), 1), else_=0)), 0)

    totals_row = (await db.execute(
        select(
            func.count(RequestLog.id),
            func.coalesce(func.sum(RequestLog.input_tokens), 0),
            func.coalesce(func.sum(RequestLog.output_tokens), 0),
            func.coalesce(func.sum(RequestLog.cost_usd), 0.0),
            func.coalesce(func.avg(RequestLog.latency_ms), 0.0),
            cache_hits, fallbacks, errors,
        ).where(*where)
    )).one()

    by_model_rows = (await db.execute(
        select(
            RequestLog.provider, RequestLog.model,
            func.count(RequestLog.id),
            func.coalesce(func.sum(RequestLog.input_tokens), 0),
            func.coalesce(func.sum(RequestLog.output_tokens), 0),
            func.coalesce(func.sum(RequestLog.cost_usd), 0.0),
        ).where(*where).group_by(RequestLog.provider, RequestLog.model)
        .order_by(func.sum(RequestLog.cost_usd).desc(), func.count(RequestLog.id).desc())
    )).all()

    feature_label = func.coalesce(RequestLog.feature_tag, UNTAGGED)
    by_feature_rows = (await db.execute(
        select(
            feature_label,
            func.count(RequestLog.id),
            func.coalesce(func.sum(RequestLog.input_tokens), 0),
            func.coalesce(func.sum(RequestLog.output_tokens), 0),
            func.coalesce(func.sum(RequestLog.cost_usd), 0.0),
        ).where(*where).group_by(feature_label)
        .order_by(func.sum(RequestLog.cost_usd).desc(), func.count(RequestLog.id).desc())
    )).all()

    day = func.date_trunc("day", func.timezone("UTC", RequestLog.created_at))
    by_day_rows = (await db.execute(
        select(
            day,
            func.count(RequestLog.id),
            func.coalesce(func.sum(RequestLog.input_tokens + RequestLog.output_tokens), 0),
            func.coalesce(func.sum(RequestLog.cost_usd), 0.0),
        ).where(*where).group_by(day).order_by(day)
    )).all()

   
    available_rows = (await db.execute(
        select(feature_label).where(*_filters(user, start, end, feature, with_feature=False))
        .distinct().order_by(feature_label)
    )).all()


    by_day_map = {row[0].date(): row for row in by_day_rows}
    last_day = (end - timedelta(microseconds=1) if end else datetime.now(timezone.utc)).date()
    series: list[dict] = []
    cursor_day: date = start.date()
    while cursor_day <= last_day:
        row = by_day_map.get(cursor_day)
        series.append({
            "date": cursor_day.isoformat(),
            "requests": int(row[1]) if row else 0,
            "tokens": int(row[2]) if row else 0,
            "cost_usd": _round_cost(row[3]) if row else 0.0,
        })
        cursor_day += timedelta(days=1)

    requests = int(totals_row[0])
    return {
        "range": {"from": start.isoformat(), "to": end.isoformat() if end else None},
        "feature": feature,
        "totals": {
            "requests": requests,
            "input_tokens": int(totals_row[1]),
            "output_tokens": int(totals_row[2]),
            "cost_usd": _round_cost(totals_row[3]),
            "avg_latency_ms": round(float(totals_row[4]), 1),
            "cache_hits": int(totals_row[5]),
            "cache_hit_rate": round(int(totals_row[5]) / requests, 4) if requests else 0.0,
            "fallbacks": int(totals_row[6]),
            "errors": int(totals_row[7]),
        },
        "by_model": [
            {
                "provider": r[0], "model": r[1], "requests": int(r[2]),
                "input_tokens": int(r[3]), "output_tokens": int(r[4]), "cost_usd": _round_cost(r[5]),
            }
            for r in by_model_rows
        ],
        "by_feature": [
            {
                "feature": r[0], "requests": int(r[1]),
                "input_tokens": int(r[2]), "output_tokens": int(r[3]), "cost_usd": _round_cost(r[4]),
            }
            for r in by_feature_rows
        ],
        "by_day": series,
        "available_features": [r[0] for r in available_rows],
        "freshness": await _freshness(db, user),
    }


async def _freshness(db: AsyncSession, user: User) -> dict:
    
    newest = (await db.execute(
        select(RequestLog.created_at, RequestLog.ingested_at)
        .where(RequestLog.user_id == user.id)
        .order_by(RequestLog.created_at.desc())
        .limit(1)
    )).first()
    last_event_at = newest[0] if newest else None
    lag = None
    if newest and newest[1] is not None:
        lag = round(max(0.0, (newest[1] - newest[0]).total_seconds()), 2)
    return {
        "pipeline": "kafka" if publisher.enabled else "direct",
        "last_event_at": last_event_at.isoformat() if last_event_at else None,
        "last_ingest_lag_seconds": lag,
    }


def _encode_cursor(created_at: datetime, row_id: uuid.UUID) -> str:
    return base64.urlsafe_b64encode(f"{created_at.isoformat()}|{row_id}".encode()).decode()


def _decode_cursor(cursor: str) -> tuple[datetime, uuid.UUID]:
    try:
        raw = base64.urlsafe_b64decode(cursor.encode()).decode()
        ts, row_id = raw.split("|", 1)
        return datetime.fromisoformat(ts), uuid.UUID(row_id)
    except Exception:
        raise HTTPException(status_code=400, detail="Invalid cursor")


@router.get("/logs")
async def usage_logs(
    limit: int = Query(default=50, ge=1, le=200),
    cursor: str | None = Query(default=None),
    feature: str | None = Query(default=None, max_length=50),
    user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
):
    conditions = [RequestLog.user_id == user.id]
    if feature:
        conditions.append(RequestLog.feature_tag.is_(None) if feature == UNTAGGED else RequestLog.feature_tag == feature)
    if cursor:
        ts, row_id = _decode_cursor(cursor)
        conditions.append(or_(
            RequestLog.created_at < ts,
            (RequestLog.created_at == ts) & (RequestLog.id < row_id),
        ))

  
    rows = (await db.execute(
        select(RequestLog).where(*conditions)
        .order_by(RequestLog.created_at.desc(), RequestLog.id.desc())
        .limit(limit + 1)
    )).scalars().all()

    has_more = len(rows) > limit
    rows = rows[:limit]
    return {
        "items": [
            {
                "id": str(r.id),
                "created_at": r.created_at.isoformat(),
                "provider": r.provider,
                "model": r.model,
                "feature_tag": r.feature_tag,
                "classification": r.classification,
                "input_tokens": r.input_tokens,
                "output_tokens": r.output_tokens,
                "cost_usd": _round_cost(r.cost_usd),
                "latency_ms": round(r.latency_ms or 0, 1),
                "cache_hit": r.cache_hit,
                "fallback_used": r.fallback_used,
                "error": (r.error[:200] if r.error else None),
            }
            for r in rows
        ],
        "next_cursor": _encode_cursor(rows[-1].created_at, rows[-1].id) if has_more and rows else None,
    }


def _month_start() -> datetime:
    now = datetime.now(timezone.utc)
    return now.replace(day=1, hour=0, minute=0, second=0, microsecond=0)


async def _budget_status(db: AsyncSession, user: User) -> dict:
    alert = await db.get(BudgetAlert, user.id)
    period_start = _month_start()
    spend = (await db.execute(
        select(func.coalesce(func.sum(RequestLog.cost_usd), 0.0))
        .where(RequestLog.user_id == user.id, RequestLog.created_at >= period_start)
    )).scalar_one()
    month_spend = _round_cost(spend)

    if alert is None:
        return {
            "threshold_amount": None, "notify_at_percent": 80, "period": "monthly",
            "period_start": period_start.isoformat(), "month_spend": month_spend,
            "percent_used": None, "state": "none",
        }

    percent_used = round(month_spend / alert.threshold_amount * 100, 1)
    if month_spend >= alert.threshold_amount:
        state = "exceeded"
    elif percent_used >= alert.notify_at_percent:
        state = "warning"
    else:
        state = "ok"
    return {
        "threshold_amount": alert.threshold_amount, "notify_at_percent": alert.notify_at_percent,
        "period": "monthly", "period_start": period_start.isoformat(),
        "month_spend": month_spend, "percent_used": percent_used, "state": state,
    }


@router.get("/budget")
async def get_budget(user: User = Depends(get_current_user), db: AsyncSession = Depends(get_db)):
    return await _budget_status(db, user)


@router.put("/budget")
async def set_budget(body: BudgetIn, user: User = Depends(get_current_user), db: AsyncSession = Depends(get_db)):
    existing = await db.get(BudgetAlert, user.id)

    if body.threshold_amount is None:
        if existing is not None:
            await db.delete(existing)
            await db.commit()
    elif existing is None:
        db.add(BudgetAlert(
            user_id=user.id, threshold_amount=body.threshold_amount, notify_at_percent=body.notify_at_percent,
        ))
        await db.commit()
    else:
        existing.threshold_amount = body.threshold_amount
        existing.notify_at_percent = body.notify_at_percent
        await db.commit()

    return await _budget_status(db, user)
