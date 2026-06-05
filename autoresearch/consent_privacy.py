from __future__ import annotations

import hashlib
import json
import re
from datetime import datetime, timezone
from typing import Any


CONSENT_TYPES = {
    "data_storage",
    "matching",
    "bot_communication",
    "verification",
    "document_generation",
    "tenancy_memory",
    "renewal_reminder",
    "rag_source_import",
}

CONSENT_POLICY = {
    "save_personal_data": ["data_storage"],
    "matching": ["data_storage", "matching"],
    "bot_relay": ["data_storage", "bot_communication"],
    "verification": ["data_storage", "verification"],
    "document_generation": ["data_storage", "document_generation"],
    "tenancy_memory": ["data_storage", "tenancy_memory"],
    "renewal_reminder": ["data_storage", "renewal_reminder"],
    "rag_source_import": ["rag_source_import"],
}

NOTICE_TEXTS = {
    "tenant": "By continuing, you agree that the information you provide may be stored and used to match you with suitable rental options, facilitate bot-mediated communication, maintain rental records, verify information you voluntarily provide, support renewals, and improve matching quality.",
    "landlord": "By continuing, you agree that your property, contact, communication, and listing information may be stored and used to match you with suitable tenants, facilitate bot-mediated communication, prepare document drafts, support renewals, verify information you voluntarily provide, and improve platform matching quality.",
    "verification": "By continuing, you agree that information you voluntarily provide may be checked for verification and stored as internal verification status without public scores or rankings.",
    "bot_communication": "By continuing, you agree that messages you send may be stored and relayed through bot-mediated communication. No WhatsApp or bot message is sent automatically without consent.",
    "document_generation": "By continuing, you agree that information you provide may be used to prepare document drafts for review. This is not legal advice.",
    "tenancy_memory": "By continuing, you agree that tenancy and rental-history information you provide may be stored as private platform memory.",
    "renewal_reminder": "By continuing, you agree that renewal-related information may be stored and used to generate reminder drafts.",
    "rag_source_import": "By continuing, you confirm that manually imported source text has a valid consent basis for governed RAG intake review.",
    "unknown": "By continuing, you agree that the information you provide may be stored and used only for the requested rental platform workflow, subject to privacy controls and review.",
}

TENANT_WHATSAPP_CONSENT_DRAFT = "Before we continue, please confirm that you agree for us to store and use the information you share to help match you with suitable rentals, keep communication through the bot, and maintain rental records. Reply YES to continue."
LANDLORD_WHATSAPP_CONSENT_DRAFT = "Before we continue, please confirm that you agree for us to store and use your property and contact information to help match you with suitable tenants, keep communication through the bot, prepare drafts, and support renewals. Reply YES to continue."


