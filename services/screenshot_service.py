from datetime import date
from pathlib import Path

from playwright.sync_api import Locator, Page

from utils.slugify import slugify


class ScreenshotService:
    def __init__(self, root: Path):
        self.root = root

    def path_for(
        self, business_name: str, client_id: int, check_date: date
    ) -> Path:
        directory = self.root / f"{slugify(business_name)}-{client_id}"
        directory.mkdir(parents=True, exist_ok=True)
        return directory / f"{check_date.isoformat()}.png"

    def capture(
        self,
        page: Page,
        post: Locator | None,
        business_name: str,
        client_id: int,
        check_date: date,
    ) -> Path:
        path = self.path_for(business_name, client_id, check_date)
        if post is not None:
            try:
                post.scroll_into_view_if_needed()
                post.screenshot(path=str(path))
                return path
            except Exception:
                # The Google card can be detached while its carousel rerenders.
                pass
        page.screenshot(path=str(path), full_page=False)
        return path
