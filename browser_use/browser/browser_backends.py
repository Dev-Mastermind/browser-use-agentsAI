from typing import Any, Dict, Optional
from .browser_interface import BrowserInterface

# --- Playwright Implementation ---
from playwright.async_api import async_playwright

class PlaywrightBrowser(BrowserInterface):
    def __init__(self):
        self._playwright = None
        self._browser = None
        self._page = None

    async def start(self):
        self._playwright = await async_playwright().start()
        self._browser = await self._playwright.chromium.launch(headless=False)
        self._page = await self._browser.new_page()

    async def stop(self):
        if self._browser:
            await self._browser.close()
        if self._playwright:
            await self._playwright.stop()

    async def navigate(self, url: str):
        await self._page.goto(url)

    async def click(self, selector: str):
        await self._page.click(selector)

    async def evaluate(self, script: str, *args, **kwargs) -> Any:
        return await self._page.evaluate(script, *args, **kwargs)

# --- Chrome Extension Implementation (stub, assumes local HTTP API) ---
import aiohttp

class ChromeExtensionBrowser(BrowserInterface):
    def __init__(self, endpoint_url: str = "http://localhost:8765"):
        self.endpoint_url = endpoint_url
        self.session = None

    async def start(self):
        self.session = aiohttp.ClientSession()
        # Optionally: perform handshaking with the extension here

    async def stop(self):
        if self.session:
            await self.session.close()

    async def _post(self, action: str, data: Optional[Dict[str, Any]] = None) -> Any:
        url = f"{self.endpoint_url}/{action}"
        async with self.session.post(url, json=data or {}) as resp:
            return await resp.json()

    async def navigate(self, url: str):
        print(f"Navigating to {url}")
        return await self._post("navigate", {"url": url})

    async def click(self, selector: str):
        return await self._post("click", {"selector": selector})

    async def evaluate(self, script: str, *args, **kwargs) -> Any:
        return await self._post("evaluate", {"script": script, "args": args, "kwargs": kwargs})

# --- Factory ---

def get_browser(backend: str = "playwright", **kwargs) -> BrowserInterface:
    if backend == "playwright":
        return PlaywrightBrowser()
    elif backend == "chrome_extension":
        return ChromeExtensionBrowser(**kwargs)
    else:
        raise ValueError(f"Unknown browser backend '{backend}'")
