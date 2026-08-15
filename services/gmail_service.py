import base64
import logging
import mimetypes
import os
from email.message import EmailMessage
from pathlib import Path
from typing import Any

from google.auth.transport.requests import Request
from google.oauth2.credentials import Credentials
from google_auth_oauthlib.flow import InstalledAppFlow
from googleapiclient.discovery import build
from googleapiclient.errors import HttpError


logger = logging.getLogger(__name__)
SCOPES = ["https://www.googleapis.com/auth/gmail.compose"]


class GmailService:
    """Creates Gmail drafts only. This class intentionally has no send method."""

    def __init__(self, credentials_path: Path, token_path: Path):
        self.credentials_path = credentials_path
        self.token_path = token_path
        self._service: Any | None = None

    def authenticate(self) -> Any:
        credentials: Credentials | None = None
        if self.token_path.exists():
            credentials = Credentials.from_authorized_user_file(
                str(self.token_path), SCOPES
            )
        if credentials and credentials.expired and credentials.refresh_token:
            credentials.refresh(Request())
        elif not credentials or not credentials.valid:
            if not self.credentials_path.exists():
                raise FileNotFoundError(
                    f"Gmail OAuth credentials not found at {self.credentials_path}"
                )
            flow = InstalledAppFlow.from_client_secrets_file(
                str(self.credentials_path), SCOPES
            )
            credentials = flow.run_local_server(port=0)

        self.token_path.parent.mkdir(parents=True, exist_ok=True)
        self.token_path.write_text(credentials.to_json(), encoding="utf-8")
        os.chmod(self.token_path, 0o600)
        self._service = build("gmail", "v1", credentials=credentials)
        logger.info("Gmail authentication ready", extra={"event": "gmail_authenticated"})
        return self._service

    def create_message(
        self,
        recipient: str,
        subject: str,
        body: str,
        attachment: Path | None = None,
        message_id: str | None = None,
    ) -> EmailMessage:
        message = EmailMessage()
        message["To"] = recipient
        message["Subject"] = subject
        if message_id:
            message["Message-ID"] = message_id
        message.set_content(body)
        if attachment is not None:
            self.attach_file(message, attachment)
        return message

    @staticmethod
    def attach_file(message: EmailMessage, attachment: Path) -> None:
        if not attachment.is_file():
            raise FileNotFoundError(f"Attachment not found: {attachment}")
        content_type, _ = mimetypes.guess_type(attachment.name)
        main_type, sub_type = (
            content_type.split("/", 1)
            if content_type
            else ("application", "octet-stream")
        )
        message.add_attachment(
            attachment.read_bytes(),
            maintype=main_type,
            subtype=sub_type,
            filename=attachment.name,
        )

    def create_draft(
        self,
        recipient: str,
        subject: str,
        body: str,
        attachment: Path,
        message_id: str | None = None,
    ) -> str:
        service = self._service or self.authenticate()
        message = self.create_message(
            recipient, subject, body, attachment, message_id=message_id
        )
        raw = base64.urlsafe_b64encode(message.as_bytes()).decode("ascii")
        try:
            response = (
                service.users()
                .drafts()
                .create(userId="me", body={"message": {"raw": raw}})
                .execute()
            )
        except HttpError:
            logger.exception(
                "Gmail API failed to create draft",
                extra={"event": "gmail_draft_failed"},
            )
            raise
        draft_id = response.get("id")
        if not draft_id:
            raise RuntimeError("Gmail API returned no draft ID")
        logger.info(
            "Gmail draft created; no email was sent",
            extra={"event": "gmail_draft_created"},
        )
        return str(draft_id)

    def find_draft_by_message_id(self, message_id: str) -> str | None:
        """Reconcile a draft created before its ID was persisted locally."""
        service = self._service or self.authenticate()
        page_token: str | None = None
        while True:
            request = service.users().drafts().list(
                userId="me", maxResults=100, pageToken=page_token
            )
            response = request.execute()
            for draft in response.get("drafts", []):
                details = (
                    service.users()
                    .drafts()
                    .get(
                        userId="me",
                        id=draft["id"],
                        format="metadata",
                    )
                    .execute()
                )
                headers = details.get("message", {}).get("payload", {}).get(
                    "headers", []
                )
                if any(
                    header.get("name", "").casefold() == "message-id"
                    and header.get("value") == message_id
                    for header in headers
                ):
                    return str(draft["id"])
            page_token = response.get("nextPageToken")
            if not page_token:
                return None

    def test_connection(self) -> str:
        service = self._service or self.authenticate()
        profile = service.users().getProfile(userId="me").execute()
        return str(profile.get("emailAddress", "authenticated Gmail account"))
