from sqlalchemy import Column, Integer, String, Float, Boolean, DateTime, Index, ForeignKey
from sqlalchemy.sql import func

from models.database import Base


class Metric(Base):
    __tablename__ = "metrics"

    id = Column(Integer, primary_key=True, index=True)
    server_id = Column(Integer, ForeignKey("servers.id"), nullable=False, index=True)

    cpu_percent = Column(Float, default=0.0)
    ram_used_mb = Column(Float, default=0.0)
    ram_total_mb = Column(Float, default=0.0)
    ram_percent = Column(Float, default=0.0)
    disk_used_percent = Column(Float, default=0.0)
    network_rx_bytes = Column(Float, default=0.0)
    network_tx_bytes = Column(Float, default=0.0)
    uptime_seconds = Column(Float, default=0.0)
    is_available = Column(Boolean, default=True)

    timestamp = Column(DateTime(timezone=True), server_default=func.now(), index=True)

    __table_args__ = (
        Index("ix_metrics_server_id_timestamp", "server_id", "timestamp"),
    )

    def __repr__(self) -> str:
        return f"<Metric(id={self.id}, server_id={self.server_id}, cpu={self.cpu_percent}%, timestamp={self.timestamp})>"
