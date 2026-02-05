# Contact Information Extraction Prompt

Extract contact information from the provided page text.

## Response Format

Return JSON:
```json
{
  "business_name": "Name" or null,
  "phone": "Phone number" or null,
  "email": "Email" or null,
  "address": "Address" or null,
  "contact_form": true or false,
  "social_media": ["link1", "link2"] or []
}
```

## Guidelines

1. Extract only information that is clearly present in the text
2. Use null for any fields that cannot be determined
3. Phone numbers should be formatted as found
4. Email addresses should be exact matches
5. For social_media, include any links to social platforms (Facebook, Twitter, Instagram, etc.)
6. Set contact_form to true if there's mention of a contact form or "contact us" functionality

Return ONLY valid JSON.
