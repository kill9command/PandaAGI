"""
orchestrator/ui_vision_agent.py

Vision-Guided UI Agent - "Diablo-style" click automation

Provides reliable UI interaction by combining DOM automation (fast, precise)
with computer vision fallback (works when DOM fails). Uses a four-module architecture:

Module 1 - Perception: Extract clickable candidates from DOM + OCR + shape detection
Module 2 - Targeting Policy: Rank candidates and choose best match for goal
Module 3 - Actuators: Execute DOM clicks or vision-based mouse actions
Module 4 - Verification: Confirm action succeeded via DOM changes or screenshot diff

Integration: Used by browser_agent for pagination, "load more", consent banners,
and by internet_research_mcp for sites requiring vision-guided interaction.

Stealth: Operates within existing BrowserFingerprint and CrawlerSessionManager context.
"""
from __future__ import annotations
import asyncio
import json
import logging
import os
import re
import time
from dataclasses import dataclass, asdict
from datetime import datetime
from typing import Any, Dict, List, Optional, Tuple
from enum import Enum

from libs.gateway.llm.recipe_loader import load_recipe, RecipeNotFoundError

logger = logging.getLogger(__name__)

# Recipe cache for UI prompts
_recipe_cache: Dict[str, str] = {}


def _load_ui_prompt(prompt_name: str) -> str:
    """
    Load a UI/browser prompt via the recipe system.

    Uses caching to avoid repeated recipe loads.

    Args:
        prompt_name: Recipe name without path prefix (e.g., "element_selector")

    Returns:
        Prompt content as string, or empty string if not found
    """
    if prompt_name in _recipe_cache:
        return _recipe_cache[prompt_name]

    try:
        recipe = load_recipe(f"browser/{prompt_name}")
        prompt = recipe.get_prompt()
        _recipe_cache[prompt_name] = prompt
        logger.debug(f"[UIVisionAgent] Loaded prompt via recipe: browser/{prompt_name}")
        return prompt
    except RecipeNotFoundError:
        logger.warning(f"[UIVisionAgent] Recipe not found: browser/{prompt_name}")
        return ""
    except Exception as e:
        logger.warning(f"[UIVisionAgent] Failed to load recipe browser/{prompt_name}: {e}")
        return ""


# ============================================================================
# Data Models
# ============================================================================

class CandidateSource(Enum):
    """Source of a UI candidate"""
    DOM = "dom"              # Extracted from Playwright DOM
    VISION_OCR = "vision_ocr"  # Found via OCR text recognition
    VISION_SHAPE = "vision_shape"  # Detected via shape/contour analysis


@dataclass
class BoundingBox:
    """Bounding box coordinates (x, y, width, height)"""
    x: float
    y: float
    width: float
    height: float

    @property
    def center(self) -> Tuple[float, float]:
        """Get center point of bounding box"""
        return (self.x + self.width / 2, self.y + self.height / 2)

    def to_dict(self) -> Dict[str, float]:
        return {"x": self.x, "y": self.y, "width": self.width, "height": self.height}


@dataclass
class UICandidate:
    """
    Represents a potential UI target (button, link, input, etc.)

    Unified representation for both DOM-extracted and vision-detected elements.
    """
    source: CandidateSource
    text: str  # Label, aria-label, OCR text, or ""
    bbox: BoundingBox  # Position and size
    confidence: float  # 0.0-1.0, higher = more confident match
    metadata: Dict[str, Any]  # Source-specific data (role, selector, etc.)

    def to_dict(self) -> Dict[str, Any]:
        return {
            "source": self.source.value,
            "text": self.text,
            "bbox": self.bbox.to_dict(),
            "confidence": self.confidence,
            "metadata": self.metadata
        }


@dataclass
class ActionResult:
    """Result of attempting a UI action"""
    success: bool
    candidate: UICandidate
    verification_method: str  # "dom_mutation", "url_change", "screenshot_diff", "timeout"
    metadata: Dict[str, Any]  # Additional details (error, timing, etc.)

    def to_dict(self) -> Dict[str, Any]:
        return {
            "success": self.success,
            "candidate": self.candidate.to_dict(),
            "verification_method": self.verification_method,
            "metadata": self.metadata
        }


# ============================================================================
# Module 1 - Perception
# ============================================================================

