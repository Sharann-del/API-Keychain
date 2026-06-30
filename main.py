"""API Keychain — an AI API gateway aggregating free-tier LLM providers behind
a single OpenAI-compatible endpoint.

Run with:  uvicorn main:app --reload
Requires environment variables:
  MASTER_SECRET        — encrypts stored provider keys (AES-256-GCM).
  SUPABASE_JWT_SECRET  — verifies Supabase JWTs on the /users/... management
                         routes (HS256). Not needed for /v1/* (ak-... auth).
"""

from __future__ import annotations

import env_loader  # noqa: F401 — load .env.local before models/crypto read env

import base64
import datetime as dt
import os
import secrets
import time
from contextlib import asynccontextmanager
from typing import Any, AsyncIterator, Callable, Dict, List, Literal, Optional, Tuple

import jwt

from fastapi import Depends, FastAPI, Header, HTTPException, Path, Query, Request
from fastapi.encoders import jsonable_encoder
from fastapi.exceptions import RequestValidationError
from fastapi.responses import JSONResponse, StreamingResponse
from pydantic import BaseModel, Field
from sqlalchemy import func, select
from sqlalchemy.orm import Session
from starlette.exceptions import HTTPException as StarletteHTTPException

from anthropic_adapter import (
    anthropic_error,
    anthropic_to_openai_body,
    convert_openai_stream_to_anthropic,
    estimate_input_tokens,
    openai_to_anthropic_message,
    resolve_effort as resolve_anthropic_effort,
)
from responses_adapter import (
    convert_openai_stream_to_responses,
    openai_to_responses_response,
    resolve_responses_effort,
    responses_to_openai_body,
)
from crypto import encrypt, hash_token, mask_token
from models import (
    KeychainKey,
    ProviderHealth,
    ProviderKey,
    RequestLog,
    SessionLocal,
    User,
    UserModel,
    UserPreference,
    init_db,
)
from registry import (
    MODEL_TIERS,
    SUPPORTED_PROVIDERS,
    build_effective_table,
    effective_cascade,
    models_by_tier,
    provider_catalog,
)
from router import (
    COOLDOWN_SECONDS,
    AllProvidersFailed,
    Attempt,
    NoModelsAvailable,
    RouteResult,
    StreamHandle,
    iter_stream,
    open_stream,
    route_chat_completion,
)


def _utcnow() -> dt.datetime:
    return dt.datetime.now(dt.timezone.utc)


def _as_aware(d: Optional[dt.datetime]) -> Optional[dt.datetime]:
    """Normalize a possibly-naive stored datetime to aware UTC for comparison."""
    if d is None:
        return None
    return d if d.tzinfo is not None else d.replace(tzinfo=dt.timezone.utc)


@asynccontextmanager
async def _lifespan(app: FastAPI):
    init_db()
    yield


app = FastAPI(title="API Keychain", version="1.0.0", lifespan=_lifespan)

# Allow the Next.js dashboard (browser) to call the management routes directly.
from fastapi.middleware.cors import CORSMiddleware  # noqa: E402

_cors_origins = os.environ.get(
    "CORS_ORIGINS",
    "http://localhost:3000,https://www.apikeychain.dev,https://apikeychain.dev",
)
app.add_middleware(
    CORSMiddleware,
    allow_origins=[o.strip() for o in _cors_origins.split(",") if o.strip()],
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)


# --------------------------------------------------------------------------- #
# DB dependency
# --------------------------------------------------------------------------- #
def get_db() -> Session:
    db = SessionLocal()
    try:
        yield db
    finally:
        db.close()


# --------------------------------------------------------------------------- #
# Schemas
# --------------------------------------------------------------------------- #
class StoreKeyRequest(BaseModel):
    provider: str = Field(..., description=f"One of: {', '.join(SUPPORTED_PROVIDERS)}")
    api_key: str = Field(..., description="The provider's raw API key")
    key_label: str = Field(
        default="default",
        description="Label to allow multiple keys per provider (for rotation).",
    )


class StoreKeyResponse(BaseModel):
    user_id: str
    provider: str
    key_label: str
    key_id: int
    status: str


class ProviderKeyInfo(BaseModel):
    id: int
    provider: str
    key_label: str
    created_at: Optional[str] = None


class ListKeysResponse(BaseModel):
    user_id: str
    # Distinct provider names (backwards-compatible with the original shape).
    providers: List[str]
    # Per-key detail (no secret values), including ids for deletion.
    keys: List[ProviderKeyInfo]


class ChatMessage(BaseModel):
    role: str
    content: str


class ChatCompletionRequest(BaseModel):
    messages: List[ChatMessage]
    effort: Literal["low", "medium", "high"] = "medium"
    # OpenAI clients select a "model". We honor the pseudo-models
    # keychain-low/medium/high (mapping to effort); other values are ignored and
    # routing falls back to the `effort` field.
    model: Optional[str] = None
    # Common passthrough OpenAI params (optional).
    temperature: Optional[float] = None
    max_tokens: Optional[int] = None
    top_p: Optional[float] = None
    stream: Optional[bool] = Field(
        default=None,
        description="If true, proxies the provider's SSE stream back to you.",
    )

    model_config = {"extra": "allow"}


# --------------------------------------------------------------------------- #
# Auth
# --------------------------------------------------------------------------- #
def _new_token() -> str:
    return "ak-" + secrets.token_urlsafe(32)


def _err_type_for_status(status_code: int) -> str:
    if status_code == 401:
        return "authentication_error"
    if status_code == 403:
        return "permission_error"
    if status_code == 429:
        return "rate_limit_error"
    if status_code >= 500:
        return "api_error"
    return "invalid_request_error"


def _openai_error(
    status_code: int,
    message: str,
    err_type: Optional[str] = None,
    code: Optional[str] = None,
    extra: Optional[Dict[str, Any]] = None,
) -> JSONResponse:
    """An OpenAI-compatible error envelope: {"error": {...}}."""
    error: Dict[str, Any] = {
        "message": message,
        "type": err_type or _err_type_for_status(status_code),
        "param": None,
        "code": code,
    }
    if extra:
        error.update(extra)
    return JSONResponse(status_code=status_code, content={"error": error})


# Make ALL errors OpenAI-compatible ({"error": {...}}), not FastAPI's {"detail"}.
@app.exception_handler(StarletteHTTPException)
async def _http_exception_handler(request: Request, exc: StarletteHTTPException):
    return _openai_error(exc.status_code, str(exc.detail), code=None)


@app.exception_handler(RequestValidationError)
async def _validation_exception_handler(request: Request, exc: RequestValidationError):
    return _openai_error(
        422,
        "Invalid request body or parameters.",
        err_type="invalid_request_error",
        extra={"validation": jsonable_encoder(exc.errors())},
    )


