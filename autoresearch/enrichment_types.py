from __future__ import annotations

import json
import os
from dataclasses import dataclass
from typing import Any
from urllib.parse import quote_plus, urlencode
from urllib.request import Request, urlopen

GTM_SIGNAL_TYPES = {
    "company_priority",
    "hiring_signal",
    "funding_signal",
    "product_launch",
    "buyer_intent",
    "communication_context",
    "competitor_signal",
    "operational_need",
}

RENTAL_SIGNAL_TYPES = {
    "tenant_intent",
    "landlord_supply",
    "property_availability",
    "rental_budget",
    "move_in_timeline",
    "area_preference",
    "property_type_preference",
    "viewing_intent",
    "lease_duration",
    "furnishing_preference",
    "household_profile",
    "pet_requirement",
    "school_or_work_location",
    "landlord_preference",
    "document_readiness",
    "verification_need",
    "maintenance_signal",
    "dispute_signal",
    "renewal_signal",
    "buying_interest",
    "risk_signal",
}

SIGNAL_TYPES = GTM_SIGNAL_TYPES | RENTAL_SIGNAL_TYPES

ENTITY_TYPES = {
    "company",
    "person",
    "account",
    "tenant",
    "landlord",
    "property",
    "area",
    "source_channel",
}

RENTAL_ENTITY_TYPES = {"tenant", "landlord", "property", "area", "source_channel"}

SOURCE_TYPES = {
    "direct_interaction",
    "official_website",
    "recent_news",
    "social_post",
    "third_party_scrape",
    "expat_forum",
    "relocation_group",
    "facebook_group",
    "landlord_ad",
    "property_listing",
    "whatsapp_message",
    "manual_import",
    "referral",
    "official_property_source",
    "third_party_listing",
}

SOURCE_WEIGHTS = {
    "direct_interaction": (0.95, 60),
    "official_website": (0.85, 45),
    "recent_news": (0.7, 30),
    "social_post": (0.6, 14),
    "third_party_scrape": (0.45, 7),
    "manual_import": (0.8, 45),
    "referral": (0.75, 30),
    "whatsapp_message": (0.7, 21),
    "official_property_source": (0.85, 45),
    "property_listing": (0.65, 14),
    "landlord_ad": (0.7, 21),
    "third_party_listing": (0.55, 10),
    "expat_forum": (0.55, 10),
    "relocation_group": (0.6, 14),
    "facebook_group": (0.5, 7),
}

TENANT_ACQUISITION_QUERIES = [
    "moving to Singapore rental budget",
    "looking for room Singapore",
    "expat moving to Singapore condo",
    "Singapore rental near MRT",
    "family relocating to Singapore housing",
]

LANDLORD_ACQUISITION_QUERIES = [
    "Singapore landlord renting room",
    "owner renting condo Singapore",
    "direct landlord rental Singapore",
    "room for rent Singapore owner",
    "available unit Singapore rental",
]

SINGAPORE_AREA_HINTS = [
    "Tanjong Pagar",
    "Jurong",
    "Orchard",
    "Novena",
    "Bugis",
    "Clementi",
    "Tampines",
    "Woodlands",
    "Punggol",
    "Serangoon",
    "Holland Village",
    "River Valley",
    "East Coast",
    "Marina Bay",
    "Raffles Place",
    "near MRT",
]


IMPORT_TIMING_STATES = {
    "queued",
    "processing",
    "imported",
    "enriched",
    "review_ready",
    "delayed",
    "stale",
    "ignored",
    "failed",
}

SOURCE_RECENCY_LABELS = {"fresh", "normal", "stale", "expired"}

REVIEW_REASONS = {
    "duplicate",
    "missing_budget",
    "missing_rent",
    "missing_area",
    "low_confidence",
    "contact_unclear",
    "not_singapore",
    "spam",
    "other",
}


VERIFICATION_SIGNAL_TYPES = {
    "phone_reachable",
    "whatsapp_reachable",
    "email_reachable",
    "identity_document_submitted",
    "identity_document_matches_name",
    "landlord_ownership_document_submitted",
    "property_address_matches_listing",
    "duplicate_contact_detected",
    "prior_platform_history_found",
    "scam_pattern_detected",
    "manual_review_required",
}

CONSENT_STATUSES = {"not_requested", "requested", "granted", "denied"}
VERIFICATION_STATUSES = {"unverified", "partial", "verified", "review_required", "rejected"}
VERIFICATION_RESULTS = {"pass", "fail", "unknown", "review_required"}
VERIFICATION_SOURCES = {"user_submitted", "platform_history", "document_check", "manual_review", "provider_stub"}

IMPORT_TEMPLATES = {
    "Paste Tenant Inquiry": {"template": "Paste Tenant Inquiry", "route": "importTenantInquiryText", "default_source_type": "manual_import"},
    "Paste Landlord Ad": {"template": "Paste Landlord Ad", "route": "importLandlordAdText", "default_source_type": "landlord_ad"},
    "Paste Expat Forum Post": {"template": "Paste Expat Forum Post", "route": "importTenantInquiryText", "default_source_type": "expat_forum"},
    "Paste Property Listing": {"template": "Paste Property Listing", "route": "importLandlordAdText", "default_source_type": "property_listing"},
}


