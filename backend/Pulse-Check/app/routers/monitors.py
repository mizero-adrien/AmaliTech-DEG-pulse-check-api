import logging
from datetime import datetime, timezone
from typing import List

from fastapi import APIRouter, Depends, HTTPException, Query, Request, status
from sqlalchemy import func, select
from sqlalchemy.ext.asyncio import AsyncSession

from app.database import get_db
from app.main import limiter
from app.models import Alert, Monitor
from app.schemas import (
    AlertOut,
    DashboardOut,
    DeviceHistoryOut,
    DiagnosisBreakdown,
    MonitorCreate,
    MonitorOut,
    MonitorStatusOut,
    PaginatedAlertsOut,
    PaginatedMonitorsOut,
    PaginationMeta,
)
from app.security import verify_any_auth, verify_api_key, verify_jwt

logger = logging.getLogger(__name__)
router = APIRouter(prefix="/monitors", tags=["monitors"])


@limiter.limit("10/minute")
@router.post("", status_code=status.HTTP_201_CREATED, response_model=MonitorOut, dependencies=[Depends(verify_any_auth)])
async def create_monitor(request: Request, payload: MonitorCreate, db: AsyncSession = Depends(get_db)):
    result = await db.execute(select(Monitor).where(Monitor.id == payload.id))
    if result.scalar_one_or_none():
        raise HTTPException(
            status_code=status.HTTP_409_CONFLICT,
            detail=f"Monitor '{payload.id}' already exists",
        )

    monitor = Monitor(
        id=payload.id,
        timeout=payload.timeout,
        alert_email=str(payload.alert_email),
        status="active",
        last_ping=datetime.now(timezone.utc),
    )
    db.add(monitor)
    await db.commit()
    await db.refresh(monitor)

    request_id = getattr(request.state, "request_id", "N/A")
    logger.info("Request ID: %s | Monitor '%s' registered (timeout=%ds, email=%s)", request_id, payload.id, payload.timeout, payload.alert_email)
    return monitor


@limiter.limit("60/minute")
@router.post("/{device_id}/heartbeat", response_model=MonitorOut, dependencies=[Depends(verify_api_key)])
async def heartbeat(request: Request, device_id: str, db: AsyncSession = Depends(get_db)):
    monitor = await _get_or_404(db, device_id)
    prev_status = monitor.status

    monitor.last_ping = datetime.now(timezone.utc)
    if monitor.status in ("paused", "down"):
        monitor.status = "active"

    await db.commit()
    await db.refresh(monitor)

    request_id = getattr(request.state, "request_id", "N/A")
    logger.info("Request ID: %s | Heartbeat '%s' (prev=%s now=%s)", request_id, device_id, prev_status, monitor.status)
    return monitor


@limiter.limit("10/minute")
@router.post("/{device_id}/pause", response_model=MonitorOut, dependencies=[Depends(verify_api_key)])
async def pause_monitor(request: Request, device_id: str, db: AsyncSession = Depends(get_db)):
    monitor = await _get_or_404(db, device_id)
    monitor.status = "paused"
    await db.commit()
    await db.refresh(monitor)
    request_id = getattr(request.state, "request_id", "N/A")
    logger.info("Request ID: %s | Monitor '%s' paused", request_id, device_id)
    return monitor


@router.get("/{device_id}/status", response_model=MonitorStatusOut, dependencies=[Depends(verify_jwt)])
async def get_status(request: Request, device_id: str, db: AsyncSession = Depends(get_db)):
    monitor = await _get_or_404(db, device_id)

    result = await db.execute(
        select(Alert)
        .where(Alert.device_id == device_id)
        .order_by(Alert.created_at.desc())
        .limit(5)
    )
    recent_alerts = result.scalars().all()

    out = MonitorStatusOut.model_validate(monitor)
    out.alerts = [AlertOut.model_validate(a) for a in recent_alerts]
    return out


