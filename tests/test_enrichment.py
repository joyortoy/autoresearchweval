from autoresearch.enrichment import (
    ENTITY_TYPES,
    RENTAL_SIGNAL_TYPES,
    EnrichmentModule,
    EnrichmentStore,
    RealEstateRagAdapter,
    SearchProvider,
    build_search_provider,
)


class FakeProvider(SearchProvider):
    def __init__(self, source_type="official_website"):
        self.source_type = source_type
        self.seen_entities = []

    def search(self, entity):
        self.seen_entities.append(entity)
        return [{"url": entity.get("canonical_url") or f"memory://{entity['name']}", "source_type": self.source_type}]


class CompanyEnrichmentModule(EnrichmentModule):
    def fetchSource(self, url: str):
        return {
            "source_url": url,
            "raw_text": '{"signals":[{"signal_type":"hiring_signal","content":"Growing AE headcount."},{"signal_type":"product_launch","content":"Launched AI copilot."}]}',
            "fetched_at": "2026-05-20T00:00:00+00:00",
        }


class TenantEnrichmentModule(EnrichmentModule):
    def fetchSource(self, url: str):
        return {
            "source_url": url,
            "raw_text": "Moving to Singapore in August. Budget S$4k-S$5k. Looking for 2BR condo near MRT in Tanjong Pagar. Family of 3, no pets, 12 months lease. Contact me at tenant@example.com or +65 9123 4567.",
            "fetched_at": "2026-05-20T00:00:00+00:00",
        }


class PropertyEnrichmentModule(EnrichmentModule):
    def fetchSource(self, url: str):
        return {
            "source_url": url,
            "raw_text": "Owner renting 1BR condo in Tanjong Pagar. Rent S$4.2k, available July, fully furnished. Viewing this weekend. Prefer professionals. Address 123 Example Road.",
            "fetched_at": "2026-05-20T00:00:00+00:00",
        }


def signal_types(result):
    return {signal["signal_type"] for signal in result["extracted_signals"]}


def test_existing_company_enrichment_still_passes():
    seen = {}
    module = CompanyEnrichmentModule(EnrichmentStore(), search_provider=FakeProvider(), runtime_hook=lambda payload: seen.update(payload))
    out = module.enrichEntity({"name": "Acme", "canonical_url": "https://acme.test", "type": "company"})
    assert out["memory_packet_id"]
    assert len(out["extracted_signals"]) == 2
    assert all(s["confidence"] >= 0.8 for s in out["extracted_signals"])
    assert seen["memory_packet_id"] == out["memory_packet_id"]


def test_build_search_provider_default():
    provider = build_search_provider()
    assert provider is not None


def test_rental_entity_and_signal_types_are_supported():
    assert {"tenant", "landlord", "property", "area", "source_channel"}.issubset(ENTITY_TYPES)
    assert {"tenant_intent", "landlord_supply", "property_availability", "rental_budget", "risk_signal"}.issubset(RENTAL_SIGNAL_TYPES)


def test_rental_search_queries_are_prepared_not_scraped():
    provider = FakeProvider(source_type="third_party_listing")
    module = EnrichmentModule(EnrichmentStore(), search_provider=provider)
    targets = module.searchExternalData({"name": "Tenant Leads", "type": "source_channel", "acquisition_type": "tenant"})
    assert len(provider.seen_entities) == 5
    assert any("moving to Singapore rental budget" in item["search_query"] for item in provider.seen_entities)
    assert targets[0]["source_type"] == "third_party_listing"


def test_tenant_inquiry_extracts_budget_area_move_in_property_type_without_contact_leakage():
    module = TenantEnrichmentModule(EnrichmentStore(), search_provider=FakeProvider(source_type="whatsapp_message"))
    out = module.enrichEntity({"name": "Tenant lead", "canonical_url": "memory://tenant", "type": "tenant"})
    types = signal_types(out)
    assert {"tenant_intent", "rental_budget", "area_preference", "move_in_timeline", "property_type_preference"}.issubset(types)
    draft_text = str(out["rental_runtime"]["drafts"])
    assert "tenant@example.com" not in draft_text
    assert "+65 9123 4567" not in draft_text
    assert "[redacted-email]" in draft_text
    assert "[redacted-phone]" in draft_text


def test_landlord_ad_extracts_rent_area_availability_furnishing_and_property_packet():
    seen = {}
    module = PropertyEnrichmentModule(EnrichmentStore(), search_provider=FakeProvider(source_type="landlord_ad"), runtime_hook=lambda payload: seen.update(payload))
    out = module.enrichEntity({"name": "Tanjong Pagar 1BR", "canonical_url": "memory://property", "type": "property"})
    types = signal_types(out)
    assert {"landlord_supply", "property_availability", "rental_budget", "area_preference", "furnishing_preference"}.issubset(types)
    assert out["memory_packet_id"]
    assert seen["rental_runtime"]["drafts"][0]["draft_type"] == "Property Profile draft"
    assert "123 Example Road" not in str(seen["rental_runtime"])


def test_extraction_does_not_hallucinate_missing_fields():
    module = EnrichmentModule(EnrichmentStore())
    signals = module.extractSignals({"raw_text": "Hello, just browsing options in Singapore.", "entity_type": "tenant", "rental_context": True})
    assert signals == []


def test_memory_packet_created_for_tenant_intent_and_runtime_hook_emits_draft():
    seen = {}
    module = TenantEnrichmentModule(EnrichmentStore(), search_provider=FakeProvider(source_type="manual_import"), runtime_hook=lambda payload: seen.update(payload))
    out = module.enrichEntity({"name": "Tenant lead", "canonical_url": "memory://tenant", "type": "tenant"})
    assert out["memory_packet_id"]
    assert seen["rental_runtime"]["drafts"][0]["draft_type"] == "Tenant Intent Profile draft"
    assert seen["rental_runtime"]["drafts"][0]["auto_create_final_record"] is False


def test_confidence_decay_and_raw_retrieval_governed_rule_still_work():
    module = TenantEnrichmentModule(EnrichmentStore(), search_provider=FakeProvider(source_type="property_listing"))
    out = module.enrichEntity({"name": "Tenant lead", "canonical_url": "memory://tenant", "type": "tenant"})
    assert all(signal["confidence"] > 0 for signal in out["extracted_signals"])
    assert all(signal["decay_rate"] > 0 for signal in out["extracted_signals"])
    assert "Never answer from retrieval directly" in out["memory_context"]["runtime_rule"]


def test_rag_intake_review_is_collapsed_secondary_admin_section():
    module = TenantEnrichmentModule(EnrichmentStore(), search_provider=FakeProvider(source_type="manual_import"))
    out = module.enrichEntity({"name": "Tenant lead", "canonical_url": "memory://tenant", "type": "tenant"})
    review = out["rag_intake_review"]
    assert review["section_title"] == "RAG Intake Review"
    assert review["collapsed"] is True
    assert review["display"] == "secondary_admin_section"
    assert review["actions"] == ["Approve", "Ignore", "Needs Review"]
    assert review["public_visibility"] is False


def test_llm_extractor_receives_rental_allowed_types_and_validates_output():
    payloads = []

    def extractor(payload):
        payloads.append(payload)
        return [
            {"signal_type": "tenant_intent", "content": "Looking for rental."},
            {"signal_type": "not_allowed", "content": "Should be filtered."},
        ]

    module = EnrichmentModule(EnrichmentStore(), llm_extractor=extractor)
    signals = module.extractSignals({"raw_text": "Looking for rental", "entity_type": "tenant", "rental_context": True})
    assert payloads[0]["allowed_signal_types"] == sorted(RENTAL_SIGNAL_TYPES)
    assert signals == [{"signal_type": "tenant_intent", "content": "Looking for rental."}]


def tenant_text():
    return "Moving to Singapore in August. Budget S$4k-S$5k. Looking for 2BR condo near MRT in Tanjong Pagar. Contact tenant@example.com +65 9123 4567."


def landlord_text():
    return "Owner renting 2BR condo in Tanjong Pagar. Rent S$4.8k, available August, fully furnished. Viewing Sunday. 123 Example Road."


class NoSearchProvider(SearchProvider):
    def search(self, entity):
        raise AssertionError("import-first rental intake must not call search providers or scrape automatically")


def test_import_tenant_inquiry_creates_pending_rag_intake_item_without_auto_scrape():
    module = EnrichmentModule(EnrichmentStore(), search_provider=NoSearchProvider())
    out = module.importTenantInquiryText(tenant_text(), {"source_type": "manual_import", "source_url": "manual://tenant-a"})
    review = module.renderRagIntakeReviewSection()
    assert out["review_item_id"]
    assert review["items"][0]["status"] == "pending"
    assert review["items"][0]["entity_type"] == "tenant"
    assert review["items"][0]["suggested_draft_type"] == "Tenant Intent Profile draft"