@dataclass
class EnrichmentEntity:
    id: str
    type: str
    name: str
    canonical_url: str


class SearchProvider:
    """Existing provider abstraction reused by GTM and rental enrichment."""

    def search(self, entity: dict[str, Any]) -> list[dict[str, str]]:
        raise NotImplementedError


class DuckDuckGoSearchProvider(SearchProvider):
    def search(self, entity: dict[str, Any]) -> list[dict[str, str]]:
        query = entity.get("search_query") or f"{entity['name']} company hiring funding launch"
        source_type = entity.get("source_type", "recent_news")
        targets = []
        canonical_url = entity.get("canonical_url")
        if canonical_url:
            targets.append({"url": canonical_url, "source_type": entity.get("canonical_source_type", "official_website")})
        targets.append({"url": f"https://duckduckgo.com/html/?q={quote_plus(query)}", "source_type": source_type})
        return targets


class _APIBackedProvider(SearchProvider):
    def _fetch_json(self, url: str, headers: dict[str, str] | None = None) -> dict[str, Any]:
        req = Request(url, headers=headers or {"User-Agent": "NanoClaw-Enrichment/3.1"})
        with urlopen(req, timeout=15) as response:
            return json.loads(response.read().decode("utf-8", errors="ignore"))


class SerpAPISearchProvider(_APIBackedProvider):
    def __init__(self, api_key: str):
        self.api_key = api_key

    def search(self, entity: dict[str, Any]) -> list[dict[str, str]]:
        query = entity.get("search_query") or f"{entity['name']} company news"
        params = urlencode({"engine": "google", "q": query, "api_key": self.api_key, "num": 5})
        payload = self._fetch_json(f"https://serpapi.com/search.json?{params}")
        urls = [
            {"url": r.get("link", ""), "source_type": entity.get("source_type", "recent_news")}
            for r in payload.get("organic_results", [])
            if r.get("link")
        ]
        canonical = entity.get("canonical_url")
        return ([{"url": canonical, "source_type": entity.get("canonical_source_type", "official_website")}] if canonical else []) + urls


class TavilySearchProvider(_APIBackedProvider):
    def __init__(self, api_key: str):
        self.api_key = api_key

    def search(self, entity: dict[str, Any]) -> list[dict[str, str]]:
        query = entity.get("search_query") or f"{entity['name']} funding hiring product launch"
        params = urlencode({"api_key": self.api_key, "query": query, "max_results": 5})
        payload = self._fetch_json(f"https://api.tavily.com/search?{params}")
        urls = [
            {"url": r.get("url", ""), "source_type": entity.get("source_type", "recent_news")}
            for r in payload.get("results", [])
            if r.get("url")
        ]
        canonical = entity.get("canonical_url")
        return ([{"url": canonical, "source_type": entity.get("canonical_source_type", "official_website")}] if canonical else []) + urls


class ExaSearchProvider(_APIBackedProvider):
    def __init__(self, api_key: str):
        self.api_key = api_key

    def search(self, entity: dict[str, Any]) -> list[dict[str, str]]:
        query = entity.get("search_query") or f"{entity['name']} company GTM signals"
        params = urlencode({"query": query, "num_results": 5})
        payload = self._fetch_json(
            f"https://api.exa.ai/search?{params}",
            headers={"x-api-key": self.api_key, "User-Agent": "NanoClaw-Enrichment/3.1"},
        )
        urls = [
            {"url": r.get("url", ""), "source_type": entity.get("source_type", "recent_news")}
            for r in payload.get("results", [])
            if r.get("url")
        ]
        canonical = entity.get("canonical_url")
        return ([{"url": canonical, "source_type": entity.get("canonical_source_type", "official_website")}] if canonical else []) + urls


class BrightDataSearchProvider(_APIBackedProvider):
    def __init__(self, api_key: str):
        self.api_key = api_key

    def search(self, entity: dict[str, Any]) -> list[dict[str, str]]:
        query = entity.get("search_query") or f"{entity['name']} company announcements"
        params = urlencode({"query": query})
        payload = self._fetch_json(
            f"https://api.brightdata.com/search?{params}",
            headers={"Authorization": f"Bearer {self.api_key}", "User-Agent": "NanoClaw-Enrichment/3.1"},
        )
        urls = [
            {"url": r.get("url", ""), "source_type": entity.get("source_type", "recent_news")}
            for r in payload.get("results", [])
            if r.get("url")
        ]
        canonical = entity.get("canonical_url")
        return ([{"url": canonical, "source_type": entity.get("canonical_source_type", "official_website")}] if canonical else []) + urls


def build_search_provider() -> SearchProvider:
    if os.getenv("SERPAPI_API_KEY"):
        return SerpAPISearchProvider(os.environ["SERPAPI_API_KEY"])
    if os.getenv("TAVILY_API_KEY"):
        return TavilySearchProvider(os.environ["TAVILY_API_KEY"])
    if os.getenv("EXA_API_KEY"):
        return ExaSearchProvider(os.environ["EXA_API_KEY"])
    if os.getenv("BRIGHTDATA_API_KEY"):
        return BrightDataSearchProvider(os.environ["BRIGHTDATA_API_KEY"])
    return DuckDuckGoSearchProvider()
