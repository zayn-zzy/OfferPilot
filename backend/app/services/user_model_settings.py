"""Resolve account-scoped model credentials over deployment defaults."""

from __future__ import annotations

from uuid import UUID

from pydantic import SecretStr
from sqlalchemy.orm import Session

from app.core.config import Settings
from app.models import UserModelConfiguration
from app.services.model_credentials import ModelCredentialError, decrypt_model_credential


def resolve_user_model_settings(
    session: Session,
    user_id: UUID,
    deployment_settings: Settings,
) -> Settings:
    """Return a copy of settings with this account's overrides applied.

    Deployment values remain the fallback. If an account credential exists but cannot be
    decrypted, return an empty key instead of silently falling back to a shared key.
    """

    configuration = session.get(UserModelConfiguration, user_id)
    if configuration is None:
        return deployment_settings

    updates: dict[str, object] = {}
    credential_fields = (
        ("llm_api_key_ciphertext", "llm_api_key", "chat_completions"),
        ("embedding_api_key_ciphertext", "embedding_api_key", "embeddings"),
    )
    for ciphertext_field, settings_field, provider in credential_fields:
        encrypted = getattr(configuration, ciphertext_field)
        if encrypted is None:
            continue
        try:
            credential = decrypt_model_credential(
                deployment_settings,
                user_id,
                provider,
                encrypted,
            )
        except ModelCredentialError:
            credential = ""
        updates[settings_field] = SecretStr(credential)

    if configuration.llm_model is not None:
        updates["llm_model"] = configuration.llm_model
    if configuration.embedding_model is not None:
        updates["embedding_model"] = configuration.embedding_model
    return deployment_settings.model_copy(update=updates)
