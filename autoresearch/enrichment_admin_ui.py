from __future__ import annotations

import hashlib
import json
import re
from datetime import datetime, timezone
from typing import Any

from .real_estate_memory_os import RealEstateRagAdapter


class EnrichmentAdminUIMixin:
    """Privacy-safe Rental Intent Network admin UI renderer.

    The renderer composes existing backend payloads into collapsed operator
    sections. It intentionally does not run retrieval, post messages, send
    WhatsApp, or expose raw traces/private contact details.
    """

    PRIMARY_WORKFLOW_SECTIONS = ["Match Now", "Waiting / Not Ready", "At Risk", "Tenancy Activation", "Renewal Queue"]
    ROLE_ACTIONS = {
        "super_admin": {"approve", "ignore", "needs_review", "edit_reply", "mark_posted_manually", "create_task", "use_note", "manage_users", "manage_roles"},
        "admin": {"approve", "ignore", "needs_review", "edit_reply", "mark_posted_manually", "create_task", "use_note"},
        "operator": {"approve_low_risk", "ignore", "needs_review", "create_task", "use_note"},
        "reviewer": {"ignore", "needs_review"},
        "readonly": set(),
    }

    def renderRentalAdminUI(self, leadId: str | None = None, role: str = "admin", sessionToken: str | None = None, timelineEntityType: str = "person") -> dict[str, Any]:
        role = self._resolve_role(role, sessionToken)
        return {
            "screen": "Rental Intent Network Admin",
            "role": role,
            "main_dashboard": {
                "primary_workflow": self.PRIMARY_WORKFLOW_SECTIONS.copy(),
                "rag_panel": None,
                "analytics_panels": [],
            },
            "secondary_sections": {
                "rag_intake_review": self.renderRagIntakeReviewAdminSection(role=role, sessionToken=sessionToken),
                "reply_drafts": self.renderReplyDraftsSection(role=role, sessionToken=sessionToken),
                "consent_privacy": self.renderConsentPrivacySection(role=role, sessionToken=sessionToken),
                "external_context": self.renderExternalContextSection(leadId, role=role, sessionToken=sessionToken) if leadId else None,
            },
            "workspace_tabs": {
                "timeline": self.renderTimelineTab(leadId, timelineEntityType, role=role, sessionToken=sessionToken) if leadId else None,
            },
            "side_effects": {"auto_scrape": False, "auto_post": False, "auto_whatsapp_send": False},
        }

    def renderRagIntakeReviewAdminSection(self, role: str = "admin", sessionToken: str | None = None) -> dict[str, Any]:
        role = self._resolve_role(role, sessionToken)
        payload = self.getRagIntakeReview()
        items = []
        for item in payload.get("items", []):
            risk_level = self._rag_item_risk(item)
            actions = self._action_buttons(
                ["Approve", "Ignore", "Needs Review"], role, risk_level, item["id"], consent_blocked=bool(item.get("blocked_reason")), sessionToken=sessionToken
            )
            items.append(
                {
                    "id": item["id"],
                    "source_type": item["source_type"],
                    "sanitized_preview": self._ui_safe_text(item["short_preview"]),
                    "extracted_signals": [
                        {
                            "signal_type": signal.get("signal_type"),
                            "content": self._ui_safe_text(signal.get("content", "")),
                            "verification_status": self._neutral_verification_label(signal.get("verification_status", "verified")),
                        }
                        for signal in item.get("extracted_rental_signals", [])
                    ],
                    "suggested_draft_type": item["suggested_draft_type"],
                    "priority": item["priority"],
                    "risk_level": risk_level,
                    "confidence_label": item["confidence_label"],
                    "freshness_label": item["freshness_label"],
                    "privacy_flags": item["privacy_flags"],
                    "consent_status": self._summarize_consent_status(item.get("consent_status", {})),
                    "blocked_reason": item.get("blocked_reason"),
                    "profile_creation_allowed": item.get("profile_creation_allowed", True),
                    "status": self._neutral_review_status(item["status"]),
                    "actions": [button["label"] for button in actions],
                    "action_buttons": actions,
                }
            )
        return {
            "section_title": "RAG Intake Review",
            "collapsed": True,
            "display": "secondary_admin_section",
            "count_badge": len(items),
            "empty_state": "No RAG intake items need review." if not items else None,
            "actions": ["Approve", "Ignore", "Needs Review"],
            "items": items,
            "import_timing": self.renderImportTimingSection(payload.get("import_timing", {}), role=role, sessionToken=sessionToken),
            "public_visibility": False,
            "raw_source_trace_public": False,
            "analytics_panels": [],
            "role_access": self._role_access_summary(role),
        }

    def renderImportTimingSection(self, import_timing: dict[str, Any] | None = None, role: str = "admin", sessionToken: str | None = None) -> dict[str, Any]:
        payload = import_timing or self.getImportTimingQueue()
        allowed = [
            item
            for item in payload.get("items", [])
            if item.get("import_priority") == "high" or item.get("import_status") in {"delayed", "stale", "failed"}
        ]
        return {
            "section_title": "Import Timing",
            "collapsed": True,
            "display": "nested_secondary_section",
            "count_badge": len(allowed),
            "empty_state": "No high-priority, delayed, stale, or failed imports." if not allowed else None,
            "items": [
                {
                    "source_type": item.get("source_type"),
                    "import_status": item.get("import_status"),
                    "import_priority": item.get("import_priority"),
                    "source_recency_label": item.get("source_recency_label"),
                    "failure_reason": self._ui_safe_text(item.get("failure_reason") or ""),
                }
                for item in allowed
            ],
            "analytics_panels": [],
            "role_access": self._role_access_summary(role),
        }

    def renderReplyDraftsSection(self, role: str = "admin", sessionToken: str | None = None) -> dict[str, Any]:
        role = self._resolve_role(role, sessionToken)
        rows = self.store.conn.execute("SELECT * FROM reply_drafts ORDER BY updated_at DESC").fetchall()
        items = []
        for row in rows:
            risk_level = "medium" if json.loads(row["risk_flags"] or "[]") else "low"
            actions = self._action_buttons(["Approve", "Edit", "Ignore", "Mark Posted Manually"], role, risk_level, row["id"], sessionToken=sessionToken)
            items.append(
                {
                    "id": row["id"],
                    "original_message_preview": self._ui_safe_text(row["original_message_preview"]),
                    "detected_intent": self._ui_safe_text(row["detected_intent"]),
                    "extracted_slots": self._sanitize_slots(json.loads(row["extracted_slots"] or "{}")),
                    "memory_used_summary": self._ui_safe_text(row["memory_used_summary"]),
                    "draft_reply": self._ui_safe_text(row["draft_reply"]),
                    "risk_flags": [self._neutral_risk_flag(flag) for flag in json.loads(row["risk_flags"] or "[]")],
                    "status": self._neutral_reply_status(row["status"]),
                    "risk_level": risk_level,
                    "actions": [button["label"] for button in actions],
                    "action_buttons": actions,
                }
            )
        return {
            "section_title": "Reply Drafts",
            "collapsed": True,
            "display": "secondary_admin_section",
            "count_badge": len(items),
            "empty_state": "No reply drafts pending operator review." if not items else None,
            "actions": ["Approve", "Edit", "Ignore", "Mark Posted Manually"],
            "items": items,
            "public_visibility": False,
            "auto_post": False,
            "auto_send": False,
            "analytics_panels": [],
            "role_access": self._role_access_summary(role),
        }

    def renderConsentPrivacySection(self, role: str = "admin", sessionToken: str | None = None) -> dict[str, Any]:
        role = self._resolve_role(role, sessionToken)
        payload = self.getConsentPrivacySection()
        items = payload.get("items", [])
        blocked = payload.get("blocked_actions", [])
        placeholders = payload.get("privacy_request_placeholders", [])
        return {
            **payload,
            "collapsed": True,
            "display": "secondary_admin_section",
            "count_badge": len(items) + len(blocked) + len(placeholders),
            "empty_state": "No pending consent or privacy items." if not items and not blocked and not placeholders else None,
            "analytics_panels": [],
            "role_access": self._role_access_summary(role),
            "action_buttons": [self._button("Withdraw Consent", role, "medium", "consent", action_name="withdraw_consent", sessionToken=sessionToken)],
        }

    def renderExternalContextSection(self, leadId: str, role: str = "admin", sessionToken: str | None = None) -> dict[str, Any]:
        role = self._resolve_role(role, sessionToken)
        payload = RealEstateRagAdapter(self.store).getLeadWorkspaceExternalContext(leadId)
        items = []
        for item in payload.get("items", []):
            risk_level = "high" if item.get("confidenceLabel") == "high" else "medium" if item.get("confidenceLabel") == "medium" else "low"
            actions = self._action_buttons(["Use in Note", "Create Task", "Ignore"], role, risk_level, item["eventId"], sessionToken=sessionToken, sensitivity="high" if risk_level in {"medium", "high"} else "low")
            items.append({**item, "actions": [button["label"] for button in actions], "action_buttons": actions})
        return {
            "section_title": "External Context",
            "collapsed": True,
            "display": "lead_workspace_secondary_section",
            "count_badge": len(items),
            "empty_state": "No external context available for this lead." if not items else None,
            "items": items,
            "actions": ["Use in Note", "Create Task", "Ignore"],
            "public_visibility": False,
            "raw_source_trace_public": False,
            "role_access": self._role_access_summary(role),
        }

    def approveReplyDraft(self, id: str, sessionToken: str | None = None) -> dict[str, Any]:
        allowed = self._enforce_ui_permission("approve", "low", sessionToken)
        if not allowed["allowed"]:
            return allowed
        return self._set_reply_draft_status(id, "approved")

    def ignoreReplyDraft(self, id: str, sessionToken: str | None = None) -> dict[str, Any]:
        allowed = self._enforce_ui_permission("ignore", "low", sessionToken)
        if not allowed["allowed"]:
            return allowed
        return self._set_reply_draft_status(id, "ignored")

    def markReplyDraftNeedsReview(self, id: str, sessionToken: str | None = None) -> dict[str, Any]:
        allowed = self._enforce_ui_permission("needs_review", "low", sessionToken)
        if not allowed["allowed"]:
            return allowed
        return self._set_reply_draft_status(id, "needs_review")

    def markReplyDraftPostedManually(self, id: str, sessionToken: str | None = None) -> dict[str, Any]:
        allowed = self._enforce_ui_permission("mark_posted_manually", "medium", sessionToken)
        if not allowed["allowed"]:
            return allowed
        return {**self._set_reply_draft_status(id, "posted_manually"), "confirmation": self.actionConfirmationMetadata("mark_posted_manually", id, "medium")}

    def editReplyDraft(self, id: str, editedText: str, reason: str, editedBy: str, sessionToken: str | None = None) -> dict[str, Any]:
        allowed = self._enforce_ui_permission("edit", "medium", sessionToken)
        if not allowed["allowed"]:
            return allowed
        row = self.store.conn.execute("SELECT * FROM reply_drafts WHERE id=?", (id,)).fetchone()
        if row is None:
            raise ValueError(f"Unknown reply draft: {id}")
        validation = self.validatePublicReplyDraft(editedText)
        now = datetime.now(timezone.utc).isoformat()
        status = "edited" if validation["isValid"] else "needs_review"
        self.store.conn.execute(
            "UPDATE reply_drafts SET draft_reply=?, status=?, updated_at=? WHERE id=?",
            (validation["sanitizedText"], status, now, id),
        )
        edit_id = hashlib.sha1(f"reply-edit:{id}:{now}".encode()).hexdigest()
        self.store.conn.execute(
            """
            INSERT INTO reply_draft_edits
            (id, draft_id, original_draft_text, edited_draft_text, edit_reason, edited_by, violations, status, edited_at)
            VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?)
            """,
            (
                edit_id,
                id,
                self._ui_safe_text(row["draft_reply"]),
                validation["sanitizedText"],
                self._ui_safe_text(reason),
                self._ui_safe_text(editedBy),
                json.dumps(validation["violations"]),
                status,
                now,
            ),
        )
        self.store.conn.commit()
        return {"draftId": id, "status": status, "validation": validation, "autoPost": False, "autoSend": False}

    def getReplyDraftEditHistory(self, id: str) -> list[dict[str, Any]]:
        rows = self.store.conn.execute("SELECT * FROM reply_draft_edits WHERE draft_id=? ORDER BY edited_at ASC", (id,)).fetchall()
        return [
            {
                "draftId": row["draft_id"],
                "originalDraftText": row["original_draft_text"],
                "editedDraftText": row["edited_draft_text"],
                "editReason": row["edit_reason"],
                "editedBy": row["edited_by"],
                "violations": json.loads(row["violations"] or "[]"),
                "status": row["status"],
                "editedAt": row["edited_at"],
            }
            for row in rows
        ]

    def validatePublicReplyDraft(self, text: str) -> dict[str, Any]:
        violations = []
        if re.search(r"[A-Z0-9._%+-]+@[A-Z0-9.-]+\.[A-Z]{2,}", text, flags=re.IGNORECASE):
            violations.append("contact_detail")
        if re.search(r"(?:\+?\d[\d\s().-]{7,}\d)", text):
            violations.append("contact_detail")
        if re.search(r"\b\d{1,5}\s+[A-Za-z0-9 .'-]+\s(?:Street|St|Road|Rd|Avenue|Ave|Lane|Ln|Drive|Dr|Block|Blk)\b", text, flags=re.IGNORECASE):
            violations.append("private_address")
        if re.search(r"\b(?:guaranteed housing|guaranteed rental|guaranteed approval)\b", text, flags=re.IGNORECASE):
            violations.append("guaranteed_housing_claim")
        if re.search(r"\b(?:high risk|blacklist|do not rent|bad tenant|bad landlord|risky person|shady|suspicious|low score)\b", text, flags=re.IGNORECASE):
            violations.append("private_trust_label")
        if "raw source trace" in text.lower() or "internal://" in text:
            violations.append("raw_source_trace")
        sanitized = self._ui_safe_text(text)
        sanitized = re.sub(r"\b(?:guaranteed housing|guaranteed rental|guaranteed approval)\b", "[requires-review]", sanitized, flags=re.IGNORECASE)
        return {
            "isValid": not violations,
            "sanitizedText": sanitized,
            "violations": sorted(set(violations)),
            "requiresReview": bool(violations),
        }

    def markRagEnrichmentUsed(self, eventId: str, sessionToken: str | None = None) -> dict[str, Any]:
        allowed = self._enforce_ui_permission("use_external_context_in_note", "medium", sessionToken)
        if not allowed["allowed"]:
            return allowed
        return self.store.markRagEnrichmentUsed(eventId)

    def ignoreRagEnrichmentEvent(self, eventId: str, reason: str, sessionToken: str | None = None) -> dict[str, Any]:
        allowed = self._enforce_ui_permission("ignore", "low", sessionToken)
        if not allowed["allowed"]:
            return allowed
        return self.store.ignoreRagEnrichmentEvent(eventId, reason)

    def actionConfirmationMetadata(self, actionName: str, itemId: str, riskLevel: str = "low", sensitivity: str = "low") -> dict[str, Any]:
        sensitive = actionName in {"mark_posted_manually", "withdraw_consent", "ignore_consent_blocked_item"}
        sensitive = sensitive or (actionName == "approve" and riskLevel == "high")
        sensitive = sensitive or (actionName == "use_external_context_in_note" and sensitivity in {"medium", "high"})
        return {
            "actionName": actionName,
            "itemId": itemId,
            "riskLevel": riskLevel,
            "confirmationRequired": sensitive,
            "confirmationMessage": f"Confirm {actionName.replace('_', ' ')} for this {riskLevel}-risk item." if sensitive else "",
        }

    def _set_reply_draft_status(self, id: str, status: str) -> dict[str, Any]:
        now = datetime.now(timezone.utc).isoformat()
        self.store.conn.execute("UPDATE reply_drafts SET status=?, updated_at=? WHERE id=?", (status, now, id))
        self.store.conn.commit()
        return {"replyDraftId": id, "status": status, "autoPost": False, "autoSend": False}

    def _button(self, label: str, role: str, risk_level: str, item_id: str, action_name: str | None = None, sensitivity: str = "low", sessionToken: str | None = None) -> dict[str, Any]:
        action = action_name or label.lower().replace(" ", "_")
        enabled = self._role_can(role, action, risk_level, sessionToken=sessionToken)
        confirmation = self.actionConfirmationMetadata(action, item_id, risk_level, sensitivity=sensitivity)
        return {"label": label, "actionName": action, "enabled": enabled, "confirmation": confirmation}

    def _action_buttons(self, labels: list[str], role: str, risk_level: str, item_id: str, consent_blocked: bool = False, sensitivity: str = "low", sessionToken: str | None = None) -> list[dict[str, Any]]:
        buttons = []
        for label in labels:
            action = label.lower().replace(" ", "_")
            if label == "Needs Review":
                action = "needs_review"
            if label == "Use in Note":
                action = "use_external_context_in_note"
            if label == "Mark Posted Manually":
                action = "mark_posted_manually"
            if label == "Approve" and consent_blocked:
                action = "ignore_consent_blocked_item" if role in {"reviewer", "readonly"} else "approve"
            buttons.append(self._button(label, role, risk_level, item_id, action_name=action, sensitivity=sensitivity, sessionToken=sessionToken))
        return buttons

    def _resolve_role(self, role: str, sessionToken: str | None = None) -> str:
        if sessionToken:
            return self.getUserRole(sessionToken) or "readonly"
        return self._normalize_role(role)

    def _permission_for_action(self, action: str, risk_level: str) -> str | None:
        mapping = {
            "approve": "approve_rag_intake",
            "ignore": "ignore_rag_intake",
            "needs_review": "ignore_rag_intake",
            "edit": "edit_reply_draft",
            "mark_posted_manually": "mark_posted_manually",
            "create_task": "create_task",
            "use_external_context_in_note": "create_note",
            "withdraw_consent": "withdraw_consent",
            "ignore_consent_blocked_item": "ignore_rag_intake",
        }
        return mapping.get(action)

    def _enforce_ui_permission(self, action: str, risk_level: str, sessionToken: str | None) -> dict[str, Any]:
        permission = self._permission_for_action(action, risk_level)
        if permission is None:
            return {"allowed": False, "reason": "permission_denied", "actionName": action}
        check = self.enforcePermission(sessionToken, permission, action)
        if not check["allowed"]:
            return check
        if action == "approve" and risk_level == "high":
            return self.enforcePermission(sessionToken, "approve_high_risk_item", action)
        return check

    def _role_can(self, role: str, action: str, risk_level: str, sessionToken: str | None = None) -> bool:
        if sessionToken is not None:
            permission = self._permission_for_action(action, risk_level)
            if permission is None:
                return False
            if not self.hasPermission(sessionToken, permission):
                return False
            if action == "approve" and risk_level == "high" and not self.hasPermission(sessionToken, "approve_high_risk_item"):
                return False
            return True
        if role in {"super_admin", "admin"}:
            return True
        if role == "readonly":
            return False
        if role == "reviewer":
            return action in {"ignore", "needs_review"}
        if role == "operator":
            if action == "approve":
                return risk_level == "low"
            return action in {"ignore", "needs_review", "create_task", "use_external_context_in_note"}
        return False

    def _role_access_summary(self, role: str) -> dict[str, Any]:
        return {"role": role, "readonly": role == "readonly", "allowedActions": sorted(self.ROLE_ACTIONS.get(role, set()))}

    def _normalize_role(self, role: str) -> str:
        return role if role in self.ROLE_ACTIONS else "readonly"

    def _rag_item_risk(self, item: dict[str, Any]) -> str:
        if item.get("priority") == "high" or item.get("blocked_reason") or item.get("privacy_flags"):
            return "high"
        if item.get("priority") == "medium":
            return "medium"
        return "low"

    def _sanitize_slots(self, slots: dict[str, Any]) -> dict[str, Any]:
        return {key: self._ui_safe_text(str(value)) for key, value in slots.items()}

    def _ui_safe_text(self, text: str) -> str:
        safe = self.sanitizePublicText(text or "")
        safe = safe.replace("raw source trace", "source trace withheld")
        safe = safe.replace("Raw source trace", "Source trace withheld")
        safe = safe.replace("internal://", "[internal-link-redacted]")
        return safe

    def _neutral_verification_label(self, status: str) -> str:
        if status == "verified":
            return "Verified"
        if status in {"review_required", "conflict", "needs_review"}:
            return "Manual review required"
        if status in {"consent_required", "consent_denied"}:
            return "Consent required"
        return "Verification pending"

    def _neutral_review_status(self, status: str) -> str:
        if status == "needs_review":
            return "Needs review"
        if status == "approved":
            return "Verified"
        if status in {"consent_required", "blocked"}:
            return "Consent required"
        return status

    def _neutral_reply_status(self, status: str) -> str:
        if status == "needs_review":
            return "Needs review"
        if status in {"draft", "edited", "pending"}:
            return "Draft only"
        return status

    def _summarize_consent_status(self, consent_status: dict[str, Any]) -> str:
        consents = consent_status.get("consents", {}) if consent_status else {}
        if consents.get("data_storage", {}).get("status") == "accepted":
            return "Verified"
        if consents.get("data_storage", {}).get("status") in {"declined", "withdrawn"}:
            return "Consent required"
        return "Verification pending"

    def _neutral_risk_flag(self, flag: str) -> str:
        if flag in {"manual_review_required", "needs_review", "consent_required"}:
            return "Manual review required"
        return self._ui_safe_text(flag)