def test_import_landlord_ad_creates_pending_rag_intake_item():
    module = EnrichmentModule(EnrichmentStore(), search_provider=NoSearchProvider())
    out = module.importLandlordAdText(landlord_text(), {"source_type": "landlord_ad", "source_url": "manual://property-a"})
    review = module.renderRagIntakeReviewSection()
    assert out["review_item_id"]
    assert review["items"][0]["status"] == "pending"
    assert review["items"][0]["entity_type"] == "property"
    assert review["items"][0]["suggested_draft_type"] == "Property Profile draft"


def test_enrichment_output_becomes_persisted_review_item_and_governed_memory_remains():
    module = EnrichmentModule(EnrichmentStore(), search_provider=NoSearchProvider())
    out = module.importTenantInquiryText(tenant_text(), {"source_type": "manual_import"})
    item = module._load_review_item(out["review_item_id"])
    assert item["status"] == "pending"
    assert out["memory_packet_id"]
    assert "retrieved source -> extracted signal -> verified signal" in out["governed_memory_rule"]


def test_approve_tenant_draft_creates_tenant_intent_draft_and_matching_queue():
    module = EnrichmentModule(EnrichmentStore())
    out = module.importTenantInquiryText(tenant_text(), {"source_type": "manual_import"})
    approved = module.approveRagIntakeItem(out["review_item_id"])
    assert approved["created"]["draft_type"] == "Tenant Intent Profile draft"
    assert approved["created"]["queue_status"] == "Match Now"
    assert module.store.conn.execute("SELECT COUNT(*) AS c FROM tenant_intent_drafts").fetchone()["c"] == 1
    assert module.store.conn.execute("SELECT COUNT(*) AS c FROM matching_queue WHERE draft_type='Tenant Intent Profile draft'").fetchone()["c"] == 1


def test_approve_property_draft_creates_property_profile_draft_and_pool_entry():
    module = EnrichmentModule(EnrichmentStore())
    out = module.importLandlordAdText(landlord_text(), {"source_type": "landlord_ad"})
    approved = module.approveRagIntakeItem(out["review_item_id"])
    assert approved["created"]["draft_type"] == "Property Profile draft"
    assert approved["created"]["queue_status"] == "Property Matching Pool"
    assert module.store.conn.execute("SELECT COUNT(*) AS c FROM property_profile_drafts").fetchone()["c"] == 1


def test_ignored_item_does_not_create_profile_and_needs_review_stores_reason():
    module = EnrichmentModule(EnrichmentStore())
    ignored = module.importTenantInquiryText(tenant_text(), {"source_type": "manual_import"})
    module.ignoreRagIntakeItem(ignored["review_item_id"])
    assert module.store.conn.execute("SELECT COUNT(*) AS c FROM tenant_intent_drafts").fetchone()["c"] == 0
    needs = module.importLandlordAdText(landlord_text(), {"source_type": "landlord_ad"})
    marked = module.markRagIntakeNeedsReview(needs["review_item_id"], "contact_unclear")
    row = module._load_review_item(needs["review_item_id"])
    assert marked["reason"] == "contact_unclear"
    assert row["status"] == "needs_review"
    assert row["review_reason"] == "contact_unclear"


def test_approved_tenant_and_property_enter_queue_without_auto_match_then_explicit_match_recommendation():
    module = EnrichmentModule(EnrichmentStore())
    tenant = module.importTenantInquiryText(tenant_text(), {"source_type": "manual_import"})
    prop = module.importLandlordAdText(landlord_text(), {"source_type": "landlord_ad"})
    approved_tenant = module.approveRagIntakeItem(tenant["review_item_id"])
    approved_prop = module.approveRagIntakeItem(prop["review_item_id"])
    assert approved_tenant["match_recommendations"] == []
    assert approved_prop["match_recommendations"] == []
    assert module.store.conn.execute("SELECT COUNT(*) AS c FROM matching_queue").fetchone()["c"] == 2
    assert module.store.conn.execute("SELECT COUNT(*) AS c FROM match_recommendations").fetchone()["c"] == 0
    recommendations = module.generateMatchRecommendations()
    assert recommendations
    assert module.store.conn.execute("SELECT COUNT(*) AS c FROM match_recommendations").fetchone()["c"] == 1


def test_review_ui_redacts_contact_details_and_stays_collapsed_clean():
    module = EnrichmentModule(EnrichmentStore())
    module.importTenantInquiryText(tenant_text(), {"source_type": "manual_import"})
    review = module.renderRagIntakeReviewSection()
    rendered = str(review)
    assert review["section_title"] == "RAG Intake Review"
    assert review["collapsed"] is True
    assert review["display"] == "secondary_admin_section"
    assert review["analytics_panels"] == []
    assert "tenant@example.com" not in rendered
    assert "+65 9123 4567" not in rendered
    assert "[redacted-email]" in rendered
    assert "[redacted-phone]" in rendered
    assert review["raw_source_trace_public"] is False


def test_no_auto_posting_or_whatsapp_sending_on_approval():
    module = EnrichmentModule(EnrichmentStore())
    out = module.importTenantInquiryText(tenant_text(), {"source_type": "whatsapp_message"})
    approved = module.approveRagIntakeItem(out["review_item_id"])
    assert approved["side_effects"] == {"auto_post": False, "auto_whatsapp_send": False, "auto_match": False}


def test_import_templates_route_to_correct_intake_functions():
    module = EnrichmentModule(EnrichmentStore())
    templates = {template["template"]: template for template in module.getImportTemplates()}
    assert templates["Paste Tenant Inquiry"]["route"] == "importTenantInquiryText"
    assert templates["Paste Landlord Ad"]["route"] == "importLandlordAdText"
    tenant = module.importFromTemplate("Paste Tenant Inquiry", tenant_text())
    landlord = module.importFromTemplate("Paste Landlord Ad", landlord_text())
    forum = module.importFromTemplate("Paste Expat Forum Post", tenant_text())
    listing = module.importFromTemplate("Paste Property Listing", landlord_text())
    assert tenant["entity_type"] == "tenant"
    assert landlord["entity_type"] == "property"
    assert forum["entity_type"] == "tenant"
    assert listing["entity_type"] == "property"


def test_duplicate_source_does_not_create_duplicate_review_card_and_adds_audit_event():
    module = EnrichmentModule(EnrichmentStore())
    first = module.importTenantInquiryText(tenant_text(), {"source_type": "manual_import", "source_url": "manual://dup"})
    second = module.importTenantInquiryText(tenant_text(), {"source_type": "manual_import", "source_url": "manual://dup"})
    assert first["review_item_id"] == second["review_item_id"]
    review = module.renderRagIntakeReviewSection()
    assert len(review["items"]) == 1
    assert module.store.conn.execute("SELECT COUNT(*) AS c FROM rag_intake_audit_events WHERE event_type='duplicate_intake_linked'").fetchone()["c"] == 1


def test_review_priority_labels_for_high_and_low_priority_items():
    module = EnrichmentModule(EnrichmentStore())
    tenant = module.importTenantInquiryText(tenant_text(), {"source_type": "manual_import"})
    prop = module.importLandlordAdText(landlord_text(), {"source_type": "landlord_ad"})
    vague = module.importTenantInquiryText("Just browsing maybe moving someday.", {"source_type": "manual_import", "source_url": "manual://vague"})
    rows = {row["id"]: row for row in module.store.conn.execute("SELECT * FROM rag_intake_review_items").fetchall()}
    assert rows[tenant["review_item_id"]]["priority"] == "high"
    assert rows[prop["review_item_id"]]["priority"] == "high"
    assert rows[vague["review_item_id"]]["priority"] == "low"


def test_structured_review_reasons_and_notes_are_stored_safely():
    module = EnrichmentModule(EnrichmentStore())
    item = module.importTenantInquiryText(tenant_text(), {"source_type": "manual_import"})
    module.ignoreRagIntakeItem(item["review_item_id"], reason="duplicate", notes="same as +65 9123 4567")
    ignored = module._load_review_item(item["review_item_id"])
    assert ignored["review_reason"] == "duplicate"
    assert ignored["review_notes"] == "same as [redacted-phone]"
    item2 = module.importLandlordAdText(landlord_text(), {"source_type": "landlord_ad"})
    module.markRagIntakeNeedsReview(item2["review_item_id"], reason="missing_area", notes="verify 123 Example Road")
    needs = module._load_review_item(item2["review_item_id"])
    assert needs["review_reason"] == "missing_area"
    assert "123 Example Road" not in needs["review_notes"]


def test_review_ui_contract_uses_labels_not_numeric_confidence_or_raw_trace():
    module = EnrichmentModule(EnrichmentStore())
    module.importTenantInquiryText(tenant_text(), {"source_type": "manual_import"})
    card = module.renderRagIntakeReviewSection()["items"][0]
    assert card["confidence_label"] in {"high", "medium", "low"}
    assert card["freshness_label"] in {"fresh", "aging", "stale"}
    assert "confidence" not in card
    assert "freshness" not in card
    assert "decay_rate" not in str(card["extracted_rental_signals"])
    assert "verification_boost" not in str(card["extracted_rental_signals"])
    assert "url" not in card


