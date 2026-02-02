"""
orchestrator/desktop_perception.py

Desktop Perception Engine - Screen capture and OCR for Computer Agent

Extracts UI candidates from desktop screenshots using:
- OCR (PaddleOCR for text recognition)
- Shape detection (OpenCV for buttons/icons)
- Window detection (platform-specific window APIs)

Reuses PerceptionEngine patterns from ui_vision_agent.py
"""
from __future__ import annotations
import asyncio
import logging
import tempfile
import platform
from typing import List, Optional, Tuple, Dict, Any
from dataclasses import dataclass
from enum import Enum

logger = logging.getLogger(__name__)

# Lazy-load optional dependencies
_cv2 = None
_np = None
_paddle_ocr = None


def _get_cv2():
    """Lazy-load OpenCV."""
    global _cv2
    if _cv2 is None:
        try:
            import cv2
            _cv2 = cv2
        except ImportError:
            logger.warning("OpenCV not available. Install: pip install opencv-python")
    return _cv2


def _get_numpy():
    """Lazy-load numpy."""
    global _np
    if _np is None:
        try:
            import numpy as np
            _np = np
        except ImportError:
            logger.warning("Numpy not available. Install: pip install numpy")
    return _np


def _get_paddle_ocr():
    """Lazy-load PaddleOCR."""
    global _paddle_ocr
    if _paddle_ocr is None:
        try:
            from paddleocr import PaddleOCR
            _paddle_ocr = PaddleOCR(
                use_angle_cls=True,
                lang='en',
                use_gpu=False,
                show_log=False
            )
        except ImportError:
            logger.warning("PaddleOCR not available. Install: pip install paddleocr")
    return _paddle_ocr


class CandidateSource(Enum):
    """Source of UI candidate."""
    SCREEN_OCR = "screen_ocr"  # OCR from screenshot
    SCREEN_SHAPE = "screen_shape"  # Shape detection from screenshot
    WINDOW_API = "window_api"  # Platform-specific window enumeration


@dataclass
class BoundingBox:
    """Screen coordinates for UI element."""
    x: float
    y: float
    width: float
    height: float


@dataclass
class UICandidate:
    """
    Unified representation of a clickable UI element on desktop.

    Attributes:
        source: How this candidate was detected
        text: Detected text or description
        bbox: Screen coordinates
        confidence: Detection confidence (0.0-1.0)
        metadata: Additional info (window_title, process_name, etc.)
    """
    source: CandidateSource
    text: str
    bbox: BoundingBox
    confidence: float
    metadata: Dict[str, Any]


@dataclass
class WindowInfo:
    """Platform-specific window information."""
    title: str
    process_name: str
    bbox: BoundingBox
    is_visible: bool
    is_focused: bool