class PerceptionEngine:
    """
    Extracts UI candidates from DOM and vision sources.

    Strategy:
    1. Try DOM first (fast, precise): ARIA roles, clickable elements, labels
    2. Fall back to OCR (slower): Text recognition on screenshot
    3. Fall back to shape detection (slowest): Find button-like shapes
    """

    def __init__(self, enable_ocr: bool = True, enable_shapes: bool = True):
        self.enable_ocr = enable_ocr
        self.enable_shapes = enable_shapes
        self._ocr_engine = None
        self._shape_detector = None

    async def extract_candidates(
        self,
        page,  # Playwright Page object
        screenshot_path: Optional[str] = None
    ) -> List[UICandidate]:
        """
        Extract all UI candidates from page.

        Args:
            page: Playwright Page object
            screenshot_path: Optional path to save screenshot for vision processing

        Returns:
            List of UICandidate objects sorted by confidence (highest first)
        """
        candidates = []

        # Module 1.1: DOM Extraction
        logger.info("[Perception] Extracting DOM candidates...")
        dom_candidates = await self._extract_dom_candidates(page)
        candidates.extend(dom_candidates)
        logger.info(f"[Perception] Found {len(dom_candidates)} DOM candidates")

        # Module 1.2: OCR Extraction (if enabled and DOM is insufficient)
        if self.enable_ocr and len(dom_candidates) < 3:
            logger.info("[Perception] DOM candidates low, trying OCR...")
            if not screenshot_path:
                screenshot_path = f"/tmp/ui_vision_{int(time.time())}.png"

            await page.screenshot(path=screenshot_path)
            ocr_candidates = await self._extract_ocr_candidates(screenshot_path)
            candidates.extend(ocr_candidates)
            logger.info(f"[Perception] Found {len(ocr_candidates)} OCR candidates")

        # Module 1.3: Shape Detection (if enabled and still insufficient)
        if self.enable_shapes and len(candidates) < 5:
            logger.info("[Perception] Candidates still low, trying shape detection...")
            if screenshot_path:
                shape_candidates = await self._extract_shape_candidates(screenshot_path)
                candidates.extend(shape_candidates)
                logger.info(f"[Perception] Found {len(shape_candidates)} shape candidates")

        # Sort by confidence (highest first)
        candidates.sort(key=lambda c: c.confidence, reverse=True)

        return candidates

    async def _extract_dom_candidates(self, page) -> List[UICandidate]:
        """
        Extract clickable elements from DOM via Playwright.

        OPTIMIZED: Uses a single JavaScript evaluate() call to collect all
        candidate data at once, instead of making ~9 async calls per element.
        This reduces extraction from 3+ minutes to ~1 second on large pages.

        Looks for:
        - ARIA roles: button, link, menuitem, tab, etc.
        - Elements with pointer cursor
        - Form inputs with labels
        """
        candidates = []

        # JavaScript that extracts all candidates in ONE call
        # This replaces thousands of sequential async calls with one JS execution
        js_extract_candidates = """
        () => {
            const candidates = [];
            const seenBboxes = new Set();  // Dedupe by position

            // Helper to get best label
            function getLabel(elem) {
                const sources = [
                    ['inner_text', elem.innerText?.trim()],
                    ['aria_label', elem.getAttribute('aria-label')?.trim()],
                    ['title', elem.getAttribute('title')?.trim()],
                    ['value', elem.getAttribute('value')?.trim()],
                    ['placeholder', elem.getAttribute('placeholder')?.trim()],
                    ['alt', elem.getAttribute('alt')?.trim()],
                ];
                for (const [source, value] of sources) {
                    if (value) return { text: value.substring(0, 100), source };
                }
                return { text: '', source: 'unknown' };
            }

            // Helper to check visibility
            function isVisible(elem) {
                const style = window.getComputedStyle(elem);
                if (style.display === 'none' || style.visibility === 'hidden' || style.opacity === '0') {
                    return false;
                }
                const rect = elem.getBoundingClientRect();
                return rect.width > 0 && rect.height > 0;
            }

            // Helper to add candidate
            function addCandidate(elem, role, confidence) {
                if (!isVisible(elem)) return;

                const rect = elem.getBoundingClientRect();
                if (rect.width < 5 || rect.height < 5) return;

                // Dedupe by position (rounded to avoid float precision issues)
                const bboxKey = `${Math.round(rect.x)},${Math.round(rect.y)},${Math.round(rect.width)},${Math.round(rect.height)}`;
                if (seenBboxes.has(bboxKey)) return;
                seenBboxes.add(bboxKey);

                const label = getLabel(elem);
                const enabled = !elem.disabled && !elem.hasAttribute('aria-disabled');

                candidates.push({
                    text: label.text,
                    label_source: label.source,
                    bbox: { x: rect.x, y: rect.y, width: rect.width, height: rect.height },
                    role: role,
                    enabled: enabled,
                    confidence: confidence
                });
            }

            // Query all interactive ARIA roles
            const roles = ['button', 'link', 'menuitem', 'menuitemcheckbox', 'menuitemradio',
                          'tab', 'checkbox', 'radio', 'switch', 'option'];

            for (const role of roles) {
                try {
                    // Use querySelectorAll with role attribute for faster lookup
                    document.querySelectorAll(`[role="${role}"]`).forEach(elem => {
                        addCandidate(elem, role, 0.9);
                    });
                } catch (e) {}
            }

            // Also get native interactive elements
            document.querySelectorAll('button, a[href], input[type="submit"], input[type="button"]').forEach(elem => {
                const tag = elem.tagName.toLowerCase();
                const role = tag === 'a' ? 'link' : 'button';
                addCandidate(elem, role, 0.9);
            });

            // Get text input elements (search boxes, text fields, etc.)
            document.querySelectorAll('input[type="text"], input[type="search"], input[type="email"], input[type="url"], input:not([type]), textarea').forEach(elem => {
                addCandidate(elem, 'textbox', 0.9);
            });

            // Look for pointer cursor elements (clickable divs)
            document.querySelectorAll('[style*="cursor: pointer"], [style*="cursor:pointer"]').forEach(elem => {
                addCandidate(elem, 'cursor_pointer', 0.7);
            });

            // Also check computed cursor style for common clickable patterns
            document.querySelectorAll('[onclick], [data-click], [data-action]').forEach(elem => {
                addCandidate(elem, 'onclick', 0.8);
            });

            return candidates;
        }
        """

        try:
            # Execute JS to extract all candidates at once (1 call vs 2400+ calls)
            raw_candidates = await page.evaluate(js_extract_candidates)

            for data in raw_candidates:
                try:
                    candidate = UICandidate(
                        source=CandidateSource.DOM,
                        text=data.get("text", ""),
                        bbox=BoundingBox(
                            x=data["bbox"]["x"],
                            y=data["bbox"]["y"],
                            width=data["bbox"]["width"],
                            height=data["bbox"]["height"]
                        ),
                        confidence=data.get("confidence", 0.9),
                        metadata={
                            "role": data.get("role", "unknown"),
                            "selector": None,
                            "enabled": data.get("enabled", True),
                            "label_source": data.get("label_source", "unknown")
                        }
                    )
                    candidates.append(candidate)
                except Exception as e:
                    logger.debug(f"[Perception] Failed to parse candidate: {e}")
                    continue

            logger.debug(f"[Perception] JS extraction returned {len(candidates)} candidates")

        except Exception as e:
            logger.warning(f"[Perception] JS extraction failed, falling back to slow method: {e}")
            # Fallback to original slow method only if JS fails
            candidates = await self._extract_dom_candidates_slow(page)

        return candidates

    async def _extract_dom_candidates_slow(self, page) -> List[UICandidate]:
        """
        Legacy slow DOM extraction method.

        Only used as fallback if JS evaluate fails.
        Makes ~9 async calls per element which is very slow on large pages.
        """
        candidates = []

        async def _get_element_label(elem) -> tuple[str, str]:
            label_sources = [
                ("inner_text", await elem.inner_text()),
                ("aria_label", await elem.get_attribute("aria-label")),
                ("title", await elem.get_attribute("title")),
                ("value", await elem.get_attribute("value")),
                ("placeholder", await elem.get_attribute("placeholder")),
                ("alt", await elem.get_attribute("alt")),
            ]
            for source_name, raw_value in label_sources:
                if raw_value:
                    text = raw_value.strip()
                    if text:
                        return text, source_name
            return "", ""

        roles_to_check = [
            "button", "link", "menuitem", "menuitemcheckbox", "menuitemradio",
            "tab", "checkbox", "radio", "switch", "option"
        ]

        for role in roles_to_check:
            try:
                elements = await page.get_by_role(role).all()
                for elem in elements:
                    try:
                        is_visible = await elem.is_visible()
                        if not is_visible:
                            continue
                        box = await elem.bounding_box()
                        if not box:
                            continue
                        text, label_source = await _get_element_label(elem)
                        candidate = UICandidate(
                            source=CandidateSource.DOM,
                            text=text,
                            bbox=BoundingBox(
                                x=box["x"], y=box["y"],
                                width=box["width"], height=box["height"]
                            ),
                            confidence=0.9,
                            metadata={
                                "role": role,
                                "selector": None,
                                "enabled": await elem.is_enabled(),
                                "label_source": label_source or "unknown"
                            }
                        )
                        candidates.append(candidate)
                    except Exception:
                        continue
            except Exception:
                continue

        return candidates

    async def _extract_ocr_candidates(self, screenshot_path: str) -> List[UICandidate]:
        """
        Extract text candidates via OCR.

        Uses PaddleOCR (or fallback to Tesseract) to find text on screenshot.
        Each detected text box becomes a potential click target.
        """
        candidates = []

        # Lazy-load OCR engine
        if not self._ocr_engine:
            try:
                from paddleocr import PaddleOCR
                self._ocr_engine = PaddleOCR(
                    use_angle_cls=True,
                    lang='en',
                    show_log=False
                )
                logger.info("[Perception] Initialized PaddleOCR")
            except ImportError:
                logger.warning("[Perception] PaddleOCR not available, OCR disabled")
                return candidates

        # Run OCR
        try:
            result = self._ocr_engine.ocr(screenshot_path, cls=True)

            if not result or not result[0]:
                return candidates

            # Parse OCR results
            for line in result[0]:
                try:
                    bbox_points = line[0]  # [[x1,y1], [x2,y2], [x3,y3], [x4,y4]]
                    text_data = line[1]    # (text, confidence)
                    text = text_data[0]
                    confidence = text_data[1]

                    # Calculate bounding box from points
                    x_coords = [p[0] for p in bbox_points]
                    y_coords = [p[1] for p in bbox_points]
                    x = min(x_coords)
                    y = min(y_coords)
                    width = max(x_coords) - x
                    height = max(y_coords) - y

                    candidate = UICandidate(
                        source=CandidateSource.VISION_OCR,
                        text=text.strip(),
                        bbox=BoundingBox(x=x, y=y, width=width, height=height),
                        confidence=float(confidence),
                        metadata={"ocr_engine": "paddleocr"}
                    )
                    candidates.append(candidate)

                except Exception as e:
                    logger.debug(f"[Perception] Failed to parse OCR line: {e}")
                    continue

        except Exception as e:
            logger.error(f"[Perception] OCR failed: {e}")

        return candidates

    async def _extract_shape_candidates(self, screenshot_path: str) -> List[UICandidate]:
        """
        Extract button-like shapes via computer vision.

        Uses OpenCV to find rectangular/rounded contours that look like buttons.
        Useful when page has icon-only buttons or custom UI elements.
        """
        candidates = []

        # Lazy-load OpenCV
        try:
            import cv2
            import numpy as np
        except ImportError:
            logger.warning("[Perception] OpenCV not available, shape detection disabled")
            return candidates

        try:
            # Read image
            img = cv2.imread(screenshot_path)
            if img is None:
                return candidates

            # Convert to grayscale
            gray = cv2.cvtColor(img, cv2.COLOR_BGR2GRAY)

            # Edge detection
            edges = cv2.Canny(gray, 50, 150, apertureSize=3)

            # Find contours
            contours, _ = cv2.findContours(edges, cv2.RETR_EXTERNAL, cv2.CHAIN_APPROX_SIMPLE)

            for contour in contours:
                # Filter by area (buttons are typically 20x20 to 300x300 pixels)
                x, y, w, h = cv2.boundingRect(contour)
                area = w * h

                if area < 400 or area > 90000:  # 20x20 to 300x300
                    continue

                # Filter by aspect ratio (buttons are roughly square or wide rectangles)
                aspect_ratio = w / h if h > 0 else 0
                if aspect_ratio < 0.3 or aspect_ratio > 5:
                    continue

                # Calculate confidence based on shape regularity
                perimeter = cv2.arcLength(contour, True)
                circularity = 4 * np.pi * area / (perimeter * perimeter) if perimeter > 0 else 0
                confidence = min(circularity, 0.6)  # Cap at 0.6 (shapes are less reliable)

                candidate = UICandidate(
                    source=CandidateSource.VISION_SHAPE,
                    text="",  # No text from shape detection
                    bbox=BoundingBox(x=float(x), y=float(y), width=float(w), height=float(h)),
                    confidence=confidence,
                    metadata={
                        "area": area,
                        "aspect_ratio": aspect_ratio,
                        "circularity": circularity
                    }
                )
                candidates.append(candidate)

        except Exception as e:
            logger.error(f"[Perception] Shape detection failed: {e}")

        return candidates


