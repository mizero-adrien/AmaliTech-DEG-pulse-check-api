import logging
from datetime import datetime, timezone

from apscheduler.schedulers.asyncio import AsyncIOScheduler
from sqlalchemy import func, select, update

from app.database import AsyncSessionLocal
from app.models import Alert, Monitor
from app.services.ai_analyzer import analyze_device_failure

logger = logging.getLogger(__name__)

scheduler = AsyncIOScheduler(timezone="UTC")


async def check_monitors() -> None:
    """Tick function: detect every active monitor that has exceeded its timeout."""
    async with AsyncSessionLocal() as db:
        try:
            now = datetime.now(timezone.utc)
            result = await db.execute(select(Monitor).where(Monitor.status == "active"))
            active = result.scalars().all()

            for monitor in active:
                last_ping = monitor.last_ping
                if last_ping is None:
                    continue
                if last_ping.tzinfo is None:
                    last_ping = last_ping.replace(tzinfo=timezone.utc)
                if (now - last_ping).total_seconds() >= monitor.timeout:
                    await _handle_timeout(db, monitor)

        except Exception:
            logger.exception("Unhandled error in check_monitors")


async def _handle_timeout(db, monitor: Monitor) -> None:
    """
    Atomically claim the monitor (status active → down) then run AI analysis.
    The WHERE status='active' guard prevents duplicate alerts if ticks overlap.
    """
    result = await db.execute(
        update(Monitor)
        .where(Monitor.id == monitor.id, Monitor.status == "active")
        .values(status="down")
    )
    await db.commit()

    if result.rowcount == 0:
        return  # Another tick already handled this monitor

    logger.warning("Device '%s' timed out — requesting AI diagnosis", monitor.id)

    count_result = await db.execute(
        select(func.count(Alert.id)).where(Alert.device_id == monitor.id)
    )
    previous_count = count_result.scalar_one()

    try:
        analysis = await analyze_device_failure(
            device_id=monitor.id,
            last_ping=monitor.last_ping,
            timeout=monitor.timeout,
            previous_alert_count=previous_count,
        )
    except Exception as exc:
        logger.error("AI analysis failed for '%s': %s", monitor.id, exc)
        analysis = {
            "diagnosis": "unknown",
            "recommended_action": "Investigate manually",
            "confidence": "0%",
            "health_score": 0,
        }

    await db.execute(
        update(Monitor)
        .where(Monitor.id == monitor.id)
        .values(health_score=float(analysis.get("health_score", 0)))
    )

    alert = Alert(
        device_id=monitor.id,
        message=f"Device '{monitor.id}' timed out after {monitor.timeout}s with no heartbeat",
        ai_analysis=(
            f"{analysis.get('diagnosis', 'unknown')} — "
            f"{analysis.get('recommended_action', '')}"
        ),
        confidence=str(analysis.get("confidence", "0%")),
    )
    db.add(alert)
    await db.commit()

    logger.warning(
        "\n%s\n[ALERT] Device '%s' is DOWN\n"
        "  Diagnosis:  %s\n"
        "  Action:     %s\n"
        "  Confidence: %s\n"
        "  Health:     %s/100\n"
        "  Email:      %s\n%s",
        "=" * 60, monitor.id,
        analysis.get("diagnosis"),
        analysis.get("recommended_action"),
        analysis.get("confidence"),
        analysis.get("health_score"),
        monitor.alert_email,
        "=" * 60,
    )


async def startup_check() -> None:
    """
    Run immediately on server startup to catch any monitors that timed out
    while the server was down — so no timeout is silently missed on restart.
    """
    logger.info("Running startup recovery check for missed timeouts...")
    await check_monitors()
    logger.info("Startup recovery check complete")


def start_scheduler() -> None:
    scheduler.add_job(
        check_monitors,
        "interval",
        seconds=1,
        id="monitor_check",
        replace_existing=True,
        max_instances=1,  # Skip tick if previous one is still running (e.g. slow AI call)
    )
    scheduler.start()
    logger.info("APScheduler started — polling monitors every 1s")


def stop_scheduler() -> None:
    if scheduler.running:
        scheduler.shutdown(wait=False)
        logger.info("APScheduler stopped")