def test_tenant_queue_with_move_in_budget_area_contact_is_high_priority():
    module = EnrichmentModule(EnrichmentStore())
    queued = module.queueImportSource(tenant_text(), "whatsapp_message")
    assert queued["import_status"] == "queued"
    assert queued["import_priority"] == "high"


def test_landlord_queue_with_rent_area_availability_owner_is_high_priority():
    module = EnrichmentModule(EnrichmentStore())
    queued = module.queueImportSource(landlord_text(), "landlord_ad")
    assert queued["import_status"] == "queued"
    assert queued["import_priority"] == "high"


def test_vague_forum_post_is_medium_or_low_priority():
    module = EnrichmentModule(EnrichmentStore())
    queued = module.queueImportSource("Maybe moving someday, just browsing.", "expat_forum")
    assert queued["import_priority"] in {"medium", "low"}


def test_duplicate_queue_import_updates_last_seen_instead_of_new_source():
    module = EnrichmentModule(EnrichmentStore())
    first = module.queueImportSource(tenant_text(), "manual_import", {"source_url": "manual://same"})
    second = module.queueImportSource(tenant_text(), "manual_import", {"source_url": "manual://same"})
    assert first["source_id"] == second["source_id"]
    assert module.store.conn.execute("SELECT COUNT(*) AS c FROM raw_sources").fetchone()["c"] == 1
    row = module.store.conn.execute("SELECT last_seen_at FROM raw_sources WHERE id=?", (first["source_id"],)).fetchone()
    assert row["last_seen_at"]


def test_stale_property_ad_is_marked_stale_when_availability_has_passed():
    module = EnrichmentModule(EnrichmentStore())
    queued = module.queueImportSource("Owner renting condo in Tanjong Pagar. Rent S$4.8k, available January.", "landlord_ad")
    stale = module.refreshStaleSources()
    assert any(item["source_id"] == queued["source_id"] and item["import_status"] == "stale" for item in stale)


class FailingImportModule(EnrichmentModule):
    def runRentalEnrichmentForSource(self, sourceId: str):
        raise RuntimeError("extractor offline")


def test_failed_import_retries_then_fails():
    module = FailingImportModule(EnrichmentStore())
    queued = module.queueImportSource(tenant_text(), "manual_import")
    assert module.processNextImport()["retry_count"] == 1
    assert module.processNextImport()["retry_count"] == 2
    failed = module.processNextImport()
    assert failed["import_status"] == "failed"
    assert failed["retry_count"] == 3
    row = module.store.conn.execute("SELECT import_status, failure_reason FROM raw_sources WHERE id=?", (queued["source_id"],)).fetchone()
    assert row["import_status"] == "failed"
    assert "extractor offline" in row["failure_reason"]


def test_process_next_import_creates_review_item_and_timing_section_is_collapsed():
    module = EnrichmentModule(EnrichmentStore())
    queued = module.queueImportSource(tenant_text(), "manual_import")
    processed = module.processNextImport()
    assert processed["review_item_id"]
    row = module.store.conn.execute("SELECT import_status FROM raw_sources WHERE id=?", (queued["source_id"],)).fetchone()
    assert row["import_status"] == "review_ready"
    review = module.renderRagIntakeReviewSection()
    assert review["import_timing"]["section_title"] == "Import Timing"
    assert review["import_timing"]["collapsed"] is True
    assert review["import_timing"]["analytics_panels"] == []


def test_high_priority_imports_returns_only_high_priority_sources():
    module = EnrichmentModule(EnrichmentStore())
    high = module.queueImportSource(tenant_text(), "manual_import")
    module.queueImportSource("Just browsing maybe.", "expat_forum", {"source_url": "manual://low"})
    high_priority = module.getHighPriorityImports()
    assert [item["id"] for item in high_priority] == [high["source_id"]]


def test_verification_requires_consent_before_signals_are_recorded():
    module = EnrichmentModule(EnrichmentStore())
    verification = module.createPersonVerification("tenant-1", "tenant", phone="+65 9000 1111", email="t@example.com")
    blocked = module.addVerificationSignal(
        verification["id"],
        {"signalType": "phone_reachable", "result": "pass", "confidence": "high", "source": "provider_stub", "publicSafe": False},
    )
    assert blocked == {"verificationId": verification["id"], "accepted": False, "reason": "consent_required"}
    assert module.store.conn.execute("SELECT COUNT(*) AS c FROM verification_signals").fetchone()["c"] == 0


def test_phone_email_are_hashed_for_duplicate_detection_and_not_raw():
    module = EnrichmentModule(EnrichmentStore())
    verification = module.createPersonVerification("tenant-2", "tenant", phone="+65 9000 2222", email="hash@example.com")
    row = module.store.conn.execute("SELECT phone_hash, email_hash FROM person_verifications WHERE id=?", (verification["id"],)).fetchone()
    assert row["phone_hash"]
    assert row["email_hash"]
    assert "+65 9000 2222" not in str(dict(row))
    assert "hash@example.com" not in str(dict(row))
    duplicate = module.checkDuplicateContact("hash@example.com")
    assert duplicate["duplicate"] is True


def test_duplicate_contact_creates_review_flag_after_consent():
    module = EnrichmentModule(EnrichmentStore())
    module.createPersonVerification("tenant-a", "tenant", phone="+65 9000 3333")
    verification = module.createPersonVerification("tenant-b", "tenant", phone="+65 9000 3333")
    module.recordVerificationConsent("tenant-b", True)
    duplicate = module.checkDuplicateContact("+65 9000 3333", verification["id"])
    status = module.evaluateVerificationStatus(verification["id"])
    assert duplicate["duplicate"] is True
    assert status["verificationStatus"] == "review_required"


def test_verified_document_signals_create_verified_status():
    module = EnrichmentModule(EnrichmentStore())
    verification = module.createPersonVerification("tenant-doc", "tenant")
    module.requestVerificationConsent("tenant-doc", "tenant")
    module.recordVerificationConsent("tenant-doc", True)
    module.addVerificationSignal(verification["id"], {"signalType": "identity_document_submitted", "result": "pass", "confidence": "high", "source": "document_check", "publicSafe": False})
    result = module.addVerificationSignal(verification["id"], {"signalType": "identity_document_matches_name", "result": "pass", "confidence": "high", "source": "document_check", "publicSafe": False})
    assert result["verificationStatus"] == "verified"


def test_scam_pattern_creates_review_required_status():
    module = EnrichmentModule(EnrichmentStore())
    verification = module.createPersonVerification("landlord-risk", "landlord")
    module.recordVerificationConsent("landlord-risk", True)
    result = module.addVerificationSignal(verification["id"], {"signalType": "scam_pattern_detected", "result": "review_required", "confidence": "high", "source": "platform_history", "publicSafe": False})
    assert result["verificationStatus"] == "review_required"


def test_public_verification_summary_does_not_expose_contact_or_score():
    module = EnrichmentModule(EnrichmentStore())
    verification = module.createPersonVerification("tenant-public", "tenant", phone="+65 9000 4444", email="public@example.com")
    summary = module.getInternalVerificationSummary("tenant-public")
    public = module.sanitizeVerificationForPublic(summary)
    assert public["label"] == "Verification pending"
    assert "+65 9000 4444" not in str(public)
    assert "public@example.com" not in str(public)
    assert "score" not in str(public).lower()
    assert "phoneHash" not in public
    assert "emailHash" not in public


def test_matching_uses_verification_status_internally_without_public_score():
    module = EnrichmentModule(EnrichmentStore())
    tenant = module.importTenantInquiryText(tenant_text(), {"source_type": "manual_import"})
    prop = module.importLandlordAdText(landlord_text(), {"source_type": "landlord_ad"})
    verification = module.createPersonVerification(tenant["entity_id"], "tenant")
    module.recordVerificationConsent(tenant["entity_id"], True)
    module.addVerificationSignal(verification["id"], {"signalType": "manual_review_required", "result": "review_required", "confidence": "high", "source": "manual_review", "publicSafe": False})
    module.approveRagIntakeItem(tenant["review_item_id"])
    module.approveRagIntakeItem(prop["review_item_id"])
    rec = module.generateMatchRecommendations()[0]
    assert rec["verificationSafetyInput"]["requiresManualReview"] is True
    assert "score" not in str(rec).lower()


def test_denied_consent_does_not_run_verification():
    module = EnrichmentModule(EnrichmentStore())
    verification = module.createPersonVerification("tenant-denied", "tenant")
    module.recordVerificationConsent("tenant-denied", False)
    blocked = module.addVerificationSignal(verification["id"], {"signalType": "email_reachable", "result": "pass", "confidence": "high", "source": "provider_stub", "publicSafe": False})
    assert blocked["reason"] == "consent_required"
    summary = module.getInternalVerificationSummary("tenant-denied")
    assert summary["consentStatus"] == "denied"
    assert summary["verificationStatus"] == "unverified"


