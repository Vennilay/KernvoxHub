from fastapi import APIRouter, Depends, HTTPException, Query
from sqlalchemy.orm import Session
from typing import List, Optional
from datetime import datetime

from models.database import get_db
from models.server import Server
from models.metric import Metric
from schemas.metric import MetricCreate, MetricResponse, MetricsHistoryResponse

router = APIRouter(prefix="/api/v1", tags=["metrics"])


@router.get("/servers/{server_id}/metrics", response_model=List[MetricResponse])
def get_current_metrics(
    server_id: int,
    limit: int = Query(default=1, ge=1, le=10),
    db: Session = Depends(get_db)
) -> List[MetricResponse]:
    server = db.query(Server).filter(Server.id == server_id).first()
    if not server:
        raise HTTPException(status_code=404, detail="Server not found")

    metrics = (
        db.query(Metric)
        .filter(Metric.server_id == server_id)
        .order_by(Metric.timestamp.desc())
        .limit(limit)
        .all()
    )
    return metrics


@router.get("/servers/{server_id}/metrics/history", response_model=MetricsHistoryResponse)
def get_metrics_history(
    server_id: int,
    from_date: Optional[datetime] = Query(None, alias="from"),
    to_date: Optional[datetime] = Query(None, alias="to"),
    db: Session = Depends(get_db)
) -> MetricsHistoryResponse:
    server = db.query(Server).filter(Server.id == server_id).first()
    if not server:
        raise HTTPException(status_code=404, detail="Server not found")

    query = db.query(Metric).filter(Metric.server_id == server_id)

    if from_date:
        query = query.filter(Metric.timestamp >= from_date)
    if to_date:
        query = query.filter(Metric.timestamp <= to_date)

    metrics = query.order_by(Metric.timestamp.desc()).all()

    return MetricsHistoryResponse(
        server_id=server_id,
        server_name=server.name,
        metrics=metrics
    )


@router.post("/servers/{server_id}/metrics", response_model=MetricResponse, status_code=201)
def create_metric(
    server_id: int,
    metric: MetricCreate,
    db: Session = Depends(get_db)
) -> MetricResponse:
    server = db.query(Server).filter(Server.id == server_id).first()
    if not server:
        raise HTTPException(status_code=404, detail="Server not found")

    db_metric = Metric(**metric.model_dump(), server_id=server_id)
    db.add(db_metric)
    db.commit()
    db.refresh(db_metric)
    return db_metric
