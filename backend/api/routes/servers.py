from fastapi import APIRouter, Depends, HTTPException, status
from sqlalchemy.orm import Session
from typing import List

from models.database import get_db
from models.server import Server
from schemas.server import ServerCreate, ServerUpdate, ServerResponse

router = APIRouter(prefix="/api/v1/servers", tags=["servers"])


@router.get("", response_model=List[ServerResponse])
def get_servers(skip: int = 0, limit: int = 100, db: Session = Depends(get_db)) -> List[ServerResponse]:
    servers = db.query(Server).filter(Server.is_active == True).offset(skip).limit(limit).all()
    return servers


@router.get("/{server_id}", response_model=ServerResponse)
def get_server(server_id: int, db: Session = Depends(get_db)) -> ServerResponse:
    server = db.query(Server).filter(Server.id == server_id).first()
    if not server:
        raise HTTPException(status_code=404, detail="Server not found")
    return server


@router.post("", response_model=ServerResponse, status_code=status.HTTP_201_CREATED)
def create_server(server: ServerCreate, db: Session = Depends(get_db)) -> ServerResponse:
    db_server = Server(**server.model_dump())
    db.add(db_server)
    db.commit()
    db.refresh(db_server)
    return db_server


@router.put("/{server_id}", response_model=ServerResponse)
def update_server(server_id: int, server: ServerUpdate, db: Session = Depends(get_db)) -> ServerResponse:
    db_server = db.query(Server).filter(Server.id == server_id).first()
    if not db_server:
        raise HTTPException(status_code=404, detail="Server not found")

    update_data = server.model_dump(exclude_unset=True)
    for field, value in update_data.items():
        setattr(db_server, field, value)

    db.commit()
    db.refresh(db_server)
    return db_server


@router.delete("/{server_id}", status_code=status.HTTP_204_NO_CONTENT)
def delete_server(server_id: int, db: Session = Depends(get_db)) -> None:
    db_server = db.query(Server).filter(Server.id == server_id).first()
    if not db_server:
        raise HTTPException(status_code=404, detail="Server not found")

    db_server.is_active = False
    db.commit()
