"""
Product Requirements for LLM-Integrated Navigation Validation.

This module defines structured requirements that flow from Phase 1 intelligence
through the navigation and extraction pipeline. Requirements are used by LLM
decision points to determine:
- Whether a page has relevant products (navigation decisions)
- Whether extracted products match specifications (validation)
- When to stop searching (early stopping)
- How to relax requirements if no matches found

Author: Panda System
Date: 2025-12-09
"""

from dataclasses import dataclass, field
from typing import Dict, List, Tuple, Optional, Any
import re
import yaml
import logging

logger = logging.getLogger(__name__)


@dataclass
class ProductRequirements:
    """
    Structured product requirements for navigation and validation.

    Created from Phase 1 intelligence output. Used by:
    - NavigatorRecipeExecutor for LLM decision prompts
    - Quick title checks before expensive PDP extraction
    - Early stopping when enough matches found
    - Relaxation loop when no strict matches found
    """

    # Core identification
    category: str  # "laptop", "hamster", "furniture"
    query: str  # Original user query

    # Required specifications (from Phase 1 hard_requirements)
    required_specs: Dict[str, str] = field(default_factory=dict)
    # Example: {"gpu": "nvidia", "type": "laptop"}

    # Acceptable alternatives (LLM-generated variants)
    acceptable_alternatives: Dict[str, List[str]] = field(default_factory=dict)
    # Example: {"gpu": ["RTX 4060", "RTX 4050", "RTX 3060", "GTX 1660"]}

    # Deal breakers (things that disqualify a product)
    deal_breakers: List[str] = field(default_factory=list)
    # Example: ["integrated graphics", "Intel UHD", "no dedicated GPU"]

    # Relaxation tiers (how to broaden search if no matches)
    relaxation_tiers: List[Dict[str, Any]] = field(default_factory=list)
    # Example: [{"tier": 1, "description": "Include GTX series", "add_to_acceptable": {...}}]

    # Stopping criteria
    target_quantity: int = 5  # Stop when this many matches found

    # Metadata
    current_relaxation_tier: int = 0  # 0 = strict, increases as we relax

    def to_markdown(self) -> str:
        """
        Serialize to markdown for recipe input documents.

        This is the document format consumed by navigator recipes.
        """
        lines = [
            "# Product Requirements",
            f"**Query:** {self.query}",
            f"**Category:** {self.category}",
            f"**Target Quantity:** {self.target_quantity}",
            "",
            "## Required Specifications",
        ]

        if self.required_specs:
            for key, value in self.required_specs.items():
                lines.append(f"- **{key}:** {value}")
        else:
            lines.append("- (none specified)")

        lines.extend([
            "",
            "## Acceptable Alternatives",
            "Products matching ANY of these are valid:",
        ])

        if self.acceptable_alternatives:
            for spec_key, alternatives in self.acceptable_alternatives.items():
                lines.append(f"- **{spec_key}:** {', '.join(alternatives)}")
        else:
            lines.append("- (use required specs only)")

        lines.extend([
            "",
            "## Deal Breakers",
            "Reject products containing ANY of these:",
        ])

        if self.deal_breakers:
            for breaker in self.deal_breakers:
                lines.append(f"- {breaker}")
        else:
            lines.append("- (none specified)")

        if self.current_relaxation_tier > 0:
            lines.extend([
                "",
                f"## Current Relaxation Tier: {self.current_relaxation_tier}",
                "Requirements have been relaxed from original strict criteria."
            ])

        return "\n".join(lines)

    def to_prompt_context(self) -> str:
        """
        Generate concise context string for inline LLM prompts.

        Shorter than to_markdown(), suitable for embedding in larger prompts.
        """
        parts = [
            f"REQUIREMENTS for {self.category}:",
            f"- Query: {self.query}",
        ]

        if self.required_specs:
            specs_str = ", ".join(f"{k}={v}" for k, v in self.required_specs.items())
            parts.append(f"- Must have: {specs_str}")

        if self.acceptable_alternatives:
            for key, alts in self.acceptable_alternatives.items():
                parts.append(f"- Acceptable {key}: {', '.join(alts[:5])}")  # Limit to 5
                if len(alts) > 5:
                    parts.append(f"  ... and {len(alts) - 5} more")

        if self.deal_breakers:
            parts.append(f"- Reject if contains: {', '.join(self.deal_breakers[:5])}")

        parts.append(f"- Need {self.target_quantity} matching products")

        return "\n".join(parts)

    def quick_title_check(self, title: str) -> Tuple[bool, str]:
        """
        Fast regex check before committing to expensive PDP extraction.

        Args:
            title: Product listing title

        Returns:
            (worth_checking, reason) tuple
            - worth_checking: True if PDP extraction is worthwhile
            - reason: Explanation of decision
        """
        if not title:
            return (True, "Empty title, verify via PDP")

        title_lower = title.lower()

        # Check deal breakers first (fast rejection)
        for breaker in self.deal_breakers:
            breaker_lower = breaker.lower()
            # Use word boundary matching for better accuracy
            if breaker_lower in title_lower:
                return (False, f"Deal breaker found: '{breaker}'")

        # Check if any acceptable alternative is mentioned
        for spec_key, alternatives in self.acceptable_alternatives.items():
            for alt in alternatives:
                alt_lower = alt.lower()
                if alt_lower in title_lower:
                    return (True, f"Found {spec_key}: '{alt}'")

        # Check required specs
        for spec_key, spec_value in self.required_specs.items():
            spec_lower = spec_value.lower()
            if spec_lower in title_lower:
                return (True, f"Found required {spec_key}: '{spec_value}'")

        # Category check
        if self.category.lower() in title_lower:
            return (True, f"Category match: '{self.category}'")

        # Unknown - worth checking to be safe
        return (True, "No clear match/rejection, verify via PDP")

    def validate_specs(self, specs: Dict[str, str]) -> Tuple[bool, str]:
        """
        Validate extracted product specs against requirements.

        Args:
            specs: Dict of spec_name -> spec_value from PDP extraction

        Returns:
            (is_valid, reason) tuple
        """
        if not specs:
            return (False, "No specs provided")

        # Combine title and specs for checking
        specs_text = " ".join(str(v) for v in specs.values()).lower()

        # Check deal breakers in specs
        for breaker in self.deal_breakers:
            if breaker.lower() in specs_text:
                return (False, f"Deal breaker in specs: '{breaker}'")

        # Check if any required spec is satisfied
        for spec_key, required_value in self.required_specs.items():
            # Check direct match in specs
            if spec_key in specs:
                spec_val = specs[spec_key].lower()
                if required_value.lower() in spec_val:
                    continue  # This required spec is satisfied

                # Check acceptable alternatives
                if spec_key in self.acceptable_alternatives:
                    matched = False
                    for alt in self.acceptable_alternatives[spec_key]:
                        if alt.lower() in spec_val:
                            matched = True
                            break
                    if not matched:
                        return (False, f"Spec '{spec_key}' value '{specs[spec_key]}' not in acceptable alternatives")
            else:
                # Spec not in extracted specs - check if mentioned anywhere
                found_in_any = False
                for val in specs.values():
                    val_lower = str(val).lower()
                    if required_value.lower() in val_lower:
                        found_in_any = True
                        break
                    # Check alternatives
                    if spec_key in self.acceptable_alternatives:
                        for alt in self.acceptable_alternatives[spec_key]:
                            if alt.lower() in val_lower:
                                found_in_any = True
                                break

                if not found_in_any:
                    return (False, f"Required spec '{spec_key}={required_value}' not found")

        return (True, "All requirements satisfied")

    def apply_relaxation(self, tier_data: Dict[str, Any]) -> 'ProductRequirements':
        """
        Create relaxed version of requirements using tier data.

        Args:
            tier_data: Relaxation tier from relaxation_tiers list

        Returns:
            New ProductRequirements with relaxed criteria
        """
        # Create copy with updated alternatives
        new_alternatives = dict(self.acceptable_alternatives)

        # Add new acceptable alternatives from tier
        add_to_acceptable = tier_data.get("add_to_acceptable", {})
        for key, new_values in add_to_acceptable.items():
            if key in new_alternatives:
                # Extend existing list
                new_alternatives[key] = list(new_alternatives[key]) + new_values
            else:
                new_alternatives[key] = new_values

        # Remove deal breakers if specified
        new_deal_breakers = list(self.deal_breakers)
        remove_deal_breakers = tier_data.get("remove_deal_breakers", [])
        for breaker in remove_deal_breakers:
            if breaker in new_deal_breakers:
                new_deal_breakers.remove(breaker)

        # Create new requirements
        return ProductRequirements(
            category=self.category,
            query=self.query,
            required_specs=self.required_specs,  # Keep original required specs
            acceptable_alternatives=new_alternatives,
            deal_breakers=new_deal_breakers,
            relaxation_tiers=self.relaxation_tiers,
            target_quantity=self.target_quantity,
            current_relaxation_tier=tier_data.get("tier", self.current_relaxation_tier + 1)
        )

    def relax_to_tier(self, tier: int) -> 'ProductRequirements':
        """
        Relax requirements to specified tier level.

        Args:
            tier: Target tier (0 = strict, 1+ = relaxed)

        Returns:
            ProductRequirements at specified relaxation level
        """
        if tier == 0:
            return self

        if tier > len(self.relaxation_tiers):
            logger.warning(f"Requested tier {tier} exceeds available tiers ({len(self.relaxation_tiers)})")
            tier = len(self.relaxation_tiers)

        # Apply relaxations cumulatively
        result = self
        for i in range(tier):
            result = result.apply_relaxation(self.relaxation_tiers[i])

        return result

    def can_relax(self) -> bool:
        """
        Check if further relaxation is possible.

        Returns:
            True if there are unused relaxation tiers available
        """
        return self.current_relaxation_tier < len(self.relaxation_tiers)

    def relax(self) -> Dict[str, Any]:
        """
        Apply the next relaxation tier (mutates self in place).

        This method modifies the current instance rather than creating a new one,
        making it suitable for use in loops.

        Returns:
            Dict describing what was relaxed, or empty dict if no relaxation available
        """
        if not self.can_relax():
            return {}

        # Get next tier data
        tier_idx = self.current_relaxation_tier
        tier_data = self.relaxation_tiers[tier_idx]

        # Apply changes to current instance
        add_to_acceptable = tier_data.get("add_to_acceptable", {})
        for key, new_values in add_to_acceptable.items():
            if key in self.acceptable_alternatives:
                self.acceptable_alternatives[key] = list(self.acceptable_alternatives[key]) + new_values
            else:
                self.acceptable_alternatives[key] = new_values

        # Remove deal breakers if specified
        remove_deal_breakers = tier_data.get("remove_deal_breakers", [])
        for breaker in remove_deal_breakers:
            if breaker in self.deal_breakers:
                self.deal_breakers.remove(breaker)

        # Increment tier
        self.current_relaxation_tier += 1

        # Return what was changed
        return {
            "tier": self.current_relaxation_tier,
            "description": tier_data.get("description", f"Tier {self.current_relaxation_tier}"),
            "added_alternatives": add_to_acceptable,
            "removed_deal_breakers": remove_deal_breakers
        }

    @classmethod
    def from_phase1_intelligence(
        cls,
        intelligence: Dict[str, Any],
        query: str
    ) -> 'ProductRequirements':
        """
        Create ProductRequirements from Phase 1 intelligence output.

        Maps Phase 1 fields to requirements structure:
        - hard_requirements -> required_specs
        - acceptable_alternatives -> acceptable_alternatives (if present)
        - specs_discovered -> used to build acceptable_alternatives
        - deal_breakers -> deal_breakers (if present)
        - relaxation_tiers -> relaxation_tiers (if present)

        Args:
            intelligence: Phase 1 output dict from _synthesize_phase1_intelligence
            query: Original user query

        Returns:
            ProductRequirements instance
        """
        if not intelligence:
            logger.warning("Empty intelligence dict, creating minimal requirements")
            return cls(
                category="product",
                query=query,
                target_quantity=5
            )

        # Extract category from hard_requirements or infer from query
        hard_reqs = intelligence.get("hard_requirements", [])
        category = "product"
        if hard_reqs:
            # First item is often the category
            category = hard_reqs[0] if isinstance(hard_reqs[0], str) else "product"

        # Build required_specs from hard_requirements
        required_specs = {}
        user_reqs = intelligence.get("user_explicit_requirements", [])
        for req in user_reqs:
            # Parse "nvidia gpu" -> {"gpu": "nvidia"}
            req_lower = req.lower()
            if "nvidia" in req_lower or "rtx" in req_lower or "gtx" in req_lower:
                required_specs["gpu"] = "nvidia"
            elif "amd" in req_lower:
                required_specs["gpu"] = "amd"
            elif "intel" in req_lower and "cpu" not in required_specs:
                required_specs["cpu"] = "intel"

        # Use acceptable_alternatives if provided by Phase 1
        acceptable_alternatives = intelligence.get("acceptable_alternatives", {})

        # If not provided, build from specs_discovered
        if not acceptable_alternatives:
            specs_discovered = intelligence.get("specs_discovered", {})
            for spec_key, spec_info in specs_discovered.items():
                if isinstance(spec_info, dict):
                    value = spec_info.get("value", "")
                    if value:
                        acceptable_alternatives[spec_key] = [value]
                elif isinstance(spec_info, str):
                    acceptable_alternatives[spec_key] = [spec_info]

        # Get deal_breakers or default to empty
        deal_breakers = intelligence.get("deal_breakers", [])

        # Get relaxation_tiers or default to empty
        relaxation_tiers = intelligence.get("relaxation_tiers", [])

        return cls(
            category=category,
            query=query,
            required_specs=required_specs,
            acceptable_alternatives=acceptable_alternatives,
            deal_breakers=deal_breakers,
            relaxation_tiers=relaxation_tiers,
            target_quantity=5
        )

    def to_dict(self) -> Dict[str, Any]:
        """Serialize to dictionary for JSON storage."""
        return {
            "category": self.category,
            "query": self.query,
            "required_specs": self.required_specs,
            "acceptable_alternatives": self.acceptable_alternatives,
            "deal_breakers": self.deal_breakers,
            "relaxation_tiers": self.relaxation_tiers,
            "target_quantity": self.target_quantity,
            "current_relaxation_tier": self.current_relaxation_tier
        }

    @classmethod
    def from_dict(cls, data: Dict[str, Any]) -> 'ProductRequirements':
        """Deserialize from dictionary."""
        return cls(
            category=data.get("category", "product"),
            query=data.get("query", ""),
            required_specs=data.get("required_specs", {}),
            acceptable_alternatives=data.get("acceptable_alternatives", {}),
            deal_breakers=data.get("deal_breakers", []),
            relaxation_tiers=data.get("relaxation_tiers", []),
            target_quantity=data.get("target_quantity", 5),
            current_relaxation_tier=data.get("current_relaxation_tier", 0)
        )