class DesktopPerceptionEngine:
    """
    Desktop perception engine for Computer Agent.

    Extracts UI candidates from desktop screenshots using OCR and shape detection.
    Optionally enumerates windows using platform-specific APIs.
    """

    def __init__(
        self,
        enable_ocr: bool = True,
        enable_shapes: bool = True,
        enable_windows: bool = False,
        ocr_confidence_threshold: float = 0.5
    ):
        """
        Initialize desktop perception engine.

        Args:
            enable_ocr: Enable PaddleOCR text detection
            enable_shapes: Enable OpenCV shape detection
            enable_windows: Enable platform-specific window enumeration
            ocr_confidence_threshold: Minimum OCR confidence
        """
        self.enable_ocr = enable_ocr
        self.enable_shapes = enable_shapes
        self.enable_windows = enable_windows
        self.ocr_confidence_threshold = ocr_confidence_threshold

        # Lazy-loaded dependencies
        self._ocr_engine = None
        self._cv2 = None
        self._np = None

    # ========================================================================
    # Main API
    # ========================================================================

    async def extract_candidates(
        self,
        screenshot_path: str,
        screen_width: int,
        screen_height: int
    ) -> List[UICandidate]:
        """
        Extract all UI candidates from desktop screenshot.

        Args:
            screenshot_path: Path to screenshot image
            screen_width: Screen width (for coordinate validation)
            screen_height: Screen height (for coordinate validation)

        Returns:
            List of UI candidates sorted by confidence
        """
        candidates = []

        # 1. OCR-based candidates
        if self.enable_ocr:
            ocr_candidates = await self._extract_ocr_candidates(screenshot_path)
            candidates.extend(ocr_candidates)
            logger.debug(f"[DesktopPerception] OCR found {len(ocr_candidates)} candidates")

        # 2. Shape-based candidates
        if self.enable_shapes:
            shape_candidates = await self._extract_shape_candidates(screenshot_path)
            candidates.extend(shape_candidates)
            logger.debug(f"[DesktopPerception] Shapes found {len(shape_candidates)} candidates")

        # 3. Window enumeration (optional)
        if self.enable_windows:
            window_candidates = await self._extract_window_candidates()
            candidates.extend(window_candidates)
            logger.debug(f"[DesktopPerception] Windows found {len(window_candidates)} candidates")

        # Filter candidates within screen bounds
        valid_candidates = [
            c for c in candidates
            if self._is_valid_bbox(c.bbox, screen_width, screen_height)
        ]

        # Sort by confidence
        valid_candidates.sort(key=lambda c: c.confidence, reverse=True)

        logger.info(
            f"[DesktopPerception] Extracted {len(valid_candidates)} candidates "
            f"({len(candidates) - len(valid_candidates)} filtered)"
        )

        return valid_candidates

    # ========================================================================
    # OCR Detection
    # ========================================================================

    async def _extract_ocr_candidates(self, screenshot_path: str) -> List[UICandidate]:
        """Extract text candidates using PaddleOCR."""
        try:
            ocr = _get_paddle_ocr()
            if ocr is None:
                return []

            # Run OCR (blocking, so use thread)
            result = await asyncio.to_thread(ocr.ocr, screenshot_path, cls=True)

            candidates = []
            if result and result[0]:
                for line in result[0]:
                    bbox_points = line[0]  # [[x1,y1], [x2,y2], [x3,y3], [x4,y4]]
                    text_info = line[1]  # (text, confidence)
                    text = text_info[0]
                    confidence = float(text_info[1])

                    # Skip low-confidence detections
                    if confidence < self.ocr_confidence_threshold:
                        continue

                    # Convert polygon to bounding box
                    xs = [p[0] for p in bbox_points]
                    ys = [p[1] for p in bbox_points]
                    bbox = BoundingBox(
                        x=min(xs),
                        y=min(ys),
                        width=max(xs) - min(xs),
                        height=max(ys) - min(ys)
                    )

                    candidates.append(UICandidate(
                        source=CandidateSource.SCREEN_OCR,
                        text=text,
                        bbox=bbox,
                        confidence=confidence,
                        metadata={"ocr_polygon": bbox_points}
                    ))

            return candidates

        except Exception as e:
            logger.error(f"[DesktopPerception] OCR failed: {e}")
            return []

    # ========================================================================
    # Shape Detection
    # ========================================================================

    async def _extract_shape_candidates(self, screenshot_path: str) -> List[UICandidate]:
        """Extract button-like shapes using OpenCV contour detection."""
        try:
            cv2 = _get_cv2()
            np = _get_numpy()
            if cv2 is None or np is None:
                return []

            # Load image
            img = await asyncio.to_thread(cv2.imread, screenshot_path)
            if img is None:
                logger.error(f"[DesktopPerception] Failed to load screenshot: {screenshot_path}")
                return []

            # Convert to grayscale
            gray = await asyncio.to_thread(cv2.cvtColor, img, cv2.COLOR_BGR2GRAY)

            # Edge detection
            edges = await asyncio.to_thread(cv2.Canny, gray, 50, 150)

            # Find contours
            contours, _ = await asyncio.to_thread(
                cv2.findContours, edges, cv2.RETR_EXTERNAL, cv2.CHAIN_APPROX_SIMPLE
            )

            candidates = []
            for contour in contours:
                # Get bounding rect
                x, y, w, h = cv2.boundingRect(contour)

                # Filter by size (buttons typically 20x20 to 300x100 pixels)
                if w < 20 or h < 20 or w > 500 or h > 200:
                    continue

                # Filter by aspect ratio (buttons are usually wider than tall or square)
                aspect_ratio = w / h
                if aspect_ratio < 0.3 or aspect_ratio > 10.0:
                    continue

                # Calculate area and perimeter for confidence
                area = cv2.contourArea(contour)
                perimeter = cv2.arcLength(contour, True)

                # Confidence based on regularity
                # More regular shapes (rectangles) have higher confidence
                if perimeter > 0:
                    regularity = 4 * 3.14159 * area / (perimeter * perimeter)
                    confidence = min(regularity, 0.9)  # Cap at 0.9
                else:
                    confidence = 0.5

                candidates.append(UICandidate(
                    source=CandidateSource.SCREEN_SHAPE,
                    text=f"shape_{x}_{y}",  # Generic identifier
                    bbox=BoundingBox(x=x, y=y, width=w, height=h),
                    confidence=confidence,
                    metadata={
                        "area": int(area),
                        "perimeter": int(perimeter),
                        "aspect_ratio": round(aspect_ratio, 2)
                    }
                ))

            return candidates

        except Exception as e:
            logger.error(f"[DesktopPerception] Shape detection failed: {e}")
            return []

    # ========================================================================
    # Window Detection (Platform-Specific)
    # ========================================================================

    async def _extract_window_candidates(self) -> List[UICandidate]:
        """
        Extract window information using platform-specific APIs.

        Platform support:
        - Windows: pywinauto
        - macOS: atomac/pyobjc
        - Linux: python-dogtail

        Returns empty list if platform APIs not available.
        """
        system = platform.system()

        if system == "Windows":
            return await self._extract_windows_windows()
        elif system == "Darwin":  # macOS
            return await self._extract_windows_macos()
        elif system == "Linux":
            return await self._extract_windows_linux()
        else:
            logger.warning(f"[DesktopPerception] Window detection not supported on {system}")
            return []

    async def _extract_windows_windows(self) -> List[UICandidate]:
        """Extract windows on Windows using pywinauto."""
        try:
            from pywinauto import Desktop

            desktop = Desktop(backend="uia")
            windows = await asyncio.to_thread(desktop.windows)

            candidates = []
            for window in windows:
                try:
                    # Get window properties
                    title = window.window_text()
                    rect = window.rectangle()
                    is_visible = window.is_visible()

                    if not is_visible or not title:
                        continue

                    bbox = BoundingBox(
                        x=rect.left,
                        y=rect.top,
                        width=rect.width(),
                        height=rect.height()
                    )

                    candidates.append(UICandidate(
                        source=CandidateSource.WINDOW_API,
                        text=title,
                        bbox=bbox,
                        confidence=0.95,  # High confidence from API
                        metadata={
                            "platform": "windows",
                            "class_name": window.class_name()
                        }
                    ))
                except Exception as e:
                    logger.debug(f"[DesktopPerception] Skipped window: {e}")
                    continue

            return candidates

        except ImportError:
            logger.warning("[DesktopPerception] pywinauto not installed (Windows only)")
            return []
        except Exception as e:
            logger.error(f"[DesktopPerception] Windows window detection failed: {e}")
            return []

    async def _extract_windows_macos(self) -> List[UICandidate]:
        """Extract windows on macOS using atomac."""
        try:
            import atomac

            # Get all application windows
            apps = await asyncio.to_thread(atomac.getAppRefByPid, -1)  # All apps

            # TODO: Implement macOS window enumeration
            # This requires iterating through accessibility hierarchy
            # which is complex and platform-specific

            logger.warning("[DesktopPerception] macOS window detection not yet implemented")
            return []

        except ImportError:
            logger.warning("[DesktopPerception] atomac not installed (macOS only)")
            return []
        except Exception as e:
            logger.error(f"[DesktopPerception] macOS window detection failed: {e}")
            return []

    async def _extract_windows_linux(self) -> List[UICandidate]:
        """Extract windows on Linux using python-dogtail."""
        try:
            from dogtail.tree import root

            # Get all windows
            # TODO: Implement Linux window enumeration
            # This requires accessibility API interaction

            logger.warning("[DesktopPerception] Linux window detection not yet implemented")
            return []

        except ImportError:
            logger.warning("[DesktopPerception] python-dogtail not installed (Linux only)")
            return []
        except Exception as e:
            logger.error(f"[DesktopPerception] Linux window detection failed: {e}")
            return []

    # ========================================================================
    # Utilities
    # ========================================================================

    def _is_valid_bbox(
        self,
        bbox: BoundingBox,
        screen_width: int,
        screen_height: int
    ) -> bool:
        """Check if bounding box is within screen bounds."""
        return (
            bbox.x >= 0 and
            bbox.y >= 0 and
            bbox.x + bbox.width <= screen_width and
            bbox.y + bbox.height <= screen_height and
            bbox.width > 0 and
            bbox.height > 0
        )
