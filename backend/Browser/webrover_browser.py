# webrover_browser.py
import asyncio
import platform
from pathlib import Path
from typing import Optional, Tuple
from playwright.async_api import async_playwright, Browser, BrowserContext, Page
import re
import os
import aiohttp
import socket

class WebRoverBrowser:
    def __init__(self, 
                 user_data_dir: Optional[str] = None,
                 headless: bool = False,
                 proxy: Optional[str] = None):
        self.user_data_dir = user_data_dir or self._default_user_dir()
        self.headless = headless
        self.proxy = proxy
        self._browser: Optional[Browser] = None
        self._context: Optional[BrowserContext] = None
        self._playwright = None

    def _default_user_dir(self) -> str:
        """Get an isolated Chrome profile directory for WebRover."""
        system = platform.system()
        if system == "Windows":
            return str(Path.home() / "AppData/Local/WebRover/Chrome")
        elif system == "Darwin":
            return str(Path.home() / "Library/Application Support/WebRover/Chrome")
        else:  # Linux
            return str(Path.home() / ".config/webrover/chrome")

    async def connect_to_chrome(self, 
                              timeout: float = 30,
                              retries: int = 3) -> Tuple[Browser, BrowserContext]:
        """Connect to existing Chrome instance with retry logic"""
        self._playwright = await async_playwright().start()
        
        # Check if Chrome is already running on remote debugging port 9222
        is_running = False
        try:
            sock = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
            sock.settimeout(1.0)
            is_running = (sock.connect_ex(('127.0.0.1', 9222)) == 0)
            sock.close()
        except Exception:
            pass

        if not is_running:
            print("Starting Chrome with remote debugging...")
            await self.launch_chrome_with_remote_debugging()
            await asyncio.sleep(2)  # Wait for Chrome to initialize
        else:
            print("Chrome is already listening on port 9222, connecting directly...")
        
        print("Attempting to connect to Chrome...")
        for attempt in range(retries):
            try:
                # Connect to the existing Chrome instance
                ws_endpoint = None
                print("Getting browser websocket URL")
                # Get the WebSocket endpoint from Chrome's debugging API
                async with aiohttp.ClientSession() as session:
                    # Then get the browser websocket URL
                    print("Getting browser websocket URL")
                    async with session.get("http://127.0.0.1:9222/json/version") as response:
                        data = await response.json()
                        ws_endpoint = data.get('webSocketDebuggerUrl')
                
                if not ws_endpoint:
                    raise RuntimeError("Could not get WebSocket debugger URL")
                
                print(f"Connecting to WebSocket endpoint: {ws_endpoint}")
                self._browser = await self._playwright.chromium.connect_over_cdp(
                    ws_endpoint
                )


                print("Connected to browser:", self._browser)
                
                # Use the first available context instead of creating a new one
                contexts = self._browser.contexts
                if not contexts:
                    raise RuntimeError("No browser contexts available after connection")
                self._context = contexts[0]
                print("Context: ", self._context)
                
                print("Successfully connected to Chrome")
                return self._browser, self._context
            
            except Exception as e:
                print(f"Connection attempt {attempt + 1} failed: {str(e)}")
                if attempt == retries - 1:
                    raise RuntimeError(f"Failed to connect to Chrome after {retries} attempts: {str(e)}")
                await asyncio.sleep(2 ** attempt)

    async def launch_chrome_with_remote_debugging(self):
        """Launch Chrome with remote debugging port"""
        # First check if port 9222 is already open
        try:
            sock = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
            sock.settimeout(1.0)
            if sock.connect_ex(('127.0.0.1', 9222)) == 0:
                sock.close()
                print("Chrome is already listening on remote debugging port 9222")
                return None
            sock.close()
        except Exception:
            pass

        # First launch Chrome normally to let user select profile
        chrome_path = {
            "Windows": "C:\\Program Files\\Google\\Chrome\\Application\\chrome.exe",
            "Darwin": "/Applications/Google Chrome.app/Contents/MacOS/Google Chrome",
            "Linux": "/usr/bin/google-chrome"
        }.get(platform.system())

        cmd = [
            chrome_path,
            f"--remote-debugging-port=9222",
            f"--user-data-dir={self.user_data_dir}",
            "--no-first-run",
            "--no-default-browser-check",
            "--start-maximized",
        ]

        if self.headless:
            cmd.append("--headless=new")

        process = None
        try:
            Path(self.user_data_dir).mkdir(parents=True, exist_ok=True)
            print("Launching Chrome with command:", " ".join(cmd))
            process = await asyncio.create_subprocess_exec(
                *cmd,
                stdout=asyncio.subprocess.PIPE,
                stderr=asyncio.subprocess.PIPE
            )
            
            print("Waiting for Chrome to start and verify port is listening")
            # Wait for Chrome to start and verify port is listening
            for _ in range(10):  # Try for 10 seconds
                await asyncio.sleep(1)
                try:
                    sock = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
                    result = sock.connect_ex(('127.0.0.1', 9222))
                    sock.close()
                    if result == 0:
                        print("Chrome started successfully with remote debugging port")
                        return process
                except:
                    continue
                if process.returncode is not None:
                    try:
                        sock = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
                        sock.settimeout(1.0)
                        is_active = (sock.connect_ex(('127.0.0.1', 9222)) == 0)
                        sock.close()
                        if is_active:
                            print("Chrome connected through existing session on port 9222")
                            return None
                    except Exception:
                        pass
                    stderr = await process.stderr.read()
                    raise RuntimeError(
                        f"Chrome exited before opening port 9222: {stderr.decode().strip()}"
                    )
            
            raise RuntimeError("Chrome failed to start with remote debugging port")
            
        except Exception as e:
            print(f"Error launching Chrome: {e}")
            if process and process.returncode is not None:
                stderr = await process.stderr.read()
                print(f"Chrome stderr output: {stderr.decode()}")
            raise RuntimeError(f"Failed to launch Chrome: {str(e)}")

    async def create_context(self, 
                           viewport: dict = {"width": 2560, "height": 1440},
                           user_agent: str = None) -> BrowserContext:
        """Create optimized browser context with human-like settings"""
        if not self._browser:
            raise RuntimeError("Browser not connected. Call connect_to_chrome first.")

        # Return existing context if it exists
        if self._context:
            return self._context

        # Create new context with optimized settings
        self._context = await self._browser.new_context(
            viewport=viewport,
            user_agent=user_agent or self._modern_user_agent(),
            locale="en-US",
            timezone_id="America/New_York",
            permissions=["geolocation"],
            geolocation={"latitude": 40.7128, "longitude": -74.0060},  # NYC
            http_credentials=None,
            proxy=self._proxy_settings(),
            color_scheme="light",
        )

        await self._add_anti_detection()
        await self._configure_network()
        return self._context

    async def _add_anti_detection(self):
        """Inject JavaScript to mask automation"""
        await self._context.add_init_script("""
            Object.defineProperty(navigator, 'webdriver', { get: () => undefined });
            Object.defineProperty(navigator, 'plugins', { get: () => [1, 2, 3] });
            Object.defineProperty(navigator, 'languages', { get: () => ['en-US'] });
            window.chrome = { runtime: {} };
        """)

    async def _configure_network(self):
        """Block unnecessary resources for faster loading"""
        await self._context.route("**/*.{png,jpg,jpeg,webp}", lambda route: route.abort())
        await self._context.route("**/*.css", lambda route: route.abort())
        await self._context.route(re.compile(r"(analytics|tracking|beacon)"), lambda route: route.abort())

    def _modern_user_agent(self) -> str:
        """Generate current Chrome user agent string"""
        versions = {
            "Windows": "122.0.0.0",
            "Darwin": "122.0.0.0",
            "Linux": "122.0.0.0"
        }
        system = platform.system()
        return f"Mozilla/5.0 ({self._os_info()}) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/{versions[system]} Safari/537.36"

    def _os_info(self) -> str:
        """Get platform-specific OS info for user agent"""
        if platform.system() == "Windows":
            return "Windows NT 10.0; Win64; x64"
        elif platform.system() == "Darwin":
            return "Macintosh; Intel Mac OS X 10_15_7"
        else:
            return "X11; Linux x86_64"

    def _proxy_settings(self) -> Optional[dict]:
        """Parse proxy configuration"""
        if not self.proxy:
            return None
        return {
            "server": self.proxy,
            "username": os.getenv("PROXY_USER"),
            "password": os.getenv("PROXY_PASS")
        }

    async def close(self):
        """Cleanup resources"""
        if self._context:
            await self._context.close()
        if self._browser:
            await self._browser.close()
        if self._playwright:
            await self._playwright.stop()
