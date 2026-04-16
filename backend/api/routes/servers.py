from fastapi import APIRouter, Depends, status
from sqlalchemy.orm import Session
from typing import List

from models.database import get_db
from api.routes.common import get_server_or_404
from models.server import Server
from schemas.server import ServerCreate, ServerUpdate, ServerResponse

router = APIRouter(prefix="/api/v1/servers", tags=["servers"])


@router.get("", response_model=List[ServerResponse])
def get_servers(skip: int = 0, limit: int = 100, db: Session = Depends(get_db)) -> List[ServerResponse]:
    servers = db.query(Server).filter(Server.is_active == True).offset(skip).limit(limit).all()
    return servers


@router.get("/{server_id}", response_model=ServerResponse)
def get_server(server_id: int, db: Session = Depends(get_db)) -> ServerResponse:
    return get_server_or_404(db, server_id, active_only=True)


@router.post("", response_model=ServerResponse, status_code=status.HTTP_201_CREATED)
def create_server(server: ServerCreate, db: Session = Depends(get_db)) -> ServerResponse:
    db_server = Server(**server.model_dump())
    db.add(db_server)
    db.commit()
    db.refresh(db_server)
    return db_server


@router.put("/{server_id}", response_model=ServerResponse)
def update_server(server_id: int, server: ServerUpdate, db: Session = Depends(get_db)) -> ServerResponse:
    db_server = get_server_or_404(db, server_id, active_only=True)

    update_data = server.model_dump(exclude_unset=True)
    host_changed = "host" in update_data and update_data["host"] != db_server.host
    port_changed = "port" in update_data and update_data["port"] != db_server.port

    for field, value in update_data.items():
        setattr(db_server, field, value)

    if host_changed or port_changed:
        db_server.host_key = None

    db.commit()
    db.refresh(db_server)
    return db_server


@router.delete("/{server_id}", status_code=status.HTTP_204_NO_CONTENT)
def delete_server(server_id: int, db: Session = Depends(get_db)) -> None:
    db_server = get_server_or_404(db, server_id, active_only=True)
    db_server.is_active = False
    db.commit()
