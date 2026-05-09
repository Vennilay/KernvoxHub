from datetime import datetime
from typing import Optional

from pydantic import BaseModel, ConfigDict


class ServerActionResponse(BaseModel):
    id: int
    server_id: int
    server_name: str
    action: str
    status: str
    message: Optional[str] = None
    created_at: datetime


class ActionAuditResponse(BaseModel):
    id: int
    server_id: int
    action: str
    status: str
    requested_by: str
    message: Optional[str] = None
    created_at: datetime

    model_config = ConfigDict(from_attributes=True)
