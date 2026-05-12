from datetime import datetime, timedelta
import secrets
from urllib.parse import urlencode
import uuid
import bcrypt
import httpx
from fastapi import APIRouter, Cookie, Depends, Header, HTTPException, Request, Response, status
from fastapi.responses import RedirectResponse
from jose import JWTError, jwt
from sqlalchemy import func, select
from sqlalchemy.ext.asyncio import AsyncSession
from app.cache.redis_client import redis_client
from app.db.session import get_db
from app.models.user import User
from app.schemas.auth import LoginRequest, LoginResponse, SessionResponse, UserCreate
from app.config import settings
from app.services.audit_service import log_action

router = APIRouter()

MICROSOFT_STATE_COOKIE = "ms_oauth_state"
MICROSOFT_NONCE_COOKIE = "ms_oauth_nonce"


@router.get("/methods")
async def auth_methods():
    return {"microsoft": settings.microsoft_auth_enabled}


def hash_password(password: str) -> str:
    return bcrypt.hashpw(password.encode(), bcrypt.gensalt()).decode()


def verify_password(password: str, hashed: str) -> bool:
    return bcrypt.checkpw(password.encode(), hashed.encode())


def create_token(data: dict, expires_delta: timedelta) -> str:
    to_encode = data.copy()
    to_encode["exp"] = datetime.utcnow() + expires_delta
    return jwt.encode(to_encode, settings.secret_key, algorithm=settings.algorithm)


def decode_token(token: str) -> dict:
    try:
        return jwt.decode(token, settings.secret_key, algorithms=[settings.algorithm])
    except JWTError:
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail="Token inválido ou expirado",
            headers={"WWW-Authenticate": "Bearer"},
        )


async def get_active_user_from_token(token: str, db: AsyncSession) -> User:
    payload = decode_token(token)
    user_id = payload.get("sub")
    if not user_id:
        raise HTTPException(status_code=status.HTTP_401_UNAUTHORIZED, detail="Token sem usuário")
    try:
        user_uuid = uuid.UUID(user_id)
    except ValueError:
        raise HTTPException(status_code=status.HTTP_401_UNAUTHORIZED, detail="Token com usuário inválido")

    user = await db.get(User, user_uuid)
    if not user or not user.active:
        raise HTTPException(status_code=status.HTTP_401_UNAUTHORIZED, detail="Usuário inválido")
    return user


async def get_current_user(
    authorization: str | None = Header(None),
    session_token: str | None = Cookie(None, alias=settings.auth_cookie_name),
    db: AsyncSession = Depends(get_db),
) -> User:
    token = session_token
    if authorization and authorization.startswith("Bearer "):
        token = authorization.removeprefix("Bearer ").strip()
    if not token:
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail="Autenticação obrigatória",
            headers={"WWW-Authenticate": "Bearer"},
        )
    return await get_active_user_from_token(token, db)


async def _check_login_rate_limit(request: Request, email: str) -> None:
    host = request.client.host if request.client else "unknown"
    key = f"auth:login_fail:{host}:{email.lower()}"
    attempts = await redis_client.incr(key)
    if attempts == 1:
        await redis_client.expire(key, 300)
    if attempts > 10:
        raise HTTPException(status_code=429, detail="Muitas tentativas de login. Tente novamente em alguns minutos.")


def _set_auth_cookie(response: Response, token: str) -> None:
    response.set_cookie(
        key=settings.auth_cookie_name,
        value=token,
        max_age=settings.access_token_expire_minutes * 60,
        httponly=True,
        secure=settings.auth_cookie_secure,
        samesite=settings.auth_cookie_samesite,
        path="/",
    )


def _clear_auth_cookie(response: Response) -> None:
    response.delete_cookie(
        key=settings.auth_cookie_name,
        httponly=True,
        secure=settings.auth_cookie_secure,
        samesite=settings.auth_cookie_samesite,
        path="/",
    )


def _set_temp_oauth_cookie(response: Response, key: str, value: str) -> None:
    response.set_cookie(
        key=key,
        value=value,
        max_age=600,
        httponly=True,
        secure=settings.auth_cookie_secure,
        samesite="lax",
        path="/api/v1/auth/microsoft",
    )


