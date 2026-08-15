# GBP Post Verifier

A Python 3.11+ service that verifies each local SEO client's daily Google
Business Profile post, captures evidence, and creates a reviewable Gmail draft.
It never sends email and never publishes or modifies a Google Business Profile.

The application uses Playwright Chromium with a persistent browser profile,
SQLite for clients and daily state, APScheduler for timezone-aware schedules,
and the official Gmail API with OAuth 2.0.

## Safety and limitations

- There is deliberately no Gmail `send` call. A person must review and send
  every draft in Gmail.
- Gmail does not offer a create-draft-only OAuth scope. `gmail.compose` also
  permits sending, so draft-only behavior is enforced by this codebase; protect
  `token.json` as a sensitive credential.
- Passwords are never requested or stored. Google login, 2FA, and CAPTCHA must
  be completed manually in the visible browser.
- The tool does not use stealth automation or bypass Google security controls.
- Google Search/Business Profile markup is not a stable public API. The checker
  uses layered semantic selectors, but a Google UI change can require selector
  maintenance. A missing or ambiguous date is treated as **not verified**.
- Keep `HEADLESS=false` until browser authentication is established and while
  diagnosing UI changes.

## Install

Requirements:

- Python 3.11 or newer
- A desktop/display for first-time Google login
- A Google account that can view the relevant profiles
- A Google Cloud OAuth desktop client with Gmail API access

```bash
cd gbp-post-verifier
python3.11 -m venv .venv
source .venv/bin/activate
python -m pip install --upgrade pip
python -m pip install -r requirements.txt
python -m playwright install chromium
cp .env.example .env
python main.py --setup
```

The setup command creates SQLite and runtime directories and validates paths.
Runtime data, browser sessions, OAuth files, screenshots, and logs are ignored
by Git.

## Configure Gmail OAuth

