import subprocess
from typing import Optional
from playwright.async_api import async_playwright, BrowserContext, Playwright
from src.config import BROWSER_PROFILE_DIR, STORAGE_STATE_PATH


def send_macos_notification(title: str, message: str) -> None:
    """Fires a native macOS desktop alert when the browser switches to headed mode."""
    try:
        script = f'display notification "{message}" with title "{title}" sound name "Glass"'
        subprocess.run(["osascript", "-e", script], check=False)
    except Exception:
        pass


class BrowserSessionManager:
    """
    Manages a persistent Chromium context that starts in Headless mode (`headless=True`)
    and seamlessly relaunches in Headed mode (`headless=False`) using the exact same
    user_data_dir and saved cookies/storage_state if any issue or blocker occurs.
    """

    def __init__(self):
        self.playwright: Optional[Playwright] = None
        self.context: Optional[BrowserContext] = None
        self.is_headless: bool = True

    async def launch(self, headless: bool = True) -> BrowserContext:
        if self.context:
            await self.save_and_close()

        self.playwright = await async_playwright().start()
        self.is_headless = headless

        if not headless:
            send_macos_notification(
                "Job Harness: Headed Mode Activated",
                "Opening visible browser window to resume your job application.",
            )

        self.context = await self.playwright.chromium.launch_persistent_context(
            user_data_dir=str(BROWSER_PROFILE_DIR),
            headless=headless,
            viewport={"width": 1440, "height": 900},
            args=[
                "--disable-blink-features=AutomationControlled",
                "--no-sandbox",
            ],
        )
        return self.context

    async def save_and_close(self) -> None:
        if self.context:
            try:
                await self.context.storage_state(path=str(STORAGE_STATE_PATH))
            except Exception:
                pass
            try:
                await self.context.close()
            except Exception:
                pass
            self.context = None

        if self.playwright:
            try:
                await self.playwright.stop()
            except Exception:
                pass
            self.playwright = None
