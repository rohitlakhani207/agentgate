"""Draft and send email -- where "send" can only ever reach the operator's own inbox.

outbox mode (default) writes .eml files and sends nothing. smtp mode really sends, but
always to `email_self`; the recipient the agent chose is kept in a header and the
subject, so the demo shows what would have happened without it happening.
"""

from __future__ import annotations

import smtplib
import uuid
from datetime import UTC, datetime
from email.message import EmailMessage
from pathlib import Path

from ..config import Settings
from .sandbox import SandboxError


class Mailer:
    def __init__(self, settings: Settings, outbox: Path):
        self.settings = settings
        self.outbox = outbox

    def _message(self, to: str, subject: str, body: str) -> EmailMessage:
        msg = EmailMessage()
        msg["From"] = self.settings.email_self or "agentgate@localhost"
        msg["To"] = to
        msg["Subject"] = subject
        msg["Date"] = datetime.now(UTC).strftime("%a, %d %b %Y %H:%M:%S +0000")
        msg.set_content(body)
        return msg

    def _save(self, folder: str, msg: EmailMessage) -> Path:
        path = (
            self.outbox / folder / f"{datetime.now(UTC):%Y%m%dT%H%M%S}-{uuid.uuid4().hex[:6]}.eml"
        )
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_bytes(bytes(msg))
        return path

    def draft_email(self, to: str, subject: str, body: str) -> str:
        path = self._save("drafts", self._message(to, subject, body))
        return f"Draft saved ({path.name}); nothing was sent."

    def send_email(self, to: str, subject: str, body: str) -> str:
        msg = self._message(to, subject, body)
        if self.settings.email_mode == "outbox":
            path = self._save("sent", msg)
            return f"Sent to {to} (outbox mode: saved as {path.name}, nothing left this machine)."

        s = self.settings
        if not (s.email_self and s.smtp_user and s.smtp_password):
            raise SandboxError("smtp mode needs AGENTGATE_EMAIL_SELF, SMTP_USER and SMTP_PASSWORD")
        # The sandbox rule: whatever the agent asked for, the mail goes to you.
        msg.replace_header("To", s.email_self)
        msg.replace_header("Subject", f"[AgentGate -> {to}] {subject}")
        msg["X-AgentGate-Intended-To"] = to
        with smtplib.SMTP(s.smtp_host, s.smtp_port, timeout=20) as smtp:
            smtp.starttls()
            smtp.login(s.smtp_user, s.smtp_password)
            smtp.send_message(msg)
        self._save("sent", msg)
        return f"Sent (delivered to your own address {s.email_self}; intended for {to})."