# ============================================================================
# Module 2 - Targeting Policy
# ============================================================================

class TargetingPolicy:
    """
    Ranks UI candidates and selects best match for a goal.

    Scoring factors:
    - Text match (exact > fuzzy > synonym > none)
    - Source reliability (DOM > OCR > Shape)
    - Element size (too small = likely decorative)
    - Viewport position (off-screen elements penalized)
    - Proximity to recent interactions (buttons near last input)
    """

    def __init__(self, synonyms: Optional[Dict[str, List[str]]] = None):
        self.synonyms = synonyms or {
            "search": ["go", "find", "lookup", "submit"],
            "next": ["continue", "forward", "more", "load more"],
            "close": ["dismiss", "cancel", "x", "exit"],
            "accept": ["ok", "agree", "confirm", "yes", "allow"],
            "accept all": ["i agree", "agree all", "accept cookies", "allow all", "ok, got it"],
            "reject all": ["decline all", "reject cookies", "deny all", "no thanks"],
            "login": ["sign in", "log in", "enter"],
        }

    def rank_candidates(
        self,
        candidates: List[UICandidate],
        goal: str,
        viewport_width: float = 1920,
        viewport_height: float = 1080,
        last_interaction_pos: Optional[Tuple[float, float]] = None
    ) -> List[UICandidate]:
        """
        Rank candidates by relevance to goal.

        Args:
            candidates: List of UICandidate objects
            goal: Target label (e.g., "click Search", "click Next")
            viewport_width: Browser viewport width
            viewport_height: Browser viewport height
            last_interaction_pos: (x, y) of last click/input

        Returns:
            Candidates sorted by score (highest first)
        """
        # Extract target text from goal (remove "click", "press", etc.)
        target = goal.lower()
        for prefix in ["click", "press", "tap", "select", "find"]:
            target = target.replace(prefix, "").strip()

        scored_candidates = []

        for candidate in candidates:
            score = 0.0

            # Factor 1: Text match (0-10 points)
            text_score = self._score_text_match(candidate.text.lower(), target)
            score += text_score * 10

            # Factor 1.5: Pagination-specific penalties/boosts
            # When looking for "Next", penalize "More" buttons
            if target in ["next", "next page"] and candidate.text.lower() in ["more", "more results"]:
                score -= 5  # Penalize wrong pagination button
                logger.debug(f"[UIVisionAgent] Penalized 'More' button when looking for 'Next': {candidate.text}")
            # Boost exact matches for pagination keywords
            elif target in ["next", "next page", "previous", "prev page"]:
                pagination_keywords = ["next", "previous", "prev", "→", "←", "›", "‹"]
                if any(keyword in candidate.text.lower() for keyword in pagination_keywords):
                    score += 3  # Boost proper pagination buttons
                    logger.debug(f"[UIVisionAgent] Boosted pagination keyword: {candidate.text}")

            # Factor 1.6: Element-type semantic matching
            # When goal implies a specific element type, boost matching elements
            element_role = candidate.metadata.get("role", "")

            # Input/search box goals should prefer textbox elements over links
            input_goal_keywords = ["search box", "search field", "text field", "input", "type in", "enter text", "search bar"]
            if any(keyword in target for keyword in input_goal_keywords):
                if element_role == "textbox":
                    score += 8  # Strong boost for textbox when looking for input
                    logger.debug(f"[UIVisionAgent] Boosted textbox for input goal: {candidate.text}")
                elif element_role == "link":
                    score -= 5  # Penalize links when looking for input
                    logger.debug(f"[UIVisionAgent] Penalized link for input goal: {candidate.text}")

            # Button goals should prefer buttons over links
            button_goal_keywords = ["button", "submit", "click button"]
            if any(keyword in target for keyword in button_goal_keywords):
                if element_role == "button":
                    score += 5  # Boost buttons
                elif element_role == "textbox":
                    score -= 5  # Penalize textboxes

            # Factor 2: Source reliability (0-5 points)
            if candidate.source == CandidateSource.DOM:
                score += 5
            elif candidate.source == CandidateSource.VISION_OCR:
                score += 3
            elif candidate.source == CandidateSource.VISION_SHAPE:
                score += 1

            # Factor 3: Confidence from perception (0-5 points)
            score += candidate.confidence * 5

            # Factor 4: Size appropriateness (0-3 points)
            # Penalize very small (decorative) or very large (container) elements
            area = candidate.bbox.width * candidate.bbox.height
            if 400 <= area <= 40000:  # 20x20 to 200x200
                score += 3
            elif area < 100 or area > 100000:
                score -= 2

            # Factor 5: Viewport position (0-2 points)
            # Penalize elements off-screen or at extreme edges
            center_x, center_y = candidate.bbox.center
            if 0 <= center_x <= viewport_width and 0 <= center_y <= viewport_height:
                score += 2
            else:
                score -= 3

            # Factor 6: Proximity to last interaction (0-2 points)
            if last_interaction_pos:
                distance = ((center_x - last_interaction_pos[0]) ** 2 +
                           (center_y - last_interaction_pos[1]) ** 2) ** 0.5
                if distance < 200:
                    score += 2
                elif distance < 500:
                    score += 1

            # Update candidate confidence with final score
            candidate.confidence = max(0.0, min(1.0, score / 30))  # Normalize to 0-1
            scored_candidates.append(candidate)

        # Sort by score (highest first)
        scored_candidates.sort(key=lambda c: c.confidence, reverse=True)

        return scored_candidates

    def _score_text_match(self, text: str, target: str) -> float:
        """
        Score text similarity (0.0-1.0).

        Returns:
            1.0 = exact match
            0.8 = fuzzy match (contains)
            0.6 = synonym match
            0.5 = high fuzzy similarity (>0.6 ratio)
            0.4 = partial word match
            0.3 = moderate fuzzy similarity (>0.4 ratio)
            0.0 = no match
        """
        if not text or not target:
            return 0.0

        # Exact match
        if text == target:
            return 1.0

        # Contains match
        if target in text or text in target:
            return 0.8

        # Synonym match (handles multi-word phrases)
        for canonical, synonyms in self.synonyms.items():
            # Check if target matches this synonym group
            target_matches = (target == canonical or target in synonyms or
                              canonical in target or any(syn in target for syn in synonyms))
            if target_matches:
                # Check if text matches this synonym group
                text_matches = (text == canonical or text in synonyms or
                               canonical in text or any(syn in text for syn in synonyms))
                if text_matches:
                    return 0.6

        # Partial word match (e.g., "search" vs "searching")
        target_words = set(target.split())
        text_words = set(text.split())
        common_words = target_words & text_words
        if common_words:
            # Score based on overlap ratio
            overlap_ratio = len(common_words) / max(len(target_words), len(text_words))
            return 0.4 + (overlap_ratio * 0.3)  # 0.4 to 0.7 based on overlap

        # Fuzzy string matching using SequenceMatcher
        from difflib import SequenceMatcher
        ratio = SequenceMatcher(None, text, target).ratio()
        if ratio > 0.6:
            return 0.5  # High fuzzy similarity
        elif ratio > 0.4:
            return 0.3  # Moderate fuzzy similarity

        return 0.0

    async def llm_select_candidate(
        self,
        candidates: List[UICandidate],
        goal: str,
        page_context: str = ""
    ) -> Optional[int]:
        """
        Use LLM to intelligently select the best candidate for a goal.

        Returns the index of the best candidate, or None if no match.

        Args:
            candidates: List of UI candidates to choose from
            goal: What we're trying to click (e.g., "Accept all", "Next page")
            page_context: Optional context about the page (URL, title)

        Returns:
            Index of best candidate (0-based), or None if no suitable match
        """
        if not candidates:
            return None

        # Build candidate list for LLM
        candidate_list = []
        for i, c in enumerate(candidates[:15]):  # Limit to top 15
            candidate_list.append(f"{i}: \"{c.text}\" (type={c.metadata.get('role', 'unknown')})")

        candidates_str = "\n".join(candidate_list)

        # Load prompt template and format
        page_context_line = f"PAGE CONTEXT: {page_context}" if page_context else ""
        prompt_template = _load_ui_prompt("element_selector")
        if prompt_template:
            prompt = prompt_template.format(
                goal=goal,
                page_context_line=page_context_line,
                candidates_str=candidates_str
            )
        else:
            # Fallback to inline prompt if file not found
            prompt = f"""You are a UI automation assistant. Select the best clickable element for the given goal.

GOAL: {goal}
{page_context_line}

AVAILABLE ELEMENTS:
{candidates_str}

INSTRUCTIONS:
- Return ONLY a JSON object with your decision
- If an element matches the goal, return {{"index": <number>, "reason": "<brief reason>"}}
- If NO element matches the goal (e.g., looking for "Accept all" but no consent button exists), return {{"index": null, "reason": "no matching element found"}}
- Be strict: "Google apps" is NOT a match for "Accept all"
- Consider synonyms: "I agree" matches "Accept all", "Continue" may match "Next"

JSON response:"""

        try:
            from apps.services.tool_server.shared import call_llm_json

            llm_url = os.getenv("SOLVER_URL", "http://127.0.0.1:8000/v1/chat/completions")
            llm_model = os.getenv("SOLVER_MODEL_ID", "qwen3-coder")
            llm_api_key = os.getenv("SOLVER_API_KEY", "qwen-local")

            result = await call_llm_json(
                prompt=prompt,
                llm_url=llm_url,
                llm_model=llm_model,
                llm_api_key=llm_api_key,
                max_tokens=100
            )

            if result and "index" in result:
                idx = result.get("index")
                reason = result.get("reason", "")
                if idx is not None and 0 <= idx < len(candidates):
                    logger.info(f"[LLM-Targeting] Selected candidate {idx}: '{candidates[idx].text}' - {reason}")
                    return idx
                else:
                    logger.info(f"[LLM-Targeting] No match found - {reason}")
                    return None

        except Exception as e:
            logger.warning(f"[LLM-Targeting] LLM selection failed: {e}")

        return None