def test_person_verification_publishes_governed_memory_for_matching_boundary():
    module = EnrichmentModule(EnrichmentStore())
    verification = module.createPersonVerification("tenant-memory", "tenant", phone="+65 9000 5555")
    module.recordVerificationConsent("tenant-memory", True)
    module.addVerificationSignal(
        verification["id"],
        {"signalType": "manual_review_required", "result": "review_required", "confidence": "high", "source": "manual_review", "publicSafe": False},
    )
    memory = module.getMemoryContext("tenant-memory")
    verification_signals = [signal for signal in memory["signals"] if signal["signal_type"] == "verification_need"]
    assert verification_signals
    assert verification_signals[0]["verification_status"] == "review_required"
    assert module.getMatchingSafetyFromMemory("tenant-memory")["requiresManualReview"] is True


def test_approved_rag_intake_marks_memory_as_approved_before_matching():
    module = EnrichmentModule(EnrichmentStore())
    tenant = module.importTenantInquiryText(tenant_text(), {"source_type": "manual_import"})
    before = module.store.conn.execute("SELECT DISTINCT status FROM memory_packets WHERE entity_id=?", (tenant["entity_id"],)).fetchall()
    assert {row["status"] for row in before} == {"active"}
    module.approveRagIntakeItem(tenant["review_item_id"])
    after = module.store.conn.execute("SELECT DISTINCT status FROM memory_packets WHERE entity_id=?", (tenant["entity_id"],)).fetchall()
    assert {row["status"] for row in after} == {"approved"}


def memory_os_packet(**overrides):
    packet = {
        "packetId": "packet-1",
        "entityId": "tenant-123",
        "entityType": "tenant",
        "summary": "Tenant wants 2BR near MRT. Email tenant@example.com, phone +65 9555 1212. Avoid bad tenant labels.",
        "signals": [
            {
                "signalType": "rental_budget",
                "content": "Budget S$4k-S$5k near 123 Example Road. Contact tenant@example.com",
                "confidence": 0.86,
                "freshness": 0.9,
                "verificationStatus": "verified",
                "sourceType": "manual_import",
                "observedAt": "2026-06-01T00:00:00+00:00",
                "expiresAt": "2026-08-01T00:00:00+00:00",
            },
            {
                "signalType": "viewing_intent",
                "content": "Asked to view this weekend.",
                "confidence": 0.8,
                "freshness": 0.9,
                "verificationStatus": "verified",
                "sourceType": "manual_import",
                "observedAt": "2026-06-01T00:00:00+00:00",
                "expiresAt": "2026-08-01T00:00:00+00:00",
            },
        ],
        "confidence": 0.84,
        "freshness": 0.9,
        "verificationStatus": "verified",
        "sensitivityLevel": "internal",
        "sourceTrace": {"sourceUrl": "internal://raw-source/secret", "rawText": "tenant@example.com +65 9555 1212"},
        "approvedForUse": True,
        "createdAt": "2026-06-01T00:00:00+00:00",
        "updatedAt": "2026-06-01T00:00:00+00:00",
    }
    packet.update(overrides)
    return packet


def test_approved_packet_imports_into_memory_os_and_creates_event():
    store = EnrichmentStore()
    adapter = RealEstateRagAdapter(store)
    result = adapter.importPacketToMemoryOs(memory_os_packet())
    assert result["imported"] is True
    events = store.listRagEnrichmentEvents(result["leadId"])
    assert len(events) == 1
    assert events[0]["packetId"] == "packet-1"
    assert events[0]["status"] == "imported"


def test_unapproved_packet_is_rejected_and_stale_packet_ignored_by_default():
    adapter = RealEstateRagAdapter(EnrichmentStore())
    assert adapter.importPacketToMemoryOs(memory_os_packet(approvedForUse=False))["imported"] is False
    stale = memory_os_packet(freshness=0.1, signals=[{**memory_os_packet()["signals"][0], "expiresAt": "2026-01-01T00:00:00+00:00"}])
    assert adapter.importPacketToMemoryOs(stale)["imported"] is False


def test_private_contact_details_redacted_and_source_trace_internal_only():
    store = EnrichmentStore()
    adapter = RealEstateRagAdapter(store)
    imported = adapter.importPacketToMemoryOs(memory_os_packet())
    event = store.listRagEnrichmentEvents(imported["leadId"])[0]
    rendered = adapter.getLeadWorkspaceExternalContext(imported["leadId"])
    assert "tenant@example.com" not in str(event["suggestedNotes"])
    assert "+65 9555 1212" not in str(event["suggestedNotes"])
    assert "sourceTrace" in event["auditTrace"]
    assert "rawText" in event["auditTrace"]["sourceTrace"]
    assert "sourceTrace" not in str(rendered)
    assert "tenant@example.com" not in str(rendered)
    assert "+65 9555 1212" not in str(rendered)
    assert "bad tenant" not in str(rendered).lower()


def test_signals_map_to_relationship_notes_tasks_and_calendar_drafts():
    adapter = RealEstateRagAdapter(EnrichmentStore())
    packet = memory_os_packet()
    relationship = adapter.mapSignalsToRelationshipMemory(packet)
    notes = adapter.mapSignalsToLeadNotes(packet)
    tasks = adapter.mapSignalsToTasks(packet)
    calendars = adapter.mapSignalsToCalendarDrafts(packet)
    assert relationship[0]["overwriteExisting"] is False
    assert any("rental_budget" in note for note in notes)
    assert any(task["title"] == "Schedule approved viewing follow-up" for task in tasks)
    assert calendars and calendars[0]["autoCreate"] is False


def test_work_queue_clean_external_context_collapsed_and_scoring_engines_preserved():
    store = EnrichmentStore()
    adapter = RealEstateRagAdapter(store)
    imported = adapter.importPacketToMemoryOs(memory_os_packet())
    work_queue = adapter.getTodaysWorkQueuePayload(imported["leadId"])
    external = adapter.getLeadWorkspaceExternalContext(imported["leadId"])
    assert work_queue["rag_panel"] is None
    assert work_queue["external_context_collapsed"] is True
    assert work_queue["scoring_control"]["close_probability_engine"] == "existing_close_probability_engine"
    assert work_queue["scoring_control"]["deal_risk_engine"] == "existing_deal_risk_engine"
    assert work_queue["scoring_control"]["rag_replaces_scoring"] is False
    assert work_queue["memory_priority"] == ["user_agent_provided_memory", "verified_internal_memory", "rag_enrichment"]
    assert external["section_title"] == "External Context"
    assert external["collapsed"] is True
    assert "confidence" not in str(external["items"][0]).replace("confidenceLabel", "")


def test_agent_entered_memory_priority_and_ignored_event_not_used():
    store = EnrichmentStore()
    adapter = RealEstateRagAdapter(store)
    imported = adapter.importPacketToMemoryOs(memory_os_packet())
    context = store.getRagContextForLead(imported["leadId"])
    assert context["memoryPriority"][0] == "user_agent_provided_memory"
    ignored = store.ignoreRagEnrichmentEvent(imported["eventId"], "not_useful")
    assert ignored["status"] == "ignored"
    assert store.getRagContextForLead(imported["leadId"])["events"] == []


def test_tenant_intake_blocked_without_data_storage_consent():
    module = EnrichmentModule(EnrichmentStore())
    result = module.importTenantInquiryText(tenant_text(), {"person_id": "tenant-consent-1", "source_type": "whatsapp_message"})
    assert result["blocked"] is True
    assert result["stored_profile"] is False
    assert "stored and used to match you" in result["consentNotice"]["noticeText"]
    assert result["consentRequestDraft"]["autoSend"] is False


def test_landlord_intake_blocked_without_data_storage_consent():
    module = EnrichmentModule(EnrichmentStore())
    result = module.importLandlordAdText(landlord_text(), {"person_id": "landlord-consent-1", "source_type": "landlord_ad"})
    assert result["blocked"] is True
    assert result["stored_profile"] is False
    assert "property, contact, communication" in result["consentNotice"]["noticeText"]


def test_accepting_consent_allows_intake_and_audit_trail_is_stored():
    module = EnrichmentModule(EnrichmentStore())
    module.recordConsentAcceptance("tenant-consent-2", ["data_storage", "matching"], "website", {"personType": "tenant", "ipAddress": "127.0.0.1"})
    result = module.importTenantInquiryText(tenant_text(), {"person_id": "tenant-consent-2", "source_type": "manual_import"})
    assert result["review_item_id"]
    status = module.getConsentStatus("tenant-consent-2")
    assert status["profileCreationAllowed"] is True
    trail = module.getConsentAuditTrail("tenant-consent-2")
    assert trail[0]["ipAddress"] == "127.0.0.1"


