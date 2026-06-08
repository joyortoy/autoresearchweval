from autoresearch.enrichment import EnrichmentModule, EnrichmentStore

COMPANIES = [
    ("OpenAI", "https://openai.com"),
    ("Stripe", "https://stripe.com"),
    ("Snowflake", "https://www.snowflake.com"),
    ("Datadog", "https://www.datadoghq.com"),
    ("HubSpot", "https://www.hubspot.com"),
]


def score_gtm_usefulness(result: dict) -> str:
    signals = result.get("memory_context", {}).get("signals", [])
    useful = [s for s in signals if s["confidence"] >= 0.7 and s["verification_status"] != "conflict"]
    if len(useful) >= 3:
        return "high"
    if len(useful) >= 1:
        return "medium"
    return "low"


if __name__ == "__main__":
    mod = EnrichmentModule(EnrichmentStore("/tmp/enrichment_real_companies.sqlite"))
    for name, url in COMPANIES:
        out = mod.enrichEntity({"name": name, "canonical_url": url})
        print(f"{name}: packet={out['memory_packet_id']} useful={score_gtm_usefulness(out)} signals={len(out['memory_context']['signals'])}")
        print(f"  next_action={out['suggested_next_action']}")