# ============================================================================
# Module 3 - Actuators
# ============================================================================

class ActionExecutor:
    """
    Execute UI actions via vision-based coordinates.

    Vision-only approach for maximum reliability:
    - Always uses coordinate-based clicking (no DOM locators)
    - Works consistently regardless of page structure
    - Avoids "strict mode" violations from duplicate elements
    - Simpler code path = fewer failure modes

    Rationale: Research workloads prioritize reliability over millisecond-level speed.
    Vision clicks (2-3s) are negligible compared to total research time (30-120s).
    """

    def __init__(self, page):
        self.page = page
        self.last_click_pos: Optional[Tuple[float, float]] = None

    async def execute_click(
        self,
        candidate: UICandidate,
        use_human_timing: bool = True
    ) -> Tuple[bool, str, Dict[str, Any]]:
        """
        Execute click action on candidate using vision-based coordinates.

        Args:
            candidate: UI target to click (source doesn't matter, always uses vision)
            use_human_timing: Add human-like delays and movements

        Returns:
            (success, method_used, metadata)
        """
        # Vision-only strategy: Always click at coordinates
        logger.info(f"[Executor] Vision click on '{candidate.text[:30]}' (source={candidate.source.value})")
        success, method, metadata = await self._try_vision_click(candidate, use_human_timing)

        return (success, method, metadata)

    async def _try_dom_click(
        self,
        candidate: UICandidate,
        use_human_timing: bool
    ) -> Tuple[bool, str, Dict[str, Any]]:
        """
        Try clicking via DOM locator.

        NOTE: This method is currently UNUSED (vision-only mode).
        Kept for historical reference and potential future use.
        """
        try:
            role = candidate.metadata.get("role")
            text = candidate.text

            logger.info(f"[Executor] Trying DOM click: role={role}, text='{text[:30]}'")

            # Locate element by role and text
            if text:
                locator = self.page.get_by_role(role, name=text)
            else:
                # Find by role only (less reliable)
                all_elements = await self.page.get_by_role(role).all()
                if not all_elements:
                    return (False, "dom_no_elements", {})

                # Use bounding box to match
                target_center = candidate.bbox.center
                best_match = None
                min_distance = float('inf')

                for elem in all_elements:
                    box = await elem.bounding_box()
                    if not box:
                        continue
                    elem_center = (box["x"] + box["width"] / 2, box["y"] + box["height"] / 2)
                    distance = ((elem_center[0] - target_center[0]) ** 2 +
                               (elem_center[1] - target_center[1]) ** 2) ** 0.5
                    if distance < min_distance:
                        min_distance = distance
                        best_match = elem

                if not best_match or min_distance > 50:  # Within 50px tolerance
                    return (False, "dom_no_match", {"distance": min_distance})

                locator = best_match

            # Add human-like delay before clicking
            if use_human_timing:
                await asyncio.sleep(0.1 + (time.time() % 0.3))  # 100-400ms

            # Click with retries
            for attempt in range(3):
                try:
                    await locator.click(timeout=2000, force=False)
                    logger.info("[Executor] ✓ DOM click succeeded")

                    # Update last click position
                    box = await locator.bounding_box()
                    if box:
                        self.last_click_pos = (
                            box["x"] + box["width"] / 2,
                            box["y"] + box["height"] / 2
                        )

                    return (True, "dom_click", {"attempts": attempt + 1})

                except Exception as e:
                    if attempt == 2:
                        logger.warning(f"[Executor] DOM click failed after 3 attempts: {e}")
                        return (False, "dom_click_failed", {"error": str(e)})
                    await asyncio.sleep(0.5)

        except Exception as e:
            logger.warning(f"[Executor] DOM click error: {e}")
            return (False, "dom_error", {"error": str(e)})

        return (False, "dom_unknown", {})

    async def _try_vision_click(
        self,
        candidate: UICandidate,
        use_human_timing: bool
    ) -> Tuple[bool, str, Dict[str, Any]]:
        """Click using vision-based coordinates."""
        try:
            center_x, center_y = candidate.bbox.center
            logger.info(f"[Executor] Vision click at ({center_x:.0f}, {center_y:.0f})")

            # Add human-like mouse movement (if we have previous position)
            if use_human_timing and self.last_click_pos:
                await self._human_like_movement(
                    self.last_click_pos,
                    (center_x, center_y)
                )

            # Click at coordinates
            await self.page.mouse.click(center_x, center_y)

            # Update last click position
            self.last_click_pos = (center_x, center_y)

            logger.info("[Executor] ✓ Vision click executed")
            return (True, "vision_click", {"coords": (center_x, center_y)})

        except Exception as e:
            logger.error(f"[Executor] Vision click failed: {e}")
            return (False, "vision_click_failed", {"error": str(e)})

    async def _human_like_movement(
        self,
        start: Tuple[float, float],
        end: Tuple[float, float],
        steps: int = 10
    ):
        """Move mouse with human-like easing curve."""
        try:
            # Ease-out curve (fast start, slow end)
            for i in range(steps):
                t = i / steps
                # Cubic ease-out: t = 1 - (1-t)^3
                eased_t = 1 - pow(1 - t, 3)

                x = start[0] + (end[0] - start[0]) * eased_t
                y = start[1] + (end[1] - start[1]) * eased_t

                # Add small random jitter (±2px)
                jitter_x = (time.time() % 1.0 - 0.5) * 4
                jitter_y = (time.time() % 0.7 - 0.35) * 4

                await self.page.mouse.move(x + jitter_x, y + jitter_y)
                await asyncio.sleep(0.01)  # 10ms per step = 100ms total

        except Exception as e:
            logger.debug(f"[Executor] Mouse movement warning: {e}")
            # Non-critical, just skip to click


