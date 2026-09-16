"""Resend transactional email provider implementation."""

import logging
from typing import Optional
import httpx
from bopclients.application.interfaces.email_sender import ITransactionalEmailSender
from bopclients.domain.email import (
    TransactionalEmailMessage,
    EmailDeliveryResult,
    EmailDeliveryStatus,
)

logger = logging.getLogger("bopclients.infrastructure.email.resend")

RESEND_API_URL = "https://api.resend.com/emails"


class ResendEmailSender(ITransactionalEmailSender):
    """Transactional email sender using Resend HTTP API."""

    def __init__(
        self,
        api_key: str,
        default_from: str = "BopClients <invites@bopclients.com>",
        client: Optional[httpx.Client] = None,
    ):
        self.api_key = (api_key or "").strip()
        self.default_from = default_from.strip() or "BopClients <invites@bopclients.com>"
        self._client = client

    def _get_client(self) -> httpx.Client:
        if self._client is not None:
            return self._client
        return httpx.Client(timeout=10.0)

    def send(self, message: TransactionalEmailMessage) -> EmailDeliveryResult:
        """Send message via Resend API."""
        if not self.api_key:
            return EmailDeliveryResult(
                status=EmailDeliveryStatus.NOT_CONFIGURED,
                error="Resend API key is not configured.",
            )

        from_email = (message.from_email or self.default_from).strip()
        payload = {
            "from": from_email,
            "to": [message.to],
            "subject": message.subject,
            "html": message.html_body,
            "text": message.text_body,
        }

        headers = {
            "Authorization": f"Bearer {self.api_key}",
            "Content-Type": "application/json",
            "User-Agent": "bopclients/1.0",
        }

        try:
            client = self._get_client()
            resp = client.post(RESEND_API_URL, json=payload, headers=headers)

            if resp.status_code in (200, 201):
                data = resp.json()
                msg_id = data.get("id") or "resend_msg_unknown"
                logger.info(f"Successfully dispatched transactional email via Resend (id={msg_id})")
                return EmailDeliveryResult(
                    status=EmailDeliveryStatus.SENT,
                    message_id=msg_id,
                )

            # High-level failure categorization without leaking auth headers or internal bodies
            error_text = f"Email provider delivery failed (HTTP {resp.status_code})"
            try:
                err_data = resp.json()
                if isinstance(err_data, dict):
                    msg = err_data.get("message")
                    if isinstance(msg, str) and msg.strip() and len(msg) < 150:
                        clean = msg.strip()
                        # Strictly prevent sensitive tokens, auth headers, or keys from surfacing
                        if not any(s in clean.lower() for s in ("bearer", "token", "secret", "key", "password", "authorization")):
                            error_text = f"Email provider error: {clean}"
            except Exception:
                pass

            logger.warning(f"Resend transmission failed with status {resp.status_code}")
            return EmailDeliveryResult(
                status=EmailDeliveryStatus.FAILED,
                error=error_text,
            )

        except httpx.TimeoutException:
            logger.warning("Resend transmission timed out.")
            return EmailDeliveryResult(
                status=EmailDeliveryStatus.FAILED,
                error="Transmission timed out.",
            )
        except httpx.RequestError as exc:
            logger.warning(f"Resend transmission network error: {type(exc).__name__}")
            return EmailDeliveryResult(
                status=EmailDeliveryStatus.FAILED,
                error=f"Network error connecting to email provider: {type(exc).__name__}",
            )
        except Exception as exc:
            logger.error(f"Unexpected error in ResendEmailSender: {type(exc).__name__}")
            return EmailDeliveryResult(
                status=EmailDeliveryStatus.FAILED,
                error="Internal error during email delivery.",
            )