def test_declined_and_withdrawn_consent_blocks_profile_creation_and_future_processing():
    module = EnrichmentModule(EnrichmentStore())
    module.recordConsentDecline("tenant-consent-3", ["data_storage"], "website", {"personType": "tenant"})
    declined = module.importTenantInquiryText(tenant_text(), {"person_id": "tenant-consent-3", "source_type": "manual_import"})
    assert declined["profileCreationAllowed"] is False
    module.recordConsentAcceptance("tenant-consent-3", ["data_storage"], "website", {"personType": "tenant"})
    module.withdrawConsent("tenant-consent-3", "data_storage")
    withdrawn = module.importTenantInquiryText(tenant_text(), {"person_id": "tenant-consent-3", "source_type": "manual_import"})
    assert withdrawn["blocked"] is True


def test_verification_blocked_without_privacy_layer_verification_consent():
    module = EnrichmentModule(EnrichmentStore())
    verification = module.createPersonVerification("tenant-verify-consent", "tenant")
    blocked = module.addVerificationSignal(verification["id"], {"signalType": "phone_reachable", "result": "pass", "confidence": "high"})
    assert blocked["accepted"] is False
    assert blocked["reason"] == "consent_required"


def test_bot_relay_blocked_without_bot_communication_consent_and_draft_generated():
    module = EnrichmentModule(EnrichmentStore())
    module.recordConsentAcceptance("tenant-bot-1", ["data_storage"], "whatsapp", {"personType": "tenant"})
    result = module.relayBotMessage("tenant-bot-1", "tenant", "Hello +65 9000 0000")
    assert result["relayed"] is False
    assert "bot_communication" in result["missingConsent"]
    assert "Reply YES to continue" in result["consentRequestDraft"]["message"]


def test_rag_import_with_identifiable_personal_data_requires_consent_basis_and_review_shows_status():
    module = EnrichmentModule(EnrichmentStore())
    result = module.importManualRentalSource("Tenant looking in Singapore. Contact me at person@example.com or +65 9888 7777", "manual_import")
    assert result["status"] == "needs_review"
    assert result["profileCreationAllowed"] is False
    review = module.getRagIntakeReview()["items"][0]
    assert review["status"] == "needs_review"
    assert review["profile_creation_allowed"] is False
    assert review["blocked_reason"] == "missing_data_storage_consent"
    assert "person@example.com" not in review["short_preview"]
    assert "+65 9888 7777" not in review["short_preview"]


def test_consent_privacy_section_and_public_score_absence():
    module = EnrichmentModule(EnrichmentStore())
    module.createConsentNotice("tenant", ["data_storage"], "tenant-pending", "website")
    section = module.getConsentPrivacySection()
    assert section["section_title"] == "Consent & Privacy"
    assert section["collapsed"] is True
    assert section["public_visibility"] is False
    assert "score" not in str(section).lower()


def test_privacy_request_placeholders_exist():
    module = EnrichmentModule(EnrichmentStore())
    for request_type in ["data_access", "data_correction", "data_deletion", "consent_withdrawal"]:
        module.createPrivacyRequestPlaceholder("tenant-privacy", request_type)
    requests = module.listPrivacyRequestPlaceholders("tenant-privacy")
    assert {item["request_type"] for item in requests} == {"data_access", "data_correction", "data_deletion", "consent_withdrawal"}


def seed_reply_draft(module):
    module.store.conn.execute(
        """
        INSERT INTO reply_drafts
        (id, original_message_preview, detected_intent, extracted_slots, memory_used_summary, draft_reply, risk_flags, status, created_at, updated_at)
        VALUES ('reply-1', ?, 'tenant_inquiry', ?, ?, ?, ?, 'pending', '2026-06-01T00:00:00+00:00', '2026-06-01T00:00:00+00:00')
        """,
        (
            "Hi, my email is reply@example.com and phone +65 9000 9999. Looking near MRT.",
            '{"area":"Tanjong Pagar","budget":"S$4k"}',
            "Used tenant governed memory from packet; raw source trace internal://secret",
            "Thanks, we can help. Please confirm consent before we continue. Contact +65 9000 9999",
            '["manual_review_required"]',
        ),
    )
    module.store.conn.commit()


def test_admin_ui_sections_render_collapsed_and_dashboard_clean():
    module = EnrichmentModule(EnrichmentStore())
    seed_reply_draft(module)
    module.createConsentNotice("tenant", ["data_storage"], "tenant-ui", "website")
    ui = module.renderRentalAdminUI()
    assert ui["main_dashboard"]["primary_workflow"] == ["Match Now", "Waiting / Not Ready", "At Risk", "Tenancy Activation", "Renewal Queue"]
    assert ui["main_dashboard"]["rag_panel"] is None
    assert ui["main_dashboard"]["analytics_panels"] == []
    assert ui["secondary_sections"]["rag_intake_review"]["collapsed"] is True
    assert ui["secondary_sections"]["rag_intake_review"]["import_timing"]["collapsed"] is True
    assert ui["secondary_sections"]["reply_drafts"]["collapsed"] is True
    assert ui["secondary_sections"]["consent_privacy"]["collapsed"] is True
    assert ui["side_effects"] == {"auto_scrape": False, "auto_post": False, "auto_whatsapp_send": False}


def test_reply_drafts_render_privacy_safe_and_actions_exist():
    module = EnrichmentModule(EnrichmentStore())
    seed_reply_draft(module)
    section = module.renderReplyDraftsSection()
    assert section["section_title"] == "Reply Drafts"
    assert section["actions"] == ["Approve", "Edit", "Ignore", "Mark Posted Manually"]
    rendered = str(section)
    assert "reply@example.com" not in rendered
    assert "+65 9000 9999" not in rendered
    assert "raw source trace" not in rendered.lower()
    assert "internal://secret" not in rendered
    assert "Manual review required" in rendered
    assert section["auto_post"] is False
    assert section["auto_send"] is False


def test_rag_intake_review_admin_renders_buttons_consent_block_and_redaction():
    module = EnrichmentModule(EnrichmentStore())
    module.importManualRentalSource("Tenant email person@example.com phone +65 9888 7777 looking in Singapore", "manual_import")
    section = module.renderRagIntakeReviewAdminSection()
    assert section["collapsed"] is True
    assert section["actions"] == ["Approve", "Ignore", "Needs Review"]
    item = section["items"][0]
    assert item["blocked_reason"] == "missing_data_storage_consent"
    assert item["profile_creation_allowed"] is False
    assert item["actions"] == ["Approve", "Ignore", "Needs Review"]
    rendered = str(section)
    assert "person@example.com" not in rendered
    assert "+65 9888 7777" not in rendered


def test_import_timing_admin_shows_only_high_delayed_stale_failed():
    module = EnrichmentModule(EnrichmentStore())
    high = module.queueImportSource(tenant_text(), "manual_import", {"source_url": "manual://ui-high"})
    low = module.queueImportSource("Just browsing someday.", "expat_forum", {"source_url": "manual://ui-low"})
    module.markImportDelayed(low["source_id"], "2099-01-01T00:00:00+00:00")
    section = module.renderImportTimingSection()
    ids = {item.get("import_status") for item in section["items"]}
    assert section["collapsed"] is True
    assert "queued" in ids or "delayed" in ids
    assert all(item["import_priority"] == "high" or item["import_status"] in {"delayed", "stale", "failed"} for item in section["items"])


def test_external_context_collapsed_privacy_safe_and_actions():
    store = EnrichmentStore()
    adapter = RealEstateRagAdapter(store)
    imported = adapter.importPacketToMemoryOs(memory_os_packet())
    module = EnrichmentModule(store)
    section = module.renderExternalContextSection(imported["leadId"])
    assert section["section_title"] == "External Context"
    assert section["collapsed"] is True
    assert section["actions"] == ["Use in Note", "Create Task", "Ignore"]
    rendered = str(section)
    assert "tenant@example.com" not in rendered
    assert "+65 9555 1212" not in rendered
    assert "sourceTrace" not in rendered


def test_admin_action_handlers_call_existing_backend_methods():
    module = EnrichmentModule(EnrichmentStore())
    seed_reply_draft(module)
    assert module.approveReplyDraft("reply-1")["status"] == "approved"
    assert module.markReplyDraftNeedsReview("reply-1")["status"] == "needs_review"
    assert module.ignoreReplyDraft("reply-1")["status"] == "ignored"
    assert module.markReplyDraftPostedManually("reply-1")["status"] == "posted_manually"
    result = module.importTenantInquiryText(tenant_text(), {"source_type": "manual_import"})
    assert module.markRagIntakeNeedsReview(result["review_item_id"], "other")["status"] == "needs_review"
    assert module.ignoreRagIntakeItem(result["review_item_id"], "other")["status"] == "ignored"


