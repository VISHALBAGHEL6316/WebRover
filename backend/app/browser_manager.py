from Browser.webrover_browser import WebRoverBrowser
from typing import Dict, Any, Tuple
from playwright.async_api import Page, Browser

async def setup_browser(go_to_page: str) -> Tuple[WebRoverBrowser, Page]:
    """
    Sets up a browser instance and returns the browser and page objects.
    """
    print(f"Setting up browser for {go_to_page}")
    rover_browser = WebRoverBrowser()
    _, context = await rover_browser.connect_to_chrome()

    page = await context.new_page()
    
    try:
        await page.goto(go_to_page, timeout=80000, wait_until="domcontentloaded")
    except Exception as e:
        print(f"Error loading page: {e}")
        # Fallback to Google if the original page fails to load
        await page.goto("https://www.google.com", timeout=100000, wait_until="domcontentloaded")

    return rover_browser, page

async def cleanup_browser_session(browser: WebRoverBrowser) -> None:
    """
    Cleans up browser session using WebRoverBrowser's close method.
    This ensures proper cleanup of all resources including context, browser, and playwright.
    """
    try:
        if browser:
            await browser.close()
            print("Browser session cleaned up successfully")
    except Exception as e:
        print(f"Error during browser cleanup: {e}")
        raise

