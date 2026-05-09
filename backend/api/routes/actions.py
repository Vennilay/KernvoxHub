import asyncio
import hmac
from typing import List

from fastapi import APIRouter, Depends, HTTPException, Request, status
from sqlalchemy.orm import Session

from api.routes.common import get_server_or_404
from config import settings
from models.action_audit import ActionAudit
from models.database import get_db
from schemas.action import ActionAuditResponse, ServerActionResponse
from services.server_actions import ServerConnectionData, reboot_server


router = APIRouter(prefix="/api/v1/servers", tags=["server-actions"])

ACTION_KEY_HEADER = "X-Action-Key"


def _get_requester(request: Request) -> str:
    real_ip = request.headers.get("x-real-ip")
    if real_ip:
        return real_ip.strip()
    return request.client.host if request.client else "unknown"


def _require_action_key(request: Request) -> None:
    if not settings.SERVER_ACTION_TOKEN:
        raise HTTPException(
            status_code=status.HTTP_503_SERVICE_UNAVAILABLE,
            detail="SERVER_ACTION_TOKEN is not configured",
        )

    provided = request.headers.get(ACTION_KEY_HEADER, "")
    if not hmac.compare_digest(provided, settings.SERVER_ACTION_TOKEN):
        raise HTTPException(
            status_code=status.HTTP_403_FORBIDDEN,
            detail="Server action key is required",
        )


def _create_audit(
    db: Session,
    *,
    server_id: int,
    action: str,
    status_value: str,
    requested_by: str,
    message: str,
) -> ActionAudit:
    audit = ActionAudit(
        server_id=server_id,
        action=action,
        status=status_value,
        requested_by=requested_by,
        message=message,
    )
    db.add(audit)
    db.commit()
    db.refresh(audit)
    return audit


@router.post(
    "/{server_id}/actions/reboot",
    response_model=ServerActionResponse,
    status_code=status.HTTP_202_ACCEPTED,
)
async def reboot_server_action(
    server_id: int,
    request: Request,
    db: Session = Depends(get_db),
) -> ServerActionResponse:
    _require_action_key(request)
    server = get_server_or_404(db, server_id, active_only=True)
    saved_host_key = server.host_key

    connection = ServerConnectionData(
        host=server.host,
        port=server.port,
        username=server.username,
        password=server.password,
        ssh_key=server.ssh_key,
        saved_host_key=saved_host_key,
    )
    result = await asyncio.to_thread(reboot_server, connection)

    if saved_host_key is None and result.discovered_host_key is not None:
        server.host_key = result.discovered_host_key
        db.commit()

    requester = _get_requester(request)
    audit = _create_audit(
        db,
        server_id=server.id,
        action="reboot",
        status_value=result.status,
        requested_by=requester,
        message=result.message,
    )

    if result.status == "host_key_mismatch":
        raise HTTPException(status_code=503, detail="Host key verification failed")
    if result.status in {"connect_failed", "failed", "error"}:
        raise HTTPException(status_code=503, detail=result.message)

    return ServerActionResponse(
        id=audit.id,
        server_id=server.id,
        server_name=server.name,
        action=audit.action,
        status=audit.status,
        message=audit.message,
        created_at=audit.created_at,
    )


@router.get("/{server_id}/actions", response_model=List[ActionAuditResponse])
def get_server_actions(
    server_id: int,
    limit: int = 50,
    db: Session = Depends(get_db),
) -> List[ActionAuditResponse]:
    get_server_or_404(db, server_id, active_only=True)
    safe_limit = max(1, min(limit, 200))
    return (
        db.query(ActionAudit)
        .filter(ActionAudit.server_id == server_id)
        .order_by(ActionAudit.created_at.desc(), ActionAudit.id.desc())
        .limit(safe_limit)
        .all()
    )
