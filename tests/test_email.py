from pathlib import Path

from services.gmail_service import GmailService
from services.workflow import render_template


def test_email_template_rendering() -> None:
    result = render_template(
        "Hi {{client_name}}, post date: {{date}}. Regards, {{agency_name}}",
        {
            "client_name": "Alex",
            "date": "2026-08-08",
            "agency_name": "Local SEO Co",
        },
    )
    assert result == "Hi Alex, post date: 2026-08-08. Regards, Local SEO Co"


def test_email_message_includes_large_bold_html_alternative(
    tmp_path: Path,
) -> None:
    service = GmailService(tmp_path / "credentials.json", tmp_path / "token.json")

    message = service.create_message(
        "client@example.com",
        "Test subject",
        "Hi Client, today's post is ready.",
    )

    html_parts = [
        part
        for part in message.walk()
        if part.get_content_type() == "text/html"
    ]
    assert len(html_parts) == 1
    html = html_parts[0].get_content()
    assert "font-size: 20px" in html
    assert "font-weight: 700" in html
    assert "Hi Client, today&#x27;s post is ready." in html