def require_key(
    authorization: Optional[str] = Header(
        default=None, description="Bearer <api-keychain-key>"
    ),
    x_api_key: Optional[str] = Header(default=None, alias="x-api-key"),
    db: Session = Depends(get_db),
) -> KeychainKey:
    """Resolve a Bearer ak-... token (by hash) to its non-revoked keychain key."""
    token: Optional[str] = None
    if authorization and authorization.lower().startswith("bearer "):
        token = authorization[len("Bearer ") :].strip()
    elif x_api_key:
        token = x_api_key.strip()
    if not token:
        raise HTTPException(status_code=401, detail="Missing or malformed Bearer token")
    key = db.execute(
        select(KeychainKey).where(
            KeychainKey.key_hash == hash_token(token),
            KeychainKey.revoked.is_(False),
        )
    ).scalar_one_or_none()
    if key is None:
        raise HTTPException(status_code=401, detail="Invalid or revoked API key")
    key.last_used_at = _utcnow()
    db.commit()
    return key


# --------------------------------------------------------------------------- #
# Supabase JWT auth (management routes only; /v1/* still uses ak-... above)
# --------------------------------------------------------------------------- #
def _supabase_jwt_secret() -> str:
    secret = os.environ.get("SUPABASE_JWT_SECRET")
    if not secret:
        raise HTTPException(
            status_code=500,
            detail="SUPABASE_JWT_SECRET is not configured on the server.",
        )
    return secret


def _supabase_url() -> Optional[str]:
    """Project URL, used to fetch the JWKS for asymmetric (ES256/RS256) tokens.

    Accepts SUPABASE_URL or NEXT_PUBLIC_SUPABASE_URL (the dashboard's var) so a
    single .env works for both. Returns None when unset.
    """
    url = os.environ.get("SUPABASE_URL") or os.environ.get("NEXT_PUBLIC_SUPABASE_URL")
    return url.rstrip("/") if url else None


# Cache one PyJWKClient per JWKS URL; it caches fetched keys internally.
_jwk_clients: Dict[str, "jwt.PyJWKClient"] = {}


def _jwk_client() -> "jwt.PyJWKClient":
    url = _supabase_url()
    if not url:
        raise HTTPException(
            status_code=500,
            detail="SUPABASE_URL is not configured on the server (needed to verify "
            "asymmetric Supabase tokens).",
        )
    jwks_url = f"{url}/auth/v1/.well-known/jwks.json"
    client = _jwk_clients.get(jwks_url)
    if client is None:
        client = jwt.PyJWKClient(jwks_url)
        _jwk_clients[jwks_url] = client
    return client


def require_jwt(
    authorization: Optional[str] = Header(
        default=None, description="Bearer <supabase-jwt>"
    ),
) -> str:
    """Verify a Supabase JWT and return its `sub` (the user id).

    Supports both signing schemes Supabase issues: legacy symmetric HS256
    (verified with the shared SUPABASE_JWT_SECRET) and the newer asymmetric
    ES256/RS256 signing keys (verified against the project's public JWKS). The
    token's own header `alg` selects the path.
    """
    if not authorization or not authorization.lower().startswith("bearer "):
        raise HTTPException(status_code=401, detail="Missing or malformed Bearer token")
    token = authorization[len("Bearer ") :].strip()
    try:
        alg = jwt.get_unverified_header(token).get("alg", "")
        if alg == "HS256":
            claims = jwt.decode(
                token,
                _supabase_jwt_secret(),
                algorithms=["HS256"],
                audience="authenticated",
            )
        else:
            signing_key = _jwk_client().get_signing_key_from_jwt(token).key
            claims = jwt.decode(
                token,
                signing_key,
                algorithms=["ES256", "RS256"],
                audience="authenticated",
            )
    except jwt.ExpiredSignatureError:
        raise HTTPException(status_code=401, detail="Supabase token has expired")
    except jwt.InvalidTokenError as exc:
        raise HTTPException(status_code=401, detail=f"Invalid Supabase token: {exc}")
    except jwt.PyJWKClientError as exc:
        raise HTTPException(
            status_code=401, detail=f"Could not resolve Supabase signing key: {exc}"
        )
    sub = claims.get("sub")
    if not sub:
        raise HTTPException(status_code=401, detail="Token is missing the 'sub' claim")
    return sub


def require_jwt_user(
    user_id: str = Path(...),
    sub: str = Depends(require_jwt),
) -> str:
    """Auth for /users/{user_id}/... routes: JWT sub must equal the path user_id."""
    if sub != user_id:
        raise HTTPException(
            status_code=403,
            detail="JWT subject does not match the user_id in the path.",
        )
    return sub


# --------------------------------------------------------------------------- #
# User onboarding — Supabase only. Users are created exclusively via /users/init
# from a verified Supabase JWT, so there are no orphan (non-Supabase) users.
# --------------------------------------------------------------------------- #
@app.post("/users/init")
def init_user(
    sub: str = Depends(require_jwt),
    db: Session = Depends(get_db),
) -> Dict[str, Any]:
    """Create-or-upsert a user keyed by the Supabase JWT `sub`.

    Idempotent: the website calls this once after a user signs in with Supabase.
    The user_id is taken from the verified token, never from the request body.
    Afterwards, mint ak-... keys for /v1/* via POST /users/{user_id}/keychain-keys.
    """
    user = db.get(User, sub)
    created = False
    if user is None:
        # users.api_key is a non-null/unique legacy column; store a random,
        # non-recoverable hash (Supabase users authenticate via JWT, and use
        # separately-minted ak-... keychain keys for /v1/*).
        user = User(id=sub, api_key=hash_token(_new_token()))
        db.add(user)
        db.commit()
        created = True
    return {"user_id": sub, "created": created}


# --------------------------------------------------------------------------- #
# Keychain (ak-...) key management
# --------------------------------------------------------------------------- #
def _load_user_or_404(db: Session, user_id: str) -> User:
    user = db.get(User, user_id)
    if user is None:
        raise HTTPException(status_code=404, detail="User not found")
    return user


class CreateKeychainKeyRequest(BaseModel):
    label: str = Field(default="default", description="A name like 'prod' or 'dev'.")
    rate_limit_per_minute: Optional[int] = Field(
        default=None, ge=1, description="Optional requests/min cap for this key."
    )


def _keychain_key_public(k: KeychainKey) -> Dict[str, Any]:
    return {
        "id": k.id,
        "label": k.label,
        "masked": k.masked,
        "is_primary": k.is_primary,
        "rate_limit_per_minute": k.rate_limit_per_minute,
        "revoked": k.revoked,
        "created_at": k.created_at.isoformat() if k.created_at else None,
        "last_used_at": k.last_used_at.isoformat() if k.last_used_at else None,
    }


@app.post("/users/{user_id}/keychain-keys", dependencies=[Depends(require_jwt_user)])
def create_keychain_key(
    body: CreateKeychainKeyRequest,
    user_id: str = Path(...),
    db: Session = Depends(get_db),
) -> Dict[str, Any]:
    _load_user_or_404(db, user_id)
    token = _new_token()
    key = KeychainKey(
        user_id=user_id,
        label=body.label,
        key_hash=hash_token(token),
        masked=mask_token(token),
        is_primary=False,
        rate_limit_per_minute=body.rate_limit_per_minute,
    )
    db.add(key)
    db.commit()
    db.refresh(key)
    # Plaintext token is returned exactly once and never stored.
    return {
        "user_id": user_id,
        "api_key": token,
        "warning": "Save this now — it is shown only once.",
        **_keychain_key_public(key),
    }


