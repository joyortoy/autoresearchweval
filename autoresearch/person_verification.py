from __future__ import annotations

import hashlib
import json
import re
from datetime import datetime, timezone
from typing import Any

from .enrichment_types import VERIFICATION_SIGNAL_TYPES


class PersonVerificationMixin:
    def _hash_contact(self, value: str | None) -> str | None:
        if not value:
            return None
        normalized = re.sub(r"\s+", "", value.strip().lower())
        return hashlib.sha256(normalized.encode()).hexdigest()

    def _verification_id(self, person_id: str, person_type: str) -> str:
        return hashlib.sha1(f"verification:{person_type}:{person_id}".encode()).hexdigest()

    def _ensure_memory_identity(self, person_id: str, person_type: str) -> None:
        now = datetime.now(timezone.utc).isoformat()
        self.store.conn.execute(
            """
            INSERT INTO entities (id, type, name, canonical_url, created_at, updated_at)
            VALUES (?, ?, ?, '', ?, ?)
            ON CONFLICT(id) DO UPDATE SET updated_at=excluded.updated_at
            """,
            (person_id, person_type, person_id, now, now),
        )
        self.store.conn.commit()

    def _log_verification_event(self, verification_id: str, event_type: str, payload: dict[str, Any]) -> None:
        now = datetime.now(timezone.utc).isoformat()
        event_id = hashlib.sha1(f"verification-audit:{verification_id}:{event_type}:{now}".encode()).hexdigest()
        self.store.conn.execute(
            "INSERT INTO verification_audit_events (id, verification_id, event_type, payload, created_at) VALUES (?, ?, ?, ?, ?)",
            (event_id, verification_id, event_type, json.dumps(payload), now),
        )
        self.store.conn.commit()

    def requestVerificationConsent(self, personId: str, personType: str) -> dict[str, Any]:
        verification = self.createPersonVerification(personId, personType)
        now = datetime.now(timezone.utc).isoformat()
        self.store.conn.execute(
            "UPDATE person_verifications SET consent_status='requested', updated_at=? WHERE id=? AND consent_status!='granted'",
            (now, verification["id"]),
        )
        self.store.conn.commit()
        self._log_verification_event(verification["id"], "consent_requested", {"person_id": personId, "person_type": personType})
        return {**verification, "consentStatus": "requested"}

    def recordVerificationConsent(self, personId: str, granted: bool) -> dict[str, Any]:
        row = self.store.conn.execute("SELECT * FROM person_verifications WHERE person_id=? ORDER BY created_at DESC LIMIT 1", (personId,)).fetchone()
        if row is None:
            raise ValueError(f"No verification exists for person: {personId}")
        status = "granted" if granted else "denied"
        now = datetime.now(timezone.utc).isoformat()
        self.store.conn.execute("UPDATE person_verifications SET consent_status=?, updated_at=? WHERE id=?", (status, now, row["id"]))
        self.store.conn.commit()
        if granted:
            self.recordConsentAcceptance(personId, ["data_storage", "verification"], "manual_import", {"personType": row["person_type"]})
        else:
            self.recordConsentDecline(personId, ["verification"], "manual_import", {"personType": row["person_type"]})
        self._log_verification_event(row["id"], "consent_recorded", {"granted": granted})
        return {"verificationId": row["id"], "personId": personId, "consentStatus": status}

    def createPersonVerification(
        self,
        personId: str,
        personType: str,
        phone: str | None = None,
        email: str | None = None,
        name: str | None = None,
    ) -> dict[str, Any]:
        if personType not in {"tenant", "landlord"}:
            raise ValueError("personType must be tenant or landlord")
        self._ensure_memory_identity(personId, personType)
        verification_id = self._verification_id(personId, personType)
        now = datetime.now(timezone.utc).isoformat()
        phone_hash = self._hash_contact(phone)
        email_hash = self._hash_contact(email)
        existing = self.store.conn.execute("SELECT * FROM person_verifications WHERE id=?", (verification_id,)).fetchone()
        if existing:
            self.store.conn.execute(
                "UPDATE person_verifications SET phone_hash=COALESCE(?, phone_hash), email_hash=COALESCE(?, email_hash), updated_at=? WHERE id=?",
                (phone_hash, email_hash, now, verification_id),
            )
        else:
            self.store.conn.execute(
                """
                INSERT INTO person_verifications
                (id, person_type, person_id, phone_hash, email_hash, consent_status, verification_status,
                 verification_signals, risk_flags, notes, created_at, updated_at)
                VALUES (?, ?, ?, ?, ?, 'not_requested', 'unverified', '[]', '[]', ?, ?, ?)
                """,
                (verification_id, personType, personId, phone_hash, email_hash, self.sanitizePublicText(name or ""), now, now),
            )
        self.store.conn.commit()
        self._log_verification_event(verification_id, "verification_created", {"person_id": personId, "person_type": personType})
        if phone_hash:
            self.checkDuplicateContact(phone, verification_id)
        if email_hash:
            self.checkDuplicateContact(email, verification_id)
        row = self.store.conn.execute("SELECT * FROM person_verifications WHERE id=?", (verification_id,)).fetchone()
        return self._verification_row_to_summary(row, internal=True)

    def addVerificationSignal(self, verificationId: str, signal: dict[str, Any]) -> dict[str, Any]:
        verification = self.store.conn.execute("SELECT * FROM person_verifications WHERE id=?", (verificationId,)).fetchone()
        if verification is None:
            raise ValueError(f"Unknown verification: {verificationId}")
        if verification["consent_status"] != "granted" or not self.hasActiveConsent(verification["person_id"], "verification") or not self.hasActiveConsent(verification["person_id"], "data_storage"):
            self._log_verification_event(verificationId, "verification_blocked_no_consent", {"signal_type": signal.get("signalType") or signal.get("signal_type")})
            return {"verificationId": verificationId, "accepted": False, "reason": "consent_required"}
        signal_type = signal.get("signalType") or signal.get("signal_type")
        if signal_type not in VERIFICATION_SIGNAL_TYPES:
            raise ValueError("Unsupported verification signal type")
        result = signal.get("result", "unknown")
        confidence = signal.get("confidence", "low")
        source = signal.get("source", "manual_review")
        public_safe = bool(signal.get("publicSafe", False))
        now = datetime.now(timezone.utc).isoformat()
        signal_id = hashlib.sha1(f"verification-signal:{verificationId}:{signal_type}:{now}".encode()).hexdigest()
        self.store.conn.execute(
            """
            INSERT INTO verification_signals (id, verification_id, signal_type, result, confidence, source, public_safe, created_at)
            VALUES (?, ?, ?, ?, ?, ?, ?, ?)
            """,
            (signal_id, verificationId, signal_type, result, confidence, source, int(public_safe), now),
        )
        self.store.conn.commit()
        self._log_verification_event(verificationId, "signal_added", {"signal_type": signal_type, "result": result, "source": source})
        status = self.evaluateVerificationStatus(verificationId)
        return {"id": signal_id, "verificationId": verificationId, "accepted": True, "verificationStatus": status["verificationStatus"]}

    def checkDuplicateContact(self, phoneOrEmail: str, verificationId: str | None = None) -> dict[str, Any]:
        contact_hash = self._hash_contact(phoneOrEmail)
        rows = self.store.conn.execute(
            """
            SELECT id FROM person_verifications
            WHERE (phone_hash=? OR email_hash=?) AND (? IS NULL OR id != ?)
            """,
            (contact_hash, contact_hash, verificationId, verificationId),
        ).fetchall()
        duplicate = bool(rows)
        if verificationId:
            owner = self.store.conn.execute("SELECT person_id, consent_status FROM person_verifications WHERE id=?", (verificationId,)).fetchone()
            if owner and (owner["consent_status"] != "granted" or not self.hasActiveConsent(owner["person_id"], "verification") or not self.hasActiveConsent(owner["person_id"], "data_storage")):
                self._log_verification_event(verificationId, "duplicate_contact_lookup_blocked_no_consent", {"duplicate": duplicate})
                return {"contactHash": contact_hash, "duplicate": False, "matchingVerificationIds": [], "blockedReason": "consent_required"}
            self._log_verification_event(verificationId, "duplicate_contact_lookup", {"duplicate": duplicate, "matches": len(rows)})
            if duplicate:
                consent = self.store.conn.execute("SELECT consent_status FROM person_verifications WHERE id=?", (verificationId,)).fetchone()
                if consent and consent["consent_status"] == "granted":
                    self.addVerificationSignal(
                        verificationId,
                        {
                            "signalType": "duplicate_contact_detected",
                            "result": "review_required",
                            "confidence": "high",
                            "source": "platform_history",
                            "publicSafe": False,
                        },
                    )
        return {"contactHash": contact_hash, "duplicate": duplicate, "matchingVerificationIds": [row["id"] for row in rows]}

    def evaluateVerificationStatus(self, verificationId: str) -> dict[str, Any]:
        row = self.store.conn.execute("SELECT * FROM person_verifications WHERE id=?", (verificationId,)).fetchone()
        if row is None:
            raise ValueError(f"Unknown verification: {verificationId}")
        if row["consent_status"] == "denied":
            status = "consent_denied"
        else:
            signals = self.store.conn.execute("SELECT * FROM verification_signals WHERE verification_id=?", (verificationId,)).fetchall()
            signal_types = {signal["signal_type"]: signal for signal in signals}
            review_types = {"duplicate_contact_detected", "scam_pattern_detected", "manual_review_required"}
            if any(signal["signal_type"] in review_types and signal["result"] in {"fail", "review_required"} for signal in signals):
                status = "review_required"
            elif row["person_type"] == "tenant" and all(
                signal_types.get(name) and signal_types[name]["result"] == "pass"
                for name in ("identity_document_submitted", "identity_document_matches_name")
            ):
                status = "verified"
            elif row["person_type"] == "landlord" and all(
                signal_types.get(name) and signal_types[name]["result"] == "pass"
                for name in ("landlord_ownership_document_submitted", "property_address_matches_listing")
            ):
                status = "verified"
            elif any(signal["result"] == "pass" for signal in signals):
                status = "partial"
            else:
                status = "unverified"
        risk_flags = []
        if status == "review_required":
            risk_flags.append("manual_review_required")
        now = datetime.now(timezone.utc).isoformat()
        self.store.conn.execute(
            "UPDATE person_verifications SET verification_status=?, risk_flags=?, updated_at=? WHERE id=?",
            (status, json.dumps(risk_flags), now, verificationId),
        )
        self.store.conn.commit()
        self._log_verification_event(verificationId, "status_evaluated", {"verification_status": status})
        self._publish_verification_memory_signal(row, status)
        return {"verificationId": verificationId, "verificationStatus": status, "riskFlags": risk_flags}

    def _publish_verification_memory_signal(self, verification_row: Any, status: str) -> str:
        """Publish neutral verification state into governed memory for downstream matching.

        Person verification only performs consent-gated checks. Identity/history and
        the match-consumable safety input are represented as internal governed
        memory, preserving the Rental RAG intake boundary.
        """
        person_id = verification_row["person_id"]
        person_type = verification_row["person_type"]
        self._ensure_memory_identity(person_id, person_type)
        now = datetime.now(timezone.utc)
        label = "Verified" if status == "verified" else "Manual review required" if status in {"review_required", "rejected"} else "Verification pending"
        source_id = hashlib.sha1(f"verification-source:{verification_row['id']}".encode()).hexdigest()
        raw_text = f"Consent-based person verification status for {person_type}: {label}."
        self.store.conn.execute(
            """
            INSERT OR REPLACE INTO raw_sources
            (id, entity_id, source_url, source_type, raw_text, fetched_at, content_hash, import_status, import_priority,
             first_seen_at, last_seen_at, imported_at, processed_at, retry_count, freshness_window_hours, source_recency_label)
            VALUES (?, ?, ?, 'manual_import', ?, ?, ?, 'enriched', 'medium', ?, ?, ?, ?, 0, 720, 'fresh')
            """,
            (
                source_id,
                person_id,
                f"internal://person-verification/{verification_row['id']}",
                raw_text,
                now.isoformat(),
                hashlib.sha256(raw_text.encode()).hexdigest(),
                now.isoformat(),
                now.isoformat(),
                now.isoformat(),
                now.isoformat(),
            ),
        )
        confidence = 0.9 if status == "verified" else 0.65 if status == "partial" else 0.45 if status == "review_required" else 0.3
        verification_status = "verified" if status == "verified" else "review_required" if status in {"review_required", "rejected"} else "unverified"
        signal = {
            "source_id": source_id,
            "signal_type": "verification_need",
            "content": f"Internal person verification label: {label}.",
            "confidence": confidence,
            "freshness_score": 1.0,
            "decay_rate": round(1 / 180, 4),
            "verification_status": verification_status,
            "sensitivity_level": "internal",
        }
        packet_id = self.upsertMemoryPacket(person_id, [signal])
        self._log_verification_event(verification_row["id"], "verification_memory_published", {"memory_packet_id": packet_id, "status": status})
        return packet_id

    def getMatchingSafetyFromMemory(self, personId: str | None) -> dict[str, Any]:
        if not personId:
            return {"trustBoost": False, "matchConfidenceAdjustment": "neutral", "source": "governed_memory"}
        row = self.store.conn.execute(
            """
            SELECT content, verification_status
            FROM signals
            WHERE entity_id=? AND signal_type='verification_need'
            ORDER BY created_at DESC LIMIT 1
            """,
            (personId,),
        ).fetchone()
        if row is None:
            return {"trustBoost": False, "matchConfidenceAdjustment": "neutral", "source": "governed_memory"}
        content = row["content"].lower()
        if row["verification_status"] == "verified" or ("verified" in content and "pending" not in content):
            return {"trustBoost": True, "matchConfidenceAdjustment": "boost", "source": "governed_memory"}
        if row["verification_status"] == "review_required" or "manual review required" in content:
            return {"trustBoost": False, "matchConfidenceAdjustment": "reduce", "requiresManualReview": True, "source": "governed_memory"}
        return {"trustBoost": False, "matchConfidenceAdjustment": "neutral", "source": "governed_memory"}

    def getInternalVerificationSummary(self, personId: str) -> dict[str, Any]:
        row = self.store.conn.execute("SELECT * FROM person_verifications WHERE person_id=? ORDER BY updated_at DESC LIMIT 1", (personId,)).fetchone()
        if row is None:
            return {"personId": personId, "label": "Verification pending", "verificationStatus": "unverified"}
        self._log_verification_event(row["id"], "internal_summary_lookup", {"person_id": personId})
        return self._verification_row_to_summary(row, internal=True)

    def sanitizeVerificationForPublic(self, summary: dict[str, Any]) -> dict[str, Any]:
        status = summary.get("verificationStatus", "unverified")
        label = "Verified" if status == "verified" else "Manual review required" if status in {"review_required", "rejected"} else "Verification pending"
        return {"personId": summary.get("personId"), "label": label, "publicSafe": True}

    def _verification_row_to_summary(self, row: Any, internal: bool = False) -> dict[str, Any]:
        label = "Verified" if row["verification_status"] == "verified" else "Manual review required" if row["verification_status"] in {"review_required", "rejected"} else "Verification pending"
        summary = {
            "id": row["id"],
            "personType": row["person_type"],
            "personId": row["person_id"],
            "consentStatus": row["consent_status"],
            "verificationStatus": row["verification_status"],
            "label": label,
            "riskFlags": json.loads(row["risk_flags"] or "[]"),
            "matchingSafetyInput": self._matching_safety_input(row["verification_status"]),
        }
        if internal:
            summary["phoneHash"] = row["phone_hash"]
            summary["emailHash"] = row["email_hash"]
        return summary

    def _matching_safety_input(self, status: str) -> dict[str, Any]:
        if status == "verified":
            return {"trustBoost": True, "matchConfidenceAdjustment": "boost"}
        if status == "review_required":
            return {"trustBoost": False, "matchConfidenceAdjustment": "reduce", "requiresManualReview": True}
        if status == "rejected":
            return {"trustBoost": False, "matchConfidenceAdjustment": "block_without_admin_override", "requiresAdminOverride": True}
        return {"trustBoost": False, "matchConfidenceAdjustment": "neutral"}