def _clear_temp_oauth_cookies(response: Response) -> None:
    for key in (MICROSOFT_STATE_COOKIE, MICROSOFT_NONCE_COOKIE):
        response.delete_cookie(
            key=key,
            httponly=True,
            secure=settings.auth_cookie_secure,
            samesite="lax",
            path="/api/v1/auth/microsoft",
        )


def _microsoft_authority() -> str:
    tenant = settings.microsoft_tenant_id.strip()
    if not settings.microsoft_auth_enabled or not tenant or not settings.microsoft_client_id or not settings.microsoft_client_secret:
        raise HTTPException(status_code=503, detail="Login Microsoft não configurado")
    return f"https://login.microsoftonline.com/{tenant}/oauth2/v2.0"


def _microsoft_issuer() -> str:
    return f"https://login.microsoftonline.com/{settings.microsoft_tenant_id.strip()}/v2.0"


def _normalize_email(claims: dict) -> str:
    email = claims.get("email") or claims.get("preferred_username") or claims.get("upn")
    if not email or "@" not in email:
        raise HTTPException(status_code=401, detail="Conta Microsoft sem email válido")
    return email.lower()


def _assert_allowed_domain(email: str) -> None:
    allowed_domains = settings.microsoft_domains
    if allowed_domains and email.split("@", 1)[1].lower() not in allowed_domains:
        raise HTTPException(status_code=403, detail="Domínio Microsoft não autorizado")


async def _verify_microsoft_id_token(id_token: str, expected_nonce: str) -> dict:
    header = jwt.get_unverified_header(id_token)
    kid = header.get("kid")
    if not kid or header.get("alg") != "RS256":
        raise HTTPException(status_code=401, detail="Token Microsoft sem chave")

    keys_url = f"https://login.microsoftonline.com/{settings.microsoft_tenant_id.strip()}/discovery/v2.0/keys"
    try:
        async with httpx.AsyncClient(timeout=10) as client:
            response = await client.get(keys_url)
            response.raise_for_status()
    except httpx.HTTPError:
        raise HTTPException(status_code=503, detail="Falha ao buscar chaves Microsoft")
    key = next((item for item in response.json().get("keys", []) if item.get("kid") == kid), None)
    if not key:
        raise HTTPException(status_code=401, detail="Chave Microsoft não encontrada")

    try:
        claims = jwt.decode(
            id_token,
            key,
            algorithms=["RS256"],
            audience=settings.microsoft_client_id,
            issuer=_microsoft_issuer(),
            options={"verify_at_hash": False},
        )
    except JWTError:
        raise HTTPException(status_code=401, detail="Token Microsoft inválido")
    if claims.get("nonce") != expected_nonce:
        raise HTTPException(status_code=401, detail="Nonce Microsoft inválido")
    return claims


@router.post("/login", response_model=LoginResponse)
async def login(request: Request, response: Response, credentials: LoginRequest, db: AsyncSession = Depends(get_db)):
    result = await db.execute(select(User).where(User.email == credentials.email, User.active == True))
    user = result.scalar_one_or_none()
    if not user or not verify_password(credentials.password, user.hashed_password):
        await _check_login_rate_limit(request, credentials.email)
        raise HTTPException(status_code=status.HTTP_401_UNAUTHORIZED, detail="Credenciais inválidas")
    token = create_token(
        {"sub": str(user.id), "email": user.email, "role": user.role},
        timedelta(minutes=settings.access_token_expire_minutes),
    )
    user.last_login_at = datetime.utcnow()
    await log_action(db, "login", f"{user.name} fez login (local)", user=user)
    await db.commit()
    _set_auth_cookie(response, token)
    return LoginResponse(role=user.role, name=user.name, email=user.email)


@router.get("/microsoft/login")
async def microsoft_login():
    authority = _microsoft_authority()
    if not settings.microsoft_redirect_uri:
        raise HTTPException(status_code=503, detail="MICROSOFT_REDIRECT_URI não configurado")

    state = secrets.token_urlsafe(32)
    nonce = secrets.token_urlsafe(32)
    params = {
        "client_id": settings.microsoft_client_id,
        "response_type": "code",
        "redirect_uri": settings.microsoft_redirect_uri,
        "response_mode": "query",
        "scope": "openid profile email",
        "state": state,
        "nonce": nonce,
    }
    response = RedirectResponse(f"{authority}/authorize?{urlencode(params)}", status_code=302)
    _set_temp_oauth_cookie(response, MICROSOFT_STATE_COOKIE, state)
    _set_temp_oauth_cookie(response, MICROSOFT_NONCE_COOKIE, nonce)
    return response