@app.get("/users/{user_id}/keychain-keys", dependencies=[Depends(require_jwt_user)])
def list_keychain_keys(
    user_id: str = Path(...),
    db: Session = Depends(get_db),
) -> Dict[str, Any]:
    _load_user_or_404(db, user_id)
    keys = (
        db.execute(
            select(KeychainKey)
            .where(KeychainKey.user_id == user_id)
            .order_by(KeychainKey.id)
        )
        .scalars()
        .all()
    )
    return {"user_id": user_id, "keys": [_keychain_key_public(k) for k in keys]}


@app.post("/users/{user_id}/regenerate-key", dependencies=[Depends(require_jwt_user)])
def regenerate_primary_key(
    user_id: str = Path(...),
    db: Session = Depends(get_db),
) -> Dict[str, Any]:
    user = _load_user_or_404(db, user_id)
    primary = db.execute(
        select(KeychainKey).where(
            KeychainKey.user_id == user_id, KeychainKey.is_primary.is_(True)
        )
    ).scalar_one_or_none()

    token = _new_token()
    token_hash = hash_token(token)
    if primary is None:
        primary = KeychainKey(
            user_id=user_id,
            label="primary",
            key_hash=token_hash,
            masked=mask_token(token),
            is_primary=True,
        )
        db.add(primary)
    else:
        primary.key_hash = token_hash
        primary.masked = mask_token(token)
        primary.revoked = False
        primary.last_used_at = None
    user.api_key = token_hash  # keep the scrubbed legacy column in sync
    db.commit()
    db.refresh(primary)
    return {
        "user_id": user_id,
        "api_key": token,
        "warning": "Save this now — it is shown only once. The old primary key no longer works.",
        **_keychain_key_public(primary),
    }


class UpdateKeychainKeyRequest(BaseModel):
    label: Optional[str] = None
    rate_limit_per_minute: Optional[int] = Field(default=None, ge=1)
    clear_rate_limit: bool = Field(
        default=False, description="Set true to remove the rate limit."
    )
    revoked: Optional[bool] = None


@app.put("/keychain-keys/{key_id}")
def update_keychain_key(
    body: UpdateKeychainKeyRequest,
    key_id: int = Path(...),
    sub: str = Depends(require_jwt),
    db: Session = Depends(get_db),
) -> Dict[str, Any]:
    key = db.get(KeychainKey, key_id)
    # 404 (not 403) when not owned, so sequential ids can't be probed.
    if key is None or key.user_id != sub:
        raise HTTPException(status_code=404, detail="Keychain key not found")
    if body.label is not None:
        key.label = body.label
    if body.clear_rate_limit:
        key.rate_limit_per_minute = None
    elif body.rate_limit_per_minute is not None:
        key.rate_limit_per_minute = body.rate_limit_per_minute
    if body.revoked is not None:
        key.revoked = body.revoked
    db.commit()
    db.refresh(key)
    return {"user_id": key.user_id, **_keychain_key_public(key)}


@app.delete("/keychain-keys/{key_id}")
def revoke_keychain_key(
    key_id: int = Path(...),
    sub: str = Depends(require_jwt),
    db: Session = Depends(get_db),
) -> Dict[str, Any]:
    key = db.get(KeychainKey, key_id)
    # 404 (not 403) when not owned, so sequential ids can't be probed.
    if key is None or key.user_id != sub:
        raise HTTPException(status_code=404, detail="Keychain key not found")
    key.revoked = True
    db.commit()
    return {"revoked": True, **_keychain_key_public(key)}


# --------------------------------------------------------------------------- #
# Provider key management
# --------------------------------------------------------------------------- #


@app.post(
    "/users/{user_id}/keys",
    response_model=StoreKeyResponse,
    dependencies=[Depends(require_jwt_user)],
)
def store_provider_key(
    body: StoreKeyRequest,
    user_id: str = Path(...),
    db: Session = Depends(get_db),
) -> StoreKeyResponse:
    if body.provider not in SUPPORTED_PROVIDERS:
        raise HTTPException(
            status_code=400,
            detail=f"Unsupported provider {body.provider!r}. "
            f"Supported: {', '.join(SUPPORTED_PROVIDERS)}",
        )
    _load_user_or_404(db, user_id)

    encrypted = encrypt(body.api_key)
    # Upsert by (provider, key_label): re-posting the same label replaces it
    # (so the default behavior of one key per provider is preserved), while a
    # new label adds an additional key for rotation.
    existing = db.execute(
        select(ProviderKey).where(
            ProviderKey.user_id == user_id,
            ProviderKey.provider == body.provider,
            ProviderKey.key_label == body.key_label,
        )
    ).scalar_one_or_none()

    if existing is not None:
        existing.encrypted_key = encrypted
        status = "updated"
    else:
        existing = ProviderKey(
            user_id=user_id,
            provider=body.provider,
            key_label=body.key_label,
            encrypted_key=encrypted,
        )
        db.add(existing)
        status = "created"

    db.commit()
    db.refresh(existing)
    return StoreKeyResponse(
        user_id=user_id,
        provider=body.provider,
        key_label=body.key_label,
        key_id=existing.id,
        status=status,
    )


@app.get(
    "/users/{user_id}/keys",
    response_model=ListKeysResponse,
    dependencies=[Depends(require_jwt_user)],
)
def list_provider_keys(
    user_id: str = Path(...),
    db: Session = Depends(get_db),
) -> ListKeysResponse:
    _load_user_or_404(db, user_id)
    rows = (
        db.execute(
            select(ProviderKey)
            .where(ProviderKey.user_id == user_id)
            .order_by(ProviderKey.provider, ProviderKey.key_label)
        )
        .scalars()
        .all()
    )
    return ListKeysResponse(
        user_id=user_id,
        providers=sorted({r.provider for r in rows}),
        keys=[
            ProviderKeyInfo(
                id=r.id,
                provider=r.provider,
                key_label=r.key_label,
                created_at=r.created_at.isoformat() if r.created_at else None,
            )
            for r in rows
        ],
    )


@app.delete("/users/{user_id}/keys/{key_id}", dependencies=[Depends(require_jwt_user)])
def delete_provider_key(
    user_id: str = Path(...),
    key_id: int = Path(...),
    db: Session = Depends(get_db),
) -> Dict[str, Any]:
    _load_user_or_404(db, user_id)
    key = db.execute(
        select(ProviderKey).where(
            ProviderKey.id == key_id, ProviderKey.user_id == user_id
        )
    ).scalar_one_or_none()
    if key is None:
        raise HTTPException(status_code=404, detail="Provider key not found")
    provider, label = key.provider, key.key_label
    db.delete(key)
    db.commit()
    return {
        "user_id": user_id,
        "deleted": {"id": key_id, "provider": provider, "key_label": label},
    }


# --------------------------------------------------------------------------- #
# Per-user model & provider management + routing preferences
# --------------------------------------------------------------------------- #
def _encode_model_id(tier: str, model_entry: str) -> str:
    """Opaque, URL-safe id for an effective-model entry (encodes tier+entry)."""
    raw = f"{tier}|{model_entry}".encode("utf-8")
    return base64.urlsafe_b64encode(raw).decode("ascii").rstrip("=")


