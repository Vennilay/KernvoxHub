from fastapi import APIRouter, Depends, HTTPException, Query, Request
from sqlalchemy.orm import Session
from typing import List, Optional, Literal
from datetime import datetime

from api.routes.common import get_server_or_404
from models.database import get_db
from models.metric import Metric
from schemas.metric import (
    MetricCreate,
    MetricResponse,
    MetricsHistoryResponse,
    MetricsSeriesResponse,
)
from config import settings
from services.metric_series import build_metrics_series_response

router = APIRouter(prefix="/api/v1", tags=["metrics"])


def _check_internal_key(request: Request) -> None:
    """Эндпоинты записи метрик требуют INTERNAL_API_KEY."""
    if not settings.INTERNAL_API_KEY:
        return
    provided = request.headers.get("X-Internal-Key", "")
    if provided != settings.INTERNAL_API_KEY:
        raise HTTPException(status_code=403, detail="Internal access only")


@router.get("/servers/{server_id}/metrics", response_model=List[MetricResponse])
def get_current_metrics(
    server_id: int,
    limit: int = Query(default=1, ge=1, le=10),
    db: Session = Depends(get_db),
) -> List[MetricResponse]:
    get_server_or_404(db, server_id, active_only=True)

    metrics = (
        db.query(Metric)
        .filter(Metric.server_id == server_id)
        .order_by(Metric.timestamp.desc(), Metric.id.desc())
        .limit(limit)
        .all()
    )
    return metrics


@router.get("/servers/{server_id}/metrics/history", response_model=MetricsHistoryResponse)
def get_metrics_history(
    server_id: int,
    from_date: Optional[datetime] = Query(None, alias="from"),
    to_date: Optional[datetime] = Query(None, alias="to"),
    limit: int = Query(default=100, ge=1, le=1000),
    db: Session = Depends(get_db),
) -> MetricsHistoryResponse:
    server = get_server_or_404(db, server_id, active_only=True)

    query = db.query(Metric).filter(Metric.server_id == server_id)

    if from_date:
        query = query.filter(Metric.timestamp >= from_date)
    if to_date:
        query = query.filter(Metric.timestamp <= to_date)

    metrics = query.order_by(Metric.timestamp.desc(), Metric.id.desc()).limit(limit).all()

    return MetricsHistoryResponse(
        server_id=server_id,
        server_name=server.name,
        metrics=metrics,
    )


@router.get("/servers/{server_id}/metrics/timeseries", response_model=MetricsSeriesResponse)
def get_metrics_timeseries(
    server_id: int,
    from_date: Optional[datetime] = Query(None, alias="from"),
    to_date: Optional[datetime] = Query(None, alias="to"),
    interval: Literal["raw", "1m", "5m", "15m", "1h", "6h", "1d"] = Query(default="raw"),
    order: Literal["asc", "desc"] = Query(default="asc"),
    limit: int = Query(default=200, ge=1, le=2000),
    db: Session = Depends(get_db),
) -> MetricsSeriesResponse:
    server = get_server_or_404(db, server_id, active_only=True)

    if from_date and to_date and from_date > to_date:
        raise HTTPException(status_code=400, detail="'from' must be earlier than or equal to 'to'")

    query = db.query(Metric).filter(Metric.server_id == server_id)

    if from_date:
        query = query.filter(Metric.timestamp >= from_date)
    if to_date:
        query = query.filter(Metric.timestamp <= to_date)

    metrics = query.order_by(Metric.timestamp.asc(), Metric.id.asc()).all()

    return build_metrics_series_response(
        server_id=server_id,
        server_name=server.name,
        metrics=metrics,
        interval=interval,
        order=order,
        from_date=from_date,
        to_date=to_date,
        limit=limit,
    )


@router.post("/servers/{server_id}/metrics", response_model=MetricResponse, status_code=201)
async def create_metric(
    server_id: int,
    metric: MetricCreate,
    request: Request,
    db: Session = Depends(get_db),
) -> MetricResponse:
    _check_internal_key(request)
    get_server_or_404(db, server_id, active_only=True)

    db_metric = Metric(**metric.model_dump(), server_id=server_id)
    db.add(db_metric)
    db.commit()
    db.refresh(db_metric)
    return db_metric
