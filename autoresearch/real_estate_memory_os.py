from __future__ import annotations

import hashlib
import json
import re
from datetime import datetime, timezone
from typing import Any, TypedDict


class Signal(TypedDict, total=False):
    signalType: str
    content: str
    confidence: float
    freshness: float
    verificationStatus: str
    sourceType: str
    observedAt: str
    expiresAt: str


class GovernedMemoryPacketInput(TypedDict, total=False):
    packetId: str
    entityId: str
    entityType: str
    summary: str
    signals: list[Signal]
    confidence: float
    freshness: float
    verificationStatus: str
    sensitivityLevel: str
    sourceTrace: dict[str, Any]
    approvedForUse: bool
    createdAt: str
    updatedAt: str


class RealEstateRagAdapter:
    """Adapter from governed RAG memory packets into Real Estate Memory OS events.

    This layer intentionally maps approved governed memory into enrichment events;
    it does not run retrieval, duplicate RAG extraction, or overwrite Memory OS
    lead/relationship records.
    """

    def __init__(self, store: Any, allow_stale: bool = False) -> None:
        self.store = store
        self.allow_stale = allow_stale

    def canImportPacket(self, packet: GovernedMemoryPacketInput, allow_stale: bool | None = None) -> bool:
        if not packet.get("approvedForUse"):
            return False
        if packet.get("verificationStatus") in {"conflict", "rejected"}:
            return False
        if not (self.allow_stale if allow_stale is None else allow_stale) and self._is_stale(packet):
            return False
        return True

    def mapEntityToLead(self, packet: GovernedMemoryPacketInput) -> dict[str, Any]:
        entity_id = str(packet["entityId"])
        entity_type = str(packet.get("entityType", "person"))
        lead_id = hashlib.sha1(f"real-estate-lead:{entity_type}:{entity_id}".encode()).hexdigest()
        return {"leadId": lead_id, "entityId": entity_id, "entityType": entity_type}

    def mapSignalsToRelationshipMemory(self, packet: GovernedMemoryPacketInput) -> list[dict[str, Any]]:
        return [
            {
                "signalType": signal.get("signalType", "unknown"),
                "content": self._sanitize_text(signal.get("content", "")),
                "source": "rag_enrichment_event",
                "priority": "verified_internal_memory" if signal.get("verificationStatus") == "verified" else "rag_enrichment",
                "overwriteExisting": False,
            }
            for signal in packet.get("signals", [])
            if signal.get("verificationStatus") != "conflict"
        ]

    def mapSignalsToLeadNotes(self, packet: GovernedMemoryPacketInput) -> list[str]:
        notes = [self._sanitize_text(packet.get("summary", ""))]
        for signal in packet.get("signals", []):
            if signal.get("verificationStatus") == "conflict":
                continue
            notes.append(f"{signal.get('signalType', 'signal')}: {self._sanitize_text(signal.get('content', ''))}")
        return [note for note in notes if note.strip()]

    def mapSignalsToTasks(self, packet: GovernedMemoryPacketInput) -> list[dict[str, Any]]:
        tasks = []
        for signal in packet.get("signals", []):
            signal_type = signal.get("signalType")
            content = self._sanitize_text(signal.get("content", ""))
            if signal_type in {"move_in_timeline", "viewing_intent", "verification_need", "document_readiness"}:
                tasks.append(
                    {
                        "title": self._task_title(signal_type),
                        "detail": content,
                        "source": "rag_enrichment_event",
                        "requiresApproval": True,
                    }
                )
        return tasks

    def mapSignalsToCalendarDrafts(self, packet: GovernedMemoryPacketInput) -> list[dict[str, Any]]:
        drafts = []
        for signal in packet.get("signals", []):
            if signal.get("signalType") in {"viewing_intent", "move_in_timeline"}:
                drafts.append(
                    {
                        "title": "Draft follow-up calendar hold",
                        "context": self._sanitize_text(signal.get("content", "")),
                        "source": "rag_enrichment_event",
                        "autoCreate": False,
                    }
                )
        return drafts

    def importPacketToMemoryOs(self, packet: GovernedMemoryPacketInput, allow_stale: bool | None = None) -> dict[str, Any]:
        if not self.canImportPacket(packet, allow_stale=allow_stale):
            return {"imported": False, "reason": "packet_not_approved_or_stale"}
        lead = self.mapEntityToLead(packet)
        event = {
            **lead,
            "packetId": packet["packetId"],
            "summary": self._sanitize_text(packet.get("summary", "")),
            "mappedSignals": self.mapSignalsToRelationshipMemory(packet),
            "suggestedNotes": self.mapSignalsToLeadNotes(packet),
            "suggestedTasks": self.mapSignalsToTasks(packet),
            "suggestedCalendarDrafts": self.mapSignalsToCalendarDrafts(packet),
            "confidence": float(packet.get("confidence", 0.0)),
            "freshness": float(packet.get("freshness", 0.0)),
            "verificationStatus": packet.get("verificationStatus", "unverified"),
            "sensitivityLevel": packet.get("sensitivityLevel", "internal"),
            "sourceTrace": packet.get("sourceTrace", {}),
            "approvedForUse": packet.get("approvedForUse", False),
        }
        event_id = self.store.importRagMemoryPacket(event)
        return {"imported": True, "eventId": event_id, "leadId": lead["leadId"], "status": "imported"}

    def getLeadWorkspaceExternalContext(self, leadId: str) -> dict[str, Any]:
        context = self.store.getRagContextForLead(leadId)
        return {
            "section_title": "External Context",
            "collapsed": True,
            "display": "lead_workspace_secondary_section",
            "actions": ["Use in note", "Create task", "Ignore"],
            "public_visibility": False,
            "items": [self._render_event(event) for event in context["events"]],
        }

    def getTodaysWorkQueuePayload(self, leadId: str | None = None) -> dict[str, Any]:
        return {
            "section_title": "Today's Work Queue",
            "rag_panel": None,
            "external_context_collapsed": True,
            "rag_can_influence": ["suggested message", "next best question", "task suggestion", "meeting preparation", "lead notes"],
            "scoring_control": {
                "close_probability_engine": "existing_close_probability_engine",
                "deal_risk_engine": "existing_deal_risk_engine",
                "rag_replaces_scoring": False,
            },
            "memory_priority": ["user_agent_provided_memory", "verified_internal_memory", "rag_enrichment"],
            "leadId": leadId,
        }

    def _render_event(self, event: dict[str, Any]) -> dict[str, Any]:
        return {
            "eventId": event["id"],
            "summary": self._sanitize_text(event["summary"]),
            "signalLabels": [signal.get("signalType", "signal") for signal in event.get("mappedSignals", [])],
            "freshnessLabel": self._freshness_label(event.get("freshness", 0.0)),
            "confidenceLabel": self._confidence_label(event.get("confidence", 0.0)),
            "status": event["status"],
        }

    def _is_stale(self, packet: GovernedMemoryPacketInput) -> bool:
        if float(packet.get("freshness", 1.0)) < 0.25:
            return True
        now = datetime.now(timezone.utc)
        for signal in packet.get("signals", []):
            expires_at = signal.get("expiresAt")
            if expires_at:
                try:
                    if datetime.fromisoformat(expires_at) <= now:
                        return True
                except ValueError:
                    return True
        return False

    def _sanitize_text(self, text: str) -> str:
        text = re.sub(r"[A-Z0-9._%+-]+@[A-Z0-9.-]+\.[A-Z]{2,}", "[redacted-email]", text, flags=re.IGNORECASE)
        text = re.sub(r"(?:\+?\d[\d\s().-]{7,}\d)", "[redacted-phone]", text)
        text = re.sub(r"\b\d{1,5}\s+[A-Za-z0-9 .'-]+\s(?:Street|St|Road|Rd|Avenue|Ave|Lane|Ln|Drive|Dr|Block|Blk)\b", "[redacted-address]", text, flags=re.IGNORECASE)
        text = re.sub(r"\b(?:high risk|blacklist|do not rent|bad tenant|bad landlord)\b", "[redacted-private-label]", text, flags=re.IGNORECASE)
        return text

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
            return "normal"
        return "stale"

    def _task_title(self, signal_type: str | None) -> str:
        return {
            "move_in_timeline": "Confirm move-in timeline",
            "viewing_intent": "Schedule approved viewing follow-up",
            "verification_need": "Review verification status",
            "document_readiness": "Request missing rental documents",
        }.get(signal_type or "", "Review external context")
