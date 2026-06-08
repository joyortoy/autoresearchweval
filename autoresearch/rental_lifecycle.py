from __future__ import annotations

import hashlib
import json
from datetime import date, datetime, timedelta, timezone
from typing import Any


LIFECYCLE_STAGES = {
    "inquiry",
    "viewing",
    "application",
    "tenancy_active",
    "maintenance",
    "renewal_window",
    "renewal_offered",
    "renewed",
    "exited",
    "buying_interest",
}

LIFECYCLE_TRIGGERS = {
    "lease_start",
    "lease_end",
    "renewal_window",
    "maintenance_request",
    "inactivity",
    "buying_interest",
}

LIFECYCLE_SIDE_EFFECTS = {
    "autoSend": False,
    "autoReply": False,
    "autoPost": False,
    "autoRenew": False,
    "autoAdjustRent": False,
}


class RentalLifecycleMixin:
    """Recommendation-only lifecycle tracking for matched rental tenancies."""

    def createRentalLifecycle(
        self,
        tenancyId: str,
        tenantId: str,
        propertyId: str,
        leaseStart: str | None = None,
        leaseEnd: str | None = None,
        stage: str = "inquiry",
    ) -> dict[str, Any]:
        if stage not in LIFECYCLE_STAGES:
            raise ValueError(f"Unsupported lifecycle stage: {stage}")
        now = datetime.now(timezone.utc).isoformat()
        lifecycle_id = hashlib.sha1(f"rental-lifecycle:{tenancyId}".encode()).hexdigest()
        self.store.conn.execute(
            """
            INSERT INTO rental_lifecycles
            (id, tenancy_id, tenant_id, property_id, stage, lease_start, lease_end, last_activity_at,
             maintenance_open_count, health_status, health_summary, created_at, updated_at)
            VALUES (?, ?, ?, ?, ?, ?, ?, ?, 0, 'stable', 'Lifecycle created; recommendations only.', ?, ?)
            ON CONFLICT(tenancy_id) DO UPDATE SET tenant_id=excluded.tenant_id,
                                                  property_id=excluded.property_id,
                                                  lease_start=COALESCE(excluded.lease_start, lease_start),
                                                  lease_end=COALESCE(excluded.lease_end, lease_end),
                                                  updated_at=excluded.updated_at
            """,
            (lifecycle_id, tenancyId, tenantId, propertyId, stage, leaseStart, leaseEnd, now, now, now),
        )
        self._record_lifecycle_event(tenancyId, "lifecycle_created", stage, "Lifecycle tracking created for matched tenancy.", {"recommendationOnly": True}, now)
        self.store.conn.commit()
        return self.getRentalLifecycle(tenancyId)

    def getRentalLifecycle(self, tenancyId: str) -> dict[str, Any]:
        row = self.store.conn.execute("SELECT * FROM rental_lifecycles WHERE tenancy_id=?", (tenancyId,)).fetchone()
        if row is None:
            raise ValueError(f"Unknown tenancy lifecycle: {tenancyId}")
        return self._lifecycle_to_dict(row)

    def advanceLifecycleStage(self, tenancyId: str, stage: str, reason: str = "manual_update") -> dict[str, Any]:
        if stage not in LIFECYCLE_STAGES:
            raise ValueError(f"Unsupported lifecycle stage: {stage}")
        now = datetime.now(timezone.utc).isoformat()
        self.store.conn.execute("UPDATE rental_lifecycles SET stage=?, last_activity_at=?, updated_at=? WHERE tenancy_id=?", (stage, now, now, tenancyId))
        self._record_lifecycle_event(tenancyId, "stage_changed", stage, f"Lifecycle moved to {stage}.", {"reason": reason}, now)
        self.store.conn.commit()
        return self.getRentalLifecycle(tenancyId)

    def recordLifecycleTrigger(self, tenancyId: str, triggerType: str, payload: dict[str, Any] | None = None) -> dict[str, Any]:
        if triggerType not in LIFECYCLE_TRIGGERS:
            raise ValueError(f"Unsupported lifecycle trigger: {triggerType}")
        lifecycle = self.getRentalLifecycle(tenancyId)
        payload = payload or {}
        now = payload.get("observedAt") or datetime.now(timezone.utc).isoformat()
        stage = lifecycle["stage"]
        summary = f"Lifecycle trigger observed: {triggerType}."
        if triggerType == "lease_start":
            stage = "tenancy_active"
            summary = "Lease start reached; tenancy is active."
            self._upsert_lifecycle_recommendation(tenancyId, "reminder", "Confirm tenancy activation checklist", "Review handover, contact preferences, and maintenance reporting path.", "medium", now)
        elif triggerType == "lease_end":
            stage = "exited"
            summary = "Lease end reached; review exit or renewal outcome."
            self._upsert_lifecycle_recommendation(tenancyId, "reminder", "Review lease-end outcome", "Confirm whether the tenant renewed, exited, or needs follow-up.", "high", now)
        elif triggerType == "renewal_window":
            stage = "renewal_window"
            summary = "Renewal window opened; prepare recommendation only."
            self._upsert_lifecycle_recommendation(tenancyId, "renewal_recommendation", "Prepare renewal recommendation", "Review tenancy health, market context, and landlord/tenant intent before any offer.", "high", now)
        elif triggerType == "maintenance_request":
            return self.recordMaintenanceRequest(tenancyId, payload.get("summary", "Maintenance request recorded."), now, payload)
        elif triggerType == "inactivity":
            summary = "Inactivity detected; create follow-up reminder only."
            self._upsert_lifecycle_recommendation(tenancyId, "reminder", "Check in on inactive tenancy", "Review recent conversation history before drafting any follow-up.", "medium", now)
        elif triggerType == "buying_interest":
            stage = "buying_interest"
            summary = "Buying interest detected; prepare advisory handoff recommendation only."
            self._upsert_lifecycle_recommendation(tenancyId, "buying_interest", "Review buying-interest signal", "Create a reviewed advisory follow-up; do not replace rental lifecycle decisions.", "medium", now)
        self.store.conn.execute("UPDATE rental_lifecycles SET stage=?, last_activity_at=?, updated_at=? WHERE tenancy_id=?", (stage, now, now, tenancyId))
        self._record_lifecycle_event(tenancyId, triggerType, stage, summary, payload, now)
        self.store.conn.commit()
        return self.evaluateRentalLifecycle(tenancyId, asOf=now)

    def recordMaintenanceRequest(self, tenancyId: str, summary: str, reportedAt: str | None = None, payload: dict[str, Any] | None = None) -> dict[str, Any]:
        safe_summary = self.sanitizePublicText(summary)
        now = reportedAt or datetime.now(timezone.utc).isoformat()
        row = self.store.conn.execute("SELECT maintenance_open_count FROM rental_lifecycles WHERE tenancy_id=?", (tenancyId,)).fetchone()
        if row is None:
            raise ValueError(f"Unknown tenancy lifecycle: {tenancyId}")
        self.store.conn.execute(
            "UPDATE rental_lifecycles SET stage='maintenance', maintenance_open_count=?, last_activity_at=?, updated_at=? WHERE tenancy_id=?",
            (row["maintenance_open_count"] + 1, now, now, tenancyId),
        )
        self._record_lifecycle_event(tenancyId, "maintenance_request", "maintenance", safe_summary, payload or {}, now)
        self._upsert_lifecycle_recommendation(tenancyId, "reminder", "Review maintenance request", safe_summary, "high", now)
        self.store.conn.commit()
        return self.evaluateRentalLifecycle(tenancyId, asOf=now)

    def evaluateRentalLifecycle(self, tenancyId: str, asOf: str | None = None) -> dict[str, Any]:
        lifecycle = self.getRentalLifecycle(tenancyId)
        as_of_dt = self._parse_dt(asOf) or datetime.now(timezone.utc)
        stage = lifecycle["stage"]
        health_flags: list[str] = []
        lease_start = self._parse_date(lifecycle.get("leaseStart"))
        lease_end = self._parse_date(lifecycle.get("leaseEnd"))
        if lease_start and as_of_dt.date() >= lease_start and stage in {"inquiry", "viewing", "application"}:
            self.recordLifecycleTrigger(tenancyId, "lease_start", {"observedAt": as_of_dt.isoformat()})
            lifecycle = self.getRentalLifecycle(tenancyId)
            stage = lifecycle["stage"]
        if lease_end:
            days_to_end = (lease_end - as_of_dt.date()).days
            if 0 <= days_to_end <= 60 and stage not in {"renewal_window", "renewal_offered", "renewed", "exited"}:
                self.store.conn.execute("UPDATE rental_lifecycles SET stage='renewal_window', updated_at=? WHERE tenancy_id=?", (as_of_dt.isoformat(), tenancyId))
                self._record_lifecycle_event(tenancyId, "renewal_window", "renewal_window", "Renewal window opened; recommendation only.", {"daysToLeaseEnd": days_to_end}, as_of_dt.isoformat())
                self._upsert_lifecycle_recommendation(tenancyId, "renewal_recommendation", "Prepare renewal recommendation", f"Lease ends in {days_to_end} days. Review tenancy health before proposing next steps.", "high", as_of_dt.isoformat())
                stage = "renewal_window"
            elif days_to_end < 0 and stage not in {"renewed", "exited", "buying_interest"}:
                self.store.conn.execute("UPDATE rental_lifecycles SET stage='exited', updated_at=? WHERE tenancy_id=?", (as_of_dt.isoformat(), tenancyId))
                self._record_lifecycle_event(tenancyId, "lease_end", "exited", "Lease end passed; review exit status.", {"daysSinceLeaseEnd": abs(days_to_end)}, as_of_dt.isoformat())
                self._upsert_lifecycle_recommendation(tenancyId, "reminder", "Confirm lease-end status", "Lease end has passed. Confirm renewal, exit, or admin correction.", "high", as_of_dt.isoformat())
                stage = "exited"
        last_activity = self._parse_dt(lifecycle.get("lastActivityAt"))
        if last_activity and as_of_dt - last_activity > timedelta(days=14) and stage not in {"exited", "renewed"}:
            health_flags.append("inactive")
            self._upsert_lifecycle_recommendation(tenancyId, "reminder", "Review inactive tenancy", "No recent lifecycle activity; review conversation timeline before follow-up.", "medium", as_of_dt.isoformat())
        if lifecycle.get("maintenanceOpenCount", 0) > 0:
            health_flags.append("open_maintenance")
        health_status = "attention_needed" if health_flags else "stable"
        health_summary = self._build_health_summary(stage, health_flags)
        self.store.conn.execute("UPDATE rental_lifecycles SET health_status=?, health_summary=?, updated_at=? WHERE tenancy_id=?", (health_status, health_summary, as_of_dt.isoformat(), tenancyId))
        self.store.conn.commit()
        return {
            "lifecycle": self.getRentalLifecycle(tenancyId),
            "recommendations": self.listLifecycleRecommendations(tenancyId),
            "tenancyHealthSummary": self.getTenancyHealthSummary(tenancyId),
            "outputType": "recommendation_only",
            "sideEffects": LIFECYCLE_SIDE_EFFECTS.copy(),
        }

    def listLifecycleRecommendations(self, tenancyId: str) -> list[dict[str, Any]]:
        rows = self.store.conn.execute("SELECT * FROM rental_lifecycle_recommendations WHERE tenancy_id=? ORDER BY created_at ASC", (tenancyId,)).fetchall()
        return [self._recommendation_to_dict(row) for row in rows]

    def getTenancyHealthSummary(self, tenancyId: str) -> dict[str, Any]:
        lifecycle = self.getRentalLifecycle(tenancyId)
        return {
            "tenancyId": tenancyId,
            "stage": lifecycle["stage"],
            "healthStatus": lifecycle["healthStatus"],
            "summary": lifecycle["healthSummary"],
            "recommendationOnly": True,
            "sideEffects": LIFECYCLE_SIDE_EFFECTS.copy(),
        }

    def getRentalLifecycleTimeline(self, tenancyId: str, includeConversations: bool = True) -> dict[str, Any]:
        rows = self.store.conn.execute("SELECT * FROM rental_lifecycle_events WHERE tenancy_id=? ORDER BY created_at ASC", (tenancyId,)).fetchall()
        timeline = [self._lifecycle_event_to_dict(row) for row in rows]
        if includeConversations:
            conversation_rows = self.store.conn.execute("SELECT * FROM conversation_memory_events WHERE tenancy_id=? ORDER BY created_at ASC", (tenancyId,)).fetchall()
            timeline.extend(
                {
                    "eventId": row["id"],
                    "source": "conversation",
                    "conversationId": row["conversation_id"],
                    "messageId": row["message_id"],
                    "summary": self.sanitizePublicText(row["summary"]),
                    "createdAt": row["created_at"],
                }
                for row in conversation_rows
            )
        return {
            "tenancyId": tenancyId,
            "timeline": sorted(timeline, key=lambda event: event["createdAt"]),
            "sideEffects": LIFECYCLE_SIDE_EFFECTS.copy(),
        }

    def _record_lifecycle_event(self, tenancy_id: str, event_type: str, stage: str, summary: str, payload: dict[str, Any], created_at: str) -> str:
        event_id = hashlib.sha1(f"lifecycle-event:{tenancy_id}:{event_type}:{stage}:{created_at}:{summary}".encode()).hexdigest()
        self.store.conn.execute(
            """
            INSERT OR REPLACE INTO rental_lifecycle_events
            (id, tenancy_id, event_type, stage, summary, payload, created_at)
            VALUES (?, ?, ?, ?, ?, ?, ?)
            """,
            (event_id, tenancy_id, event_type, stage, self.sanitizePublicText(summary), json.dumps(payload), created_at),
        )
        return event_id

    def _upsert_lifecycle_recommendation(self, tenancy_id: str, recommendation_type: str, title: str, detail: str, priority: str, due_at: str | None = None) -> str:
        now = datetime.now(timezone.utc).isoformat()
        rec_id = hashlib.sha1(f"lifecycle-rec:{tenancy_id}:{recommendation_type}:{title}".encode()).hexdigest()
        audit_trace = {
            "recommendationOnly": True,
            "autoSend": False,
            "autoRenew": False,
            "autoAdjustRent": False,
        }
        self.store.conn.execute(
            """
            INSERT INTO rental_lifecycle_recommendations
            (id, tenancy_id, recommendation_type, title, detail, priority, status, due_at, audit_trace, created_at, updated_at)
            VALUES (?, ?, ?, ?, ?, ?, 'pending', ?, ?, ?, ?)
            ON CONFLICT(id) DO UPDATE SET detail=excluded.detail,
                                          priority=excluded.priority,
                                          status='pending',
                                          due_at=excluded.due_at,
                                          audit_trace=excluded.audit_trace,
                                          updated_at=excluded.updated_at
            """,
            (rec_id, tenancy_id, recommendation_type, self.sanitizePublicText(title), self.sanitizePublicText(detail), priority, due_at, json.dumps(audit_trace), now, now),
        )
        return rec_id

    def _lifecycle_to_dict(self, row: Any) -> dict[str, Any]:
        return {
            "id": row["id"],
            "tenancyId": row["tenancy_id"],
            "tenantId": row["tenant_id"],
            "propertyId": row["property_id"],
            "stage": row["stage"],
            "leaseStart": row["lease_start"],
            "leaseEnd": row["lease_end"],
            "lastActivityAt": row["last_activity_at"],
            "maintenanceOpenCount": row["maintenance_open_count"],
            "healthStatus": row["health_status"],
            "healthSummary": row["health_summary"],
            "createdAt": row["created_at"],
            "updatedAt": row["updated_at"],
        }

    def _lifecycle_event_to_dict(self, row: Any) -> dict[str, Any]:
        return {
            "eventId": row["id"],
            "source": "lifecycle",
            "eventType": row["event_type"],
            "stage": row["stage"],
            "summary": self.sanitizePublicText(row["summary"]),
            "payload": json.loads(row["payload"] or "{}"),
            "createdAt": row["created_at"],
        }

    def _recommendation_to_dict(self, row: Any) -> dict[str, Any]:
        return {
            "id": row["id"],
            "tenancyId": row["tenancy_id"],
            "recommendationType": row["recommendation_type"],
            "title": row["title"],
            "detail": row["detail"],
            "priority": row["priority"],
            "status": row["status"],
            "dueAt": row["due_at"],
            "auditTrace": json.loads(row["audit_trace"] or "{}"),
        }

    def _build_health_summary(self, stage: str, health_flags: list[str]) -> str:
        if not health_flags:
            return f"Tenancy lifecycle is in {stage}; no automatic action will be taken."
        labels = ", ".join(health_flags)
        return f"Tenancy lifecycle is in {stage} with {labels}; review recommendations before any operator action."

    def _parse_dt(self, value: str | None) -> datetime | None:
        if not value:
            return None
        try:
            normalized = value.replace("Z", "+00:00")
            parsed = datetime.fromisoformat(normalized)
            return parsed if parsed.tzinfo else parsed.replace(tzinfo=timezone.utc)
        except ValueError:
            return None

    def _parse_date(self, value: str | None) -> date | None:
        if not value:
            return None
        try:
            return date.fromisoformat(value[:10])
        except ValueError:
            return None