def test_external_context_action_handlers_use_store_methods():
    store = EnrichmentStore()
    adapter = RealEstateRagAdapter(store)
    imported = adapter.importPacketToMemoryOs(memory_os_packet())
    module = EnrichmentModule(store)
    assert module.markRagEnrichmentUsed(imported["eventId"])["status"] == "used"
    assert module.ignoreRagEnrichmentEvent(imported["eventId"], "not_useful")["status"] == "ignored"


def test_admin_ui_empty_states_and_count_badges_render():
    module = EnrichmentModule(EnrichmentStore())
    ui = module.renderRentalAdminUI(role="readonly")
    rag = ui["secondary_sections"]["rag_intake_review"]
    reply = ui["secondary_sections"]["reply_drafts"]
    consent = ui["secondary_sections"]["consent_privacy"]
    assert rag["count_badge"] == 0
    assert rag["empty_state"]
    assert rag["import_timing"]["count_badge"] == 0
    assert reply["count_badge"] == 0
    assert reply["empty_state"]
    assert consent["count_badge"] == 0
    assert consent["empty_state"]


def test_role_gating_readonly_reviewer_operator_admin():
    low_module = EnrichmentModule(EnrichmentStore())
    low_module.importTenantInquiryText("Looking for room Singapore", {"source_type": "manual_import"})
    readonly_item = low_module.renderRagIntakeReviewAdminSection(role="readonly")["items"][0]
    operator_item = low_module.renderRagIntakeReviewAdminSection(role="operator")["items"][0]
    assert readonly_item["action_buttons"][0]["enabled"] is False
    assert operator_item["risk_level"] == "low"
    assert operator_item["action_buttons"][0]["enabled"] is True

    high_module = EnrichmentModule(EnrichmentStore())
    high_module.importManualRentalSource("Tenant email person@example.com phone +65 9888 7777 looking in Singapore", "manual_import")
    reviewer_item = high_module.renderRagIntakeReviewAdminSection(role="reviewer")["items"][0]
    admin_item = high_module.renderRagIntakeReviewAdminSection(role="admin")["items"][0]
    assert reviewer_item["risk_level"] == "high"
    assert reviewer_item["action_buttons"][0]["enabled"] is False
    assert admin_item["action_buttons"][0]["enabled"] is True
    assert admin_item["action_buttons"][0]["confirmation"]["confirmationRequired"] is True


def test_reply_draft_editing_sanitizes_and_stores_history():
    module = EnrichmentModule(EnrichmentStore())
    seed_reply_draft(module)
    result = module.editReplyDraft("reply-1", "Thanks, we can help with rentals near MRT.", "clean copy", "operator-a")
    assert result["status"] == "edited"
    assert result["validation"]["isValid"] is True
    history = module.getReplyDraftEditHistory("reply-1")
    assert len(history) == 1
    assert history[0]["editedBy"] == "operator-a"
    assert history[0]["editedDraftText"] == "Thanks, we can help with rentals near MRT."
    assert result["autoPost"] is False
    assert result["autoSend"] is False


def test_reply_draft_edit_with_contact_or_guarantee_is_flagged():
    module = EnrichmentModule(EnrichmentStore())
    seed_reply_draft(module)
    result = module.editReplyDraft("reply-1", "Guaranteed housing. Contact me at agent@example.com or +65 9888 0000.", "bad copy", "operator-a")
    assert result["status"] == "needs_review"
    assert result["validation"]["isValid"] is False
    assert "contact_detail" in result["validation"]["violations"]
    assert "guaranteed_housing_claim" in result["validation"]["violations"]
    assert "agent@example.com" not in result["validation"]["sanitizedText"]
    assert "+65 9888 0000" not in result["validation"]["sanitizedText"]


def test_confirmation_metadata_for_sensitive_actions():
    module = EnrichmentModule(EnrichmentStore())
    posted = module.actionConfirmationMetadata("mark_posted_manually", "reply-1", "medium")
    withdrawn = module.actionConfirmationMetadata("withdraw_consent", "consent-1", "medium")
    external = module.actionConfirmationMetadata("use_external_context_in_note", "event-1", "medium", sensitivity="high")
    assert posted["confirmationRequired"] is True
    assert withdrawn["confirmationRequired"] is True
    assert external["confirmationRequired"] is True


def test_no_private_data_or_bad_labels_in_polished_admin_ui():
    module = EnrichmentModule(EnrichmentStore())
    seed_reply_draft(module)
    module.importManualRentalSource("Tenant bad tenant email person@example.com phone +65 9888 7777 at 123 Example Road", "manual_import")
    ui = module.renderRentalAdminUI(role="admin")
    rendered = str(ui).lower()
    assert "person@example.com" not in rendered
    assert "+65 9888 7777" not in rendered
    assert "123 example road" not in rendered
    assert "bad tenant" not in rendered
    assert "blacklisted" not in rendered
    assert ui["side_effects"] == {"auto_scrape": False, "auto_post": False, "auto_whatsapp_send": False}


def test_rbac_tables_seed_roles_permissions_and_login_logout_audit():
    module = EnrichmentModule(EnrichmentStore())
    role_count = module.store.conn.execute("SELECT COUNT(*) AS c FROM roles").fetchone()["c"]
    permission_count = module.store.conn.execute("SELECT COUNT(*) AS c FROM permissions").fetchone()["c"]
    assert role_count >= 5
    assert permission_count >= 10
    module.createUser("admin-user", "pw", "admin")
    login = module.login("admin-user", "pw")
    assert login["authenticated"] is True
    assert module.getUserRole(login["sessionToken"]) == "admin"
    assert module.hasPermission(login["sessionToken"], "approve_rag_intake") is True
    assert module.hasPermission(login["sessionToken"], "manage_users") is False
    module.logout(login["sessionToken"])
    assert module.getSessionUser(login["sessionToken"]) is None
    assert any(event["event_type"] == "login" for event in module.getAuthAuditLog())


def test_readonly_session_cannot_approve_rag_intake():
    module = EnrichmentModule(EnrichmentStore())
    module.createUser("readonly-user", "pw", "readonly")
    token = module.login("readonly-user", "pw")["sessionToken"]
    result = module.importTenantInquiryText("Looking for room Singapore", {"source_type": "manual_import"})
    denied = module.approveRagIntakeItem(result["review_item_id"], sessionToken=token)
    assert denied["allowed"] is False
    assert denied["reason"] == "permission_denied"


def test_operator_can_approve_low_risk_but_not_high_risk_item():
    module = EnrichmentModule(EnrichmentStore())
    module.createUser("operator-user", "pw", "operator")
    token = module.login("operator-user", "pw")["sessionToken"]
    low = module.importTenantInquiryText("Looking for room Singapore", {"source_type": "manual_import"})
    assert module.approveRagIntakeItem(low["review_item_id"], sessionToken=token)["status"] == "approved"
    high = module.importTenantInquiryText(tenant_text(), {"source_type": "manual_import", "source_url": "manual://rbac-high"})
    denied = module.approveRagIntakeItem(high["review_item_id"], sessionToken=token)
    assert denied["allowed"] is False
    assert denied["permission"] == "approve_high_risk_item"


def test_admin_can_approve_high_risk_and_reviewer_can_only_review_or_ignore():
    module = EnrichmentModule(EnrichmentStore())
    module.createUser("admin-rbac", "pw", "admin")
    module.createUser("reviewer-rbac", "pw", "reviewer")
    admin_token = module.login("admin-rbac", "pw")["sessionToken"]
    reviewer_token = module.login("reviewer-rbac", "pw")["sessionToken"]
    high = module.importTenantInquiryText(tenant_text(), {"source_type": "manual_import", "source_url": "manual://admin-high"})
    denied = module.approveRagIntakeItem(high["review_item_id"], sessionToken=reviewer_token)
    assert denied["allowed"] is False
    assert module.markRagIntakeNeedsReview(high["review_item_id"], "other", sessionToken=reviewer_token)["status"] == "needs_review"
    assert module.approveRagIntakeItem(high["review_item_id"], sessionToken=admin_token)["status"] == "approved"


def test_reply_draft_actions_enforce_permissions():
    module = EnrichmentModule(EnrichmentStore())
    seed_reply_draft(module)
    module.createUser("reviewer-reply", "pw", "reviewer")
    module.createUser("admin-reply", "pw", "admin")
    reviewer_token = module.login("reviewer-reply", "pw")["sessionToken"]
    admin_token = module.login("admin-reply", "pw")["sessionToken"]
    denied_edit = module.editReplyDraft("reply-1", "Clean reply", "copy", "reviewer", sessionToken=reviewer_token)
    assert denied_edit["allowed"] is False
    assert denied_edit["permission"] == "edit_reply_draft"
    assert module.editReplyDraft("reply-1", "Clean reply", "copy", "admin", sessionToken=admin_token)["status"] == "edited"
    denied_post = module.markReplyDraftPostedManually("reply-1", sessionToken=reviewer_token)
    assert denied_post["allowed"] is False
    assert module.markReplyDraftPostedManually("reply-1", sessionToken=admin_token)["status"] == "posted_manually"