def _decode_model_id(model_id: str) -> Tuple[str, str]:
    pad = "=" * (-len(model_id) % 4)
    try:
        raw = base64.urlsafe_b64decode(model_id + pad).decode("utf-8")
        tier, model_entry = raw.split("|", 1)
    except Exception:
        raise HTTPException(status_code=400, detail="Malformed model_id")
    return tier, model_entry


def _load_overrides_customs(
    db: Session, user_id: str
) -> Tuple[Dict[Tuple[str, str], Dict[str, Any]], List[Dict[str, Any]]]:
    rows = (
        db.execute(select(UserModel).where(UserModel.user_id == user_id))
        .scalars()
        .all()
    )
    overrides: Dict[Tuple[str, str], Dict[str, Any]] = {}
    customs: List[Dict[str, Any]] = []
    for r in rows:
        if r.is_custom:
            customs.append(
                {
                    "model_entry": r.model_entry,
                    "tier": r.tier,
                    "enabled": r.enabled,
                    "priority": r.priority,
                }
            )
        else:
            overrides[(r.model_entry, r.tier)] = {
                "enabled": r.enabled,
                "priority": r.priority,
            }
    return overrides, customs


def _effective_table(db: Session, user_id: str) -> Dict[str, List[Dict[str, Any]]]:
    overrides, customs = _load_overrides_customs(db, user_id)
    return build_effective_table(overrides, customs)


@app.get("/users/{user_id}/models", dependencies=[Depends(require_jwt_user)])
def list_user_models(
    user_id: str = Path(...),
    db: Session = Depends(get_db),
) -> Dict[str, Any]:
    _load_user_or_404(db, user_id)
    table = _effective_table(db, user_id)
    # Providers the user actually has a key for. A model whose provider isn't in
    # this set is shown in the UI but flagged as unusable — the router skips it at
    # request time — so the dashboard can tell the user to connect a key first.
    connected = set(
        db.execute(select(ProviderKey.provider).where(ProviderKey.user_id == user_id))
        .scalars()
        .all()
    )
    models = []
    for tier in ("high", "medium", "low"):
        for m in table[tier]:
            models.append(
                {
                    "id": _encode_model_id(m["tier"], m["model_entry"]),
                    "model_entry": m["model_entry"],
                    "provider": m["provider"],
                    "tier": m["tier"],
                    "enabled": m["enabled"],
                    "priority": m["priority"],
                    "is_custom": m["is_custom"],
                    "provider_connected": m["provider"] in connected,
                }
            )
    return {"user_id": user_id, "models": models}


class UpdateModelRequest(BaseModel):
    enabled: Optional[bool] = None
    priority: Optional[int] = None
    tier: Optional[Literal["low", "medium", "high"]] = Field(
        default=None, description="Re-tier (custom models only)."
    )


def _registry_has(model_entry: str, tier: str) -> bool:
    return model_entry in MODEL_TIERS.get(tier, [])


@app.put("/users/{user_id}/models/{model_id}", dependencies=[Depends(require_jwt_user)])
def update_user_model(
    body: UpdateModelRequest,
    user_id: str = Path(...),
    model_id: str = Path(...),
    db: Session = Depends(get_db),
) -> Dict[str, Any]:
    _load_user_or_404(db, user_id)
    tier, model_entry = _decode_model_id(model_id)

    existing = db.execute(
        select(UserModel).where(
            UserModel.user_id == user_id,
            UserModel.model_entry == model_entry,
            UserModel.tier == tier,
        )
    ).scalar_one_or_none()
    is_custom = existing.is_custom if existing is not None else False

    # The entry must be real: either a registry default in this tier, or an
    # existing custom row.
    if existing is None and not _registry_has(model_entry, tier):
        raise HTTPException(status_code=404, detail="Unknown model for that tier")

    if body.tier is not None and body.tier != tier and not is_custom:
        raise HTTPException(
            status_code=400,
            detail="Re-tiering is only supported for custom models. "
            "Built-in models keep their registry tier.",
        )

    if existing is None:
        # Materialize an override row for a registry default, seeding its current
        # registry priority so unrelated ordering is preserved.
        default_priority = MODEL_TIERS[tier].index(model_entry)
        existing = UserModel(
            user_id=user_id,
            model_entry=model_entry,
            tier=tier,
            enabled=True,
            priority=default_priority,
            is_custom=False,
        )
        db.add(existing)

    if body.enabled is not None:
        existing.enabled = body.enabled
    if body.priority is not None:
        existing.priority = body.priority
    if body.tier is not None and is_custom:
        existing.tier = body.tier

    db.commit()
    db.refresh(existing)
    return {
        "user_id": user_id,
        "id": _encode_model_id(existing.tier, existing.model_entry),
        "model_entry": existing.model_entry,
        "tier": existing.tier,
        "enabled": existing.enabled,
        "priority": existing.priority,
        "is_custom": existing.is_custom,
    }


class AddCustomModelRequest(BaseModel):
    # model_id collides with pydantic's protected "model_" namespace; opt out.
    model_config = {"protected_namespaces": ()}

    provider: str = Field(..., description=f"One of: {', '.join(SUPPORTED_PROVIDERS)}")
    model_id: str = Field(..., description="Upstream model name for that provider")
    tier: Literal["low", "medium", "high"]
    enabled: bool = True
    priority: int = 1000


@app.post("/users/{user_id}/models", dependencies=[Depends(require_jwt_user)])
def add_custom_model(
    body: AddCustomModelRequest,
    user_id: str = Path(...),
    db: Session = Depends(get_db),
) -> Dict[str, Any]:
    _load_user_or_404(db, user_id)
    if body.provider not in SUPPORTED_PROVIDERS:
        raise HTTPException(
            status_code=400,
            detail=f"Unsupported provider {body.provider!r}. "
            f"Supported: {', '.join(SUPPORTED_PROVIDERS)}",
        )
    # Require the user to actually have a key for that provider.
    has_key = db.execute(
        select(ProviderKey.id).where(
            ProviderKey.user_id == user_id, ProviderKey.provider == body.provider
        )
    ).first()
    if has_key is None:
        raise HTTPException(
            status_code=400,
            detail=f"Add a {body.provider} key before adding a custom {body.provider} model.",
        )

    model_entry = f"{body.provider}/{body.model_id}"
    duplicate = db.execute(
        select(UserModel).where(
            UserModel.user_id == user_id,
            UserModel.model_entry == model_entry,
            UserModel.tier == body.tier,
        )
    ).scalar_one_or_none()
    if duplicate is not None:
        raise HTTPException(
            status_code=409, detail="That model already exists in that tier"
        )

    row = UserModel(
        user_id=user_id,
        model_entry=model_entry,
        tier=body.tier,
        enabled=body.enabled,
        priority=body.priority,
        is_custom=True,
    )
    db.add(row)
    db.commit()
    db.refresh(row)
    return {
        "user_id": user_id,
        "id": _encode_model_id(row.tier, row.model_entry),
        "model_entry": row.model_entry,
        "provider": body.provider,
        "tier": row.tier,
        "enabled": row.enabled,
        "priority": row.priority,
        "is_custom": True,
    }


