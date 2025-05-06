"""
Chrome Tab Controller using Chrome DevTools Protocol (CDP).

This module provides direct control of Chrome tabs without using Playwright.
"""

import asyncio
import base64
import gc
import json
import logging
import os
import shutil
import socket
import subprocess
import sys
from typing import Any, Dict, List, Optional, Union

import httpx
import psutil
from pydantic import BaseModel, Field

from browser_use.browser.chrome import (
    CHROME_ARGS,
    CHROME_DETERMINISTIC_RENDERING_ARGS,
    CHROME_DISABLE_SECURITY_ARGS,
    CHROME_DOCKER_ARGS,
    CHROME_HEADLESS_ARGS,
)
from browser_use.browser.utils.screen_resolution import get_screen_resolution, get_window_adjustments
from browser_use.utils import time_execution_async

logger = logging.getLogger(__name__)

IN_DOCKER = os.environ.get('IN_DOCKER', 'false').lower()[0] in 'ty1'


class ChromeTabConfig(BaseModel):
    """Configuration for Chrome Tab Controller."""
    
    browser_binary_path: Optional[str] = None
    headless: bool = False
    disable_security: bool = False
    deterministic_rendering: bool = False
    keep_alive: bool = Field(default=False)
    extra_browser_args: List[str] = Field(default_factory=list)
    target_tab_url: Optional[str] = None  # URL pattern to match for selecting a specific tab
    debug_port: int = 9222
    startup_timeout: int = 30  # Seconds to wait for Chrome to start
    user_data_dir: Optional[str] = None  # Chrome user data directory