def test_withdraw_consent_enforces_permission_and_super_admin_can_manage_users():
    module = EnrichmentModule(EnrichmentStore())
    module.createUser("readonly-consent", "pw", "readonly")
    module.createUser("admin-consent", "pw", "admin")
    readonly_token = module.login("readonly-consent", "pw")["sessionToken"]
    admin_token = module.login("admin-consent", "pw")["sessionToken"]
    module.recordConsentAcceptance("tenant-rbac", ["data_storage"], "website", {"personType": "tenant"})
    denied = module.withdrawConsent("tenant-rbac", "data_storage", sessionToken=readonly_token)
    assert denied["allowed"] is False
    assert module.withdrawConsent("tenant-rbac", "data_storage", sessionToken=admin_token)["status"] == "withdrawn"
    module.createUser("super-user", "pw", "super_admin")
    super_token = module.login("super-user", "pw")["sessionToken"]
    created = module.createUser("managed-user", "pw", "readonly", actorSessionToken=super_token)
    assert created["role"] == "readonly"


def test_whatsapp_conversation_tables_exist_and_create_conversation_attaches_memory_identity():
    module = EnrichmentModule(EnrichmentStore())
    conversation = module.createConversation("tenant-42", "tenant", tenancyId="tenancy-1", propertyId="property-1")
    assert conversation["participantId"] == "tenant-42"
    assert conversation["participantType"] == "tenant"
    assert conversation["tenancyId"] == "tenancy-1"
    assert conversation["propertyId"] == "property-1"
    assert module.store.conn.execute("SELECT COUNT(*) AS c FROM conversations").fetchone()["c"] == 1
    assert module.store.conn.execute("SELECT type FROM entities WHERE id='tenant-42'").fetchone()["type"] == "tenant"


def test_add_conversation_message_sanitizes_private_contact_data_and_records_memory_event():
    module = EnrichmentModule(EnrichmentStore())
    conversation = module.createConversation("tenant-77", "tenant", tenancyId="tenancy-7")
    message = module.addConversationMessage(
        conversation["conversationId"],
        sender="tenant",
        content="My email is tenant@example.com and phone is +65 9888 7777. Budget 4200 near Orchard.",
        attachments=[{"name": "tenant@example.com screenshot.png", "type": "image"}],
    )
    rendered = str(message)
    assert "tenant@example.com" not in rendered
    assert "+65 9888 7777" not in rendered
    assert "email_redacted" in message["privacyFlags"]
    assert "phone_redacted" in message["privacyFlags"]
    assert message["sideEffects"] == {"autoSend": False, "autoReply": False, "autoPost": False}
    assert module.store.conn.execute("SELECT COUNT(*) AS c FROM conversation_memory_events").fetchone()["c"] == 1


def test_conversation_history_and_timeline_are_sanitized_and_attach_to_property():
    module = EnrichmentModule(EnrichmentStore())
    conversation = module.createConversation("landlord-1", "landlord")
    module.attachConversationToProperty(conversation["conversationId"], "property-88")
    module.addConversationMessage(
        conversation["conversationId"],
        sender="landlord",
        content="Unit at 123 Example Road is available July. Rent $4200. Reach me at owner@example.com.",
    )
    history = module.getConversationHistory(conversation["conversationId"], includePrivate=True)
    rendered = str(history)
    assert "owner@example.com" not in rendered
    assert "123 Example Road" not in rendered
    assert history["propertyId"] == "property-88"
    timeline = module.getConversationTimeline(propertyId="property-88")
    assert len(timeline["timeline"]) == 1
    assert "owner@example.com" not in str(timeline)
    assert timeline["sideEffects"] == {"autoSend": False, "autoReply": False, "autoPost": False}


def test_search_conversation_history_filters_by_participant_and_returns_sanitized_matches():
    module = EnrichmentModule(EnrichmentStore())
    tenant = module.createConversation("tenant-search", "tenant", tenancyId="tenancy-search")
    landlord = module.createConversation("landlord-search", "landlord", propertyId="property-search")
    module.addConversationMessage(tenant["conversationId"], "tenant", "Looking for condo near MRT with budget 5000. Contact +65 9000 0000")
    module.addConversationMessage(landlord["conversationId"], "landlord", "Condo near MRT available. Email owner@example.com")
    tenant_results = module.searchConversationHistory("mrt", participantId="tenant-search")
    assert len(tenant_results) == 1
    assert tenant_results[0]["participantType"] == "tenant"
    assert "+65 9000 0000" not in str(tenant_results)
    property_results = module.searchConversationHistory("mrt", propertyId="property-search")
    assert len(property_results) == 1
    assert "owner@example.com" not in str(property_results)


def test_conversation_runtime_does_not_auto_send_reply_or_post():
    module = EnrichmentModule(EnrichmentStore())
    conversation = module.createConversation("tenant-safe", "tenant")
    message = module.addConversationMessage(conversation["conversationId"], "tenant", "Can I view tomorrow?")
    timeline = module.getConversationTimeline(participantId="tenant-safe")
    assert message["sideEffects"] == {"autoSend": False, "autoReply": False, "autoPost": False}
    assert timeline["sideEffects"] == {"autoSend": False, "autoReply": False, "autoPost": False}
    assert not hasattr(module, "sendWhatsAppMessage")
    assert not hasattr(module, "autoReplyConversation")
    assert not hasattr(module, "autoPostConversation")


def test_rental_lifecycle_tables_and_create_lifecycle_model():
    module = EnrichmentModule(EnrichmentStore())
    lifecycle = module.createRentalLifecycle(
        "tenancy-100",
        "tenant-100",
        "property-100",
        leaseStart="2026-01-01",
        leaseEnd="2026-12-31",
    )
    assert lifecycle["tenancyId"] == "tenancy-100"
    assert lifecycle["stage"] == "inquiry"
    assert lifecycle["tenantId"] == "tenant-100"
    assert module.store.conn.execute("SELECT COUNT(*) AS c FROM rental_lifecycles").fetchone()["c"] == 1
    assert module.store.conn.execute("SELECT COUNT(*) AS c FROM rental_lifecycle_events").fetchone()["c"] == 1


def test_lifecycle_lease_start_and_renewal_window_generate_recommendations_only():
    module = EnrichmentModule(EnrichmentStore())
    module.createRentalLifecycle("tenancy-renew", "tenant-renew", "property-renew", leaseStart="2026-01-01", leaseEnd="2026-07-15")
    active = module.evaluateRentalLifecycle("tenancy-renew", asOf="2026-02-01T00:00:00+00:00")
    assert active["lifecycle"]["stage"] == "tenancy_active"
    renewal = module.evaluateRentalLifecycle("tenancy-renew", asOf="2026-06-01T00:00:00+00:00")
    assert renewal["lifecycle"]["stage"] == "renewal_window"
    assert any(rec["recommendationType"] == "renewal_recommendation" for rec in renewal["recommendations"])
    assert renewal["outputType"] == "recommendation_only"
    assert renewal["sideEffects"] == {"autoSend": False, "autoReply": False, "autoPost": False, "autoRenew": False, "autoAdjustRent": False}


def test_lifecycle_maintenance_request_updates_stage_health_and_reminder():
    module = EnrichmentModule(EnrichmentStore())
    module.createRentalLifecycle("tenancy-maint", "tenant-maint", "property-maint", leaseStart="2026-01-01", leaseEnd="2027-01-01")
    result = module.recordMaintenanceRequest("tenancy-maint", "Aircon leak at 123 Example Road. Contact tenant@example.com")
    assert result["lifecycle"]["stage"] == "maintenance"
    assert result["tenancyHealthSummary"]["healthStatus"] == "attention_needed"
    assert any(rec["title"] == "Review maintenance request" for rec in result["recommendations"])
    rendered = str(result)
    assert "tenant@example.com" not in rendered
    assert "123 Example Road" not in rendered


def test_lifecycle_inactivity_trigger_creates_review_reminder_only():
    module = EnrichmentModule(EnrichmentStore())
    module.createRentalLifecycle("tenancy-inactive", "tenant-inactive", "property-inactive", leaseStart="2026-01-01", leaseEnd="2027-01-01")
    module.recordLifecycleTrigger("tenancy-inactive", "lease_start", {"observedAt": "2026-01-01T00:00:00+00:00"})
    result = module.evaluateRentalLifecycle("tenancy-inactive", asOf="2026-01-20T00:00:00+00:00")
    assert result["tenancyHealthSummary"]["healthStatus"] == "attention_needed"
    assert any(rec["title"] == "Review inactive tenancy" for rec in result["recommendations"])
    assert result["sideEffects"]["autoSend"] is False


