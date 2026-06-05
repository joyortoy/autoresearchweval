from __future__ import annotations

import hashlib
import json
import re
import sqlite3
from datetime import datetime, timezone
from typing import Any

from .enrichment_types import RENTAL_ENTITY_TYPES, RENTAL_SIGNAL_TYPES, REVIEW_REASONS, EnrichmentEntity


class EnrichmentRuntimeMixin:
    def _detect_privacy_flags(self, text: str) -> list[str]:
        flags = []
        if re.search(r"[A-Z0-9._%+-]+@[A-Z0-9.-]+\.[A-Z]{2,}", text, flags=re.IGNORECASE):
            flags.append("email_redacted")
        if re.search(r"(?:\+?\d[\d\s().-]{7,}\d)", text):
            flags.append("phone_redacted")
        if re.search(r"\b\d{1,5}\s+[A-Za-z0-9 .'-]+\s(?:Street|St|Road|Rd|Avenue|Ave|Lane|Ln|Drive|Dr|Block|Blk)\b", text, flags=re.IGNORECASE):
            flags.append("address_redacted")
        if re.search(r"\b(?:high risk|blacklist|do not rent|bad tenant|bad landlord)\b", text, flags=re.IGNORECASE):
            flags.append("private_label_redacted")
        return flags

    def _confidence_label(self, confidence: float) -> str:
        if confidence >= 0.75:
            return "high"
        if confidence >= 0.55:
            return "medium"
        return "low"

    def _freshness_label(self, freshness: float) -> str:
        if freshness >= 0.75:
            return "fresh"
        if freshness >= 0.35:
            return "aging"
        return "stale"

    def _review_reason_payload(self, reason: str, notes: str | None = None) -> str:
        normalized = reason if reason in REVIEW_REASONS else "other"
        return json.dumps({"reason": normalized, "notes": self.sanitizePublicText(notes or "")})

    def buildRentalRuntimeDrafts(self, entity: EnrichmentEntity, signals: list[dict[str, Any]]) -> dict[str, Any]:
        if entity.type not in RENTAL_ENTITY_TYPES:
            return {"drafts": [], "review_items": []}
        profile_type = {
            "tenant": "Tenant Intent Profile draft",
            "landlord": "Landlord Profile draft",
            "property": "Property Profile draft",
            "area": "Area Intelligence note",
            "source_channel": "Acquisition follow-up task",
        }.get(entity.type, "Acquisition follow-up task")
        public_signals = [
            {"signal_type": signal["signal_type"], "content": self.sanitizePublicText(signal["content"])}
            for signal in signals
            if signal["verification_status"] != "conflict"
        ]
        draft = {
            "draft_type": profile_type,
            "entity_type": entity.type,
            "person_id": entity.id if entity.type in {"tenant", "landlord"} else None,
            "summary": self.sanitizePublicText(self._summarize_signals(entity.type, signals)),
            "signals": public_signals,
            "review_status": "draft_needs_review",
            "auto_create_final_record": False,
        }
        follow_up = {
            "draft_type": "Acquisition follow-up task",
            "entity_type": entity.type,
            "summary": f"Review {entity.type} rental memory packet before outreach or matching.",
            "review_status": "draft_needs_review",
            "auto_send_message": False,
        }
        match = {
            "draft_type": "Match candidate suggestion",
            "entity_type": entity.type,
            "summary": "Use verified rental memory to support matching after human approval.",
            "review_status": "draft_needs_review",
            "auto_match": False,
        }
        return {"drafts": [draft, follow_up, match], "review_items": []}
    def approveRagIntakeItem(self, id: str, sessionToken: str | None = None) -> dict[str, Any]:
        item = self._load_review_item(id)
        risk_level = "high" if item["priority"] == "high" or item["review_reason"] == "consent_required" else "medium" if item["priority"] == "medium" else "low"
        allowed = self._enforce_ui_permission("approve", risk_level, sessionToken)
        if not allowed["allowed"]:
            return allowed
        if item["status"] == "approved":
            return {"review_item_id": id, "status": "approved", "already_approved": True}
        if item["review_reason"] == "consent_required":
            entity_row = self.store.conn.execute("SELECT entity_id FROM raw_sources WHERE id=?", (item["source_id"],)).fetchone()
            person_id = entity_row["entity_id"] if entity_row else item["id"]
            if not self.hasActiveConsent(person_id, "data_storage"):
                self._set_review_status(id, "needs_review", "contact_unclear", "Consent required before profile creation.")
                return {"review_item_id": id, "status": "blocked", "created": None, "blockedReason": "missing_data_storage_consent", "profileCreationAllowed": False}
        payload = json.loads(item["suggested_draft_payload"] or "{}")
        draft_type = item["suggested_draft_type"]
        created: dict[str, Any] = {}
        now = datetime.now(timezone.utc).isoformat()
        if draft_type == "Tenant Intent Profile draft":
            created = self._create_tenant_draft(id, payload, now)
        elif draft_type == "Property Profile draft":
            created = self._create_property_draft(id, payload, now)
        elif draft_type == "Area Intelligence note":
            created = self._create_area_note(id, payload, now)
        else:
            created = self._create_acquisition_task(id, payload, now)
        self._set_review_status(id, "approved")
        self._approve_memory_for_review_item(id)
        return {
            "review_item_id": id,
            "status": "approved",
            "created": created,
            "match_recommendations": [],
            "side_effects": {"auto_post": False, "auto_whatsapp_send": False, "auto_match": False},
        }

    def _approve_memory_for_review_item(self, review_item_id: str) -> None:
        row = self.store.conn.execute(
            """
            SELECT r.entity_id
            FROM rag_intake_review_items i
            JOIN raw_sources r ON r.id=i.source_id
            WHERE i.id=?
            """,
            (review_item_id,),
        ).fetchone()
        if row is None:
            return
        self.store.conn.execute(
            "UPDATE memory_packets SET status='approved' WHERE entity_id=? AND status='active'",
            (row["entity_id"],),
        )
        self.store.conn.commit()

    def ignoreRagIntakeItem(self, id: str, reason: str = "other", notes: str | None = None, sessionToken: str | None = None) -> dict[str, Any]:
        allowed = self._enforce_ui_permission("ignore", "low", sessionToken)
        if not allowed["allowed"]:
            return allowed
        normalized_reason = reason if reason in REVIEW_REASONS else "other"
        self._set_review_status(id, "ignored", normalized_reason, notes)
        return {"review_item_id": id, "status": "ignored", "reason": normalized_reason, "notes": self.sanitizePublicText(notes or ""), "created": None}

    def markRagIntakeNeedsReview(self, id: str, reason: str, notes: str | None = None, sessionToken: str | None = None) -> dict[str, Any]:
        allowed = self._enforce_ui_permission("needs_review", "low", sessionToken)
        if not allowed["allowed"]:
            return allowed
        normalized_reason = reason if reason in REVIEW_REASONS else "other"
        self._set_review_status(id, "needs_review", normalized_reason, notes)
        return {"review_item_id": id, "status": "needs_review", "reason": normalized_reason, "notes": self.sanitizePublicText(notes or "")}

    def _create_tenant_draft(self, review_item_id: str, payload: dict[str, Any], now: str) -> dict[str, Any]:
        draft_id = hashlib.sha1(f"tenant-draft:{review_item_id}".encode()).hexdigest()
        complete = self._tenant_ready_for_match(payload)
        queue_status = "Match Now" if complete else "Waiting / Not Ready"
        self.store.conn.execute(
            "INSERT OR REPLACE INTO tenant_intent_drafts (id, review_item_id, payload, queue_status, created_at) VALUES (?, ?, ?, ?, ?)",
            (draft_id, review_item_id, json.dumps(payload), queue_status, now),
        )
        queue_id = self._enqueue_matching_draft(draft_id, "Tenant Intent Profile draft", queue_status, payload, now)
        self.store.conn.commit()
        return {"draft_id": draft_id, "draft_type": "Tenant Intent Profile draft", "queue_status": queue_status, "matching_queue_id": queue_id}

    def _create_property_draft(self, review_item_id: str, payload: dict[str, Any], now: str) -> dict[str, Any]:
        draft_id = hashlib.sha1(f"property-draft:{review_item_id}".encode()).hexdigest()
        queue_status = "Property Matching Pool"
        self.store.conn.execute(
            "INSERT OR REPLACE INTO property_profile_drafts (id, review_item_id, payload, queue_status, created_at) VALUES (?, ?, ?, ?, ?)",
            (draft_id, review_item_id, json.dumps(payload), queue_status, now),
        )
        queue_id = self._enqueue_matching_draft(draft_id, "Property Profile draft", queue_status, payload, now)
        self.store.conn.commit()
        return {"draft_id": draft_id, "draft_type": "Property Profile draft", "queue_status": queue_status, "matching_queue_id": queue_id}

    def _create_area_note(self, review_item_id: str, payload: dict[str, Any], now: str) -> dict[str, Any]:
        note_id = hashlib.sha1(f"area-note:{review_item_id}".encode()).hexdigest()
        self.store.conn.execute(
            "INSERT OR REPLACE INTO area_intelligence_notes (id, review_item_id, payload, created_at) VALUES (?, ?, ?, ?)",
            (note_id, review_item_id, json.dumps(payload), now),
        )
        self.store.conn.commit()
        return {"note_id": note_id, "draft_type": "Area Intelligence note"}

    def _create_acquisition_task(self, review_item_id: str, payload: dict[str, Any], now: str) -> dict[str, Any]:
        task_id = hashlib.sha1(f"task:{review_item_id}".encode()).hexdigest()
        self.store.conn.execute(
            "INSERT OR REPLACE INTO acquisition_tasks (id, review_item_id, payload, status, created_at) VALUES (?, ?, ?, 'pending', ?)",
            (task_id, review_item_id, json.dumps(payload), now),
        )
        self.store.conn.commit()
        return {"task_id": task_id, "draft_type": "Acquisition follow-up task", "auto_send_message": False}

    def _tenant_ready_for_match(self, payload: dict[str, Any]) -> bool:
        signal_types = {signal["signal_type"] for signal in payload.get("signals", [])}
        return {"rental_budget", "area_preference", "property_type_preference"}.issubset(signal_types)

    def _enqueue_matching_draft(self, draft_id: str, draft_type: str, queue_status: str, payload: dict[str, Any], now: str) -> str:
        queue_id = hashlib.sha1(f"queue:{draft_id}".encode()).hexdigest()
        self.store.conn.execute(
            "INSERT OR REPLACE INTO matching_queue (id, draft_id, draft_type, queue_status, payload, created_at) VALUES (?, ?, ?, ?, ?, ?)",
            (queue_id, draft_id, draft_type, queue_status, json.dumps(payload), now),
        )
        return queue_id

    def _payload_areas(self, payload: dict[str, Any]) -> set[str]:
        areas = set()
        for signal in payload.get("signals", []):
            if signal.get("signal_type") == "area_preference":
                areas.add(signal.get("content", "").lower())
        return areas

    def generateMatchRecommendations(self) -> list[dict[str, Any]]:
        return self._generate_match_recommendations()

    def _generate_match_recommendations(self) -> list[dict[str, Any]]:
        tenants = self.store.conn.execute("SELECT * FROM matching_queue WHERE draft_type='Tenant Intent Profile draft' AND queue_status='Match Now'").fetchall()
        properties = self.store.conn.execute("SELECT * FROM matching_queue WHERE draft_type='Property Profile draft'").fetchall()
        recommendations = []
        now = datetime.now(timezone.utc).isoformat()
        for tenant in tenants:
            tenant_payload = json.loads(tenant["payload"])
            tenant_areas = self._payload_areas(tenant_payload)
            for prop in properties:
                prop_payload = json.loads(prop["payload"])
                prop_areas = self._payload_areas(prop_payload)
                if tenant_areas and prop_areas and tenant_areas.isdisjoint(prop_areas):
                    continue
                rec_id = hashlib.sha1(f"match:{tenant['id']}:{prop['id']}".encode()).hexdigest()
                safety = self.getMatchingSafetyFromMemory(tenant_payload.get("person_id"))
                reason = "Rule-based match candidate from approved governed rental memory."
                if safety.get("requiresManualReview"):
                    reason += " Tenant verification requires manual review."
                self.store.conn.execute(
                    "INSERT OR IGNORE INTO match_recommendations (id, tenant_queue_id, property_queue_id, reason, status, created_at) VALUES (?, ?, ?, ?, 'recommended', ?)",
                    (rec_id, tenant["id"], prop["id"], reason, now),
                )
                recommendations.append({
                    "id": rec_id,
                    "tenant_queue_id": tenant["id"],
                    "property_queue_id": prop["id"],
                    "status": "recommended",
                    "verificationSafetyInput": safety,
                })
        self.store.conn.commit()
        return recommendations

    def getRagIntakeReview(self, entityId: str | None = None, allowPrivateAddresses: bool = False) -> dict[str, Any]:
        params: tuple[Any, ...] = ()
        where = ""
        if entityId:
            where = "WHERE r.entity_id=?"
            params = (entityId,)
        rows = self.store.conn.execute(
            f"""
            SELECT i.*
            FROM rag_intake_review_items i
            JOIN raw_sources r ON r.id = i.source_id
            {where}
            ORDER BY i.created_at DESC
            """,
            params,
        ).fetchall()
        items = []
        for row in rows:
            preview = row["raw_text_preview"] if allowPrivateAddresses else self.sanitizePublicText(row["raw_text_preview"])
            payload = json.loads(row["suggested_draft_payload"] or "{}")
            source_row = self.store.conn.execute("SELECT entity_id FROM raw_sources WHERE id=?", (row["source_id"],)).fetchone()
            consent_person_id = source_row["entity_id"] if source_row else row["id"]
            consent_status = self.getConsentStatus(consent_person_id)
            profile_creation_allowed = consent_status["profileCreationAllowed"] or row["review_reason"] != "consent_required"
            extracted = [
                {
                    "signal_type": signal.get("signal_type"),
                    "content": self.sanitizePublicText(signal.get("content", "")),
                    "verification_status": signal.get("verification_status", "verified"),
                }
                for signal in json.loads(row["extracted_signals"] or "[]")
            ]
            items.append(
                {
                    "id": row["id"],
                    "source": {"id": row["source_id"], "source_type": row["source_type"]},
                    "source_type": row["source_type"],
                    "short_preview": preview,
                    "entity_type": row["entity_type"],
                    "extracted_signal_summary": self.sanitizePublicText(
                        "; ".join(signal.get("signal_type", "") for signal in extracted)
                    ),
                    "extracted_rental_signals": extracted,
                    "confidence_label": self._confidence_label(row["confidence"]),
                    "freshness_label": self._freshness_label(row["freshness"]),
                    "suggested_draft_type": row["suggested_draft_type"],
                    "suggested_draft_payload": payload,
                    "priority": row["priority"],
                    "privacy_flags": json.loads(row["privacy_flags"] or "[]"),
                    "status": row["status"],
                    "action": row["status"] if row["status"] != "pending" else "needs review",
                    "review_reason": row["review_reason"],
                    "review_notes": self.sanitizePublicText(row["review_notes"] or ""),
                    "consent_status": consent_status,
                    "profile_creation_allowed": profile_creation_allowed,
                    "blocked_reason": "missing_data_storage_consent" if not profile_creation_allowed else None,
                }
            )
        return {
            "section_title": "RAG Intake Review",
            "collapsed": True,
            "display": "secondary_admin_section",
            "analytics_panels": [],
            "actions": ["Approve", "Ignore", "Needs Review"],
            "items": items,
            "import_timing": self.getImportTimingQueue(),
            "consent_privacy": self.getConsentPrivacySection(),
            "public_visibility": False,
            "raw_source_trace_public": False,
        }

    def renderRagIntakeReviewSection(self, allowPrivateAddresses: bool = False) -> dict[str, Any]:
        return self.getRagIntakeReview(None, allowPrivateAddresses=allowPrivateAddresses)
