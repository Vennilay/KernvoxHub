from pydantic import BaseModel, Field, ConfigDict
from typing import Optional
from datetime import datetime


class ServerBase(BaseModel):
    name: str = Field(..., min_length=1, max_length=255)
    host: str = Field(..., min_length=1)
    port: int = Field(default=22, ge=1, le=65535)
    username: str = Field(..., min_length=1, max_length=100)


class ServerCreate(ServerBase):
    ssh_key: Optional[str] = None
    password: Optional[str] = None


class ServerUpdate(BaseModel):
    name: Optional[str] = None
    host: Optional[str] = None
    port: Optional[int] = None
    username: Optional[str] = None
    ssh_key: Optional[str] = None
    password: Optional[str] = None
    is_active: Optional[bool] = None


class ServerResponse(ServerBase):
    id: int
    is_active: bool
    created_at: datetime
    updated_at: Optional[datetime] = None

    model_config = ConfigDict(from_attributes=True)
