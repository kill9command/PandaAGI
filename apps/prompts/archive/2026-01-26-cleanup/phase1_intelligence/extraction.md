# Intelligence Extraction

## Extraction Process

For each source, extract:

### 1. Key Attributes
Look for specifications, characteristics, or requirements mentioned.

**Format each attribute as:**
- Key: The attribute name (e.g., "GPU", "Cage Size", "Capacity")
- Value: The recommended/important value
- Confidence: How certain (0.0-1.0)
- Sources: Which source indices support this

**Confidence Guidelines:**
- 0.95: Multiple expert sources agree
- 0.85: Single expert source or multiple forums agree
- 0.75: General consensus in discussions
- 0.65: Single source, limited corroboration

### 2. Community Recommendations
Extract specific recommendations with attribution.

**Good recommendations include:**
- Specific product/brand suggestions with reasoning
- Techniques or approaches recommended by experts
- Resources recommended by the community

**Format:** `"[Recommendation] - from [source type/name]"`

### 3. Warnings and Cautions
Extract things to avoid or watch out for.

**Look for:**
- Common mistakes people make
- Products/approaches to avoid
- Red flags or warning signs
- Compatibility issues

### 4. Key Insights Synthesis
Combine all findings into a coherent summary.

**Include:**
- Most important takeaways
- Decision-relevant information
- Context for Phase 2 search

## Domain-Specific Extraction

### Electronics
- Look for: specs, benchmarks, compatibility, price/performance
- Key attributes: CPU, GPU, RAM, storage, display, battery

### Pets
- Look for: care requirements, habitat needs, diet, health
- Key attributes: lifespan, size, temperament, cost, maintenance level

### Appliances
- Look for: features, capacity, durability, ease of use
- Key attributes: size, power, features, brand reputation

### Travel
- Look for: timing, booking tips, destinations, costs
- Key attributes: price ranges, best times, requirements

## Quality Checks

Before finalizing extraction:
1. Are attributes supported by sources?
2. Are recommendations actionable?
3. Are warnings specific and helpful?
4. Does the synthesis capture key points?