@app.delete(
    "/users/{user_id}/models/{model_id}", dependencies=[Depends(require_jwt_user)]
)
def delete_user_model(
    user_id: str = Path(...),
    model_id: str = Path(...),
    db: Session = Depends(get_db),
) -> Dict[str, Any]:
    _load_user_or_404(db, user_id)
    tier, model_entry = _decode_model_id(model_id)
    row = db.execute(
        select(UserModel).where(
            UserModel.user_id == user_id,
            UserModel.model_entry == model_entry,
            UserModel.tier == tier,
            UserModel.is_custom.is_(True),
        )
    ).scalar_one_or_none()
    if row is None:
        raise HTTPException(
            status_code=404,
            detail="Custom model not found. Only custom models can be deleted; "
            "to hide a built-in model, PUT enabled=false instead.",
        )
    db.delete(row)
    db.commit()
    return {"user_id": user_id, "deleted": {"model_entry": model_entry, "tier": tier}}


class PreferencesBody(BaseModel):
    preferred_providers: List[str] = []
    excluded_providers: List[str] = []
    excluded_models: List[str] = []


def _load_preferences(db: Session, user_id: str) -> Dict[str, Any]:
    pref = db.get(UserPreference, user_id)
    if pref is None:
        return {
            "preferred_providers": [],
            "excluded_providers": [],
            "excluded_models": [],
        }
    return {
        "preferred_providers": pref.preferred_providers or [],
        "excluded_providers": pref.excluded_providers or [],
        "excluded_models": pref.excluded_models or [],
    }


@app.get("/users/{user_id}/preferences", dependencies=[Depends(require_jwt_user)])
def get_preferences(
    user_id: str = Path(...),
    db: Session = Depends(get_db),
) -> Dict[str, Any]:
    _load_user_or_404(db, user_id)
    return {"user_id": user_id, **_load_preferences(db, user_id)}


@app.put("/users/{user_id}/preferences", dependencies=[Depends(require_jwt_user)])
def put_preferences(
    body: PreferencesBody,
    user_id: str = Path(...),
    db: Session = Depends(get_db),
) -> Dict[str, Any]:
    _load_user_or_404(db, user_id)
    bad = [
        p
        for p in set(body.preferred_providers) | set(body.excluded_providers)
        if p not in SUPPORTED_PROVIDERS
    ]
    if bad:
        raise HTTPException(
            status_code=400, detail=f"Unknown provider(s): {', '.join(sorted(bad))}"
        )

    pref = db.get(UserPreference, user_id)
    if pref is None:
        pref = UserPreference(user_id=user_id)
        db.add(pref)
    pref.preferred_providers = body.preferred_providers
    pref.excluded_providers = body.excluded_providers
    pref.excluded_models = body.excluded_models
    db.commit()
    return {"user_id": user_id, **_load_preferences(db, user_id)}


# --------------------------------------------------------------------------- #
# Unified OpenAI-compatible endpoint
# --------------------------------------------------------------------------- #
def _resolve_effort(body: ChatCompletionRequest) -> str:
    """Map a 'keychain-<tier>' pseudo-model to an effort; else use body.effort."""
    if body.model and body.model.lower().startswith("keychain-"):
        tier = body.model.split("-", 1)[1].lower()
        if tier in ("low", "medium", "high"):
            return tier
    return body.effort


def _no_models_error(exc: NoModelsAvailable) -> JSONResponse:
    return _openai_error(
        409, str(exc), err_type="invalid_request_error", code="no_models_available"
    )


def _all_failed_error(exc: AllProvidersFailed) -> JSONResponse:
    """502 listing every model tried and why each failed (status + reason)."""
    return _openai_error(
        502,
        "All candidate models were exhausted; see 'failed_attempts' for the "
        "per-model reason.",
        err_type="api_error",
        code="all_providers_failed",
        extra={"failed_attempts": [a.as_dict() for a in exc.attempts]},
    )


def _load_provider_keys(db: Session, user_id: str) -> Dict[str, List[tuple]]:
    rows = (
        db.execute(
            select(ProviderKey)
            .where(ProviderKey.user_id == user_id)
            .order_by(ProviderKey.id)
        )
        .scalars()
        .all()
    )
    provider_keys: Dict[str, List[tuple]] = {}
    for row in rows:
        provider_keys.setdefault(row.provider, []).append(
            (row.key_label, row.encrypted_key)
        )
    return provider_keys


StreamByteTransform = Callable[[AsyncIterator[bytes]], AsyncIterator[bytes]]


async def _execute_chat_completion(
    db: Session,
    user: User,
    key: KeychainKey,
    *,
    forward_body: Dict[str, Any],
    effort: str,
    stream_transform: Optional[StreamByteTransform] = None,
):
    """Shared chat-completions pipeline for /v1/chat/completions and adapters."""
    if key.rate_limit_per_minute:
        used = _key_requests_last_minute(db, key.id)
        if used >= key.rate_limit_per_minute:
            return _openai_error(
                status_code=429,
                message=(
                    f"Rate limit reached for this keychain key: "
                    f"{key.rate_limit_per_minute} requests/min."
                ),
                err_type="rate_limit_error",
                code="rate_limit_exceeded",
            )

    provider_keys = _load_provider_keys(db, user.id)

    if not provider_keys:
        raise HTTPException(
            status_code=400,
            detail="No provider keys configured for this user. "
            "Add at least one via POST /users/{user_id}/keys.",
        )

    table = _effective_table(db, user.id)
    prefs = _load_preferences(db, user.id)
    models = effective_cascade(
        table,
        effort,
        excluded_models=set(prefs["excluded_models"]),
        excluded_providers=set(prefs["excluded_providers"]),
        preferred_providers=prefs["preferred_providers"],
    )

    deprioritized = _cooling_down_providers(db, user.id)

    if forward_body.get("stream"):
        return await _stream_chat(
            db,
            user,
            key,
            effort,
            forward_body,
            provider_keys,
            models,
            deprioritized,
            stream_transform=stream_transform,
        )

    started = time.perf_counter()
    try:
        result = await route_chat_completion(
            models=models,
            body=forward_body,
            provider_keys=provider_keys,
            deprioritized_providers=deprioritized,
            rotation_id=user.id,
            effort=effort,
        )
    except NoModelsAvailable as exc:
        _log_request(db, user.id, effort, [], None, started, 409, key.id)
        return _no_models_error(exc)
    except AllProvidersFailed as exc:
        _update_provider_health(db, user.id, exc.attempts)
        _log_request(db, user.id, effort, exc.attempts, None, started, 502, key.id)
        return _all_failed_error(exc)

    _update_provider_health(db, user.id, result.attempts)
    _log_request(db, user.id, effort, result.attempts, result, started, 200, key.id)
    return result.data


@app.post("/v1/chat/completions")
async def chat_completions(
    body: ChatCompletionRequest,
    key: KeychainKey = Depends(require_key),
    db: Session = Depends(get_db),
):
    user = db.get(User, key.user_id)
    forward_body = body.model_dump(exclude_none=True)
    effort = _resolve_effort(body)
    return await _execute_chat_completion(
        db, user, key, forward_body=forward_body, effort=effort
    )


