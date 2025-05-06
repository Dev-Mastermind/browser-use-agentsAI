"""
Example script demonstrating how to use the Chrome Tab Controller.

This example shows how to connect to a specific tab in your Chrome browser
and interact with it using the Chrome DevTools Protocol.
"""

import asyncio
import logging
import os
import sys
import tempfile
from pathlib import Path

from browser_use.browser.browser import Browser, BrowserConfig

# Set up logging
logging.basicConfig(
    level=logging.DEBUG,
    format='%(asctime)s - %(name)s - %(levelname)s - %(message)s'
)
logger = logging.getLogger(__name__)

async def main():
    try:
        # Detect OS and set default Chrome path
        if sys.platform.startswith('linux'):
            chrome_path = "/usr/bin/google-chrome"
        elif sys.platform.startswith('darwin'):  # macOS
            chrome_path = "/Applications/Google Chrome.app/Contents/MacOS/Google Chrome"
        elif sys.platform.startswith('win'):
            chrome_path = "C:\\Program Files\\Google\\Chrome\\Application\\chrome.exe"
        else:
            chrome_path = None  # Auto-detect
        
        # Verify Chrome path exists
        if chrome_path and not os.path.exists(chrome_path):
            logger.warning(f"Chrome not found at {chrome_path}, will try to auto-detect")
            chrome_path = None
        
        # Create a temporary user data directory to avoid affecting your main Chrome profile
        # Comment this out if you want to use your existing Chrome profile
        user_data_dir = tempfile.mkdtemp(prefix="chrome_tab_example_")
        logger.info(f"Using temporary user data directory: {user_data_dir}")
        
        # Create browser config
        config = BrowserConfig(
            browser_binary_path=chrome_path,
            
            # Use a temporary user data directory
            # Comment this out if you want to use your existing Chrome profile
            user_data_dir=user_data_dir,
            
            # To target a specific tab, provide a URL pattern
            # If you're using an existing Chrome instance, set this to match an open tab
            target_tab_url="github.com",  # Will connect to a tab containing this URL
            
            # Keep browser alive after script finishes
            # Set to False to close the browser when done
            keep_alive=False,
            
            # Additional Chrome arguments if needed
            extra_browser_args=[
                "--start-maximized",
                "--disable-extensions",  # Disable extensions for better stability
            ],
            
            # Increase timeout for Chrome startup
            startup_timeout=60,
        )
        
        logger.info(f"Starting Chrome with binary: {config.browser_binary_path or 'Auto-detect'}")
        
        # Create browser instance
        browser = Browser(config=config)
        
        try:
            # Create a browser context
            async with await browser.new_context() as context:
                logger.info("Successfully connected to browser context")
                
                # Navigate to a URL
                logger.info("Navigating to GitHub...")
                await context.goto("https://github.com")
                
                # Wait for a specific element to appear
                logger.info("Waiting for page to load...")
                await context.wait_for_selector("header")
                
                # Get page title
                page_title = await context.evaluate('document.title')
                logger.info(f"Page title: {page_title}")
                
                # Take a screenshot
                screenshot_path = Path("github_homepage.png")
                logger.info(f"Taking screenshot to {screenshot_path}...")
                await context.screenshot(str(screenshot_path))
                logger.info(f"Screenshot saved to {screenshot_path}")
                
                # Search for something
                logger.info("Searching for 'python'...")
                await context.click("input[name='q']")
                await context.fill("input[name='q']", "python")
                await context.evaluate("document.querySelector('input[name=\"q\"]').form.submit()")
                
                # Wait for search results
                logger.info("Waiting for search results...")
                await context.wait_for_selector(".repo-list-item")
                
                # Extract search results
                repos = await context.evaluate("""
                    Array.from(document.querySelectorAll('.repo-list-item'))
                        .slice(0, 5)
                        .map(item => {
                            const nameEl = item.querySelector('a[data-hydro-click]');
                            const descEl = item.querySelector('p');
                            return {
                                name: nameEl ? nameEl.textContent.trim() : 'Unknown',
                                description: descEl ? descEl.textContent.trim() : 'No description',
                                url: nameEl ? nameEl.href : ''
                            };
                        })
                """)
                
                # Display search results
                logger.info("Top Python repositories:")
                for i, repo in enumerate(repos, 1):
                    logger.info(f"{i}. {repo['name']}")
                    logger.info(f"   {repo['description']}")
                    logger.info(f"   URL: {repo['url']}")
                
                # Take another screenshot
                screenshot_path = Path("github_search_results.png")
                logger.info(f"Taking screenshot to {screenshot_path}...")
                await context.screenshot(str(screenshot_path))
                logger.info(f"Screenshot saved to {screenshot_path}")
                
                # Click on the first repository
                logger.info("Clicking on the first repository...")
                await context.click(".repo-list-item:first-child a[data-hydro-click]")
                
                # Wait for repository page to load
                logger.info("Waiting for repository page to load...")
                await context.wait_for_selector("article.markdown-body")
                
                # Get repository details
                repo_info = await context.evaluate("""
                    {
                        title: document.querySelector('h1')?.textContent.trim(),
                        stars: document.querySelector('a[href$="/stargazers"]')?.textContent.trim(),
                        forks: document.querySelector('a[href$="/forks"]')?.textContent.trim(),
                        description: document.querySelector('.f4.my-3')?.textContent.trim()
                    }
                """)
                
                logger.info(f"Repository: {repo_info['title']}")
                logger.info(f"Stars: {repo_info['stars']}")
                logger.info(f"Forks: {repo_info['forks']}")
                logger.info(f"Description: {repo_info['description']}")
                
                # Take a final screenshot
                screenshot_path = Path("github_repository.png")
                logger.info(f"Taking screenshot to {screenshot_path}...")
                await context.screenshot(str(screenshot_path))
                logger.info(f"Screenshot saved to {screenshot_path}")
                
                logger.info("Example completed successfully!")
                
        finally:
            # Close the browser
            logger.info("Closing browser...")
            await browser.close()
            
            # Clean up temporary directory if we created one
            if 'user_data_dir' in locals() and user_data_dir.startswith(tempfile.gettempdir()):
                import shutil
                try:
                    logger.info(f"Cleaning up temporary directory: {user_data_dir}")
                    shutil.rmtree(user_data_dir, ignore_errors=True)
                except Exception as e:
                    logger.warning(f"Failed to clean up temporary directory: {e}")
    
    except Exception as e:
        logger.error(f"Error: {e}")
        import traceback
        traceback.print_exc()

if __name__ == "__main__":
    asyncio.run(main())
