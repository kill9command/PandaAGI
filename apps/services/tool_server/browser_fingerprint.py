"""
Browser fingerprint generation for consistent, human-like crawling.

Generates realistic browser fingerprints that remain consistent across
a session to avoid detection. Uses deterministic randomization seeded
by user_id + session_id for reproducibility.

Part of Panda's human-assisted web crawling system.
"""

import random
from typing import Dict, List


class BrowserFingerprint:
    """Generates consistent browser fingerprint for a crawling session"""

    # Common desktop resolutions (weighted by popularity)
    RESOLUTIONS = [
        {"width": 1920, "height": 1080},  # Most common
        {"width": 1366, "height": 768},
        {"width": 1536, "height": 864},
        {"width": 1440, "height": 900},
        {"width": 2560, "height": 1440},  # 2K
        {"width": 1280, "height": 720},
    ]

    # Common timezones by region
    TIMEZONES = [
        "America/New_York",      # EST
        "America/Chicago",       # CST
        "America/Los_Angeles",   # PST
        "America/Denver",        # MST
        "Europe/London",         # GMT
        "Europe/Paris",          # CET
        "Asia/Tokyo",            # JST
        "Australia/Sydney",      # AEDT
    ]

    # Recent Chrome versions (last 6 releases) - updated Dec 2025
    CHROME_VERSIONS = list(range(128, 134))

    # Common locales
    LOCALES = [
        "en-US",
        "en-GB",
        "en-CA",
        "en-AU",
    ]

    # Platform options
    PLATFORMS = [
        "Linux x86_64",
        "Windows NT 10.0; Win64; x64",
        "Macintosh; Intel Mac OS X 10_15_7",
    ]

    def __init__(self, user_id: str, session_id: str):
        """
        Initialize fingerprint with deterministic randomization.

        Args:
            user_id: User identifier for cross-session consistency
            session_id: Session identifier for session-specific fingerprint

        The combination of user_id + session_id creates a deterministic seed,
        ensuring the same fingerprint is generated every time for this session.
        """
        self.user_id = user_id
        self.session_id = session_id

        # Create deterministic random generator
        seed_string = f"{user_id}:{session_id}"
        self.rng = random.Random(seed_string)

        # Generate fingerprint components (order matters - platform used in user_agent)
        self.platform = self._select_platform()
        self.user_agent = self._generate_user_agent()
        self.viewport = self._select_viewport()
        self.timezone = self._select_timezone()
        self.locale = self._select_locale()

        # Navigation behavior
        self.scroll_delay_range = (800, 2000)  # ms between scrolls
        self.click_delay_range = (300, 1000)   # ms between clicks
        self.typing_speed_range = (50, 150)    # ms per character

    def _select_platform(self) -> str:
        """Select platform string"""
        return self.rng.choice(self.PLATFORMS)

    def _generate_user_agent(self) -> str:
        """
        Generate realistic Chrome user-agent with version variance.

        Uses actual Chrome user-agent format to avoid detection.
        """
        chrome_version = self.rng.choice(self.CHROME_VERSIONS)
        webkit_version = "537.36"

        # Select platform for UA string
        if "Windows" in self.platform:
            platform_str = "Windows NT 10.0; Win64; x64"
        elif "Macintosh" in self.platform:
            platform_str = "Macintosh; Intel Mac OS X 10_15_7"
        else:
            platform_str = "X11; Linux x86_64"

        return (
            f"Mozilla/5.0 ({platform_str}) "
            f"AppleWebKit/{webkit_version} (KHTML, like Gecko) "
            f"Chrome/{chrome_version}.0.0.0 Safari/{webkit_version}"
        )

    def _select_viewport(self) -> Dict[str, int]:
        """Select from common desktop resolutions"""
        return self.rng.choice(self.RESOLUTIONS).copy()

    def _select_timezone(self) -> str:
        """Select from common timezones"""
        return self.rng.choice(self.TIMEZONES)

    def _select_locale(self) -> str:
        """Select from common locales"""
        return self.rng.choice(self.LOCALES)

    def random_delay(self, action: str = "scroll") -> int:
        """
        Generate random delay for human-like behavior.

        Args:
            action: Type of action ("scroll", "click", "type")

        Returns:
            Delay in milliseconds
        """
        if action == "scroll":
            return self.rng.randint(*self.scroll_delay_range)
        elif action == "click":
            return self.rng.randint(*self.click_delay_range)
        elif action == "type":
            return self.rng.randint(*self.typing_speed_range)
        else:
            return self.rng.randint(500, 1500)

    def to_dict(self) -> Dict:
        """Export fingerprint as dictionary for storage"""
        return {
            "user_agent": self.user_agent,
            "viewport": self.viewport,
            "timezone": self.timezone,
            "locale": self.locale,
            "platform": self.platform,
            "seed": f"{self.user_id}:{self.session_id}"
        }

    def apply_to_context_options(self) -> Dict:
        """
        Get Playwright browser context options.

        Returns:
            Dict suitable for browser.new_context(**options)
        """
        return {
            "user_agent": self.user_agent,
            "viewport": self.viewport,
            "locale": self.locale,
            "timezone_id": self.timezone,
            # Additional stealth options
            "ignore_https_errors": True,
            "java_script_enabled": True,
        }

    def __repr__(self) -> str:
        return (
            f"BrowserFingerprint(user={self.user_id}, session={self.session_id}, "
            f"viewport={self.viewport['width']}x{self.viewport['height']}, "
            f"timezone={self.timezone})"
        )


# Convenience function for quick fingerprint generation
def generate_fingerprint(user_id: str = "default", session_id: str = "default") -> BrowserFingerprint:
    """Generate a browser fingerprint with default IDs"""
    return BrowserFingerprint(user_id, session_id)


if __name__ == "__main__":
    # Test deterministic fingerprint generation
    fp1 = BrowserFingerprint("test-user", "session-123")
    fp2 = BrowserFingerprint("test-user", "session-123")

    print("Fingerprint 1:", fp1)
    print("Fingerprint 2:", fp2)

    # Should be identical
    assert fp1.user_agent == fp2.user_agent
    assert fp1.viewport == fp2.viewport
    assert fp1.timezone == fp2.timezone

    print("\n✓ Deterministic fingerprint generation verified")
    print(f"User-Agent: {fp1.user_agent}")
    print(f"Viewport: {fp1.viewport}")
    print(f"Timezone: {fp1.timezone}")
    print(f"Locale: {fp1.locale}")