def test_lifecycle_timeline_integrates_lifecycle_events_and_conversation_memory():
    module = EnrichmentModule(EnrichmentStore())
    module.createRentalLifecycle("tenancy-timeline", "tenant-time", "property-time", leaseStart="2026-01-01", leaseEnd="2026-12-31")
    conversation = module.createConversation("tenant-time", "tenant", tenancyId="tenancy-timeline", propertyId="property-time")
    module.addConversationMessage(conversation["conversationId"], "tenant", "We would like a viewing next week. Email tenant@example.com")
    module.recordLifecycleTrigger("tenancy-timeline", "lease_start", {"observedAt": "2026-01-01T00:00:00+00:00"})
    timeline = module.getRentalLifecycleTimeline("tenancy-timeline")
    sources = {event["source"] for event in timeline["timeline"]}
    assert {"lifecycle", "conversation"}.issubset(sources)
    assert "tenant@example.com" not in str(timeline)
    assert timeline["sideEffects"] == {"autoSend": False, "autoReply": False, "autoPost": False, "autoRenew": False, "autoAdjustRent": False}


def test_lifecycle_engine_does_not_auto_send_renew_or_adjust_rent():
    module = EnrichmentModule(EnrichmentStore())
    module.createRentalLifecycle("tenancy-safe-life", "tenant-safe-life", "property-safe-life", leaseStart="2026-01-01", leaseEnd="2026-06-15")
    result = module.recordLifecycleTrigger("tenancy-safe-life", "renewal_window", {"observedAt": "2026-05-01T00:00:00+00:00"})
    assert result["outputType"] == "recommendation_only"
    assert result["sideEffects"] == {"autoSend": False, "autoReply": False, "autoPost": False, "autoRenew": False, "autoAdjustRent": False}
    assert not hasattr(module, "autoRenewTenancy")
    assert not hasattr(module, "autoAdjustRent")
    assert not hasattr(module, "sendLifecycleReminder")


def test_lifecycle_lease_end_and_buying_interest_triggers_are_recommendation_only():
    module = EnrichmentModule(EnrichmentStore())
    module.createRentalLifecycle("tenancy-exit", "tenant-exit", "property-exit", leaseStart="2025-01-01", leaseEnd="2026-01-01")
    ended = module.recordLifecycleTrigger("tenancy-exit", "lease_end", {"observedAt": "2026-01-02T00:00:00+00:00"})
    assert ended["lifecycle"]["stage"] == "exited"
    assert any(rec["title"] == "Review lease-end outcome" for rec in ended["recommendations"])
    module.createRentalLifecycle("tenancy-buy", "tenant-buy", "property-buy", leaseStart="2026-01-01", leaseEnd="2027-01-01")
    buying = module.recordLifecycleTrigger("tenancy-buy", "buying_interest", {"observedAt": "2026-05-01T00:00:00+00:00"})
    assert buying["lifecycle"]["stage"] == "buying_interest"
    assert any(rec["recommendationType"] == "buying_interest" for rec in buying["recommendations"])
    assert buying["sideEffects"] == {"autoSend": False, "autoReply": False, "autoPost": False, "autoRenew": False, "autoAdjustRent": False}


def seed_unified_timeline_module():
    module = EnrichmentModule(EnrichmentStore())
    tenant = module.resolveEntity({"name": "tenant-unified", "type": "tenant", "canonical_url": ""})
    module.recordConsentAcceptance(tenant.id, ["data_storage", "matching", "verification"], "website", {"personType": "tenant"})
    verification = module.createPersonVerification(tenant.id, "tenant")
    module.recordVerificationConsent(tenant.id, True)
    module.addVerificationSignal(
        verification["id"],
        {
            "signalType": "identity_document_submitted",
            "result": "pass",
            "confidence": "high",
            "source": "document_check",
            "publicSafe": True,
        },
    )
    source = {
        "source_url": "manual://timeline-intake",
        "source_type": "manual_import",
        "raw_text": "Tenant wants viewing near MRT. Contact tenant@example.com +65 9888 0000.",
        "fetched_at": "2026-01-01T00:00:00+00:00",
    }
    source_id = module.storeRawSource(tenant.id, source)
    module._createRagIntakeReviewItem(
        tenant,
        {**source, "id": source_id},
        [{"signal_type": "viewing_intent", "content": "Viewing requested near MRT", "confidence": 0.8, "freshness_score": 1.0, "verification_status": "verified"}],
    )
    conversation = module.createConversation(tenant.id, "tenant", tenancyId="tenancy-unified", propertyId="property-unified")
    module.addConversationMessage(conversation["conversationId"], "tenant", "Can view tomorrow? Email tenant@example.com")
    module.createRentalLifecycle("tenancy-unified", tenant.id, "property-unified", leaseStart="2026-01-01", leaseEnd="2026-07-15")
    module.recordLifecycleTrigger("tenancy-unified", "lease_start", {"observedAt": "2026-01-01T00:00:00+00:00"})
    module.recordMaintenanceRequest("tenancy-unified", "Aircon issue at 123 Example Road", reportedAt="2026-02-01T00:00:00+00:00")
    module.recordLifecycleTrigger("tenancy-unified", "renewal_window", {"observedAt": "2026-06-01T00:00:00+00:00"})
    module.recordViewingEvent(tenant.id, "tenant", "Viewing scheduled at 123 Example Road", timestamp="2026-01-02T00:00:00+00:00", tenancyId="tenancy-unified")
    module.recordMemoryTimelineEvent(tenant.id, "tenant", "matching_queue", "Tenant draft entered matching queue", "matching", timestamp="2026-01-03T00:00:00+00:00")
    module.store.importRagMemoryPacket(
        {
            "packetId": "packet-unified",
            "leadId": tenant.id,
            "entityId": tenant.id,
            "entityType": "tenant",
            "summary": "External enrichment summary for tenant@example.com with no public sourceTrace.",
            "mappedSignals": [],
            "suggestedNotes": [],
            "suggestedTasks": [],
            "suggestedCalendarDrafts": [],
            "confidence": 0.99,
            "freshness": 0.99,
            "verificationStatus": "verified",
            "sensitivityLevel": "internal",
            "sourceTrace": {"raw": "private"},
            "approvedForUse": True,
        }
    )
    return module, tenant.id


def test_unified_memory_timeline_combines_all_required_sources_without_private_data_or_scores():
    module, tenant_id = seed_unified_timeline_module()
    timeline = module.getUnifiedMemoryTimeline(tenant_id, "tenant")
    sources = {item["source"] for item in timeline["items"]}
    assert {"intake", "verification", "conversations", "viewing", "tenancy", "maintenance", "renewal", "matching", "consent", "enrichment"}.issubset(sources)
    rendered = str(timeline)
    assert "tenant@example.com" not in rendered
    assert "+65 9888 0000" not in rendered
    assert "123 Example Road" not in rendered
    assert "sourceTrace" not in rendered
    assert "0.99" not in rendered
    assert timeline["rawSourceTracePublic"] is False
    assert timeline["internalScoresPublic"] is False


def test_unified_memory_timeline_filters_conversation_verification_consent_matching_and_tenancy():
    module, tenant_id = seed_unified_timeline_module()
    conversation_only = module.getUnifiedMemoryTimeline(tenant_id, "tenant", filters=["conversations"])
    assert {item["source"] for item in conversation_only["items"]} == {"conversations"}
    verification_consent = module.getUnifiedMemoryTimeline(tenant_id, "tenant", filters=["verification", "consent"])
    assert {item["source"] for item in verification_consent["items"]}.issubset({"verification", "consent"})
    tenancy_sources = {item["source"] for item in module.getUnifiedMemoryTimeline(tenant_id, "tenant", filters=["tenancy"])["items"]}
    assert {"tenancy", "maintenance", "renewal", "viewing"}.issubset(tenancy_sources)
    matching_only = module.getUnifiedMemoryTimeline(tenant_id, "tenant", filters=["matching"])
    assert {item["source"] for item in matching_only["items"]} == {"matching"}


def test_timeline_tab_payload_is_privacy_safe_and_admin_ui_includes_tab():
    module, tenant_id = seed_unified_timeline_module()
    tab = module.renderTimelineTab(tenant_id, "tenant")
    assert tab["tab_title"] == "Timeline"
    assert {"conversations", "tenancy", "matching", "verification", "consent"}.issubset(set(tab["filters"]))
    assert tab["count_badge"] == len(tab["items"])
    assert all({"timestamp", "event_type", "summary", "source"}.issubset(item) for item in tab["items"])
    rendered = str(tab)
    assert "tenant@example.com" not in rendered
    assert "sourceTrace" not in rendered
    assert "confidence" not in rendered.lower()
    assert tab["raw_source_trace_public"] is False
    assert tab["internal_scores_public"] is False
    ui = module.renderRentalAdminUI(leadId=tenant_id, timelineEntityType="tenant")
    assert ui["workspace_tabs"]["timeline"]["tab_title"] == "Timeline"
