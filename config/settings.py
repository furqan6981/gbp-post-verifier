from functools import lru_cache
from pathlib import Path

from pydantic import Field
from pydantic_settings import BaseSettings, SettingsConfigDict


PROJECT_ROOT = Path(__file__).resolve().parents[1]


class Settings(BaseSettings):
    model_config = SettingsConfigDict(
        env_file=PROJECT_ROOT / ".env",
        env_file_encoding="utf-8",
        extra="ignore",
    )

    app_name: str = "GBP Post Verification"
    database_url: str = "sqlite:///data/app.db"
    screenshot_dir: Path = Path("screenshots")
    browser_profile_dir: Path = Path("browser_profile")
    log_dir: Path = Path("logs")

    default_retry_interval_minutes: int = Field(default=30, ge=1)
    default_max_retries: int = Field(default=3, ge=1)
    agency_name: str = "Your Agency Name"

    gmail_credentials_file: Path = Path("credentials.json")
    gmail_token_file: Path = Path("token.json")
    email_subject_template: str = "Google Business Profile Post – {{date}}"
    email_template_file: Path = Path("templates/email_template.txt")

    headless: bool = False
    browser_timeout_seconds: int = Field(default=45, ge=5)
    manual_login_timeout_minutes: int = Field(default=10, ge=1)

    def resolve_path(self, value: Path) -> Path:
        return value if value.is_absolute() else PROJECT_ROOT / value

    @property
    def database_path(self) -> Path:
        prefix = "sqlite:///"
        if not self.database_url.startswith(prefix):
            raise ValueError("Only sqlite:/// DATABASE_URL values are supported")
        return self.resolve_path(Path(self.database_url.removeprefix(prefix)))

    @property
    def screenshots_path(self) -> Path:
        return self.resolve_path(self.screenshot_dir)

    @property
    def browser_profile_path(self) -> Path:
        return self.resolve_path(self.browser_profile_dir)

    @property
    def logs_path(self) -> Path:
        return self.resolve_path(self.log_dir)

    @property
    def credentials_path(self) -> Path:
        return self.resolve_path(self.gmail_credentials_file)

    @property
    def token_path(self) -> Path:
        return self.resolve_path(self.gmail_token_file)

    @property
    def template_path(self) -> Path:
        return self.resolve_path(self.email_template_file)

    def create_directories(self) -> None:
        for path in (
            self.database_path.parent,
            self.screenshots_path,
            self.browser_profile_path,
            self.logs_path,
        ):
            path.mkdir(parents=True, exist_ok=True)


@lru_cache
def get_settings() -> Settings:
    return Settings()