@app.post("/v1/responses")
async def responses_create(
    request: Request,
    key: KeychainKey = Depends(require_key),
    db: Session = Depends(get_db),
):
    """OpenAI Responses API — for Codex CLI and other /v1/responses clients."""
    try:
        body = await request.json()
    except Exception:
        return _openai_error(400, "Invalid JSON body.")
    if not isinstance(body, dict):
        return _openai_error(400, "Request body must be a JSON object.")

    user = db.get(User, key.user_id)
    forward_body = responses_to_openai_body(body)
    effort = resolve_responses_effort(body)

    stream_transform: Optional[StreamByteTransform] = None
    if body.get("stream"):
        request_snapshot = dict(body)

        def stream_transform(stream):
            return convert_openai_stream_to_responses(stream, request_snapshot)

    openai_result = await _execute_chat_completion(
        db,
        user,
        key,
        forward_body=forward_body,
        effort=effort,
        stream_transform=stream_transform,
    )
    if isinstance(openai_result, (JSONResponse, StreamingResponse)):
        return openai_result
    return openai_to_responses_response(openai_result, body)


@app.post("/v1/messages")
async def anthropic_messages(
    request: Request,
    key: KeychainKey = Depends(require_key),
    db: Session = Depends(get_db),
):
    """Anthropic Messages API — for Claude Code and Anthropic-format clients."""
    try:
        body = await request.json()
    except Exception:
        return anthropic_error(400, "Invalid JSON body.", "invalid_request_error")
    if not isinstance(body, dict):
        return anthropic_error(400, "Request body must be a JSON object.")

    user = db.get(User, key.user_id)
    if key.rate_limit_per_minute:
        used = _key_requests_last_minute(db, key.id)
        if used >= key.rate_limit_per_minute:
            return anthropic_error(
                429, "Rate limit reached for this keychain key.", "rate_limit_error"
            )

    provider_keys = _load_provider_keys(db, user.id)
    if not provider_keys:
        return anthropic_error(
            400,
            "No provider keys configured. Add at least one via the dashboard.",
            "invalid_request_error",
        )

    request_model = body.get("model") or "claude-sonnet-4-6"
    effort = resolve_anthropic_effort(body)
    forward_body = anthropic_to_openai_body(body)

    table = _effective_table(db, user.id)
    prefs = _load_preferences(db, user.id)
    models = effective_cascade(
        table,
        effort,
        excluded_models=set(prefs["excluded_models"]),
        excluded_providers=set(prefs["excluded_providers"]),
        preferred_providers=prefs["preferred_providers"],
    )
    deprioritized = _cooling_down_providers(db, user.id)

    if body.get("stream"):
        return await _stream_anthropic_messages(
            db,
            user,
            key,
            effort,
            forward_body,
            provider_keys,
            models,
            deprioritized,
            request_model,
        )

    started = time.perf_counter()
    try:
        result = await route_chat_completion(
            models=models,
            body=forward_body,
            provider_keys=provider_keys,
            deprioritized_providers=deprioritized,
            rotation_id=user.id,
            effort=effort,
        )
    except NoModelsAvailable as exc:
        _log_request(db, user.id, effort, [], None, started, 409, key.id)
        return anthropic_error(409, str(exc), "invalid_request_error")
    except AllProvidersFailed as exc:
        _update_provider_health(db, user.id, exc.attempts)
        _log_request(db, user.id, effort, exc.attempts, None, started, 502, key.id)
        return anthropic_error(502, "All candidate models were exhausted.", "api_error")

    _update_provider_health(db, user.id, result.attempts)
    _log_request(db, user.id, effort, result.attempts, result, started, 200, key.id)
    return openai_to_anthropic_message(result.data, request_model)


async def _stream_anthropic_messages(
    db,
    user,
    key,
    effort,
    forward_body,
    provider_keys,
    models,
    deprioritized,
    request_model,
):
    started = time.perf_counter()
    try:
        handle = await open_stream(
            models=models,
            body=forward_body,
            provider_keys=provider_keys,
            deprioritized_providers=deprioritized,
            rotation_id=user.id,
        )
    except NoModelsAvailable as exc:
        _log_request(db, user.id, effort, [], None, started, 409, key.id)
        return anthropic_error(409, str(exc), "invalid_request_error")
    except AllProvidersFailed as exc:
        _update_provider_health(db, user.id, exc.attempts)
        _log_request(db, user.id, effort, exc.attempts, None, started, 502, key.id)
        return anthropic_error(502, "All candidate models were exhausted.", "api_error")

    _update_provider_health(db, user.id, handle.attempts)
    log_id = _log_stream(db, user.id, effort, handle, started, key.id)

    async def _bytes() -> AsyncIterator[bytes]:
        usage: Dict[str, Any] = {}
        try:
            async for chunk in convert_openai_stream_to_anthropic(
                iter_stream(handle, usage_out=usage), request_model
            ):
                yield chunk
        finally:
            _update_stream_log(log_id, usage, started)

    return StreamingResponse(
        _bytes(),
        media_type="text/event-stream",
        headers={
            "X-Keychain-Provider": handle.provider,
            "X-Keychain-Model": handle.model_entry,
            "Cache-Control": "no-cache",
        },
    )


@app.post("/v1/messages/count_tokens")
async def anthropic_count_tokens(
    request: Request, key: KeychainKey = Depends(require_key)
):
    """Token estimate for Claude Code budgeting."""
    try:
        body = await request.json()
    except Exception:
        return anthropic_error(400, "Invalid JSON body.", "invalid_request_error")
    return {"input_tokens": estimate_input_tokens(body)}


def _log_stream(
    db: Session,
    user_id: str,
    effort: str,
    handle: StreamHandle,
    started: float,
    key_id: int,
) -> Optional[int]:
    """Log a streamed request immediately (for rate limits); tokens filled later."""
    latency_ms = int((time.perf_counter() - started) * 1000)
    try:
        row = RequestLog(
            user_id=user_id,
            effort=effort,
            models_attempted=[a.as_dict() for a in handle.attempts],
            succeeded_model=handle.model_entry,
            provider=handle.provider,
            latency_ms=latency_ms,
            status="success",
            status_code=200,
            keychain_key_id=key_id,
        )
        db.add(row)
        db.commit()
        db.refresh(row)
        return row.id
    except Exception:
        db.rollback()
        return None


def _update_stream_log(
    log_id: Optional[int], usage: Dict[str, Any], started: float
) -> None:
    """Patch token usage and final latency after a stream finishes."""
    if log_id is None or not usage:
        return
    prompt = usage.get("prompt_tokens")
    completion = usage.get("completion_tokens")
    total = usage.get("total_tokens")
    if total is None and (prompt is not None or completion is not None):
        total = int(prompt or 0) + int(completion or 0)
    if prompt is None and completion is None and total is None:
        return
    latency_ms = int((time.perf_counter() - started) * 1000)
    db = SessionLocal()
    try:
        row = db.get(RequestLog, log_id)
        if row is None:
            return
        row.prompt_tokens = prompt
        row.completion_tokens = completion
        row.total_tokens = total
        row.latency_ms = latency_ms
        db.commit()
    except Exception:
        db.rollback()
    finally:
        db.close()


