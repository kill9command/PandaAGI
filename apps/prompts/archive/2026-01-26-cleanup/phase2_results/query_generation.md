# Query Generation for Phase 2

## Source Selection by Domain

Choose appropriate sources based on the domain and result type:

### Electronics (products)
- **Amazon**: Wide selection, reviews, Prime shipping
- **Best Buy**: Good for laptops, open-box deals
- **Newegg**: PC components, detailed specs
- **B&H Photo**: Electronics, professional equipment
- **Micro Center**: In-store deals, PC building

### Pets (products + guides)
- **Petco/PetSmart**: Pet supplies, food
- **Chewy**: Online pet supplies
- **Amazon**: Wide selection
- **Pet forums**: Care guides, recommendations

### Appliances (products)
- **Amazon**: Wide selection
- **Williams-Sonoma**: Kitchen appliances
- **Sur La Table**: Cooking equipment
- **Manufacturer sites**: Warranty, specs

### Travel (listings)
- **Google Flights**: Flight search
- **Kayak**: Flights, hotels
- **Booking.com**: Hotels
- **Airline sites**: Direct booking

## Query Patterns

### Product Queries
Use attributes from Phase 1 when available:
- `site:amazon.com [product] [key spec 1] [key spec 2]`
- `[product] [brand if specified] [key requirement]`

### Examples with Phase 1 Intelligence
If Phase 1 discovered "RTX 4060" is recommended:
- `gaming laptop RTX 4060 site:amazon.com`
- `laptop RTX 4060 16GB RAM`

### Without Phase 1
Use query terms from research_plan.md:
- Follow target_sources from plan
- Use key_requirements as search terms

## Search Order

1. Search highest-quality source first
2. Move to alternatives if insufficient results
3. Consider user preferences (preferred vendors)
4. Rate-limit to avoid detection (sequential, not parallel)

## Result Count Targets

| Result Type | Target Count | Min Viable |
|-------------|--------------|------------|
| Products | 5-10 | 3 |
| Guides | 3-5 | 2 |
| Listings | 10-20 | 5 |
| Information | 3-5 | 2 |
