"""
Stealth JavaScript injection for Playwright to bypass bot detection.

Now uses playwright-stealth library which handles 100+ detection vectors
including navigator.webdriver, chrome object, plugins, permissions,
WebGL, canvas fingerprinting, and many more.

Falls back to basic homemade scripts if playwright-stealth is not available.

Usage:
    from apps.services.orchestrator.stealth_injector import inject_stealth

    context = await browser.new_context()
    await inject_stealth(context)
"""

import logging

logger = logging.getLogger(__name__)

# Try to import playwright-stealth (professional solution)
try:
    from playwright_stealth import Stealth
    HAVE_PLAYWRIGHT_STEALTH = True
except ImportError:
    HAVE_PLAYWRIGHT_STEALTH = False
    logger.warning("[StealthInjector] playwright-stealth not found, using basic fallback scripts")


def get_stealth_scripts() -> list[str]:
    """
    Get all stealth JavaScript patches to inject before page load.

    Returns:
        List of JavaScript code strings to inject via add_init_script()
    """
    return [
        _get_webdriver_override(),
        _get_chrome_object(),
        _get_plugins_override(),
        _get_permissions_override(),
        _get_webgl_vendor(),
        _get_navigator_languages(),
        _get_iframe_contentWindow(),
    ]


def _get_webdriver_override() -> str:
    """Override navigator.webdriver to hide automation"""
    return """
// Override navigator.webdriver (primary bot detection method)
Object.defineProperty(navigator, 'webdriver', {
  get: () => false,
  configurable: true
});
"""


def _get_chrome_object() -> str:
    """Add window.chrome object (missing in Chromium automation)"""
    return """
// Add window.chrome object (real Chrome browsers have this)
if (!window.chrome) {
  window.chrome = {
    runtime: {},
    loadTimes: function() {},
    csi: function() {},
    app: {}
  };
}
"""


def _get_plugins_override() -> str:
    """Populate navigator.plugins (real browsers have plugins)"""
    return """
// Override navigator.plugins (automation has 0 plugins)
Object.defineProperty(navigator, 'plugins', {
  get: () => {
    // Mimic common plugin set
    return [
      {
        0: {type: "application/x-google-chrome-pdf", suffixes: "pdf", description: "Portable Document Format"},
        description: "Portable Document Format",
        filename: "internal-pdf-viewer",
        length: 1,
        name: "Chrome PDF Plugin"
      },
      {
        0: {type: "application/pdf", suffixes: "pdf", description: "Portable Document Format"},
        description: "Portable Document Format",
        filename: "mhjfbmdgcfjbbpaeojofohoefgiehjai",
        length: 1,
        name: "Chrome PDF Viewer"
      },
      {
        0: {type: "application/x-nacl", suffixes: "", description: "Native Client Executable"},
        description: "",
        filename: "internal-nacl-plugin",
        length: 2,
        name: "Native Client"
      }
    ];
  },
  configurable: true
});
"""


def _get_permissions_override() -> str:
    """Fix permissions API to avoid fingerprinting"""
    return """
// Override permissions.query to avoid detection
const originalQuery = window.navigator.permissions.query;
window.navigator.permissions.query = (parameters) => (
  parameters.name === 'notifications' ?
    Promise.resolve({ state: Notification.permission }) :
    originalQuery(parameters)
);
"""


def _get_webgl_vendor() -> str:
    """Spoof WebGL vendor/renderer to avoid fingerprinting"""
    return """
// Override WebGL vendor/renderer (automation has suspicious values)
const getParameter = WebGLRenderingContext.prototype.getParameter;
WebGLRenderingContext.prototype.getParameter = function(parameter) {
  // UNMASKED_VENDOR_WEBGL
  if (parameter === 37445) {
    return 'Intel Inc.';
  }
  // UNMASKED_RENDERER_WEBGL
  if (parameter === 37446) {
    return 'Intel Iris OpenGL Engine';
  }
  return getParameter.apply(this, [parameter]);
};
"""


def _get_navigator_languages() -> str:
    """Ensure navigator.languages is consistent"""
    return """
// Override navigator.languages for consistency
Object.defineProperty(navigator, 'languages', {
  get: () => ['en-US', 'en'],
  configurable: true
});
"""


def _get_iframe_contentWindow() -> str:
    """Fix iframe contentWindow property (detection vector)"""
    return """
// Fix iframe contentWindow descriptor
try {
  const originalContentWindow = Object.getOwnPropertyDescriptor(HTMLIFrameElement.prototype, 'contentWindow');
  if (originalContentWindow) {
    Object.defineProperty(HTMLIFrameElement.prototype, 'contentWindow', {
      get: function() {
        return originalContentWindow.get.call(this);
      },
      configurable: true
    });
  }
} catch (e) {
  // Ignore errors in strict contexts
}
"""


async def inject_stealth(context, log: bool = True):
    """
    Inject stealth scripts into a Playwright BrowserContext.

    Uses playwright-stealth if available (handles 100+ detection vectors),
    otherwise falls back to basic homemade scripts.

    Args:
        context: Playwright BrowserContext instance
        log: Whether to log injection (default: True)

    Usage:
        context = await browser.new_context()
        await inject_stealth(context)
        page = await context.new_page()
    """
    if HAVE_PLAYWRIGHT_STEALTH:
        # Use professional playwright-stealth library (handles 100+ detection vectors)
        stealth = Stealth()
        await stealth.apply_stealth_async(context)
        if log:
            logger.info("[StealthInjector] Injected playwright-stealth (100+ detection vectors)")
    else:
        # Fallback to basic homemade scripts
        scripts = get_stealth_scripts()
        for script in scripts:
            await context.add_init_script(script)
        if log:
            logger.info(f"[StealthInjector] Injected {len(scripts)} basic stealth scripts (fallback mode)")


def inject_stealth_sync(page):
    """
    Synchronous stealth injection for sync_playwright.

    Note: This must be called BEFORE navigation. For best results,
    use inject_stealth() on the context instead.

    Args:
        page: Playwright Page instance
    """
    scripts = get_stealth_scripts()
    combined = "\n\n".join(scripts)

    page.add_init_script(combined)
    logger.info(f"[StealthInjector] Injected stealth scripts into page (sync mode)")
