from sqlalchemy import Column, Integer, String, DateTime, Text, ForeignKey
from sqlalchemy.sql import func

from models.database import Base


class ActionAudit(Base):
    __tablename__ = "action_audit"

    id = Column(Integer, primary_key=True, index=True)
    server_id = Column(Integer, ForeignKey("servers.id"), nullable=False, index=True)
    action = Column(String(64), nullable=False, index=True)
    status = Column(String(32), nullable=False, index=True)
    requested_by = Column(String(255), nullable=False)
    message = Column(Text, nullable=True)
    created_at = Column(DateTime(timezone=True), server_default=func.now(), nullable=False, index=True)

    def __repr__(self) -> str:
        return (
            f"<ActionAudit(id={self.id}, server_id={self.server_id}, "
            f"action='{self.action}', status='{self.status}')>"
        )
