"""
Confidence Calibration System

Content-type specific decay rates and confidence floors for temporal
degradation of cached information.

Architecture reference: panda_system_docs/architecture/main-system-patterns/
                       UNIVERSAL_CONFIDENCE_SYSTEM.md
"""

import time
from dataclasses import dataclass
from typing import Dict, Optional
from enum import Enum


class ContentType(Enum):
    """Types of content with different decay characteristics"""
    AVAILABILITY = "availability"     # Stock status - changes frequently
    PRICE = "price"                   # Prices - change somewhat frequently
    PRODUCT_SPEC = "product_spec"     # Specifications - rarely change
    PRODUCT_NAME = "product_name"     # Names - almost never change
    PREFERENCE = "preference"         # User preferences - stable
    SESSION_FACT = "session_fact"     # Facts from current session
    GENERAL_FACT = "general_fact"     # General knowledge


# Decay rates per day (proportion of confidence lost per day)
# Higher = faster decay
DECAY_RATES: Dict[ContentType, float] = {
    ContentType.AVAILABILITY: 0.20,   # Loses 20% per day (stale after ~3 days)
    ContentType.PRICE: 0.10,          # Loses 10% per day (stale after ~7 days)
    ContentType.PRODUCT_SPEC: 0.03,   # Loses 3% per day (stable for weeks)
    ContentType.PRODUCT_NAME: 0.01,   # Loses 1% per day (very stable)
    ContentType.PREFERENCE: 0.005,    # Loses 0.5% per day (stable for months)
    ContentType.SESSION_FACT: 0.50,   # Loses 50% per day (session-specific)
    ContentType.GENERAL_FACT: 0.02,   # Loses 2% per day
}

# Minimum confidence floors (never decay below this)
CONFIDENCE_FLOORS: Dict[ContentType, float] = {
    ContentType.AVAILABILITY: 0.10,   # Very low floor - availability gets stale fast
    ContentType.PRICE: 0.20,          # Low floor
    ContentType.PRODUCT_SPEC: 0.50,   # Medium floor - specs usually still relevant
    ContentType.PRODUCT_NAME: 0.70,   # High floor - names don't change
    ContentType.PREFERENCE: 0.80,     # Very high floor - preferences stable
    ContentType.SESSION_FACT: 0.05,   # Drops to near zero outside session
    ContentType.GENERAL_FACT: 0.40,   # Medium floor
}

# Default decay rate for unknown content types
DEFAULT_DECAY_RATE = 0.05
DEFAULT_FLOOR = 0.30


@dataclass
class CalibrationResult:
    """Result of confidence calibration"""
    original_confidence: float
    calibrated_confidence: float
    content_type: ContentType
    age_hours: float
    decay_applied: float
    hit_floor: bool