@router.get("", response_model=PaginatedMonitorsOut, dependencies=[Depends(verify_jwt)])
async def list_monitors(
    request: Request,
    page: int = Query(default=1, ge=1, description="Page number"),
    limit: int = Query(default=10, ge=1, le=100, description="Items per page"),
    status: str = Query(default=None, description="Filter by status: active, down, paused"),
    db: AsyncSession = Depends(get_db),
):
    request_id = getattr(request.state, "request_id", "N/A")

    query = select(Monitor)
    count_query = select(func.count(Monitor.id))

    if status:
        if status not in ("active", "down", "paused"):
            raise HTTPException(
                status_code=400,
                detail="Invalid status filter. Must be: active, down, or paused",
            )
        query = query.where(Monitor.status == status)
        count_query = count_query.where(Monitor.status == status)

    total_result = await db.execute(count_query)
    total = total_result.scalar_one()

    offset = (page - 1) * limit
    total_pages = max(1, -(-total // limit))

    query = query.order_by(Monitor.created_at.desc()).offset(offset).limit(limit)
    result = await db.execute(query)
    monitors = result.scalars().all()

    logger.info(
        "Request ID: %s | Listed monitors page=%d limit=%d status=%s",
        request_id, page, limit, status,
    )

    return PaginatedMonitorsOut(
        data=monitors,
        meta=PaginationMeta(
            total=total,
            page=page,
            limit=limit,
            total_pages=total_pages,
            has_next=page < total_pages,
            has_previous=page > 1,
        ),
    )


@router.get("/dashboard", response_model=DashboardOut, dependencies=[Depends(verify_jwt)])
async def get_dashboard(request: Request, db: AsyncSession = Depends(get_db)):
    request_id = getattr(request.state, "request_id", "N/A")

    monitors_result = await db.execute(select(Monitor))
    all_monitors = monitors_result.scalars().all()

    total_devices = len(all_monitors)
    active_devices = len([m for m in all_monitors if m.status == "active"])
    down_devices = len([m for m in all_monitors if m.status == "down"])
    paused_devices = len([m for m in all_monitors if m.status == "paused"])

    health_scores = [m.health_score for m in all_monitors if m.health_score is not None]
    average_health_score = round(sum(health_scores) / len(health_scores), 2) if health_scores else 0.0

    today = datetime.now(timezone.utc).replace(hour=0, minute=0, second=0, microsecond=0)
    today_alerts_result = await db.execute(select(Alert).where(Alert.created_at >= today))
    total_alerts_today = len(today_alerts_result.scalars().all())

    all_alerts_count_result = await db.execute(select(func.count(Alert.id)))
    total_alerts_all_time = all_alerts_count_result.scalar_one()

    all_alerts_result = await db.execute(select(Alert))
    all_alerts = all_alerts_result.scalars().all()

    breakdown = DiagnosisBreakdown()
    for alert in all_alerts:
        if alert.ai_analysis:
            analysis_lower = alert.ai_analysis.lower()
            if "power failure" in analysis_lower:
                breakdown.power_failure += 1
            elif "network issue" in analysis_lower:
                breakdown.network_issue += 1
            elif "hardware failure" in analysis_lower:
                breakdown.hardware_failure += 1
            elif "theft" in analysis_lower:
                breakdown.theft += 1
            else:
                breakdown.unknown += 1

    recent_alert_result = await db.execute(
        select(Alert).order_by(Alert.created_at.desc()).limit(1)
    )
    recent_alert = recent_alert_result.scalar_one_or_none()
    most_recent_alert = recent_alert.message if recent_alert else None

    if down_devices == 0:
        system_status = "ALL SYSTEMS OPERATIONAL"
    elif down_devices <= total_devices * 0.3:
        system_status = "DEGRADED - Some devices offline"
    else:
        system_status = "CRITICAL - Multiple devices offline"

    logger.info("Request ID: %s | Dashboard generated", request_id)

    return DashboardOut(
        total_devices=total_devices,
        active_devices=active_devices,
        down_devices=down_devices,
        paused_devices=paused_devices,
        total_alerts_today=total_alerts_today,
        total_alerts_all_time=total_alerts_all_time,
        ai_diagnosis_breakdown=breakdown,
        average_health_score=average_health_score,
        most_recent_alert=most_recent_alert,
        system_status=system_status,
        generated_at=datetime.now(timezone.utc),
    )


@router.delete("/{device_id}", dependencies=[Depends(verify_jwt)])
async def delete_monitor(device_id: str, db: AsyncSession = Depends(get_db)):
    monitor = await _get_or_404(db, device_id)
    await db.delete(monitor)
    await db.commit()
    logger.info("Monitor '%s' deleted", device_id)
    return {"message": f"Monitor '{device_id}' deleted successfully"}



@router.get("/{device_id}/history", response_model=DeviceHistoryOut, dependencies=[Depends(verify_jwt)])
async def get_history(
    request: Request,
    device_id: str,
    page: int = Query(default=1, ge=1, description="Page number"),
    limit: int = Query(default=10, ge=1, le=100, description="Items per page"),
    db: AsyncSession = Depends(get_db),
):
    monitor = await _get_or_404(db, device_id)
    request_id = getattr(request.state, "request_id", "N/A")

    count_result = await db.execute(
        select(func.count(Alert.id)).where(Alert.device_id == device_id)
    )
    total_alerts = count_result.scalar_one()

    offset = (page - 1) * limit
    result = await db.execute(
        select(Alert)
        .where(Alert.device_id == device_id)
        .order_by(Alert.created_at.desc())
        .offset(offset)
        .limit(limit)
    )
    alerts = result.scalars().all()

    now = datetime.now(timezone.utc)
    created_at = monitor.created_at
    if created_at.tzinfo is None:
        created_at = created_at.replace(tzinfo=timezone.utc)
    total_seconds = max((now - created_at).total_seconds(), 1.0)
    estimated_downtime = total_alerts * monitor.timeout
    uptime_pct = max(0.0, min(100.0, (1 - estimated_downtime / total_seconds) * 100))

    all_alerts_result = await db.execute(
        select(Alert)
        .where(Alert.device_id == device_id)
        .order_by(Alert.created_at.asc())
    )
    all_alerts = all_alerts_result.scalars().all()
    avg_response_time = None
    if len(all_alerts) >= 2:
        times = [
            a.created_at if a.created_at.tzinfo else a.created_at.replace(tzinfo=timezone.utc)
            for a in all_alerts
        ]
        diffs = [(times[i + 1] - times[i]).total_seconds() for i in range(len(times) - 1)]
        avg_response_time = round(sum(diffs) / len(diffs), 2)

    total_pages = max(1, -(-total_alerts // limit))

    logger.info("Request ID: %s | History for '%s' page=%d", request_id, device_id, page)

    return DeviceHistoryOut(
        device_id=device_id,
        uptime_percentage=round(uptime_pct, 2),
        average_response_time_seconds=avg_response_time,
        total_alerts=total_alerts,
        alerts=[AlertOut.model_validate(a) for a in alerts],
        page=page,
        limit=limit,
        total_pages=total_pages,
        has_next=page < total_pages,
        has_previous=page > 1,
    )


async def _get_or_404(db: AsyncSession, device_id: str) -> Monitor:
    result = await db.execute(select(Monitor).where(Monitor.id == device_id))
    monitor = result.scalar_one_or_none()
    if not monitor:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail=f"Monitor '{device_id}' not found",
        )
    return monitor
