from __future__ import annotations

import hashlib
import json
import re
from datetime import datetime, timezone
from typing import Any


TIMELINE_FILTERS = {"conversations", "tenancy", "matching", "verification", "consent"}
TIMELINE_FILTER_SOURCES = {
    "conversations": {"conversations"},
    "tenancy": {"tenancy", "viewing", "maintenance", "renewal"},
    "matching": {"matching"},
    "verification": {"verification"},
    "consent": {"consent"},
}
TIMELINE_SIDE_EFFECTS = {"autoSend": False, "autoReply": False, "autoPost": False}


class MemoryTimelineMixin:
    """Unified, privacy-safe memory timeline across rental and enrichment events."""

    def recordMemoryTimelineEvent(
        self,
        entityId: str,
        entityType: str,
        eventType: str,
        summary: str,
        source: str,
        relatedId: str | None = None,
        timestamp: str | None = None,
        metadata: dict[str, Any] | None = None,
    ) -> dict[str, Any]:
        created_at = timestamp or datetime.now(timezone.utc).isoformat()
        event_id = hashlib.sha1(f"memory-timeline:{entityId}:{entityType}:{eventType}:{source}:{created_at}:{summary}".encode()).hexdigest()
        self.store.conn.execute(
            """
            INSERT OR REPLACE INTO memory_timeline_events
            (id, entity_id, entity_type, event_type, summary, source, related_id, metadata, created_at)
            VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?)
            """,
            (
                event_id,
                entityId,
                entityType,
                eventType,
                self.sanitizePublicText(summary),
                source,
                relatedId,
                json.dumps(self._timeline_safe_metadata(metadata or {})),
                created_at,
            ),
        )
        self.store.conn.commit()
        return self._timeline_event(created_at, eventType, summary, source, relatedId=relatedId, eventId=event_id)

    def recordViewingEvent(
        self,
        entityId: str,
        entityType: str,
        summary: str,
        timestamp: str | None = None,
        tenancyId: str | None = None,
        propertyId: str | None = None,
    ) -> dict[str, Any]:
        return self.recordMemoryTimelineEvent(
            entityId,
            entityType,
            "viewing_event",
            summary,
            "viewing",
            relatedId=tenancyId or propertyId,
            timestamp=timestamp,
            metadata={"tenancyId": tenancyId, "propertyId": propertyId},
        )

    def getUnifiedMemoryTimeline(self, entityId: str, entityType: str, filters: list[str] | None = None) -> dict[str, Any]:
        normalized_filters = [item for item in (filters or []) if item in TIMELINE_FILTERS]
        events: list[dict[str, Any]] = []
        events.extend(self._timeline_custom_events(entityId, entityType))
        events.extend(self._timeline_intake_events(entityId))
        events.extend(self._timeline_verification_events(entityId, entityType))
        events.extend(self._timeline_conversation_events(entityId, entityType))
        events.extend(self._timeline_lifecycle_events(entityId, entityType))
        events.extend(self._timeline_matching_events(entityId))
        events.extend(self._timeline_consent_events(entityId, entityType))
        events.extend(self._timeline_enrichment_events(entityId))
        events = self._apply_timeline_filters(events, normalized_filters)
        return {
            "entityId": entityId,
            "entityType": entityType,
            "filters": normalized_filters,
            "items": sorted(events, key=lambda event: event["timestamp"]),
            "rawSourceTracePublic": False,
            "internalScoresPublic": False,
            "sideEffects": TIMELINE_SIDE_EFFECTS.copy(),
        }

    def renderTimelineTab(self, entityId: str, entityType: str, filters: list[str] | None = None, role: str = "admin", sessionToken: str | None = None) -> dict[str, Any]:
        role = self._resolve_role(role, sessionToken) if hasattr(self, "_resolve_role") else role
        timeline = self.getUnifiedMemoryTimeline(entityId, entityType, filters=filters)
        return {
            "tab_title": "Timeline",
            "display": "workspace_tab",
            "role": role,
            "filters": ["conversations", "tenancy", "matching", "verification", "consent"],
            "active_filters": timeline["filters"],
            "count_badge": len(timeline["items"]),
            "empty_state": "No memory timeline events found." if not timeline["items"] else None,
            "items": [
                {
                    "timestamp": item["timestamp"],
                    "event_type": item["eventType"],
                    "summary": item["summary"],
                    "source": item["source"],
                }
                for item in timeline["items"]
            ],
            "raw_source_trace_public": False,
            "internal_scores_public": False,
            "public_visibility": False,
            "side_effects": TIMELINE_SIDE_EFFECTS.copy(),
        }

    def _timeline_custom_events(self, entity_id: str, entity_type: str) -> list[dict[str, Any]]:
        rows = self.store.conn.execute(
            "SELECT * FROM memory_timeline_events WHERE entity_id=? AND entity_type=? ORDER BY created_at ASC",
            (entity_id, entity_type),
        ).fetchall()
        return [self._timeline_event(row["created_at"], row["event_type"], row["summary"], row["source"], relatedId=row["related_id"], eventId=row["id"]) for row in rows]

    def _timeline_intake_events(self, entity_id: str) -> list[dict[str, Any]]:
        rows = self.store.conn.execute(
            """
            SELECT ri.*, rs.entity_id
            FROM rag_intake_review_items ri
            JOIN raw_sources rs ON rs.id=ri.source_id
            WHERE rs.entity_id=?
            ORDER BY ri.created_at ASC
            """,
            (entity_id,),
        ).fetchall()
        return [
            self._timeline_event(row["created_at"], "intake_review_created", f"{row['suggested_draft_type']} from {row['source_type']} is {row['status']}.", "intake", relatedId=row["id"])
            for row in rows
        ]

    def _timeline_verification_events(self, entity_id: str, entity_type: str) -> list[dict[str, Any]]:
        if entity_type not in {"tenant", "landlord", "person", "admin", "unknown"}:
            return []
        rows = self.store.conn.execute("SELECT * FROM person_verifications WHERE person_id=? ORDER BY created_at ASC", (entity_id,)).fetchall()
        events = [self._timeline_event(row["created_at"], "verification_created", f"Verification status: {self._neutral_timeline_status(row['verification_status'])}.", "verification", relatedId=row["id"]) for row in rows]
        signal_rows = self.store.conn.execute(
            """
            SELECT vs.*, pv.person_id
            FROM verification_signals vs
            JOIN person_verifications pv ON pv.id=vs.verification_id
            WHERE pv.person_id=?
            ORDER BY vs.created_at ASC
            """,
            (entity_id,),
        ).fetchall()
        events.extend(
            self._timeline_event(row["created_at"], "verification_signal", f"{row['signal_type']} check result: {self._neutral_timeline_status(row['result'])}.", "verification", relatedId=row["verification_id"])
            for row in signal_rows
        )
        return events

    def _timeline_conversation_events(self, entity_id: str, entity_type: str) -> list[dict[str, Any]]:
        if entity_type == "tenancy":
            where, params = "tenancy_id=?", (entity_id,)
        elif entity_type == "property":
            where, params = "property_id=?", (entity_id,)
        else:
            where, params = "participant_id=?", (entity_id,)
        rows = self.store.conn.execute(f"SELECT * FROM conversation_memory_events WHERE {where} ORDER BY created_at ASC", params).fetchall()
        return [self._timeline_event(row["created_at"], "conversation_message", row["summary"], "conversations", relatedId=row["conversation_id"], eventId=row["id"]) for row in rows]

    def _timeline_lifecycle_events(self, entity_id: str, entity_type: str) -> list[dict[str, Any]]:
        where = "rl.tenancy_id=?" if entity_type == "tenancy" else "rl.property_id=?" if entity_type == "property" else "rl.tenant_id=?"
        rows = self.store.conn.execute(
            f"""
            SELECT rle.*
            FROM rental_lifecycle_events rle
            JOIN rental_lifecycles rl ON rl.tenancy_id=rle.tenancy_id
            WHERE {where}
            ORDER BY rle.created_at ASC
            """,
            (entity_id,),
        ).fetchall()
        events = [self._timeline_event(row["created_at"], row["event_type"], row["summary"], self._lifecycle_timeline_source(row["event_type"], row["stage"]), relatedId=row["tenancy_id"], eventId=row["id"]) for row in rows]
        recommendation_rows = self.store.conn.execute(
            f"""
            SELECT rlr.*
            FROM rental_lifecycle_recommendations rlr
            JOIN rental_lifecycles rl ON rl.tenancy_id=rlr.tenancy_id
            WHERE {where}
            ORDER BY rlr.created_at ASC
            """,
            (entity_id,),
        ).fetchall()
        events.extend(
            self._timeline_event(row["created_at"], row["recommendation_type"], row["title"], "renewal" if row["recommendation_type"] == "renewal_recommendation" else "tenancy", relatedId=row["tenancy_id"], eventId=row["id"])
            for row in recommendation_rows
        )
        return events

    def _timeline_matching_events(self, entity_id: str) -> list[dict[str, Any]]:
        queue_rows = self.store.conn.execute(
            """
            SELECT mq.*
            FROM matching_queue mq
            LEFT JOIN tenant_intent_drafts td ON td.id=mq.draft_id
            LEFT JOIN property_profile_drafts pd ON pd.id=mq.draft_id
            LEFT JOIN rag_intake_review_items tri ON tri.id=td.review_item_id
            LEFT JOIN rag_intake_review_items pri ON pri.id=pd.review_item_id
            LEFT JOIN raw_sources trs ON trs.id=tri.source_id
            LEFT JOIN raw_sources prs ON prs.id=pri.source_id
            WHERE trs.entity_id=? OR prs.entity_id=? OR mq.payload LIKE ?
            ORDER BY mq.created_at ASC
            """,
            (entity_id, entity_id, f"%{entity_id}%"),
        ).fetchall()
        events = [self._timeline_event(row["created_at"], "matching_queue", f"{row['draft_type']} entered {row['queue_status']}.", "matching", relatedId=row["id"]) for row in queue_rows]
        queue_ids = [row["id"] for row in queue_rows]
        if queue_ids:
            placeholders = ",".join("?" for _ in queue_ids)
            rec_rows = self.store.conn.execute(
                f"SELECT * FROM match_recommendations WHERE tenant_queue_id IN ({placeholders}) OR property_queue_id IN ({placeholders}) ORDER BY created_at ASC",
                (*queue_ids, *queue_ids),
            ).fetchall()
            events.extend(self._timeline_event(row["created_at"], "match_recommendation", row["reason"], "matching", relatedId=row["id"]) for row in rec_rows)
        return events

    def _timeline_consent_events(self, entity_id: str, entity_type: str) -> list[dict[str, Any]]:
        if entity_type not in {"tenant", "landlord", "person", "admin", "unknown"}:
            return []
        rows = self.store.conn.execute("SELECT * FROM consent_records WHERE person_id=? ORDER BY created_at ASC", (entity_id,)).fetchall()
        return [self._timeline_event(row["updated_at"] or row["created_at"], f"consent_{row['status']}", f"{row['consent_type']} consent is {self._neutral_timeline_status(row['status'])}.", "consent", relatedId=row["id"]) for row in rows]

    def _timeline_enrichment_events(self, entity_id: str) -> list[dict[str, Any]]:
        rows = self.store.conn.execute(
            "SELECT * FROM rag_enrichment_events WHERE lead_id=? OR entity_id=? ORDER BY created_at ASC",
            (entity_id, entity_id),
        ).fetchall()
        return [self._timeline_event(row["created_at"], "rag_enrichment_event", row["summary"], "enrichment", relatedId=row["id"]) for row in rows]

    def _apply_timeline_filters(self, events: list[dict[str, Any]], filters: list[str]) -> list[dict[str, Any]]:
        if not filters:
            return events
        allowed_sources = set().union(*(TIMELINE_FILTER_SOURCES[item] for item in filters))
        return [event for event in events if event["source"] in allowed_sources]

    def _timeline_event(self, timestamp: str, eventType: str, summary: str, source: str, relatedId: str | None = None, eventId: str | None = None) -> dict[str, Any]:
        safe_summary = self._timeline_safe_text(str(summary))
        return {
            "id": eventId or hashlib.sha1(f"timeline:{timestamp}:{eventType}:{source}:{safe_summary}".encode()).hexdigest(),
            "timestamp": timestamp,
            "eventType": eventType,
            "summary": safe_summary,
            "source": source,
            "relatedId": relatedId,
        }

    def _lifecycle_timeline_source(self, event_type: str, stage: str) -> str:
        if stage == "viewing" or "viewing" in event_type:
            return "viewing"
        if stage == "maintenance" or "maintenance" in event_type:
            return "maintenance"
        if stage.startswith("renewal") or "renewal" in event_type:
            return "renewal"
        return "tenancy"

    def _neutral_timeline_status(self, status: str) -> str:
        if status in {"accepted", "verified", "pass", "approved", "granted"}:
            return "Verified"
        if status in {"review_required", "needs_review", "fail", "conflict"}:
            return "Manual review required"
        if status in {"declined", "withdrawn", "denied", "consent_denied"}:
            return "Consent required"
        return "Verification pending"

    def _timeline_safe_metadata(self, metadata: dict[str, Any]) -> dict[str, Any]:
        blocked = {"sourceTrace", "rawSourceTrace", "confidence", "score", "riskFlags", "auditTrace"}
        return {key: self._timeline_safe_text(str(value)) for key, value in metadata.items() if key not in blocked and value is not None}

    def _timeline_safe_text(self, text: str) -> str:
        safe = self.sanitizePublicText(text)
        safe = re.sub(r"\b(?:sourceTrace|rawSourceTrace|raw source trace|source trace)\b", "[redacted-trace]", safe, flags=re.IGNORECASE)
        return safe