# ============================================================================
# Module 4 - Verification
# ============================================================================

class ActionVerifier:
    """
    Verify action success via DOM changes or screenshot diff.

    Methods:
    1. DOM mutation: Wait for selector, URL change, element disappearance
    2. Network idle: Wait for page to finish loading
    3. Screenshot diff: Compare before/after screenshots
    """

    def __init__(self, page):
        self.page = page

    async def verify_action(
        self,
        before_url: str,
        before_screenshot: Optional[str] = None,
        verification_timeout: float = 3.0
    ) -> Tuple[bool, str, Dict[str, Any]]:
        """
        Verify that action had an effect.

        Args:
            before_url: URL before action
            before_screenshot: Path to screenshot before action (optional)
            verification_timeout: Max time to wait for changes

        Returns:
            (success, verification_method, metadata)
        """
        start_time = time.time()
        metadata = {}

        # Method 1: Check for URL change
        try:
            await asyncio.sleep(0.5)  # Give page time to start navigating
            current_url = self.page.url

            if current_url != before_url:
                logger.info(f"[Verifier] ✓ URL changed: {before_url[:50]} → {current_url[:50]}")
                return (True, "url_change", {"old_url": before_url, "new_url": current_url})

        except Exception as e:
            logger.debug(f"[Verifier] URL check warning: {e}")

        # Method 2: Wait for network idle (indicates page activity)
        try:
            await self.page.wait_for_load_state("networkidle", timeout=verification_timeout * 1000)
            elapsed = time.time() - start_time

            if elapsed > 0.2:  # Network activity happened
                logger.info(f"[Verifier] ✓ Network activity detected ({elapsed:.1f}s)")
                return (True, "network_idle", {"elapsed": elapsed})

        except Exception as e:
            logger.debug(f"[Verifier] Network idle timeout: {e}")

        # Method 3: Screenshot diff (if before screenshot provided)
        if before_screenshot:
            try:
                after_screenshot = before_screenshot.replace(".png", "_after.png")
                await self.page.screenshot(path=after_screenshot)

                diff_score = await self._compute_screenshot_diff(
                    before_screenshot,
                    after_screenshot
                )

                if diff_score > 0.01:  # More than 1% difference
                    logger.info(f"[Verifier] ✓ Screenshot diff: {diff_score:.2%}")
                    return (True, "screenshot_diff", {"diff_score": diff_score})

            except Exception as e:
                logger.warning(f"[Verifier] Screenshot diff failed: {e}")

        # Method 4: Check for any DOM mutations (scroll, animations, etc.)
        try:
            # Take another screenshot and compare with before
            if before_screenshot:
                after_screenshot_2 = before_screenshot.replace(".png", "_after2.png")
                await asyncio.sleep(0.5)
                await self.page.screenshot(path=after_screenshot_2)

                diff_score = await self._compute_screenshot_diff(
                    before_screenshot,
                    after_screenshot_2
                )

                if diff_score > 0.005:  # Even tiny changes count
                    logger.info(f"[Verifier] ✓ Visual change detected: {diff_score:.2%}")
                    return (True, "visual_change", {"diff_score": diff_score})

        except Exception as e:
            logger.debug(f"[Verifier] Visual change check failed: {e}")

        # No verification succeeded
        elapsed = time.time() - start_time
        logger.warning(f"[Verifier] ✗ No changes detected after {elapsed:.1f}s")
        return (False, "no_change", {"elapsed": elapsed})

    async def _compute_screenshot_diff(
        self,
        img1_path: str,
        img2_path: str
    ) -> float:
        """
        Compute difference between two screenshots.

        Returns:
            Difference score (0.0 = identical, 1.0 = completely different)
        """
        try:
            import cv2
            import numpy as np

            # Read images
            img1 = cv2.imread(img1_path)
            img2 = cv2.imread(img2_path)

            if img1 is None or img2 is None:
                return 0.0

            # Ensure same size
            if img1.shape != img2.shape:
                img2 = cv2.resize(img2, (img1.shape[1], img1.shape[0]))

            # Compute absolute difference
            diff = cv2.absdiff(img1, img2)

            # Convert to grayscale
            diff_gray = cv2.cvtColor(diff, cv2.COLOR_BGR2GRAY)

            # Count changed pixels (threshold at 30/255 to ignore noise)
            changed_pixels = np.sum(diff_gray > 30)
            total_pixels = diff_gray.size

            return changed_pixels / total_pixels if total_pixels > 0 else 0.0

        except ImportError:
            logger.warning("[Verifier] OpenCV not available for screenshot diff")
            return 0.0
        except Exception as e:
            logger.warning(f"[Verifier] Screenshot diff error: {e}")
            return 0.0