class ConfidenceCalibrator:
    """
    Calibrates confidence scores based on content type and age.
    Applies temporal decay to reflect staleness of information.
    """

    def __init__(
        self,
        decay_rates: Optional[Dict[ContentType, float]] = None,
        floors: Optional[Dict[ContentType, float]] = None
    ):
        self.decay_rates = decay_rates or DECAY_RATES
        self.floors = floors or CONFIDENCE_FLOORS

    def calibrate(
        self,
        confidence: float,
        content_type: ContentType,
        timestamp: float,
        current_time: Optional[float] = None
    ) -> CalibrationResult:
        """
        Calibrate confidence based on content type and age.

        Args:
            confidence: Original confidence score (0.0 to 1.0)
            content_type: Type of content
            timestamp: Unix timestamp when data was captured
            current_time: Current time (defaults to now)

        Returns:
            CalibrationResult with calibrated confidence
        """
        current_time = current_time or time.time()

        # Calculate age
        age_seconds = max(0, current_time - timestamp)
        age_hours = age_seconds / 3600
        age_days = age_hours / 24

        # Get decay rate and floor
        decay_rate = self.decay_rates.get(content_type, DEFAULT_DECAY_RATE)
        floor = self.floors.get(content_type, DEFAULT_FLOOR)

        # Apply exponential decay
        # confidence_t = confidence_0 * e^(-decay_rate * days)
        import math
        decay_factor = math.exp(-decay_rate * age_days)
        decayed = confidence * decay_factor

        # Apply floor
        calibrated = max(floor, decayed)
        hit_floor = decayed < floor

        return CalibrationResult(
            original_confidence=confidence,
            calibrated_confidence=calibrated,
            content_type=content_type,
            age_hours=age_hours,
            decay_applied=confidence - calibrated,
            hit_floor=hit_floor
        )

    def calibrate_by_type_string(
        self,
        confidence: float,
        type_string: str,
        timestamp: float,
        current_time: Optional[float] = None
    ) -> CalibrationResult:
        """
        Calibrate using a string type name (convenience method).

        Args:
            confidence: Original confidence
            type_string: Content type as string (e.g., "price", "availability")
            timestamp: Data capture timestamp
            current_time: Current time

        Returns:
            CalibrationResult
        """
        content_type = self._string_to_content_type(type_string)
        return self.calibrate(confidence, content_type, timestamp, current_time)

    def get_staleness_warning(
        self,
        content_type: ContentType,
        timestamp: float,
        current_time: Optional[float] = None
    ) -> Optional[str]:
        """
        Get a staleness warning if data is old enough to warrant one.

        Returns:
            Warning string or None
        """
        current_time = current_time or time.time()
        age_hours = (current_time - timestamp) / 3600
        age_days = age_hours / 24

        # Thresholds for warnings (in days)
        warning_thresholds = {
            ContentType.AVAILABILITY: 0.5,    # 12 hours
            ContentType.PRICE: 2.0,           # 2 days
            ContentType.PRODUCT_SPEC: 30.0,   # 30 days
            ContentType.PRODUCT_NAME: 90.0,   # 90 days
            ContentType.PREFERENCE: 180.0,    # 6 months
            ContentType.SESSION_FACT: 0.25,   # 6 hours
            ContentType.GENERAL_FACT: 14.0,   # 2 weeks
        }

        threshold = warning_thresholds.get(content_type, 7.0)

        if age_days > threshold:
            if age_days < 1:
                age_str = f"{int(age_hours)} hours"
            elif age_days < 7:
                age_str = f"{int(age_days)} days"
            else:
                age_str = f"{int(age_days / 7)} weeks"

            return f"Data is {age_str} old (may be stale for {content_type.value})"

        return None

    def estimate_validity_window(
        self,
        content_type: ContentType,
        min_useful_confidence: float = 0.5
    ) -> float:
        """
        Estimate how long data remains useful (above min confidence).

        Args:
            content_type: Type of content
            min_useful_confidence: Minimum confidence to be considered useful

        Returns:
            Hours until data drops below min_useful_confidence (from 1.0)
        """
        import math

        decay_rate = self.decay_rates.get(content_type, DEFAULT_DECAY_RATE)
        floor = self.floors.get(content_type, DEFAULT_FLOOR)

        # If floor is above min, data is always useful
        if floor >= min_useful_confidence:
            return float('inf')

        # Solve: min_confidence = e^(-decay_rate * days)
        # days = -ln(min_confidence) / decay_rate
        if min_useful_confidence <= 0:
            return float('inf')

        days = -math.log(min_useful_confidence) / decay_rate
        return days * 24  # Return hours

    def _string_to_content_type(self, type_string: str) -> ContentType:
        """Convert string to ContentType enum"""
        type_map = {
            "availability": ContentType.AVAILABILITY,
            "stock": ContentType.AVAILABILITY,
            "in_stock": ContentType.AVAILABILITY,
            "price": ContentType.PRICE,
            "cost": ContentType.PRICE,
            "spec": ContentType.PRODUCT_SPEC,
            "specification": ContentType.PRODUCT_SPEC,
            "specs": ContentType.PRODUCT_SPEC,
            "product_spec": ContentType.PRODUCT_SPEC,
            "name": ContentType.PRODUCT_NAME,
            "title": ContentType.PRODUCT_NAME,
            "product_name": ContentType.PRODUCT_NAME,
            "preference": ContentType.PREFERENCE,
            "pref": ContentType.PREFERENCE,
            "user_preference": ContentType.PREFERENCE,
            "session": ContentType.SESSION_FACT,
            "session_fact": ContentType.SESSION_FACT,
            "fact": ContentType.GENERAL_FACT,
            "general": ContentType.GENERAL_FACT,
            "general_fact": ContentType.GENERAL_FACT,
        }

        return type_map.get(type_string.lower(), ContentType.GENERAL_FACT)


# Convenience functions

def calibrate_confidence(
    confidence: float,
    content_type: str,
    timestamp: float
) -> float:
    """
    Quick calibration of a confidence score.

    Args:
        confidence: Original confidence (0.0-1.0)
        content_type: Type string (e.g., "price", "availability")
        timestamp: When data was captured (Unix timestamp)

    Returns:
        Calibrated confidence
    """
    calibrator = ConfidenceCalibrator()
    result = calibrator.calibrate_by_type_string(confidence, content_type, timestamp)
    return result.calibrated_confidence


def get_decay_rate(content_type: str) -> float:
    """Get decay rate for a content type"""
    calibrator = ConfidenceCalibrator()
    ct = calibrator._string_to_content_type(content_type)
    return DECAY_RATES.get(ct, DEFAULT_DECAY_RATE)


def get_confidence_floor(content_type: str) -> float:
    """Get confidence floor for a content type"""
    calibrator = ConfidenceCalibrator()
    ct = calibrator._string_to_content_type(content_type)
    return CONFIDENCE_FLOORS.get(ct, DEFAULT_FLOOR)