async def _stream_with_usage_log(
    handle: StreamHandle,
    *,
    tier: str,
    log_id: Optional[int],
    started: float,
) -> AsyncIterator[bytes]:
    usage: Dict[str, Any] = {}
    try:
        async for chunk in iter_stream(handle, tier=tier, usage_out=usage):
            yield chunk
    finally:
        _update_stream_log(log_id, usage, started)


async def _stream_chat(
    db: Session,
    user: User,
    key: KeychainKey,
    effort: str,
    forward_body: Dict[str, Any],
    provider_keys: Dict[str, List[tuple]],
    models: List[str],
    deprioritized: set,
    *,
    stream_transform: Optional[StreamByteTransform] = None,
):
    """Establish an upstream stream (with pre-start failover) and proxy its SSE.

    Failover happens only while *opening* the stream. Once bytes flow, a
    mid-stream upstream failure cannot fall back — it propagates to the client.
    """
    started = time.perf_counter()
    try:
        handle = await open_stream(
            models=models,
            body=forward_body,
            provider_keys=provider_keys,
            deprioritized_providers=deprioritized,
            rotation_id=user.id,
        )
    except NoModelsAvailable as exc:
        _log_request(db, user.id, effort, [], None, started, 409, key.id)
        return _no_models_error(exc)
    except AllProvidersFailed as exc:
        _update_provider_health(db, user.id, exc.attempts)
        _log_request(db, user.id, effort, exc.attempts, None, started, 502, key.id)
        return _all_failed_error(exc)

    # Stream started: record health + log now (before draining), so the request
    # counts toward rate limits and analytics even if the client disconnects.
    _update_provider_health(db, user.id, handle.attempts)
    log_id = _log_stream(db, user.id, effort, handle, started, key.id)

    byte_stream: AsyncIterator[bytes] = _stream_with_usage_log(
        handle, tier=effort, log_id=log_id, started=started
    )
    if stream_transform is not None:
        byte_stream = stream_transform(byte_stream)

    return StreamingResponse(
        byte_stream,
        media_type="text/event-stream",
        headers={
            "X-Keychain-Provider": handle.provider,
            "X-Keychain-Model": handle.model_entry,
            "X-Keychain-Key-Label": handle.key_label or "",
            "Cache-Control": "no-cache",
        },
    )


# --------------------------------------------------------------------------- #
# Usage tracking & analytics
# --------------------------------------------------------------------------- #
def _log_request(
    db: Session,
    user_id: str,
    effort: str,
    attempts: List[Attempt],
    result: Optional[RouteResult],
    started: float,
    status_code: int,
    keychain_key_id: Optional[int] = None,
) -> None:
    """Persist a RequestLog row. Best-effort: never breaks the request path."""
    latency_ms = int((time.perf_counter() - started) * 1000)
    usage = result.usage if result is not None else {}
    try:
        db.add(
            RequestLog(
                user_id=user_id,
                effort=effort,
                models_attempted=[a.as_dict() for a in attempts],
                succeeded_model=result.model_entry if result else None,
                provider=result.provider if result else None,
                prompt_tokens=usage.get("prompt_tokens"),
                completion_tokens=usage.get("completion_tokens"),
                total_tokens=usage.get("total_tokens"),
                latency_ms=latency_ms,
                status="success" if result is not None else "error",
                status_code=status_code,
                keychain_key_id=keychain_key_id,
            )
        )
        db.commit()
    except Exception:
        db.rollback()


def _key_requests_last_minute(db: Session, key_id: int) -> int:
    since = _utcnow() - dt.timedelta(minutes=1)
    return int(
        db.scalar(
            select(func.count())
            .select_from(RequestLog)
            .where(
                RequestLog.keychain_key_id == key_id,
                RequestLog.timestamp >= since,
            )
        )
        or 0
    )


# --------------------------------------------------------------------------- #
# Per-provider health & rate-limit tracking
# --------------------------------------------------------------------------- #
def _cooling_down_providers(db: Session, user_id: str) -> set[str]:
    """Providers that 429'd within the cooldown window -> deprioritize them."""
    cutoff = _utcnow() - dt.timedelta(seconds=COOLDOWN_SECONDS)
    rows = db.execute(
        select(ProviderHealth.provider, ProviderHealth.last_429_at).where(
            ProviderHealth.user_id == user_id,
            ProviderHealth.last_429_at.isnot(None),
        )
    ).all()
    return {
        prov
        for prov, last_429 in rows
        if _as_aware(last_429) and _as_aware(last_429) >= cutoff
    }


def _update_provider_health(db: Session, user_id: str, attempts: List[Attempt]) -> None:
    """Stamp success/failure/429 timestamps per provider from a request's attempts."""
    now = _utcnow()
    try:
        for attempt in attempts:
            health = db.execute(
                select(ProviderHealth).where(
                    ProviderHealth.user_id == user_id,
                    ProviderHealth.provider == attempt.provider,
                )
            ).scalar_one_or_none()
            if health is None:
                health = ProviderHealth(user_id=user_id, provider=attempt.provider)
                db.add(health)

            if attempt.status is not None and 200 <= attempt.status < 300:
                health.last_success_at = now
            else:
                health.last_failure_at = now
                if attempt.status == 429:
                    health.last_429_at = now
        db.commit()
    except Exception:
        db.rollback()


def _provider_request_counts(
    db: Session, user_id: str, since: dt.datetime
) -> Dict[str, int]:
    rows = db.execute(
        select(RequestLog.models_attempted).where(
            RequestLog.user_id == user_id,
            RequestLog.timestamp >= since,
        )
    ).all()
    counts: Dict[str, int] = {}
    for (attempts,) in rows:
        for a in attempts or []:
            prov = a.get("provider")
            if prov:
                counts[prov] = counts.get(prov, 0) + 1
    return counts


@app.get("/users/{user_id}/providers/health", dependencies=[Depends(require_jwt_user)])
def get_provider_health(
    user_id: str = Path(...),
    db: Session = Depends(get_db),
) -> Dict[str, Any]:
    _load_user_or_404(db, user_id)

    now = _utcnow()
    cutoff_429 = now - dt.timedelta(seconds=COOLDOWN_SECONDS)
    counts_minute = _provider_request_counts(db, user_id, now - dt.timedelta(minutes=1))
    counts_day = _provider_request_counts(db, user_id, now - dt.timedelta(days=1))

    # Providers the user has keys for, plus any with recorded health history.
    configured = set(
        db.execute(select(ProviderKey.provider).where(ProviderKey.user_id == user_id))
        .scalars()
        .all()
    )
    health_rows = {
        h.provider: h
        for h in db.execute(
            select(ProviderHealth).where(ProviderHealth.user_id == user_id)
        )
        .scalars()
        .all()
    }

    providers = {}
    for provider in sorted(configured | set(health_rows)):
        h = health_rows.get(provider)
        last_429 = _as_aware(h.last_429_at) if h else None
        if h is None or (
            h.last_success_at is None
            and h.last_failure_at is None
            and h.last_429_at is None
        ):
            status = "untested"
        elif last_429 is not None and last_429 >= cutoff_429:
            status = "cooling_down"
        else:
            status = "active"

        providers[provider] = {
            "status": status,
            "configured": provider in configured,
            "last_success": _as_aware(h.last_success_at).isoformat()
            if h and h.last_success_at
            else None,
            "last_failure": _as_aware(h.last_failure_at).isoformat()
            if h and h.last_failure_at
            else None,
            "last_429": last_429.isoformat() if last_429 else None,
            "cooldown_seconds_remaining": (
                max(
                    0,
                    int(
                        (
                            last_429 + dt.timedelta(seconds=COOLDOWN_SECONDS) - now
                        ).total_seconds()
                    ),
                )
                if status == "cooling_down"
                else 0
            ),
            "requests_last_minute": counts_minute.get(provider, 0),
            "requests_last_day": counts_day.get(provider, 0),
        }

    return {
        "user_id": user_id,
        "cooldown_seconds": COOLDOWN_SECONDS,
        "providers": providers,
    }


