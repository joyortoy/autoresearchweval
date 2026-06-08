from __future__ import annotations

import json
import logging
from datetime import datetime, timezone
from typing import Any, Callable

from .auth_rbac import PERMISSIONS, ROLE_PERMISSIONS, AuthRbacMixin
from .consent_privacy import CONSENT_POLICY, CONSENT_TYPES, ConsentPrivacyMixin
from .conversation_runtime import ConversationRuntimeMixin
from .enrichment_admin_ui import EnrichmentAdminUIMixin
from .enrichment_extractors import EnrichmentExtractionMixin
from .enrichment_runtime import EnrichmentRuntimeMixin
from .enrichment_store import EnrichmentStore
from .memory_timeline import TIMELINE_FILTERS, MemoryTimelineMixin
from .enrichment_types import (
    ENTITY_TYPES,
    GTM_SIGNAL_TYPES,
    IMPORT_TEMPLATES,
    IMPORT_TIMING_STATES,
    VERIFICATION_SIGNAL_TYPES,
    LANDLORD_ACQUISITION_QUERIES,
    RENTAL_ENTITY_TYPES,
    RENTAL_SIGNAL_TYPES,
    REVIEW_REASONS,
    SIGNAL_TYPES,
    SOURCE_TYPES,
    SOURCE_WEIGHTS,
    TENANT_ACQUISITION_QUERIES,
    BrightDataSearchProvider,
    DuckDuckGoSearchProvider,
    EnrichmentEntity,
    ExaSearchProvider,
    SearchProvider,
    SerpAPISearchProvider,
    TavilySearchProvider,
    build_search_provider,
)
from .person_verification import PersonVerificationMixin
from .real_estate_memory_os import GovernedMemoryPacketInput, RealEstateRagAdapter, Signal
from .rental_intake import RentalIntakeMixin
from .rental_lifecycle import LIFECYCLE_STAGES, LIFECYCLE_TRIGGERS, RentalLifecycleMixin

LOGGER = logging.getLogger(__name__)