class ConsentPrivacyMixin:
    def _now(self) -> str:
        return datetime.now(timezone.utc).isoformat()

    def _consent_notice_text(self, person_type: str, consent_types: list[str]) -> str:
        if person_type in {"tenant", "landlord"}:
            return NOTICE_TEXTS[person_type]
        if len(consent_types) == 1 and consent_types[0] in NOTICE_TEXTS:
            return NOTICE_TEXTS[consent_types[0]]
        return NOTICE_TEXTS.get(person_type, NOTICE_TEXTS["unknown"])

    def createConsentNotice(self, personType: str, consentTypes: list[str], personId: str | None = None, source: str = "manual_import") -> dict[str, Any]:
        normalized = [item for item in consentTypes if item in CONSENT_TYPES]
        notice = self._consent_notice_text(personType, normalized)
        records = []
        if personId:
            records = [self._upsert_consent_record(personId, personType, consent_type, "pending", notice, source, {}) for consent_type in normalized]
        return {
            "personType": personType,
            "consentTypes": normalized,
            "consentVersion": "2026-06-privacy-v1",
            "noticeText": notice,
            "status": "pending",
            "records": records,
        }

    def recordConsentAcceptance(self, personId: str, consentTypes: list[str], source: str, metadata: dict[str, Any] | None = None) -> list[dict[str, Any]]:
        person_type = (metadata or {}).get("personType", "unknown")
        notice = self._consent_notice_text(person_type, consentTypes)
        return [self._upsert_consent_record(personId, person_type, item, "accepted", notice, source, metadata or {}) for item in consentTypes if item in CONSENT_TYPES]

    def recordConsentDecline(self, personId: str, consentTypes: list[str], source: str, metadata: dict[str, Any] | None = None) -> list[dict[str, Any]]:
        person_type = (metadata or {}).get("personType", "unknown")
        notice = self._consent_notice_text(person_type, consentTypes)
        return [self._upsert_consent_record(personId, person_type, item, "declined", notice, source, metadata or {}) for item in consentTypes if item in CONSENT_TYPES]

    def withdrawConsent(self, personId: str, consentType: str, sessionToken: str | None = None) -> dict[str, Any]:
        allowed = self.enforcePermission(sessionToken, "withdraw_consent", "withdraw_consent")
        if not allowed["allowed"]:
            return allowed
        row = self.store.conn.execute(
            "SELECT * FROM consent_records WHERE person_id=? AND consent_type=? ORDER BY updated_at DESC LIMIT 1",
            (personId, consentType),
        ).fetchone()
        if row is None:
            return self._upsert_consent_record(personId, "unknown", consentType, "withdrawn", NOTICE_TEXTS["unknown"], "manual_import", {})
        now = self._now()
        self.store.conn.execute(
            "UPDATE consent_records SET status='withdrawn', withdrawn_at=?, updated_at=? WHERE id=?",
            (now, now, row["id"]),
        )
        self.store.conn.commit()
        return self._consent_row_to_dict(self.store.conn.execute("SELECT * FROM consent_records WHERE id=?", (row["id"],)).fetchone())

    def hasActiveConsent(self, personId: str, consentType: str) -> bool:
        row = self.store.conn.execute(
            "SELECT status FROM consent_records WHERE person_id=? AND consent_type=? ORDER BY updated_at DESC LIMIT 1",
            (personId, consentType),
        ).fetchone()
        return bool(row and row["status"] == "accepted")

    def requireConsentOrBlock(self, personId: str, consentType: str, actionName: str) -> dict[str, Any]:
        if self.hasActiveConsent(personId, consentType):
            return {"allowed": True, "personId": personId, "consentType": consentType, "actionName": actionName}
        now = self._now()
        block_id = hashlib.sha1(f"consent-block:{personId}:{consentType}:{actionName}:{now}".encode()).hexdigest()
        self.store.conn.execute(
            "INSERT INTO consent_action_blocks (id, person_id, consent_type, action_name, reason, created_at) VALUES (?, ?, ?, ?, ?, ?)",
            (block_id, personId, consentType, actionName, "missing_or_inactive_consent", now),
        )
        self.store.conn.commit()
        return {
            "allowed": False,
            "personId": personId,
            "consentType": consentType,
            "actionName": actionName,
            "blockedReason": "missing_or_inactive_consent",
            "consentRequestDraft": self.createConsentRequestDraft("tenant" if "tenant" in personId.lower() else "landlord" if "landlord" in personId.lower() else "unknown"),
        }

    def getConsentStatus(self, personId: str) -> dict[str, Any]:
        rows = self.store.conn.execute("SELECT * FROM consent_records WHERE person_id=? ORDER BY updated_at DESC", (personId,)).fetchall()
        by_type = {}
        for row in rows:
            by_type.setdefault(row["consent_type"], self._consent_row_to_dict(row))
        return {"personId": personId, "consents": by_type, "profileCreationAllowed": by_type.get("data_storage", {}).get("status") == "accepted"}

    def getConsentAuditTrail(self, personId: str) -> list[dict[str, Any]]:
        rows = self.store.conn.execute("SELECT * FROM consent_records WHERE person_id=? ORDER BY created_at ASC", (personId,)).fetchall()
        return [self._consent_row_to_dict(row) for row in rows]

    def createConsentRequestDraft(self, personType: str, channel: str = "whatsapp") -> dict[str, Any]:
        text = TENANT_WHATSAPP_CONSENT_DRAFT if personType == "tenant" else LANDLORD_WHATSAPP_CONSENT_DRAFT if personType == "landlord" else NOTICE_TEXTS["unknown"]
        return {"channel": channel, "personType": personType, "message": text, "autoSend": False, "publicSafe": True}

    def relayBotMessage(self, personId: str, personType: str, message: str) -> dict[str, Any]:
        missing = [consent for consent in ("data_storage", "bot_communication") if not self.hasActiveConsent(personId, consent)]
        if missing:
            for consent in missing:
                self.requireConsentOrBlock(personId, consent, "bot_relay")
            return {"relayed": False, "missingConsent": missing, "consentRequestDraft": self.createConsentRequestDraft(personType)}
        return {"relayed": True, "message": self.sanitizePublicText(message), "autoWhatsAppSend": False}

    def createPrivacyRequestPlaceholder(self, personId: str, requestType: str, source: str = "manual_import") -> dict[str, Any]:
        if requestType not in {"data_access", "data_correction", "data_deletion", "consent_withdrawal"}:
            raise ValueError("Unsupported privacy request type")
        now = self._now()
        request_id = hashlib.sha1(f"privacy-request:{personId}:{requestType}:{now}".encode()).hexdigest()
        self.store.conn.execute(
            "INSERT INTO privacy_requests (id, person_id, request_type, status, source, created_at, updated_at) VALUES (?, ?, ?, 'placeholder', ?, ?, ?)",
            (request_id, personId, requestType, source, now, now),
        )
        self.store.conn.commit()
        return {"id": request_id, "personId": personId, "requestType": requestType, "status": "placeholder"}

    def listPrivacyRequestPlaceholders(self, personId: str) -> list[dict[str, Any]]:
        rows = self.store.conn.execute("SELECT * FROM privacy_requests WHERE person_id=? ORDER BY created_at DESC", (personId,)).fetchall()
        return [dict(row) for row in rows]

    def getConsentPrivacySection(self) -> dict[str, Any]:
        rows = self.store.conn.execute("SELECT * FROM consent_records WHERE status IN ('pending', 'declined', 'withdrawn') ORDER BY updated_at DESC").fetchall()
        blocks = self.store.conn.execute("SELECT * FROM consent_action_blocks ORDER BY created_at DESC").fetchall()
        privacy_requests = self.store.conn.execute("SELECT * FROM privacy_requests ORDER BY created_at DESC").fetchall()
        return {
            "section_title": "Consent & Privacy",
            "collapsed": True,
            "display": "secondary_admin_section",
            "items": [self._consent_row_to_dict(row) for row in rows],
            "blocked_actions": [dict(row) for row in blocks],
            "privacy_request_placeholders": [dict(row) for row in privacy_requests],
            "public_visibility": False,
            "analytics_panels": [],
        }

    def _upsert_consent_record(
        self,
        person_id: str,
        person_type: str,
        consent_type: str,
        status: str,
        notice_text: str,
        source: str,
        metadata: dict[str, Any],
    ) -> dict[str, Any]:
        now = self._now()
        existing = self.store.conn.execute(
            "SELECT id FROM consent_records WHERE person_id=? AND consent_type=? ORDER BY updated_at DESC LIMIT 1",
            (person_id, consent_type),
        ).fetchone()
        accepted_at = now if status == "accepted" else None
        declined_at = now if status == "declined" else None
        withdrawn_at = now if status == "withdrawn" else None
        if existing:
            self.store.conn.execute(
                """
                UPDATE consent_records
                SET person_type=?, consent_version=?, status=?, notice_text=?, accepted_at=?, declined_at=?, withdrawn_at=?,
                    source=?, ip_address=?, user_agent=?, updated_at=?
                WHERE id=?
                """,
                (
                    person_type,
                    "2026-06-privacy-v1",
                    status,
                    notice_text,
                    accepted_at,
                    declined_at,
                    withdrawn_at,
                    source,
                    metadata.get("ipAddress"),
                    metadata.get("userAgent"),
                    now,
                    existing["id"],
                ),
            )
            record_id = existing["id"]
        else:
            record_id = hashlib.sha1(f"consent:{person_id}:{consent_type}:{now}".encode()).hexdigest()
            self.store.conn.execute(
                """
                INSERT INTO consent_records
                (id, person_id, person_type, consent_type, consent_version, status, notice_text, accepted_at, declined_at,
                 withdrawn_at, source, ip_address, user_agent, created_at, updated_at)
                VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
                """,
                (
                    record_id,
                    person_id,
                    person_type,
                    consent_type,
                    "2026-06-privacy-v1",
                    status,
                    notice_text,
                    accepted_at,
                    declined_at,
                    withdrawn_at,
                    source,
                    metadata.get("ipAddress"),
                    metadata.get("userAgent"),
                    now,
                    now,
                ),
            )
        self.store.conn.commit()
        return self._consent_row_to_dict(self.store.conn.execute("SELECT * FROM consent_records WHERE id=?", (record_id,)).fetchone())

    def _consent_row_to_dict(self, row: Any) -> dict[str, Any]:
        return {
            "id": row["id"],
            "personId": row["person_id"],
            "personType": row["person_type"],
            "consentType": row["consent_type"],
            "consentVersion": row["consent_version"],
            "status": row["status"],
            "noticeText": row["notice_text"],
            "acceptedAt": row["accepted_at"],
            "declinedAt": row["declined_at"],
            "withdrawnAt": row["withdrawn_at"],
            "source": row["source"],
            "ipAddress": row["ip_address"],
            "userAgent": row["user_agent"],
            "createdAt": row["created_at"],
            "updatedAt": row["updated_at"],
        }

    def _contains_identifiable_personal_data(self, text: str) -> bool:
        return bool(
            re.search(r"[A-Z0-9._%+-]+@[A-Z0-9.-]+\.[A-Z]{2,}", text, flags=re.IGNORECASE)
            or re.search(r"(?:\+?\d[\d\s().-]{7,}\d)", text)
        )
