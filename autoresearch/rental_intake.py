from __future__ import annotations

import hashlib
import json
import re
import sqlite3
from datetime import datetime, timezone
from typing import Any

from .enrichment_types import IMPORT_TEMPLATES, RENTAL_ENTITY_TYPES, EnrichmentEntity


class RentalIntakeMixin:
    def _infer_rental_entity_type(self, text: str, source_type: str) -> str:
        lower = text.lower()
        if source_type in {"landlord_ad", "property_listing", "official_property_source", "third_party_listing"}:
            return "property"
        if source_type in {"whatsapp_message", "manual_import", "referral", "relocation_group", "expat_forum", "facebook_group"} and any(
            word in lower for word in ("looking", "moving", "relocating", "budget", "need a room", "tenant")
        ):
            return "tenant"
        if any(word in lower for word in ("owner", "landlord", "for rent", "available", "renting")):
            return "property"
        return "source_channel"

    def importManualRentalSource(self, text: str, sourceType: str, sourceMeta: dict[str, Any] | None = None) -> str | dict[str, Any]:
        """Import-only path: stores operator-provided rental source text without search/scrape/send side effects."""
        sourceMeta = sourceMeta or {}
        consent_basis = sourceMeta.get("consent_basis")
        if self._contains_identifiable_personal_data(text) and consent_basis in {None, "consent_required"}:
            entity_type = self._infer_rental_entity_type(text, sourceType)
            entity = self.resolveEntity({"name": f"manual-{entity_type}-{hashlib.sha1(text.encode()).hexdigest()[:8]}", "type": entity_type, "canonical_url": ""})
            source = {
                "source_url": f"manual://consent-required/{hashlib.sha1(text.encode()).hexdigest()}",
                "source_type": sourceType,
                "raw_text": self.sanitizePublicText(text[:500]),
                "fetched_at": datetime.now(timezone.utc).isoformat(),
                "import_status": "review_ready",
            }
            source_id = self.storeRawSource(entity.id, source)
            review_id = self._createConsentBlockedReviewItem(entity, source_id, source, "consent_required")
            return {"source_id": source_id, "review_item_id": review_id, "status": "needs_review", "consentBasis": "consent_required", "profileCreationAllowed": False}
        entity_type = self._infer_rental_entity_type(text, sourceType)
        entity = self.resolveEntity({"name": f"manual-{entity_type}-{hashlib.sha1(text.encode()).hexdigest()[:8]}", "type": entity_type, "canonical_url": ""})
        source = {
            "source_url": f"manual://{hashlib.sha1(text.encode()).hexdigest()}",
            "source_type": sourceType,
            "raw_text": text,
            "fetched_at": datetime.now(timezone.utc).isoformat(),
        }
        return self.storeRawSource(entity.id, source)

    def importTenantInquiryText(self, text: str, sourceMeta: dict[str, Any]) -> dict[str, Any]:
        person_id = sourceMeta.get("person_id")
        if person_id and not self.hasActiveConsent(person_id, "data_storage"):
            notice = self.createConsentNotice("tenant", ["data_storage", "matching", "bot_communication", "tenancy_memory"], person_id, sourceMeta.get("source", "manual_import"))
            block = self.requireConsentOrBlock(person_id, "data_storage", "tenant_intake")
            return {"blocked": True, "stored_profile": False, "profileCreationAllowed": False, "blockedReason": block["blockedReason"], "consentNotice": notice, "consentRequestDraft": self.createConsentRequestDraft("tenant")}
        entity = self.resolveEntity(
            {
                "name": sourceMeta.get("name", f"tenant-inquiry-{hashlib.sha1(text.encode()).hexdigest()[:8]}"),
                "type": "tenant",
                "canonical_url": sourceMeta.get("source_url", ""),
            }
        )
        source = {
            "source_url": sourceMeta.get("source_url", f"manual://tenant/{hashlib.sha1(text.encode()).hexdigest()}"),
            "source_type": sourceMeta.get("source_type", "manual_import"),
            "raw_text": text,
            "fetched_at": datetime.now(timezone.utc).isoformat(),
            "import_status": "imported",
            "import_priority": self._source_timing_priority(text, sourceMeta.get("source_type", "manual_import"), "tenant"),
            "first_seen_at": datetime.now(timezone.utc).isoformat(),
            "last_seen_at": datetime.now(timezone.utc).isoformat(),
            "imported_at": datetime.now(timezone.utc).isoformat(),
            "expires_at": self._extract_timing_expiry(text),
            "source_recency_label": "fresh",
        }
        source_id = self.storeRawSource(entity.id, source)
        return self.runRentalEnrichmentForSource(source_id)

    def importLandlordAdText(self, text: str, sourceMeta: dict[str, Any]) -> dict[str, Any]:
        person_id = sourceMeta.get("person_id")
        if person_id and not self.hasActiveConsent(person_id, "data_storage"):
            notice = self.createConsentNotice("landlord", ["data_storage", "matching", "bot_communication", "document_generation", "renewal_reminder"], person_id, sourceMeta.get("source", "manual_import"))
            block = self.requireConsentOrBlock(person_id, "data_storage", "landlord_intake")
            return {"blocked": True, "stored_profile": False, "profileCreationAllowed": False, "blockedReason": block["blockedReason"], "consentNotice": notice, "consentRequestDraft": self.createConsentRequestDraft("landlord")}
        entity = self.resolveEntity(
            {
                "name": sourceMeta.get("name", f"property-ad-{hashlib.sha1(text.encode()).hexdigest()[:8]}"),
                "type": sourceMeta.get("entity_type", "property"),
                "canonical_url": sourceMeta.get("source_url", ""),
            }
        )
        source = {
            "source_url": sourceMeta.get("source_url", f"manual://property/{hashlib.sha1(text.encode()).hexdigest()}"),
            "source_type": sourceMeta.get("source_type", "landlord_ad"),
            "raw_text": text,
            "fetched_at": datetime.now(timezone.utc).isoformat(),
            "import_status": "imported",
            "import_priority": self._source_timing_priority(text, sourceMeta.get("source_type", "landlord_ad"), sourceMeta.get("entity_type", "property")),
            "first_seen_at": datetime.now(timezone.utc).isoformat(),
            "last_seen_at": datetime.now(timezone.utc).isoformat(),
            "imported_at": datetime.now(timezone.utc).isoformat(),
            "expires_at": self._extract_timing_expiry(text),
            "source_recency_label": "fresh",
        }
        source_id = self.storeRawSource(entity.id, source)
        return self.runRentalEnrichmentForSource(source_id)

    def runRentalEnrichmentForSource(self, sourceId: str) -> dict[str, Any]:
        row = self.store.conn.execute(
            """
            SELECT r.*, e.type AS entity_type, e.name AS entity_name, e.canonical_url AS entity_url
            FROM raw_sources r
            JOIN entities e ON e.id = r.entity_id
            WHERE r.id=?
            """,
            (sourceId,),
        ).fetchone()
        if row is None:
            raise ValueError(f"Unknown rental source: {sourceId}")
        raw = {
            "source_url": row["source_url"],
            "source_type": row["source_type"],
            "raw_text": row["raw_text"],
            "fetched_at": row["fetched_at"],
            "entity_type": row["entity_type"],
            "rental_context": True,
        }
        existing = self.store.conn.execute("SELECT signal_type, content FROM signals WHERE entity_id=?", (row["entity_id"],)).fetchall()
        signals = self.verifySignals(self.extractSignals(raw), existing)
        freshness = self._freshness_score(raw["fetched_at"])
        for signal in signals:
            signal["source_id"] = sourceId
            signal["freshness_score"] = freshness
            signal["confidence"] = self.scoreConfidence(signal, row["source_type"])
            signal["decay_rate"] = self.assignDecayRate(signal, row["source_type"])
        packet_id = self.upsertMemoryPacket(row["entity_id"], signals) if signals else None
        entity = EnrichmentEntity(id=row["entity_id"], type=row["entity_type"], name=row["entity_name"], canonical_url=row["entity_url"])
        review_id = self._createRagIntakeReviewItem(entity, row, signals) if signals else None
        processed_at = datetime.now(timezone.utc).isoformat()
        import_status = "review_ready" if review_id else "enriched"
        self.store.conn.execute(
            "UPDATE raw_sources SET import_status=?, processed_at=?, source_recency_label=? WHERE id=?",
            (import_status, processed_at, self._recency_label(row["first_seen_at"] or row["fetched_at"], row["freshness_window_hours"], row["expires_at"]), sourceId),
        )
        self.store.conn.commit()
        payload = {
            "source_id": sourceId,
            "entity_id": row["entity_id"],
            "entity_type": row["entity_type"],
            "memory_packet_id": packet_id,
            "review_item_id": review_id,
            "extracted_signals": signals,
            "memory_context": self.getMemoryContext(row["entity_id"]),
            "rental_runtime": self.buildRentalRuntimeDrafts(entity, signals),
            "governed_memory_rule": "retrieved source -> extracted signal -> verified signal -> scored signal -> governed memory packet -> review draft",
            "import_status": import_status,
            "side_effects": {"auto_scrape": False, "auto_post": False, "auto_whatsapp_send": False, "auto_match": False},
        }
        if self.runtime_hook:
            self.runtime_hook(payload)
        return payload

    def getImportTemplates(self) -> list[dict[str, str]]:
        return list(IMPORT_TEMPLATES.values())

    def importFromTemplate(self, templateName: str, text: str, sourceMeta: dict[str, Any] | None = None) -> dict[str, Any]:
        template = IMPORT_TEMPLATES[templateName]
        meta = {"source_type": template["default_source_type"], **(sourceMeta or {})}
        if template["route"] == "importTenantInquiryText":
            return self.importTenantInquiryText(text, meta)
        return self.importLandlordAdText(text, meta)

    def _suggested_draft_type(self, entity_type: str, signals: list[dict[str, Any]]) -> str:
        if entity_type == "tenant":
            return "Tenant Intent Profile draft"
        if entity_type in {"landlord", "property"}:
            return "Property Profile draft"
        if entity_type == "area":
            return "Area Intelligence note"
        return "Acquisition follow-up task"

    def _review_priority(self, entity_type: str, signals: list[dict[str, Any]], confidence: float) -> str:
        signal_types = {signal["signal_type"] for signal in signals}
        has_singapore = any("singapore" in signal.get("content", "").lower() for signal in signals)
        if entity_type == "tenant" and {"rental_budget", "move_in_timeline", "area_preference"}.issubset(signal_types):
            return "high"
        if entity_type in {"landlord", "property"} and {"rental_budget", "area_preference", "property_availability"}.issubset(signal_types):
            return "high"
        if "tenant_intent" in signal_types and has_singapore:
            return "high"
        if confidence < 0.55 or "rental_budget" not in signal_types and entity_type == "tenant":
            return "low"
        if confidence < 0.55 or "rental_budget" not in signal_types and entity_type in {"landlord", "property"}:
            return "low"
        return "medium"

    def _signal_fingerprint(self, signals: list[dict[str, Any]]) -> str:
        normalized = sorted((signal["signal_type"], signal["content"].strip().lower()) for signal in signals)
        return hashlib.sha1(json.dumps(normalized).encode()).hexdigest()

    def _find_duplicate_review_item(self, source: sqlite3.Row | dict[str, Any], signals: list[dict[str, Any]]) -> str | None:
        source_id = source["id"] if isinstance(source, sqlite3.Row) else source["id"]
        source_url = source["source_url"]
        content_hash = source["content_hash"] if isinstance(source, sqlite3.Row) else hashlib.sha256(source["raw_text"].encode("utf-8")).hexdigest()
        direct = self.store.conn.execute("SELECT id FROM rag_intake_review_items WHERE source_id=? AND status!='ignored'", (source_id,)).fetchone()
        if direct:
            return str(direct["id"])
        same_source = self.store.conn.execute(
            """
            SELECT i.id
            FROM rag_intake_review_items i
            JOIN raw_sources r ON r.id=i.source_id
            WHERE (r.source_url=? OR r.content_hash=?) AND i.status!='ignored'
            ORDER BY i.created_at DESC LIMIT 1
            """,
            (source_url, content_hash),
        ).fetchone()
        if same_source:
            return str(same_source["id"])
        fingerprint = self._signal_fingerprint(signals)
        for row in self.store.conn.execute("SELECT id, extracted_signals FROM rag_intake_review_items WHERE status!='ignored'").fetchall():
            existing = json.loads(row["extracted_signals"] or "[]")
            if self._signal_fingerprint(existing) == fingerprint:
                return str(row["id"])
        return None

    def _add_review_audit_event(self, review_item_id: str, event_type: str, payload: dict[str, Any]) -> None:
        now = datetime.now(timezone.utc).isoformat()
        event_id = hashlib.sha1(f"audit:{review_item_id}:{event_type}:{now}".encode()).hexdigest()
        self.store.conn.execute(
            "INSERT INTO rag_intake_audit_events (id, review_item_id, event_type, payload, created_at) VALUES (?, ?, ?, ?, ?)",
            (event_id, review_item_id, event_type, json.dumps(payload), now),
        )
        self.store.conn.commit()

    def _createRagIntakeReviewItem(self, entity: EnrichmentEntity, source: sqlite3.Row | dict[str, Any], signals: list[dict[str, Any]]) -> str:
        duplicate_id = self._find_duplicate_review_item(source, signals)
        source_id = source["id"] if isinstance(source, sqlite3.Row) else source["id"]
        if duplicate_id:
            self._add_review_audit_event(duplicate_id, "duplicate_intake_linked", {"duplicate_source_id": source_id})
            return duplicate_id
        now = datetime.now(timezone.utc).isoformat()
        raw_text = source["raw_text"]
        confidence = round(sum(signal.get("confidence", 0) for signal in signals) / max(1, len(signals)), 3)
        freshness = round(sum(signal.get("freshness_score", 0) for signal in signals) / max(1, len(signals)), 3)
        draft_type = self._suggested_draft_type(entity.type, signals)
        draft_payload = self.buildRentalRuntimeDrafts(entity, signals)["drafts"][0] if entity.type in RENTAL_ENTITY_TYPES else {}
        review_id = hashlib.sha1(f"review:{source_id}:{now}".encode()).hexdigest()
        self.store.conn.execute(
            """
            INSERT INTO rag_intake_review_items
            (id, source_id, source_type, source_url, raw_text_preview, entity_type, extracted_signals, confidence,
             freshness, suggested_draft_type, suggested_draft_payload, status, priority, import_status, import_priority,
             source_recency_label, privacy_flags, review_reason, review_notes, duplicate_of, created_at, updated_at)
            VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, 'pending', ?, 'review_ready', ?, ?, ?, NULL, NULL, NULL, ?, ?)
            """,
            (
                review_id,
                source_id,
                source["source_type"],
                source["source_url"],
                self.sanitizePublicText(raw_text[:240]),
                entity.type,
                json.dumps([{**signal, "content": self.sanitizePublicText(signal["content"])} for signal in signals]),
                confidence,
                freshness,
                draft_type,
                json.dumps(draft_payload),
                self._review_priority(entity.type, signals, confidence),
                source["import_priority"] if "import_priority" in source.keys() else self._review_priority(entity.type, signals, confidence),
                source["source_recency_label"] if "source_recency_label" in source.keys() else "fresh",
                json.dumps(self._detect_privacy_flags(raw_text)),
                now,
                now,
            ),
        )
        self.store.conn.commit()
        self._add_review_audit_event(review_id, "created", {"source_id": source_id, "draft_type": draft_type})
        return review_id

    def _createConsentBlockedReviewItem(self, entity: EnrichmentEntity, source_id: str, source: dict[str, Any], reason: str) -> str:
        now = datetime.now(timezone.utc).isoformat()
        review_id = hashlib.sha1(f"consent-review:{source_id}:{now}".encode()).hexdigest()
        payload = {"draft_type": self._suggested_draft_type(entity.type, []), "entity_type": entity.type, "auto_create_final_record": False, "blocked_reason": reason}
        self.store.conn.execute(
            """
            INSERT INTO rag_intake_review_items
            (id, source_id, source_type, source_url, raw_text_preview, entity_type, extracted_signals, confidence,
             freshness, suggested_draft_type, suggested_draft_payload, status, priority, import_status, import_priority,
             source_recency_label, privacy_flags, review_reason, review_notes, duplicate_of, created_at, updated_at)
            VALUES (?, ?, ?, ?, ?, ?, '[]', 0, 0, ?, ?, 'needs_review', 'high', 'review_ready', 'high', 'fresh', ?, ?, ?, NULL, ?, ?)
            """,
            (
                review_id,
                source_id,
                source["source_type"],
                source["source_url"],
                self.sanitizePublicText(source["raw_text"][:240]),
                entity.type,
                self._suggested_draft_type(entity.type, []),
                json.dumps(payload),
                json.dumps(self._detect_privacy_flags(source["raw_text"])),
                "consent_required",
                "Identifiable personal data requires consent basis before profile creation.",
                now,
                now,
            ),
        )
        self.store.conn.commit()
        self._add_review_audit_event(review_id, "consent_required", {"reason": reason})
        return review_id

    def _load_review_item(self, item_id: str) -> sqlite3.Row:
        row = self.store.conn.execute("SELECT * FROM rag_intake_review_items WHERE id=?", (item_id,)).fetchone()
        if row is None:
            raise ValueError(f"Unknown RAG intake review item: {item_id}")
        return row

    def _set_review_status(self, item_id: str, status: str, reason: str | None = None, notes: str | None = None) -> None:
        from .enrichment_types import REVIEW_REASONS

        normalized_reason = reason if reason in REVIEW_REASONS else ("other" if reason else None)
        safe_notes = self.sanitizePublicText(notes or "") if notes else None
        self.store.conn.execute(
            "UPDATE rag_intake_review_items SET status=?, review_reason=?, review_notes=?, updated_at=? WHERE id=?",
            (status, normalized_reason, safe_notes, datetime.now(timezone.utc).isoformat(), item_id),
        )
        self._add_review_audit_event(item_id, status, {"reason": normalized_reason, "notes": safe_notes or ""})
        self.store.conn.commit()

    def _source_timing_priority(self, text: str, source_type: str, entity_type: str) -> str:
        signals = self._extract_rental_signals(text, entity_type)
        signal_types = {signal["signal_type"] for signal in signals}
        lower = text.lower()
        if entity_type == "tenant":
            if {"rental_budget", "area_preference"}.issubset(signal_types) and (
                "move_in_timeline" in signal_types or "[redacted-phone]" in self.sanitizePublicText(text) or "contact" in lower
            ):
                return "high"
        if entity_type in {"landlord", "property"}:
            if {"rental_budget", "area_preference", "property_availability"}.issubset(signal_types) and any(
                word in lower for word in ("owner", "direct landlord", "landlord direct", "no agent")
            ):
                return "high"
        if source_type in {"expat_forum", "relocation_group"}:
            if "singapore" in lower and any(word in lower for word in ("moving", "relocating", "looking for", "housing", "rental")):
                return "high"
            return "medium"
        return "low" if not signals else "medium"

    def _recency_label(self, first_seen_at: str, freshness_window_hours: int, expires_at: str | None = None) -> str:
        now = datetime.now(timezone.utc)
        if expires_at and datetime.fromisoformat(expires_at) <= now:
            return "expired"
        age_hours = (now - datetime.fromisoformat(first_seen_at)).total_seconds() / 3600
        if age_hours > freshness_window_hours * 2:
            return "stale"
        if age_hours > freshness_window_hours:
            return "normal"
        return "fresh"

    def _extract_timing_expiry(self, text: str) -> str | None:
        # Conservative month-only timing: if month has already passed this year, treat as stale candidate.
        match = re.search(r"\b(?:available|move[- ]?in|moving|from)\s+(?:in\s+)?(jan|feb|mar|apr|may|jun|jul|aug|sep|oct|nov|dec)[a-z]*\b", text, re.IGNORECASE)
        if not match:
            return None
        months = {"jan": 1, "feb": 2, "mar": 3, "apr": 4, "may": 5, "jun": 6, "jul": 7, "aug": 8, "sep": 9, "oct": 10, "nov": 11, "dec": 12}
        now = datetime.now(timezone.utc)
        month = months[match.group(1).lower()[:3]]
        year = now.year
        expiry = datetime(year, month, 28, tzinfo=timezone.utc)
        return expiry.isoformat()

    def queueImportSource(self, text: str, sourceType: str, sourceMeta: dict[str, Any] | None = None) -> dict[str, Any]:
        sourceMeta = sourceMeta or {}
        entity_type = sourceMeta.get("entity_type") or self._infer_rental_entity_type(text, sourceType)
        entity = self.resolveEntity(
            {
                "name": sourceMeta.get("name", f"queued-{entity_type}-{hashlib.sha1(text.encode()).hexdigest()[:8]}"),
                "type": entity_type,
                "canonical_url": sourceMeta.get("source_url", ""),
            }
        )
        now = datetime.now(timezone.utc).isoformat()
        freshness_window = int(sourceMeta.get("freshness_window_hours", 72))
        expires_at = sourceMeta.get("expires_at") or self._extract_timing_expiry(text)
        priority = sourceMeta.get("import_priority") or self._source_timing_priority(text, sourceType, entity_type)
        source = {
            "source_url": sourceMeta.get("source_url", f"manual://queued/{hashlib.sha1(text.encode()).hexdigest()}"),
            "source_type": sourceType,
            "raw_text": text,
            "fetched_at": now,
            "import_status": "queued",
            "import_priority": priority,
            "first_seen_at": now,
            "last_seen_at": now,
            "imported_at": None,
            "freshness_window_hours": freshness_window,
            "expires_at": expires_at,
            "source_recency_label": self._recency_label(now, freshness_window, expires_at),
        }
        source_id = self.storeRawSource(entity.id, source)
        self.store.conn.execute(
            """
            UPDATE raw_sources
            SET import_status='queued', import_priority=?, first_seen_at=COALESCE(first_seen_at, ?), last_seen_at=?,
                next_refresh_at=?, expires_at=?, freshness_window_hours=?, source_recency_label=?
            WHERE id=?
            """,
            (priority, now, now, sourceMeta.get("next_refresh_at"), expires_at, freshness_window, source["source_recency_label"], source_id),
        )
        self.store.conn.commit()
        return {"source_id": source_id, "import_status": "queued", "import_priority": priority, "source_recency_label": source["source_recency_label"]}

    def processNextImport(self) -> dict[str, Any] | None:
        row = self.store.conn.execute(
            """
            SELECT id FROM raw_sources
            WHERE import_status IN ('queued', 'delayed')
              AND (next_refresh_at IS NULL OR next_refresh_at <= ?)
            ORDER BY CASE import_priority WHEN 'high' THEN 0 WHEN 'medium' THEN 1 ELSE 2 END, first_seen_at ASC
            LIMIT 1
            """,
            (datetime.now(timezone.utc).isoformat(),),
        ).fetchone()
        if row is None:
            return None
        source_id = row["id"]
        try:
            self.store.conn.execute("UPDATE raw_sources SET import_status='processing' WHERE id=?", (source_id,))
            self.store.conn.commit()
            result = self.runRentalEnrichmentForSource(source_id)
            now = datetime.now(timezone.utc).isoformat()
            self.store.conn.execute(
                "UPDATE raw_sources SET import_status='review_ready', imported_at=COALESCE(imported_at, ?), processed_at=?, failure_reason=NULL WHERE id=?",
                (now, now, source_id),
            )
            if result.get("review_item_id"):
                self.store.conn.execute(
                    "UPDATE rag_intake_review_items SET import_status='review_ready' WHERE id=?",
                    (result["review_item_id"],),
                )
            self.store.conn.commit()
            result["import_status"] = "review_ready"
            return result
        except Exception as exc:  # noqa: BLE001
            current = self.store.conn.execute("SELECT retry_count FROM raw_sources WHERE id=?", (source_id,)).fetchone()
            retry_count = int(current["retry_count"] if current else 0) + 1
            status = "failed" if retry_count >= 3 else "queued"
            self.store.conn.execute(
                "UPDATE raw_sources SET import_status=?, retry_count=?, failure_reason=? WHERE id=?",
                (status, retry_count, str(exc), source_id),
            )
            self.store.conn.commit()
            return {"source_id": source_id, "import_status": status, "retry_count": retry_count, "failure_reason": str(exc)}

    def processImportQueue(self, limit: int | None = None) -> list[dict[str, Any]]:
        results = []
        while limit is None or len(results) < limit:
            result = self.processNextImport()
            if result is None:
                break
            results.append(result)
        return results

    def markImportDelayed(self, sourceId: str, nextRefreshAt: str, reason: str | None = None) -> dict[str, Any]:
        self.store.conn.execute(
            "UPDATE raw_sources SET import_status='delayed', next_refresh_at=?, failure_reason=? WHERE id=?",
            (nextRefreshAt, reason, sourceId),
        )
        self.store.conn.commit()
        return {"source_id": sourceId, "import_status": "delayed", "next_refresh_at": nextRefreshAt}

    def markImportStale(self, sourceId: str, reason: str | None = None) -> dict[str, Any]:
        self.store.conn.execute(
            "UPDATE raw_sources SET import_status='stale', source_recency_label='stale', failure_reason=? WHERE id=?",
            (reason, sourceId),
        )
        self.store.conn.commit()
        return {"source_id": sourceId, "import_status": "stale", "source_recency_label": "stale"}

    def refreshStaleSources(self) -> list[dict[str, Any]]:
        now = datetime.now(timezone.utc).isoformat()
        rows = self.store.conn.execute("SELECT * FROM raw_sources WHERE import_status!='ignored'").fetchall()
        updated = []
        for row in rows:
            label = self._recency_label(row["first_seen_at"] or row["fetched_at"], row["freshness_window_hours"], row["expires_at"])
            no_useful_signal = self.store.conn.execute("SELECT COUNT(*) AS c FROM signals WHERE source_id=?", (row["id"],)).fetchone()["c"] == 0
            if label in {"stale", "expired"} or no_useful_signal and row["processed_at"]:
                status = "stale"
                self.store.conn.execute(
                    "UPDATE raw_sources SET import_status=?, source_recency_label=?, next_refresh_at=? WHERE id=?",
                    (status, label if label != "fresh" else "stale", now, row["id"]),
                )
                updated.append({"source_id": row["id"], "import_status": status, "source_recency_label": label if label != "fresh" else "stale"})
        self.store.conn.commit()
        return updated

    def getImportTimingQueue(self) -> dict[str, Any]:
        rows = self.store.conn.execute(
            """
            SELECT id, source_type, source_url, import_status, import_priority, first_seen_at, last_seen_at,
                   imported_at, processed_at, next_refresh_at, expires_at, retry_count, failure_reason,
                   freshness_window_hours, source_recency_label
            FROM raw_sources
            WHERE import_priority='high' OR import_status IN ('delayed', 'stale', 'failed')
            ORDER BY CASE import_priority WHEN 'high' THEN 0 WHEN 'medium' THEN 1 ELSE 2 END, last_seen_at DESC
            """
        ).fetchall()
        return {
            "section_title": "Import Timing",
            "collapsed": True,
            "display": "nested_secondary_section",
            "analytics_panels": [],
            "items": [dict(row) for row in rows],
        }

    def getHighPriorityImports(self) -> list[dict[str, Any]]:
        rows = self.store.conn.execute("SELECT * FROM raw_sources WHERE import_priority='high' AND import_status!='ignored' ORDER BY last_seen_at DESC").fetchall()
        return [dict(row) for row in rows]