class EnrichmentModule(
    AuthRbacMixin,
    ConversationRuntimeMixin,
    MemoryTimelineMixin,
    EnrichmentAdminUIMixin,
    ConsentPrivacyMixin,
    PersonVerificationMixin,
    RentalIntakeMixin,
    RentalLifecycleMixin,
    EnrichmentRuntimeMixin,
    EnrichmentExtractionMixin,
):
    """Thin orchestrator that preserves the governed enrichment public API."""

    def __init__(
        self,
        store: EnrichmentStore,
        search_provider: SearchProvider | None = None,
        llm_extractor: Callable[[dict[str, Any]], list[dict[str, Any]]] | None = None,
        runtime_hook: Callable[[dict[str, Any]], None] | None = None,
    ):
        self.store = store
        self.search_provider = search_provider or build_search_provider()
        self.llm_extractor = llm_extractor
        self.runtime_hook = runtime_hook

    def buildRentalSearchQueries(self, acquisition_type: str) -> list[str]:
        if acquisition_type == "tenant":
            return TENANT_ACQUISITION_QUERIES.copy()
        if acquisition_type == "landlord":
            return LANDLORD_ACQUISITION_QUERIES.copy()
        return TENANT_ACQUISITION_QUERIES + LANDLORD_ACQUISITION_QUERIES

    def buildRentalSearchTargets(self, acquisition_type: str, source_type: str = "third_party_listing") -> list[dict[str, str]]:
        return [
            {
                "name": f"rental-{acquisition_type}-{idx}",
                "type": "source_channel",
                "search_query": query,
                "source_type": source_type,
            }
            for idx, query in enumerate(self.buildRentalSearchQueries(acquisition_type), start=1)
        ]

    def searchExternalData(self, entity: dict[str, Any]) -> list[dict[str, str]]:
        if entity.get("type") in RENTAL_ENTITY_TYPES and entity.get("acquisition_type"):
            targets: list[dict[str, str]] = []
            for query_entity in self.buildRentalSearchTargets(entity["acquisition_type"], entity.get("source_type", "third_party_listing")):
                targets.extend(self.search_provider.search(query_entity))
            return targets
        return self.search_provider.search(entity)

    def enrichEntity(self, entity: dict[str, Any]) -> dict[str, Any]:
        resolved, fetched_sources, all_signals = self.resolveEntity(entity), [], []
        existing = self.store.conn.execute("SELECT signal_type, content FROM signals WHERE entity_id=?", (resolved.id,)).fetchall()
        for target in self.searchExternalData(entity):
            try:
                raw = self.fetchSource(target["url"])
                raw["source_type"] = target["source_type"]
            except Exception as exc:  # noqa: BLE001
                LOGGER.warning("fetch failed for %s: %s", target["url"], exc)
                raw = {
                    "source_url": target["url"],
                    "source_type": target["source_type"],
                    "raw_text": json.dumps(
                        {"signals": [{"signal_type": "communication_context", "content": "External retrieval unavailable; cached context placeholder created."}]}
                    ),
                    "fetched_at": datetime.now(timezone.utc).isoformat(),
                }
            raw["entity_type"] = resolved.type
            raw["rental_context"] = resolved.type in RENTAL_ENTITY_TYPES
            sid = self.storeRawSource(resolved.id, raw)
            fetched_sources.append(
                {
                    "url": target["url"],
                    "source_type": target["source_type"],
                    "source_id": sid,
                    "fallback": raw["raw_text"].startswith('{"signals"'),
                }
            )
            verified = self.verifySignals(self.extractSignals(raw), existing)
            freshness = self._freshness_score(raw["fetched_at"])
            for sig in verified:
                sig["source_id"] = sid
                sig["freshness_score"] = freshness
                sig["confidence"] = self.scoreConfidence(sig, target["source_type"])
                sig["decay_rate"] = self.assignDecayRate(sig, target["source_type"])
            all_signals.extend(verified)
            if resolved.type in RENTAL_ENTITY_TYPES and verified:
                self._createRagIntakeReviewItem(resolved, {**raw, "id": sid}, verified)
        packet_id = self.upsertMemoryPacket(resolved.id, all_signals) if all_signals else None
        memory_context = self.getMemoryContext(resolved.id)
        rental_runtime = self.buildRentalRuntimeDrafts(resolved, all_signals)
        review = self.getRagIntakeReview(resolved.id) if resolved.type in RENTAL_ENTITY_TYPES else None
        payload = {
            "entity_id": resolved.id,
            "entity_type": resolved.type,
            "memory_packet_id": packet_id,
            "memory_context": memory_context,
            "rental_runtime": rental_runtime,
            "rag_intake_review": review,
        }
        if self.runtime_hook:
            self.runtime_hook(payload)
        return {
            **payload,
            "fetched_sources": fetched_sources,
            "extracted_signals": all_signals,
            "suggested_next_action": "Use only verified/fresh governed memory signals for reviewed rental acquisition, matching, or GTM prioritization.",
        }


def run_demo(company_name: str, website: str) -> dict[str, Any]:
    return EnrichmentModule(EnrichmentStore()).enrichEntity({"name": company_name, "canonical_url": website, "type": "company"})


__all__ = [
    "BrightDataSearchProvider",
    "PERMISSIONS",
    "ROLE_PERMISSIONS",
    "CONSENT_POLICY",
    "CONSENT_TYPES",
    "DuckDuckGoSearchProvider",
    "ENTITY_TYPES",
    "EnrichmentEntity",
    "EnrichmentModule",
    "EnrichmentStore",
    "ExaSearchProvider",
    "GovernedMemoryPacketInput",
    "GTM_SIGNAL_TYPES",
    "IMPORT_TEMPLATES",
    "IMPORT_TIMING_STATES",
    "LIFECYCLE_STAGES",
    "LIFECYCLE_TRIGGERS",
    "TIMELINE_FILTERS",
    "VERIFICATION_SIGNAL_TYPES",
    "RENTAL_SIGNAL_TYPES",
    "RealEstateRagAdapter",
    "REVIEW_REASONS",
    "SIGNAL_TYPES",
    "SOURCE_TYPES",
    "SOURCE_WEIGHTS",
    "Signal",
    "SearchProvider",
    "SerpAPISearchProvider",
    "TavilySearchProvider",
    "build_search_provider",
    "run_demo",
]