1. Create or select a project in
   [Google Cloud Console](https://console.cloud.google.com/).
2. Enable **Gmail API** under APIs & Services.
3. Configure the OAuth consent screen. Add the Google account as a test user if
   the app remains in testing.
4. Create an OAuth client ID with application type **Desktop app**.
5. Download its JSON file and save it as `credentials.json` in this directory.
6. Run:

```bash
python main.py --test-gmail
```

The browser consent flow requests only `gmail.compose`. The resulting
`token.json` is stored locally with owner-only permissions. The command reads
the Gmail profile to confirm access and does not create or send a message.

You can also run `python -m scripts.setup_google_auth`.

## First Google Business Profile login

Set `HEADLESS=false` in `.env`, add one client, then run:

```bash
python main.py --test-client 1
```

If Google asks for login, complete it in the open Chromium window. The
persistent session is retained under `browser_profile/`. The application waits
up to `MANUAL_LOGIN_TIMEOUT_MINUTES`. Complete 2FA or a CAPTCHA yourself; the
automation will never attempt to bypass it.

`--test-client` checks detection and screenshot behavior only. It does not
create a Gmail draft.

To inspect a historical post during testing without creating a draft, provide
the date explicitly:

```bash
python main.py --test-client 1 --date 2026-08-14
```

## Add clients

Use IANA timezone names and a 24-hour local check time:

```bash
python -m scripts.add_client \
  --client-name "ABC Plumbing" \
  --business-name "ABC Plumbing" \
  --url "https://www.google.com/search?q=ABC+Plumbing" \
  --email "owner@example.com" \
  --timezone "America/Chicago" \
  --check-time "18:00" \
  --retry-interval 30 \
  --max-retries 3
```

The URL should open the intended Google Search business profile or its updates
view. Verify it manually in the persistent Chromium profile. Client values are
validated, including email, HTTPS URL, timezone, and positive retry settings.

The `clients` table can also be managed with any SQLite administration tool.
Restart the scheduler after changing client schedules so jobs are reloaded.
Set `active` to `0` to disable a client.

## Run

```bash
# Run continuously using every active client's local time and timezone
python main.py

# Run one client immediately, including configured retries and draft creation
python main.py --run-client 1

# Run every active client immediately
python main.py --run-all

# Show today's per-client state, based on each client's local date
python main.py --status
```

For production, run `python main.py` under a process supervisor such as systemd
with a dedicated OS user, a writable project directory, and automatic restart
on failure. Do not run multiple scheduler processes against the same browser
profile. Chromium access is serialized in-process because a persistent profile
cannot safely be opened by concurrent browser instances.

## Retries and duplicate prevention

`max_retries` is the maximum number of check attempts for that client/date,
including the initial attempt. With `18:00`, a 30-minute interval, and `3`,
attempts occur at approximately 18:00, 18:30, and 19:00.

SQLite enforces one `daily_post_checks` row per client/date. Existing
`draft_created` rows are skipped, preventing normal scheduler/manual reruns from
creating another draft. A SQLite processing lease prevents scheduled and manual
runs from creating drafts concurrently. A deterministic RFC Message-ID lets a
later run reconcile a Gmail draft if the process stopped after Gmail created it
but before SQLite stored the draft ID. If all attempts fail, the row is marked `failed`, the
reason is written to `logs/app.log`, and no client draft is created.

## Screenshots and drafts

Evidence is stored as:

```text
screenshots/<business-slug>-<client-id>/YYYY-MM-DD.png
```

The checker prefers a screenshot of the matching post card and falls back to
the current viewport if Google detaches/re-renders that card.

Email subject and body are configured by `EMAIL_SUBJECT_TEMPLATE` and
`EMAIL_TEMPLATE_FILE`. Available placeholders are:

- `{{client_name}}`
- `{{business_name}}`
- `{{date}}`
- `{{agency_name}}`

After the Gmail API returns a draft ID, it is recorded in SQLite and status
becomes `draft_created`. Open Gmail Drafts, review the recipient, text, and
attachment, then manually click Send.

## Logs and troubleshooting

Structured JSON logs are written to `logs/app.log`; concise messages also go to
the console. OAuth tokens, credentials, and passwords are never logged.

Common issues:

- **Chromium executable missing:** run `python -m playwright install chromium`.
- **Login required in headless mode:** set `HEADLESS=false` and run
  `--test-client`.
- **CAPTCHA/2FA:** complete it manually. Increase
  `MANUAL_LOGIN_TIMEOUT_MINUTES` if necessary.
- **OAuth redirect/consent failure:** confirm Desktop app credentials, Gmail API
  enablement, consent-screen test user, and `credentials.json` placement.
- **Profile not detected:** verify the client's URL and business name in the
  same persistent browser profile.
- **Post exists but is not verified:** confirm that Google visibly displays
  `Today`, a minute/hour relative date, an exact current date, or a semantic
  `<time datetime>` value. The checker intentionally avoids guessing.
- **Browser profile in use:** stop other verifier processes and close Chromium
  instances using `browser_profile/`.

## Updating Google selectors

Google-specific UI hints are isolated in `services/selectors.py`:

- `UPDATES_LABELS` controls accessible button/link text fallbacks.
- `POST_CARD_SELECTORS` identifies candidate post cards.
- `PROFILE_CONTAINER_SELECTORS` identifies business-profile containers.
- login and security-challenge text are also centralized there.

Use `--test-client` with `HEADLESS=false`, inspect `logs/app.log`, and update
the narrowest semantic selector or label. Prefer accessible roles, visible
text, semantic elements, stable attributes, and DOM relationships. Do not add
screen coordinates or anti-detection techniques.

## Tests

Browser behavior is separated behind services so workflow tests use fakes and
never contact Google or Gmail:

```bash
pytest
```

Tests cover timezone calculations, client validation, SQLite operations,
per-day deduplication, retry exhaustion, one-draft behavior, screenshot paths,
and email template rendering.

## Database

`clients` stores schedule and contact configuration. `daily_post_checks` stores
attempt count, lifecycle status, screenshot, verification time, error, and
Gmail draft ID. The supported statuses are `pending`, `checking`, `published`,
`not_found`, `retrying`, `failed`, and `draft_created`.
