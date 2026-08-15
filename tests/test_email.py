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
