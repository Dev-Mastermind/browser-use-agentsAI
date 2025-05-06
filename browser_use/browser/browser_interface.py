from abc import ABC, abstractmethod
from typing import Any

class BrowserInterface(ABC):
    @abstractmethod
    async def start(self):
        """Start the browser instance (if needed)."""
        pass

    @abstractmethod
    async def stop(self):
        """Stop/cleanup the browser instance."""
        pass

    @abstractmethod
    async def navigate(self, url: str):
        """Navigate to a URL."""
        pass

    @abstractmethod
    async def click(self, selector: str):
        """Click an element specified by a CSS selector."""
        pass

    @abstractmethod
    async def evaluate(self, script: str, *args, **kwargs) -> Any:
        """Evaluate JS in context of the page."""
        pass
