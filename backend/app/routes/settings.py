"""Owner-scoped configuration for Chat Completions and Embeddings credentials."""

from __future__ import annotations

from typing import Annotated
from uuid import UUID

from fastapi import APIRouter, Depends, HTTPException, Request, status
from sqlalchemy.orm import Session

from app.core.config import Settings
from app.models import User, UserModelConfiguration
from app.routes.auth import (
    current_user_dependency,
    enforce_same_origin,
    session_dependency,
    settings_dependency,
)
from app.schemas import (
    ModelProviderSettingsRead,
    UserModelSettingsRead,
    UserModelSettingsWrite,
)
from app.services.model_credentials import (
    ModelCredentialError,
    decrypt_model_credential,
    encrypt_model_credential,
)

router = APIRouter(prefix="/settings", tags=["settings"])


def _provider_status(
    *,
    configuration: UserModelConfiguration | None,
    settings: Settings,
    user_id: UUID,
    provider: str,
    encrypted_field: str,
    api_key_field: str,
    default_model: str,
    model_override: str | None,
) -> ModelProviderSettingsRead:
    encrypted = getattr(configuration, encrypted_field) if configuration else None
    if encrypted is not None:
        configured = True
        try:
            available = bool(
                decrypt_model_credential(settings, user_id, provider, encrypted)
            )
            source = "account" if available else "unavailable"
        except ModelCredentialError:
            available = False
            source = "unavailable"
    else:
        configured = bool(getattr(settings, api_key_field).get_secret_value().strip())
        available = configured
        source = "deployment" if configured else "not_configured"

    effective_model = model_override or default_model
    base_url = (
        settings.embedding_base_url
        if provider == "embeddings"
        else settings.llm_base_url
    )
    return ModelProviderSettingsRead(
        endpoint_configured=bool(base_url.strip()),
        default_model=default_model,
        model_override=model_override,
        effective_model=effective_model,
        credential_configured=configured,
        credential_available=available,
        credential_source=source,
        ready=bool(base_url.strip() and effective_model.strip() and available),
    )


def _read_model_settings(
    user: User,
    session: Session,
    settings: Settings,
) -> UserModelSettingsRead:
    configuration = session.get(UserModelConfiguration, user.id)
    return UserModelSettingsRead(
        chat_completions=_provider_status(
            configuration=configuration,
            settings=settings,
            user_id=user.id,
            provider="chat_completions",
            encrypted_field="llm_api_key_ciphertext",
            api_key_field="llm_api_key",
            default_model=settings.llm_model,
            model_override=configuration.llm_model if configuration else None,
        ),
        embeddings=_provider_status(
            configuration=configuration,
            settings=settings,
            user_id=user.id,
            provider="embeddings",
            encrypted_field="embedding_api_key_ciphertext",
            api_key_field="embedding_api_key",
            default_model=settings.embedding_model,
            model_override=configuration.embedding_model if configuration else None,
        ),
    )


@router.get("/models", response_model=UserModelSettingsRead)
def read_model_settings(
    user: Annotated[User, Depends(current_user_dependency)],
    session: Annotated[Session, Depends(session_dependency)],
    settings: Annotated[Settings, Depends(settings_dependency)],
) -> UserModelSettingsRead:
    """Return endpoints, model names and key-presence status without secret material."""

    return _read_model_settings(user, session, settings)


@router.put("/models", response_model=UserModelSettingsRead)
def save_model_settings(
    payload: UserModelSettingsWrite,
    request: Request,
    user: Annotated[User, Depends(current_user_dependency)],
    session: Annotated[Session, Depends(session_dependency)],
    settings: Annotated[Settings, Depends(settings_dependency)],
) -> UserModelSettingsRead:
    """Save account-specific keys and model overrides; never echo a submitted key."""

    enforce_same_origin(request, settings)
    configuration = session.get(UserModelConfiguration, user.id)
    fields_set = payload.model_fields_set
    updates: dict[str, object] = {}

    provider_fields = (
        (
            "llm_api_key",
            "clear_llm_api_key",
            "llm_api_key_ciphertext",
            "chat_completions",
        ),
        (
            "embedding_api_key",
            "clear_embedding_api_key",
            "embedding_api_key_ciphertext",
            "embeddings",
        ),
    )
    model_fields = (
        ("llm_model", "clear_llm_model"),
        ("embedding_model", "clear_embedding_model"),
    )
    try:
        for request_field, clear_field, storage_field, provider in provider_fields:
            if getattr(payload, clear_field):
                updates[storage_field] = None
            elif request_field in fields_set:
                credential = getattr(payload, request_field)
                if credential is not None:
                    updates[storage_field] = encrypt_model_credential(
                        settings,
                        user.id,
                        provider,
                        credential.get_secret_value(),
                    )
        for request_field, clear_field in model_fields:
            if getattr(payload, clear_field):
                updates[request_field] = None
            elif request_field in fields_set:
                updates[request_field] = getattr(payload, request_field)
    except ModelCredentialError:
        raise HTTPException(
            status_code=status.HTTP_503_SERVICE_UNAVAILABLE,
            detail="无法安全保存模型密钥，请检查后端 storage 目录权限和持久化配置。",
        ) from None

    if updates:
        if configuration is None:
            configuration = UserModelConfiguration(user_id=user.id)
            session.add(configuration)
        for field, value in updates.items():
            setattr(configuration, field, value)
        session.commit()
        session.refresh(configuration)

    return _read_model_settings(user, session, settings)
