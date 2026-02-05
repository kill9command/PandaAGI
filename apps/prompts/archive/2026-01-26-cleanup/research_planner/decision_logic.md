# Decision Logic

## When to Choose Each Strategy

### PHASE1_ONLY
Use when:
- Query is informational ("how to care for...", "what is the best way to...")
- User needs general knowledge, not specific products/items
- Topic is about understanding, not purchasing
- Examples:
  - "How do I care for a syrian hamster?"
  - "What's the difference between OLED and LCD?"
  - "Best practices for coffee brewing"

### PHASE2_ONLY
Use when:
- User already knows what they want (specific product/item)
- Query includes specific requirements/specs
- Prior context already has intelligence for this topic
- Examples:
  - "Find me an RTX 4060 laptop under $800"
  - "Where can I buy a 20 gallon hamster tank?"
  - "Price for Breville espresso machine"

### PHASE1_THEN_PHASE2
Use when:
- User wants to buy/find something but needs guidance first
- Query is vague about requirements ("cheapest", "best", "good")
- Domain knowledge would improve search quality
- Examples:
  - "What's the cheapest laptop with an nvidia gpu?"
  - "Best hamster cage for a beginner"
  - "Good espresso machine for home use"

## Domain Classification

Identify the primary domain from the query:

| Domain Pattern | Examples |
|----------------|----------|
| electronics.laptop | laptop, notebook, gaming laptop |
| electronics.gpu | graphics card, GPU, RTX, nvidia |
| electronics.phone | smartphone, iphone, android |
| pets.hamster | hamster, syrian hamster, dwarf hamster |
| pets.dog | dog, puppy, canine |
| appliances.coffee | coffee maker, espresso machine |
| appliances.kitchen | blender, mixer, toaster |
| travel.flights | flight, airplane, airline |
| travel.hotels | hotel, accommodation, lodging |
| health.supplement | vitamin, supplement, protein |
| general | (fallback for unclear domains) |

## Prior Research Intelligence (CRITICAL)

**Before starting any new research, check context.md §2 (Gathered Context).**

### What to Look For in §2

§2 contains intelligence gathered from prior research:

1. **Product Intelligence**
   - Recommended models/brands from real users
   - Price expectations (typical ranges, what's a "good deal")
   - Key specs to prioritize
   - Features to avoid / deal breakers

2. **Source Intelligence**
   - Trusted vendors mentioned by users
   - Forums/reviews already consulted
   - Authoritative sources for this domain

3. **User Preferences**
   - Budget constraints mentioned
   - Brand preferences (positive or negative)
   - Must-have features vs nice-to-have

### Reusing Prior Intelligence

**If §2 contains relevant intelligence for the current query:**

| §2 Contains | Decision |
|-------------|----------|
| Full specs, recommendations, price expectations for this domain | PHASE2_ONLY - just find products matching known requirements |
| Partial intelligence (some specs but not complete picture) | Targeted Phase 1 to fill gaps, then Phase 2 |
| No relevant prior research | PHASE1_THEN_PHASE2 |

**Example:**
- Query: "What's the cheapest gaming laptop with nvidia gpu?"
- §2 has: "Gaming laptops: RTX 4060 recommended, 16GB RAM minimum, expect $700-1200"
- Decision: PHASE2_ONLY (we already know what to look for)

### Session Continuity

Also check context.md for:
- User preferences (budget, brands, requirements)
- Previous queries in same session (maintain continuity)
- Corrections or clarifications the user provided

## Output Requirements

Your JSON output MUST include:
- `decision`: One of PHASE1_ONLY, PHASE2_ONLY, PHASE1_THEN_PHASE2
- `rationale`: Brief explanation of why this strategy
- `domain`: Domain classification string

For PHASE1_ONLY or PHASE1_THEN_PHASE2, include `phase1` object.
For PHASE2_ONLY or PHASE1_THEN_PHASE2, include `phase2` object.