@app.get("/users/{user_id}/usage", dependencies=[Depends(require_jwt_user)])
def get_usage(
    user_id: str = Path(...),
    db: Session = Depends(get_db),
) -> Dict[str, Any]:
    _load_user_or_404(db, user_id)

    base = select(RequestLog).where(RequestLog.user_id == user_id)
    total_requests = db.scalar(select(func.count()).select_from(base.subquery()))
    if not total_requests:
        return {
            "user_id": user_id,
            "total_requests": 0,
            "total_tokens": 0,
            "success_rate": None,
            "per_provider": {},
            "per_model": {},
            "requests_over_time": {},
        }

    success_count = db.scalar(
        select(func.count())
        .select_from(RequestLog)
        .where(RequestLog.user_id == user_id, RequestLog.status == "success")
    )
    total_tokens = db.scalar(
        select(func.coalesce(func.sum(RequestLog.total_tokens), 0)).where(
            RequestLog.user_id == user_id
        )
    )

    # Per-provider breakdown (successful requests, by serving provider).
    per_provider = {
        prov: count
        for prov, count in db.execute(
            select(RequestLog.provider, func.count())
            .where(RequestLog.user_id == user_id, RequestLog.provider.isnot(None))
            .group_by(RequestLog.provider)
        ).all()
    }
    # Per-model breakdown (by serving model).
    per_model = {
        model: count
        for model, count in db.execute(
            select(RequestLog.succeeded_model, func.count())
            .where(
                RequestLog.user_id == user_id,
                RequestLog.succeeded_model.isnot(None),
            )
            .group_by(RequestLog.succeeded_model)
        ).all()
    }
    # Daily buckets of total request count.
    requests_over_time = {
        day: count
        for day, count in db.execute(
            select(func.date(RequestLog.timestamp), func.count())
            .where(RequestLog.user_id == user_id)
            .group_by(func.date(RequestLog.timestamp))
            .order_by(func.date(RequestLog.timestamp))
        ).all()
    }

    return {
        "user_id": user_id,
        "total_requests": total_requests,
        "total_tokens": int(total_tokens or 0),
        "success_rate": round(success_count / total_requests, 4),
        "per_provider": per_provider,
        "per_model": per_model,
        "requests_over_time": requests_over_time,
    }


@app.get("/users/{user_id}/usage/recent", dependencies=[Depends(require_jwt_user)])
def get_recent_usage(
    user_id: str = Path(...),
    limit: int = Query(20, ge=1, le=500),
    db: Session = Depends(get_db),
) -> Dict[str, Any]:
    _load_user_or_404(db, user_id)
    rows = (
        db.execute(
            select(RequestLog)
            .where(RequestLog.user_id == user_id)
            .order_by(RequestLog.timestamp.desc(), RequestLog.id.desc())
            .limit(limit)
        )
        .scalars()
        .all()
    )
    return {
        "user_id": user_id,
        "count": len(rows),
        "logs": [
            {
                "id": r.id,
                "timestamp": r.timestamp.isoformat() if r.timestamp else None,
                "effort": r.effort,
                "models_attempted": r.models_attempted,
                "succeeded_model": r.succeeded_model,
                "provider": r.provider,
                "prompt_tokens": r.prompt_tokens,
                "completion_tokens": r.completion_tokens,
                "total_tokens": r.total_tokens,
                "latency_ms": r.latency_ms,
                "status": r.status,
                "status_code": r.status_code,
            }
            for r in rows
        ],
    }


# --------------------------------------------------------------------------- #
# Discovery & health
# --------------------------------------------------------------------------- #
@app.get("/models")
def discover_models() -> Dict[str, Any]:
    """Global model registry, grouped by tier (public; no auth)."""
    return {"tiers": models_by_tier()}


@app.get("/providers")
def discover_providers() -> Dict[str, Any]:
    """All supported providers with base URL + OpenAI-compatible flag."""
    catalog = provider_catalog()
    return {
        "providers": [
            {"provider": name, **meta} for name, meta in sorted(catalog.items())
        ]
    }


@app.get("/v1/models")
def openai_models(
    key: KeychainKey = Depends(require_key),
    db: Session = Depends(get_db),
) -> Dict[str, Any]:
    """OpenAI-compatible model list for tools (Cursor/Cline/etc.).

    Exposes the three effort tiers as selectable pseudo-models
    (keychain-low/medium/high) plus the user's enabled effective models.
    """
    created = int(time.time())
    data: List[Dict[str, Any]] = [
        {
            "id": f"keychain-{tier}",
            "object": "model",
            "created": created,
            "owned_by": "api-keychain",
        }
        for tier in ("low", "medium", "high")
    ]
    data.extend(
        [
            {
                "id": "claude-haiku-4-5",
                "object": "model",
                "created": created,
                "owned_by": "api-keychain",
            },
            {
                "id": "claude-sonnet-4-6",
                "object": "model",
                "created": created,
                "owned_by": "api-keychain",
            },
            {
                "id": "claude-opus-4-6",
                "object": "model",
                "created": created,
                "owned_by": "api-keychain",
            },
        ]
    )

    table = _effective_table(db, key.user_id)
    # Only advertise models the user can actually reach — i.e. whose provider
    # they have a key for. Otherwise an OpenAI client (Cursor/Cline) would list
    # and try models that always fail with "no key for provider".
    connected = set(
        db.execute(
            select(ProviderKey.provider).where(ProviderKey.user_id == key.user_id)
        )
        .scalars()
        .all()
    )
    seen = set()
    for tier in ("high", "medium", "low"):
        for m in table[tier]:
            if not m["enabled"] or m["model_entry"] in seen:
                continue
            if m["provider"] not in connected:
                continue
            seen.add(m["model_entry"])
            data.append(
                {
                    "id": m["model_entry"],
                    "object": "model",
                    "created": created,
                    "owned_by": m["provider"],
                }
            )
    return {"object": "list", "data": data}


@app.get("/health")
def health(db: Session = Depends(get_db)):
    """Server + database health."""
    try:
        db.execute(select(1))
        db_ok = True
    except Exception:
        db_ok = False
    payload = {
        "status": "ok" if db_ok else "degraded",
        "database": "ok" if db_ok else "error",
        "version": app.version,
    }
    if not db_ok:
        return JSONResponse(status_code=503, content=payload)
    return payload
