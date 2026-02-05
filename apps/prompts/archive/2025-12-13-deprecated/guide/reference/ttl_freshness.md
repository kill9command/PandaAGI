# TTL Freshness Reference

## 📅 Claim Freshness (TTL Awareness)

Check `last_verified` date before reusing claims:

- **Short TTL (3-7 days):** Prices, availability, news, API quotas
- **Medium TTL (30-90 days):** API specs, package versions, tech docs
- **Long TTL (90-180 days):** Laws, regulations, historical facts

### How to Check

1. Calculate `days_since_verified = today - last_verified`
2. If age > TTL threshold → issue freshness_check ticket
3. When critical and unsure → verify rather than risk stale data
