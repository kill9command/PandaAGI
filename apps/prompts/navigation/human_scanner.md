# Human Page Scanner

You are scanning a webpage to determine if it's relevant for: "{search_goal}"

## Context

URL: {url}

## Page Preview

{preview}

## Task

Quickly determine if this page is relevant. Answer in JSON format:

```json
{
  "is_relevant": true/false,
  "relevance_score": 0.0-1.0,
  "relevant_sections": ["brief description of relevant section 1", "section 2"],
  "skip_reason": "why not relevant (if is_relevant=false)" or null
}
```

## Guidelines

Be efficient - we're just checking if it's worth reading the full page.

### When to mark as RELEVANT:
- Forum posts discussing the topic
- Reddit threads with user experiences
- Review sites with relevant reviews
- Product pages matching the search
- Guides or tutorials on the topic

### When to mark as NOT RELEVANT:
- Completely different topic
- Generic homepage with no specific content
- Login/registration pages
- Error pages
- Paywalled content with no preview

### Scoring Guidelines:
- **0.8-1.0**: Direct match - page is specifically about the goal
- **0.6-0.8**: Strong relevance - page discusses related topics extensively
- **0.4-0.6**: Moderate relevance - page mentions the topic among other things
- **0.2-0.4**: Weak relevance - tangential connection only
- **0.0-0.2**: Not relevant - different topic entirely
