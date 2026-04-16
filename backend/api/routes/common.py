from fastapi import HTTPException
from sqlalchemy.orm import Session

from models.server import Server


def get_server_or_404(db: Session, server_id: int, *, active_only: bool = False) -> Server:
    query = db.query(Server).filter(Server.id == server_id)
    if active_only:
        query = query.filter(Server.is_active.is_(True))

    server = query.first()
    if not server:
        raise HTTPException(status_code=404, detail="Server not found")
    return server
