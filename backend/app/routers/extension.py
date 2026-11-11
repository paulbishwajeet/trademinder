"""Browser extension sign-in (connect) and the user's extension tokens."""
import uuid

from fastapi import APIRouter, Depends, HTTPException, Request
from sqlalchemy.ext.asyncio import AsyncSession

from app.database import get_db
from app.deps import get_current_user, require_session_user
from app.models.user import User
from app.schemas.auth import ExtensionConnectRequest, ExtensionConnectResponse, ExtensionTokenResponse
from app.services import auth as auth_service

router = APIRouter(prefix="/api/extension", tags=["extension"])


@router.post("/connect", response_model=ExtensionConnectResponse)
async def connect(
    payload: ExtensionConnectRequest, db: AsyncSession = Depends(get_db), user: User = Depends(require_session_user),
):
    """Called by the portal's /extension/connect page after the user approves. The token goes back to
    the extension only, in the fragment of its chromiumapp.org redirect (never sent to any server)."""
    redirect = auth_service.validate_extension_redirect(payload.redirect_uri)
    token = await auth_service.create_extension_token(db, user, payload.device_name)
    from urllib.parse import urlencode
    return ExtensionConnectResponse(redirect_to=f"{redirect}#{urlencode({'token': token, 'email': user.email})}")


@router.get("/tokens", response_model=list[ExtensionTokenResponse])
async def list_tokens(db: AsyncSession = Depends(get_db), user: User = Depends(get_current_user)):
    return await auth_service.list_extension_tokens(db, user)


# Declared before /tokens/{token_id} so "current" is never parsed as an id.
@router.delete("/tokens/current", status_code=204)
async def revoke_current(request: Request, db: AsyncSession = Depends(get_db), user: User = Depends(get_current_user)):
    """The extension's Sign out: revoke the bearer token this request was made with."""
    auth = request.headers.get("authorization", "")
    if getattr(request.state, "auth_kind", None) != "token" or not auth.lower().startswith("bearer "):
        raise HTTPException(status_code=400, detail="No extension token on this request")
    await auth_service.revoke_extension_token_value(db, auth[7:].strip())


@router.delete("/tokens/{token_id}", status_code=204)
async def revoke(token_id: uuid.UUID, db: AsyncSession = Depends(get_db), user: User = Depends(get_current_user)):
    await auth_service.revoke_extension_token(db, user, token_id)
