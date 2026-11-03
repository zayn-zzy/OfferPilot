"""Allowlisted external action executors used only after explicit approval."""

import asyncio
import smtplib
import ssl
from email.message import EmailMessage
from typing import Protocol
from uuid import UUID

from email_validator import EmailNotValidError, validate_email

from app.core.config import Settings

EMAIL_SEND_ACTION = "email.send"


class ExternalActionHandler(Protocol):
    """Provider-specific handler for one allowlisted external action type."""

    action_type: str

    def is_configured(self, settings: Settings) -> bool:
        """Return whether the external provider has the required credentials."""

    async def execute(
        self,
        settings: Settings,
        *,
        action_id: UUID,
        target: str,
        payload: dict[str, str],
    ) -> str:
        """Execute one approved payload and return a provider reference."""


class ExternalActionRegistry:
    """Resolve action types to the small set of explicitly registered handlers."""

    def __init__(self, handlers: list[ExternalActionHandler]) -> None:
        self._handlers = {handler.action_type: handler for handler in handlers}
        if len(self._handlers) != len(handlers):
            raise ValueError("External action types must be registered only once")

    def supports(self, action_type: str) -> bool:
        return action_type in self._handlers

    def is_configured(self, action_type: str, settings: Settings) -> bool:
        handler = self._handlers.get(action_type)
        return handler is not None and handler.is_configured(settings)

    async def execute(
        self,
        action_type: str,
        settings: Settings,
        *,
        action_id: UUID,
        target: str,
        payload: dict[str, str],
    ) -> str:
        handler = self._handlers.get(action_type)
        if handler is None:
            raise ValueError("No executor is registered for this action type")
        return await handler.execute(
            settings,
            action_id=action_id,
            target=target,
            payload=payload,
        )


class SMTPEmailActionHandler:
    """Send plain-text mail through an authenticated, TLS-protected SMTP server."""

    action_type = EMAIL_SEND_ACTION

    def is_configured(self, settings: Settings) -> bool:
        required_values_present = bool(
            settings.smtp_host.strip()
            and settings.smtp_username.strip()
            and settings.smtp_password.get_secret_value()
            and settings.smtp_sender.strip()
        )
        if not required_values_present or any(
            "\r" in value or "\n" in value
            for value in (settings.smtp_host, settings.smtp_username, settings.smtp_sender)
        ):
            return False
        try:
            validate_email(settings.smtp_sender.strip(), check_deliverability=False)
        except EmailNotValidError:
            return False
        return True

    async def execute(
        self,
        settings: Settings,
        *,
        action_id: UUID,
        target: str,
        payload: dict[str, str],
    ) -> str:
        if not self.is_configured(settings):
            raise RuntimeError("SMTP is not configured")
        message_id = f"<offerpilot-{action_id}@offerpilot.local>"
        message = EmailMessage()
        message["From"] = settings.smtp_sender
        message["To"] = target
        message["Subject"] = payload["subject"]
        message["Message-ID"] = message_id
        message.set_content(payload["body"])

        await asyncio.to_thread(
            self._send_message,
            settings,
            message,
        )
        return message_id

    @staticmethod
    def _send_message(settings: Settings, message: EmailMessage) -> None:
        context = ssl.create_default_context()
        if settings.smtp_use_ssl:
            server_context = smtplib.SMTP_SSL(
                settings.smtp_host,
                settings.smtp_port,
                timeout=settings.smtp_timeout_seconds,
                context=context,
            )
        else:
            server_context = smtplib.SMTP(
                settings.smtp_host,
                settings.smtp_port,
                timeout=settings.smtp_timeout_seconds,
            )
        with server_context as server:
            if not settings.smtp_use_ssl:
                server.ehlo()
                server.starttls(context=context)
                server.ehlo()
            server.login(
                settings.smtp_username,
                settings.smtp_password.get_secret_value(),
            )
            server.send_message(message)