# ============================================================================
# Main Agent Class
# ============================================================================

class UIVisionAgent:
    """
    Main entry point for vision-guided UI automation.

    Usage:
        agent = UIVisionAgent(page)
        result = await agent.click("Search", max_attempts=3)
    """

    def __init__(self, page, enable_ocr: bool = True, enable_shapes: bool = True):
        self.page = page
        self.perception = PerceptionEngine(enable_ocr=enable_ocr, enable_shapes=enable_shapes)
        self.targeting = TargetingPolicy()
        self.executor = ActionExecutor(page)
        self.verifier = ActionVerifier(page)

    async def click(
        self,
        goal: str,
        max_attempts: int = 3,
        timeout: float = 30.0
    ) -> ActionResult:
        """
        Click a UI element matching the goal.

        Args:
            goal: Target description (e.g., "Search button", "Next page")
            max_attempts: Maximum candidates to try
            timeout: Maximum time to spend (seconds)

        Returns:
            ActionResult with success status and metadata
        """
        start_time = time.time()

        # Module 1: Extract candidates
        logger.info(f"[UIVisionAgent] Extracting candidates for goal: {goal}")
        candidates = await self.perception.extract_candidates(self.page)

        if not candidates:
            logger.warning("[UIVisionAgent] No candidates found")
            return ActionResult(
                success=False,
                candidate=None,
                verification_method="none",
                metadata={"error": "no_candidates_found"}
            )

        # Module 2: Rank candidates
        logger.info(f"[UIVisionAgent] Ranking {len(candidates)} candidates")
        viewport_size = self.page.viewport_size
        ranked_candidates = self.targeting.rank_candidates(
            candidates,
            goal,
            viewport_width=viewport_size["width"] if viewport_size else 1920,
            viewport_height=viewport_size["height"] if viewport_size else 1080
        )

        # Log top candidates
        for i, candidate in enumerate(ranked_candidates[:5]):
            logger.info(
                f"[UIVisionAgent] Candidate {i+1}: {candidate.text[:30]} "
                f"(source={candidate.source.value}, confidence={candidate.confidence:.2f})"
            )

        # Module 3 & 4: Try top candidates with verification
        logger.info(f"[UIVisionAgent] Trying top {max_attempts} candidates...")

        # Minimum confidence threshold to avoid clicking wrong elements
        MIN_CONFIDENCE_THRESHOLD = 0.5
        if ranked_candidates and ranked_candidates[0].confidence < MIN_CONFIDENCE_THRESHOLD:
            logger.info(
                f"[UIVisionAgent] Low heuristic confidence ({ranked_candidates[0].confidence:.2f}), "
                f"trying LLM selection..."
            )

            # Try LLM-based selection when heuristics fail
            try:
                page_context = f"URL: {self.page.url}"
                llm_idx = await self.targeting.llm_select_candidate(
                    ranked_candidates,
                    goal,
                    page_context=page_context
                )

                if llm_idx is not None:
                    # LLM found a match - reorder candidates to put LLM's choice first
                    selected = ranked_candidates[llm_idx]
                    selected.confidence = 0.8  # Boost confidence for LLM selection
                    ranked_candidates = [selected] + [c for i, c in enumerate(ranked_candidates) if i != llm_idx]
                    logger.info(f"[UIVisionAgent] LLM selected: '{selected.text[:30]}'")
                else:
                    # LLM confirmed no match exists
                    logger.info(f"[UIVisionAgent] LLM confirmed no matching element for '{goal}'")
                    return ActionResult(
                        success=False,
                        candidate=ranked_candidates[0] if ranked_candidates else None,
                        verification_method="none",
                        metadata={"error": "no_match", "method": "llm_confirmed"}
                    )
            except Exception as e:
                logger.warning(f"[UIVisionAgent] LLM selection failed: {e}, falling back to skip")
                return ActionResult(
                    success=False,
                    candidate=ranked_candidates[0],
                    verification_method="none",
                    metadata={"error": "low_confidence", "best_confidence": ranked_candidates[0].confidence}
                )

        # Capture state before clicking
        before_url = self.page.url
        before_screenshot = f"/tmp/ui_vision_before_{int(time.time())}.png"
        await self.page.screenshot(path=before_screenshot)

        for attempt, candidate in enumerate(ranked_candidates[:max_attempts], 1):
            if time.time() - start_time > timeout:
                logger.warning(f"[UIVisionAgent] Timeout after {timeout}s")
                break

            logger.info(
                f"[UIVisionAgent] Attempt {attempt}/{max_attempts}: "
                f"Trying '{candidate.text[:30]}' ({candidate.source.value}, "
                f"confidence={candidate.confidence:.2f})"
            )

            # Module 3: Execute click
            click_success, click_method, click_metadata = await self.executor.execute_click(
                candidate,
                use_human_timing=True
            )

            if not click_success:
                logger.warning(
                    f"[UIVisionAgent] Click failed: {click_method} - {click_metadata.get('error', 'unknown')}"
                )
                continue

            logger.info(f"[UIVisionAgent] ✓ Click executed via {click_method}")

            # Module 4: Verify action had an effect
            verify_success, verify_method, verify_metadata = await self.verifier.verify_action(
                before_url=before_url,
                before_screenshot=before_screenshot,
                verification_timeout=3.0
            )

            if verify_success:
                logger.info(f"[UIVisionAgent] ✓ Verification succeeded via {verify_method}")

                # Success!
                return ActionResult(
                    success=True,
                    candidate=candidate,
                    verification_method=verify_method,
                    metadata={
                        "click_method": click_method,
                        "click_metadata": click_metadata,
                        "verify_metadata": verify_metadata,
                        "attempt": attempt,
                        "elapsed_time": time.time() - start_time
                    }
                )
            else:
                logger.warning(
                    f"[UIVisionAgent] Verification failed: {verify_method} - "
                    f"{verify_metadata.get('error', 'no change detected')}"
                )
                # Try next candidate

        # All candidates failed
        logger.error(f"[UIVisionAgent] All {max_attempts} candidates failed")
        return ActionResult(
            success=False,
            candidate=ranked_candidates[0] if ranked_candidates else None,
            verification_method="all_failed",
            metadata={
                "total_candidates": len(candidates),
                "attempts": min(max_attempts, len(ranked_candidates)),
                "elapsed_time": time.time() - start_time
            }
        )