class ChromeTabController:
    """
    Chrome Tab Controller using Chrome DevTools Protocol.
    
    This class allows direct control of Chrome tabs without using Playwright.
    It can connect to an existing Chrome instance or launch a new one.
    """
    
    def __init__(self, config: Optional[ChromeTabConfig] = None):
        logger.debug('🌎  Initializing Chrome Tab Controller')
        self.config = config or ChromeTabConfig()
        self._chrome_subprocess = None
        self._client = None
        self._tab_id = None
        self._base_url = f"http://localhost:{self.config.debug_port}"
        self._process = None  # Store the subprocess.Process object
    
    async def _get_tabs(self) -> List[Dict[str, Any]]:
        """Get list of available tabs from Chrome."""
        try:
            async with httpx.AsyncClient() as client:
                response = await client.get(f"{self._base_url}/json/list", timeout=5)
                if response.status_code != 200:
                    raise RuntimeError(f"Failed to get tabs: {response.text}")
                return response.json()
        except httpx.RequestError as e:
            logger.error(f"Error getting tabs: {e}")
            return []
    
    async def _find_target_tab(self) -> Optional[Dict[str, Any]]:
        """Find a specific tab based on URL pattern."""
        tabs = await self._get_tabs()
        
        # If no target URL is specified, use the first available tab
        if not self.config.target_tab_url:
            for tab in tabs:
                if tab.get('type') == 'page':
                    return tab
            return None
        
        # Find tab matching the target URL pattern
        for tab in tabs:
            if (tab.get('type') == 'page' and 
                self.config.target_tab_url in tab.get('url', '')):
                return tab
        
        return None
    
    async def _create_new_tab(self) -> Dict[str, Any]:
        """Create a new tab in Chrome."""
        try:
            async with httpx.AsyncClient() as client:
                response = await client.get(f"{self._base_url}/json/new", timeout=5)
                if response.status_code != 200:
                    raise RuntimeError(f"Failed to create new tab: {response.text}")
                return response.json()
        except httpx.RequestError as e:
            raise RuntimeError(f"Failed to create new tab: {e}")
    
    async def _close_tab(self, tab_id: str) -> None:
        """Close a specific tab."""
        try:
            async with httpx.AsyncClient() as client:
                await client.get(f"{self._base_url}/json/close/{tab_id}", timeout=5)
        except httpx.RequestError as e:
            logger.warning(f"Failed to close tab: {e}")
    
    def _find_chrome_binary(self) -> str:
        """Find Chrome binary if not specified."""
        if self.config.browser_binary_path and os.path.exists(self.config.browser_binary_path):
            return self.config.browser_binary_path
        
        # Common Chrome binary locations
        possible_paths = []
        
        if sys.platform.startswith('linux'):
            possible_paths = [
                "/usr/bin/google-chrome",
                "/usr/bin/google-chrome-stable",
                "/usr/bin/chromium",
                "/usr/bin/chromium-browser",
                "/snap/bin/chromium",
            ]
        elif sys.platform.startswith('darwin'):  # macOS
            possible_paths = [
                "/Applications/Google Chrome.app/Contents/MacOS/Google Chrome",
                "/Applications/Chromium.app/Contents/MacOS/Chromium",
            ]
        elif sys.platform.startswith('win'):
            possible_paths = [
                "C:\\Program Files\\Google\\Chrome\\Application\\chrome.exe",
                "C:\\Program Files (x86)\\Google\\Chrome\\Application\\chrome.exe",
                os.path.expandvars("%LOCALAPPDATA%\\Google\\Chrome\\Application\\chrome.exe"),
            ]
        
        # Check if Chrome is in PATH
        chrome_in_path = shutil.which("google-chrome") or shutil.which("chrome") or shutil.which("chromium")
        if chrome_in_path:
            return chrome_in_path
        
        # Check common locations
        for path in possible_paths:
            if os.path.exists(path):
                return path
        
        raise FileNotFoundError(
            "Chrome binary not found. Please specify the browser_binary_path in the config."
        )
    
    def _is_port_available(self, port: int) -> bool:
        """Check if a port is available."""
        with socket.socket(socket.AF_INET, socket.SOCK_STREAM) as s:
            try:
                s.bind(('localhost', port))
                return True
            except socket.error:
                return False
    
    def _find_available_port(self) -> int:
        """Find an available port if the specified one is in use."""
        if self._is_port_available(self.config.debug_port):
            return self.config.debug_port
        
        # Try to find an available port
        for port in range(9222, 9300):
            if self._is_port_available(port):
                logger.info(f"Port {self.config.debug_port} is in use, using port {port} instead")
                self.config.debug_port = port
                self._base_url = f"http://localhost:{port}"
                return port
        
        raise RuntimeError("Could not find an available port for Chrome remote debugging")
    
    async def _is_chrome_running_with_remote_debugging(self) -> bool:
        """Check if Chrome is already running with remote debugging enabled."""
        try:
            async with httpx.AsyncClient() as client:
                response = await client.get(f"{self._base_url}/json/version", timeout=2)
                return response.status_code == 200
        except httpx.RequestError:
            return False
    
    async def _setup_chrome_instance(self) -> None:
        """Setup Chrome instance with remote debugging enabled."""
        # Check if Chrome is already running with remote debugging
        if await self._is_chrome_running_with_remote_debugging():
            logger.info(f'🔌  Reusing existing Chrome instance on port {self.config.debug_port}')
            return
        
        logger.debug('🌎  No existing Chrome instance found with remote debugging, starting a new one')
        
        # Find Chrome binary
        try:
            chrome_path = self._find_chrome_binary()
            logger.info(f"Using Chrome binary: {chrome_path}")
        except FileNotFoundError as e:
            logger.error(str(e))
            raise
        
        # Find available port
        self._find_available_port()
        
        # Prepare user data directory
        user_data_args = []
        if self.config.user_data_dir:
            user_data_dir = os.path.expanduser(self.config.user_data_dir)
            os.makedirs(user_data_dir, exist_ok=True)
            user_data_args = [f"--user-data-dir={user_data_dir}"]
        
        # Start a new Chrome instance with remote debugging
        chrome_launch_args = [
            chrome_path,
            f'--remote-debugging-port={self.config.debug_port}',
            "--no-first-run",
            "--no-default-browser-check",
            *user_data_args,
            *CHROME_ARGS,
            *(CHROME_DOCKER_ARGS if IN_DOCKER else []),
            *(CHROME_HEADLESS_ARGS if self.config.headless else []),
            *(CHROME_DISABLE_SECURITY_ARGS if self.config.disable_security else []),
            *(CHROME_DETERMINISTIC_RENDERING_ARGS if self.config.deterministic_rendering else []),
            *self.config.extra_browser_args,
        ]
        
        # Remove duplicates while preserving order
        seen = set()
        chrome_launch_args = [x for x in chrome_launch_args if not (x in seen or seen.add(x))]
        
        logger.debug(f"Starting Chrome with args: {' '.join(chrome_launch_args)}")
        
        # Launch Chrome process
        try:
            # Use subprocess directly for better control
            self._process = subprocess.Popen(
                chrome_launch_args,
                stdout=subprocess.PIPE,
                stderr=subprocess.PIPE,
                text=True,
                bufsize=1,  # Line buffered
            )
            
            # Check if process started but immediately exited
            if self._process.poll() is not None:
                stdout, stderr = self._process.communicate()
                logger.error(f"Chrome process exited immediately with code {self._process.returncode}")
                logger.error(f"Chrome stdout: {stdout}")
                logger.error(f"Chrome stderr: {stderr}")
                raise RuntimeError(f"Chrome process exited immediately with code {self._process.returncode}")
            
            logger.debug(f"Chrome process started with PID {self._process.pid}")
            
            # Store process in psutil only if it's still running
            try:
                self._chrome_subprocess = psutil.Process(self._process.pid)
            except psutil.NoSuchProcess:
                stdout, stderr = self._process.communicate()
                logger.error(f"Chrome process exited unexpectedly")
                logger.error(f"Chrome stdout: {stdout}")
                logger.error(f"Chrome stderr: {stderr}")
                raise RuntimeError("Chrome process exited unexpectedly")
            
        except (subprocess.SubprocessError, OSError) as e:
            logger.error(f"Failed to start Chrome process: {e}")
            raise RuntimeError(f"Failed to start Chrome process: {e}")
        
        # Wait for Chrome to start and be ready
        timeout = self.config.startup_timeout
        logger.info(f"Waiting up to {timeout} seconds for Chrome to start...")
        
        for i in range(timeout):
            # Check if process is still running
            if self._process.poll() is not None:
                stdout, stderr = self._process.communicate()
                logger.error(f"Chrome process exited with code {self._process.returncode}")
                logger.error(f"Chrome stdout: {stdout}")
                logger.error(f"Chrome stderr: {stderr}")
                raise RuntimeError(f"Chrome process exited with code {self._process.returncode}")
            
            # Check if Chrome is responding to remote debugging requests
            if await self._is_chrome_running_with_remote_debugging():
                logger.info(f'🌎  Chrome started successfully on port {self.config.debug_port}')
                return
            
            if i % 5 == 0:  # Log only every 5 seconds to reduce noise
                logger.debug(f"Waiting for Chrome to be ready... ({i}/{timeout}s)")
            
            await asyncio.sleep(1)
        
        # If we get here, Chrome didn't start properly
        if self._process and self._process.poll() is None:
            logger.error("Chrome process is running but not responding to remote debugging requests")
            # Try to get more diagnostic information
            try:
                self._process.terminate()
                stdout, stderr = self._process.communicate(timeout=5)
                logger.error(f"Chrome stdout: {stdout}")
                logger.error(f"Chrome stderr: {stderr}")
            except Exception as e:
                logger.error(f"Could not get Chrome process output: {e}")
                self._process.kill()  # Force kill if terminate doesn't work
        
        raise RuntimeError("Failed to start Chrome with remote debugging")
    
    @time_execution_async('--init (chrome tab)')
    async def connect(self) -> None:
        """Connect to a Chrome tab."""
        # Ensure Chrome is running with remote debugging
        await self._setup_chrome_instance()
        
        # Find or create target tab
        tab = await self._find_target_tab()
        if not tab:
            if self.config.target_tab_url:
                logger.info(f"No tab found matching URL pattern '{self.config.target_tab_url}', creating new tab")
            tab = await self._create_new_tab()
        
        self._tab_id = tab['id']
        logger.info(f"Connected to tab: {tab.get('title', 'Untitled')} ({tab.get('url', 'No URL')})")
        
        # Create WebSocket client for CDP communication
        try:
            self._ws_url = tab['webSocketDebuggerUrl']
            self._client = await httpx.AsyncClient().aconnect_ws(self._ws_url)
            
            # Initialize CDP session
            await self._send_command("Runtime.enable")
            await self._send_command("Page.enable")
            await self._send_command("Network.enable")
            
            return self
        except Exception as e:
            logger.error(f"Failed to connect to Chrome tab: {e}")
            raise RuntimeError(f"Failed to connect to Chrome tab: {e}")
    
    async def _send_command(self, method: str, params: Optional[Dict[str, Any]] = None) -> Dict[str, Any]:
        """Send a command to Chrome using CDP."""
        if not self._client:
            raise RuntimeError("Not connected to Chrome tab")
        
        command_id = id(method) + id(params or {})
        message = {
            "id": command_id,
            "method": method,
        }
        if params:
            message["params"] = params
        
        await self._client.send_text(json.dumps(message))
        
        # Wait for response with matching id
        while True:
            response = await self._client.receive_text()
            data = json.loads(response)
            if "id" in data and data["id"] == command_id:
                if "error" in data:
                    raise RuntimeError(f"CDP command error: {data['error']}")
                return data.get("result", {})
    
    async def navigate(self, url: str) -> None:
        """Navigate to a URL."""
        await self._send_command("Page.navigate", {"url": url})
    
    async def evaluate(self, expression: str) -> Any:
        """Evaluate JavaScript in the tab."""
        result = await self._send_command(
            "Runtime.evaluate", 
            {
                "expression": expression,
                "returnByValue": True,
                "awaitPromise": True
            }
        )
        if "exceptionDetails" in result:
            raise RuntimeError(f"JavaScript error: {result['exceptionDetails']}")
        return result.get("result", {}).get("value")
    
    async def get_document_content(self) -> str:
        """Get the HTML content of the page."""
        return await self.evaluate("document.documentElement.outerHTML")
    
    async def click(self, selector: str) -> None:
        """Click on an element."""
        await self.evaluate(f"""
            (function() {{
                const element = document.querySelector("{selector}");
                if (!element) throw new Error("Element not found: {selector}");
                element.click();
            }})()
        """)
    
    async def type(self, selector: str, text: str) -> None:
        """Type text into an input element."""
        await self.evaluate(f"""
            (function() {{
                const element = document.querySelector("{selector}");
                if (!element) throw new Error("Element not found: {selector}");
                element.value = "{text}";
                element.dispatchEvent(new Event('input', {{ bubbles: true }}));
                element.dispatchEvent(new Event('change', {{ bubbles: true }}));
            }})()
        """)
    
    async def wait_for_selector(self, selector: str, timeout: int = 30000) -> None:
        """Wait for an element to appear."""
        await self.evaluate(f"""
            (function() {{
                return new Promise((resolve, reject) => {{
                    if (document.querySelector("{selector}")) {{
                        return resolve();
                    }}
                    
                    const observer = new MutationObserver(() => {{
                        if (document.querySelector("{selector}")) {{
                            observer.disconnect();
                            resolve();
                        }}
                    }});
                    
                    observer.observe(document.body, {{ 
                        childList: true, 
                        subtree: true 
                    }});
                    
                    setTimeout(() => {{
                        observer.disconnect();
                        reject(new Error("Timeout waiting for selector: {selector}"));
                    }}, {timeout});
                }});
            }})()
        """)
    
    async def screenshot(self, path: str) -> None:
        """Take a screenshot of the current page."""
        result = await self._send_command("Page.captureScreenshot")
        with open(path, "wb") as f:
            f.write(base64.b64decode(result["data"]))
    
    async def close(self) -> None:
        """Close the connection and optionally the browser."""
        if self._client:
            await self._client.aclose()
            self._client = None
        
        if not self.config.keep_alive:
            if self._tab_id:
                try:
                    await self._close_tab(self._tab_id)
                except Exception as e:
                    logger.debug(f"Failed to close tab: {e}")
            
            if self._process and self._process.poll() is None:
                try:
                    self._process.terminate()
                    self._process.wait(timeout=5)
                except Exception as e:
                    logger.debug(f"Failed to terminate Chrome process gracefully: {e}")
                    try:
                        self._process.kill()
                    except Exception as e:
                        logger.debug(f"Failed to kill Chrome process: {e}")
            
            if self._chrome_subprocess:
                try:
                    # Kill all child processes to prevent zombie processes
                    for proc in self._chrome_subprocess.children(recursive=True):
                        try:
                            proc.kill()
                        except psutil.NoSuchProcess:
                            pass
                    
                    if self._chrome_subprocess.is_running():
                        self._chrome_subprocess.kill()
                except Exception as e:
                    logger.debug(f"Failed to terminate Chrome subprocess: {e}")
            
            # Force garbage collection
            self._chrome_subprocess = None
            self._process = None
            gc.collect()
    
    def __del__(self):
        """Cleanup when object is destroyed."""
        try:
            if self._client or self._process:
                loop = asyncio.get_running_loop()
                if loop.is_running():
                    loop.create_task(self.close())
                else:
                    asyncio.run(self.close())
        except Exception as e:
            logger.debug(f"Failed to cleanup in destructor: {e}")
