# Result Scorer

Score these search results for relevance to the goal.

## Goal
{original_query}

## Intent
{informational | commerce}

## Search Results
{numbered list of URLs and titles}

## Score Each Result

For each result, output:
- score: 0.0 to 1.0 (how relevant/useful it likely is)
- type: forum | review | vendor | news | official | other
- priority: must_visit | should_visit | maybe | skip

Consider:
- Does the title suggest relevant content?
- Is this a trustworthy source type for this query?
- For commerce: prioritize reviews and forums over vendors

Output as JSON array, ranked by score (highest first).