@router.get("/microsoft/callback")
async def microsoft_callback(
    code: str | None = None,
    state: str | None = None,
    error: str | None = None,
    oauth_state: str | None = Cookie(None, alias=MICROSOFT_STATE_COOKIE),
    oauth_nonce: str | None = Cookie(None, alias=MICROSOFT_NONCE_COOKIE),
    db: AsyncSession = Depends(get_db),
):
    if error:
        raise HTTPException(status_code=401, detail=f"Microsoft recusou login: {error}")
    if not code or not state or not oauth_state or not oauth_nonce or not secrets.compare_digest(state, oauth_state):
        raise HTTPException(status_code=401, detail="Estado OAuth inválido")

    authority = _microsoft_authority()
    async with httpx.AsyncClient(timeout=15) as client:
        token_response = await client.post(
            f"{authority}/token",
            data={
                "client_id": settings.microsoft_client_id,
                "client_secret": settings.microsoft_client_secret,
                "code": code,
                "redirect_uri": settings.microsoft_redirect_uri,
                "grant_type": "authorization_code",
                "scope": "openid profile email",
            },
            headers={"Content-Type": "application/x-www-form-urlencoded"},
        )
    if token_response.status_code >= 400:
        raise HTTPException(status_code=401, detail="Falha ao trocar código Microsoft")

    id_token = token_response.json().get("id_token")
    if not id_token:
        raise HTTPException(status_code=401, detail="Resposta Microsoft sem id_token")
    claims = await _verify_microsoft_id_token(id_token, oauth_nonce)
    email = _normalize_email(claims)
    _assert_allowed_domain(email)

    result = await db.execute(select(User).where(User.email == email))
    user = result.scalar_one_or_none()
    if not user:
        if not settings.microsoft_auto_create_users:
            raise HTTPException(status_code=403, detail="Usuário não cadastrado")
        user = User(
            name=claims.get("name") or email.split("@", 1)[0],
            email=email,
            hashed_password=hash_password(secrets.token_urlsafe(48)),
            role=settings.microsoft_default_role,
        )
        db.add(user)
        await db.commit()
        await db.refresh(user)
    elif not user.active:
        raise HTTPException(status_code=401, detail="Usuário inativo")

    user.last_login_at = datetime.utcnow()
    await log_action(db, "login", f"{user.name} fez login (Microsoft)", user=user)
    await db.commit()
    session_token = create_token(
        {"sub": str(user.id), "email": user.email, "role": user.role},
        timedelta(minutes=settings.access_token_expire_minutes),
    )
    response = RedirectResponse(settings.post_login_redirect_url, status_code=302)
    _set_auth_cookie(response, session_token)
    _clear_temp_oauth_cookies(response)
    return response


@router.post("/logout")
async def logout(response: Response):
    _clear_auth_cookie(response)
    return {"message": "Sessão encerrada"}


@router.get("/me", response_model=SessionResponse)
async def me(current_user: User = Depends(get_current_user)):
    return SessionResponse(
        id=str(current_user.id),
        email=current_user.email,
        role=current_user.role,
        name=current_user.name,
    )


@router.post("/register", status_code=201)
async def register(
    data: UserCreate,
    authorization: str | None = Header(None),
    db: AsyncSession = Depends(get_db),
):
    user_count = await db.scalar(select(func.count(User.id))) or 0
    if user_count > 0:
        await get_current_user(authorization=authorization, db=db)

    result = await db.execute(select(User).where(User.email == data.email))
    if result.scalar_one_or_none():
        raise HTTPException(status_code=400, detail="Email já cadastrado")
    user = User(
        name=data.name,
        email=data.email,
        hashed_password=hash_password(data.password),
        role="ADMIN" if user_count == 0 else data.role,
    )
    db.add(user)
    await db.commit()
    return {"message": "Usuário criado com sucesso"}
