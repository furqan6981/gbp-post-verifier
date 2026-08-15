from datetime import date
from pathlib import Path

from services.screenshot_service import ScreenshotService


def test_screenshot_filename_generation(tmp_path: Path) -> None:
    service = ScreenshotService(tmp_path)
    path = service.path_for("ABC Plumbing & Drain!", 42, date(2026, 8, 8))
    assert path == tmp_path / "abc-plumbing-drain-42" / "2026-08-08.png"
    assert path.parent.is_dir()
