from __future__ import annotations

import hashlib
import json
import sqlite3
from datetime import datetime, timezone
from typing import Any


class EnrichmentStore:
    def __init__(self, db_path: str = ":memory:") -> None:
        self.conn = sqlite3.connect(db_path)
        self.conn.row_factory = sqlite3.Row
        self._init_schema()

    def _init_schema(self) -> None:
        self.conn.executescript(
            """
            CREATE TABLE IF NOT EXISTS entities (
                id TEXT PRIMARY KEY,
                type TEXT NOT NULL,
                name TEXT NOT NULL,
                canonical_url TEXT,
                created_at TEXT NOT NULL,
                updated_at TEXT NOT NULL
            );
            CREATE TABLE IF NOT EXISTS raw_sources (
                id TEXT PRIMARY KEY,
                entity_id TEXT NOT NULL,
                source_url TEXT NOT NULL,
                source_type TEXT NOT NULL,
                raw_text TEXT NOT NULL,
                fetched_at TEXT NOT NULL,
                content_hash TEXT NOT NULL,
                import_status TEXT NOT NULL DEFAULT 'imported',
                import_priority TEXT NOT NULL DEFAULT 'medium',
                first_seen_at TEXT,
                last_seen_at TEXT,
                imported_at TEXT,
                processed_at TEXT,
                next_refresh_at TEXT,
                expires_at TEXT,
                retry_count INTEGER NOT NULL DEFAULT 0,
                failure_reason TEXT,
                freshness_window_hours INTEGER NOT NULL DEFAULT 72,
                source_recency_label TEXT NOT NULL DEFAULT 'fresh',
                FOREIGN KEY(entity_id) REFERENCES entities(id)
            );
            CREATE TABLE IF NOT EXISTS signals (
                id TEXT PRIMARY KEY,
                entity_id TEXT NOT NULL,
                source_id TEXT NOT NULL,
                signal_type TEXT NOT NULL,
                content TEXT NOT NULL,
                confidence REAL NOT NULL,
                freshness_score REAL NOT NULL,
                decay_rate REAL NOT NULL,
                verification_status TEXT NOT NULL,
                sensitivity_level TEXT NOT NULL,
                observed_at TEXT NOT NULL,
                expires_at TEXT NOT NULL,
                created_at TEXT NOT NULL,
                FOREIGN KEY(entity_id) REFERENCES entities(id),
                FOREIGN KEY(source_id) REFERENCES raw_sources(id)
            );
            CREATE TABLE IF NOT EXISTS memory_packets (
                id TEXT PRIMARY KEY,
                entity_id TEXT NOT NULL,
                signal_ids TEXT NOT NULL,
                summary TEXT NOT NULL,
                weight REAL NOT NULL,
                status TEXT NOT NULL,
                audit_trace TEXT NOT NULL,
                updated_at TEXT NOT NULL,
                FOREIGN KEY(entity_id) REFERENCES entities(id)
            );
            CREATE TABLE IF NOT EXISTS rag_intake_review_items (
                id TEXT PRIMARY KEY,
                source_id TEXT NOT NULL,
                source_type TEXT NOT NULL,
                source_url TEXT NOT NULL,
                raw_text_preview TEXT NOT NULL,
                entity_type TEXT NOT NULL,
                extracted_signals TEXT NOT NULL,
                confidence REAL NOT NULL,
                freshness REAL NOT NULL,
                suggested_draft_type TEXT NOT NULL,
                suggested_draft_payload TEXT NOT NULL,
                status TEXT NOT NULL,
                priority TEXT NOT NULL DEFAULT 'medium',
                import_status TEXT NOT NULL DEFAULT 'review_ready',
                import_priority TEXT NOT NULL DEFAULT 'medium',
                source_recency_label TEXT NOT NULL DEFAULT 'fresh',
                privacy_flags TEXT NOT NULL,
                review_reason TEXT,
                review_notes TEXT,
                duplicate_of TEXT,
                created_at TEXT NOT NULL,
                updated_at TEXT NOT NULL,
                FOREIGN KEY(source_id) REFERENCES raw_sources(id)
            );
            CREATE TABLE IF NOT EXISTS rag_intake_audit_events (
                id TEXT PRIMARY KEY,
                review_item_id TEXT NOT NULL,
                event_type TEXT NOT NULL,
                payload TEXT NOT NULL,
                created_at TEXT NOT NULL,
                FOREIGN KEY(review_item_id) REFERENCES rag_intake_review_items(id)
            );
            CREATE TABLE IF NOT EXISTS tenant_intent_drafts (
                id TEXT PRIMARY KEY,
                review_item_id TEXT NOT NULL,
                payload TEXT NOT NULL,
                queue_status TEXT NOT NULL,
                created_at TEXT NOT NULL,
                FOREIGN KEY(review_item_id) REFERENCES rag_intake_review_items(id)
            );
            CREATE TABLE IF NOT EXISTS property_profile_drafts (
                id TEXT PRIMARY KEY,
                review_item_id TEXT NOT NULL,
                payload TEXT NOT NULL,
                queue_status TEXT NOT NULL,
                created_at TEXT NOT NULL,
                FOREIGN KEY(review_item_id) REFERENCES rag_intake_review_items(id)
            );
            CREATE TABLE IF NOT EXISTS area_intelligence_notes (
                id TEXT PRIMARY KEY,
                review_item_id TEXT NOT NULL,
                payload TEXT NOT NULL,
                created_at TEXT NOT NULL,
                FOREIGN KEY(review_item_id) REFERENCES rag_intake_review_items(id)
            );
            CREATE TABLE IF NOT EXISTS acquisition_tasks (
                id TEXT PRIMARY KEY,
                review_item_id TEXT NOT NULL,
                payload TEXT NOT NULL,
                status TEXT NOT NULL,
                created_at TEXT NOT NULL,
                FOREIGN KEY(review_item_id) REFERENCES rag_intake_review_items(id)
            );
            CREATE TABLE IF NOT EXISTS matching_queue (
                id TEXT PRIMARY KEY,
                draft_id TEXT NOT NULL,
                draft_type TEXT NOT NULL,
                queue_status TEXT NOT NULL,
                payload TEXT NOT NULL,
                created_at TEXT NOT NULL
            );
            CREATE TABLE IF NOT EXISTS match_recommendations (
                id TEXT PRIMARY KEY,
                tenant_queue_id TEXT NOT NULL,
                property_queue_id TEXT NOT NULL,
                reason TEXT NOT NULL,
                status TEXT NOT NULL,
                created_at TEXT NOT NULL
            );
            CREATE TABLE IF NOT EXISTS person_verifications (
                id TEXT PRIMARY KEY,
                person_type TEXT NOT NULL,
                person_id TEXT NOT NULL,
                phone_hash TEXT,
                email_hash TEXT,
                consent_status TEXT NOT NULL DEFAULT 'not_requested',
                verification_status TEXT NOT NULL DEFAULT 'unverified',
                verification_signals TEXT NOT NULL DEFAULT '[]',
                risk_flags TEXT NOT NULL DEFAULT '[]',
                notes TEXT,
                created_at TEXT NOT NULL,
                updated_at TEXT NOT NULL
            );
            CREATE TABLE IF NOT EXISTS verification_signals (
                id TEXT PRIMARY KEY,
                verification_id TEXT NOT NULL,
                signal_type TEXT NOT NULL,
                result TEXT NOT NULL,
                confidence TEXT NOT NULL,
                source TEXT NOT NULL,
                public_safe INTEGER NOT NULL,
                created_at TEXT NOT NULL,
                FOREIGN KEY(verification_id) REFERENCES person_verifications(id)
            );
            CREATE TABLE IF NOT EXISTS verification_audit_events (
                id TEXT PRIMARY KEY,
                verification_id TEXT NOT NULL,
                event_type TEXT NOT NULL,
                payload TEXT NOT NULL,
                created_at TEXT NOT NULL,
                FOREIGN KEY(verification_id) REFERENCES person_verifications(id)
            );
            CREATE TABLE IF NOT EXISTS rag_enrichment_events (
                id TEXT PRIMARY KEY,
                packet_id TEXT NOT NULL,
                lead_id TEXT NOT NULL,
                entity_id TEXT NOT NULL,
                entity_type TEXT NOT NULL,
                summary TEXT NOT NULL,
                mapped_signals TEXT NOT NULL,
                suggested_notes TEXT NOT NULL,
                suggested_tasks TEXT NOT NULL,
                suggested_calendar_drafts TEXT NOT NULL,
                confidence REAL NOT NULL,
                freshness REAL NOT NULL,
                verification_status TEXT NOT NULL,
                sensitivity_level TEXT NOT NULL,
                status TEXT NOT NULL,
                audit_trace TEXT NOT NULL,
                created_at TEXT NOT NULL,
                updated_at TEXT NOT NULL
            );
            CREATE TABLE IF NOT EXISTS consent_records (
                id TEXT PRIMARY KEY,
                person_id TEXT NOT NULL,
                person_type TEXT NOT NULL,
                consent_type TEXT NOT NULL,
                consent_version TEXT NOT NULL,
                status TEXT NOT NULL,
                notice_text TEXT NOT NULL,
                accepted_at TEXT,
                declined_at TEXT,
                withdrawn_at TEXT,
                source TEXT NOT NULL,
                ip_address TEXT,
                user_agent TEXT,
                created_at TEXT NOT NULL,
                updated_at TEXT NOT NULL
            );
            CREATE TABLE IF NOT EXISTS consent_action_blocks (
                id TEXT PRIMARY KEY,
                person_id TEXT NOT NULL,
                consent_type TEXT NOT NULL,
                action_name TEXT NOT NULL,
                reason TEXT NOT NULL,
                created_at TEXT NOT NULL
            );
            CREATE TABLE IF NOT EXISTS privacy_requests (
                id TEXT PRIMARY KEY,
                person_id TEXT NOT NULL,
                request_type TEXT NOT NULL,
                status TEXT NOT NULL,
                source TEXT NOT NULL,
                created_at TEXT NOT NULL,
                updated_at TEXT NOT NULL
            );
            CREATE TABLE IF NOT EXISTS reply_drafts (
                id TEXT PRIMARY KEY,
                original_message_preview TEXT NOT NULL,
                detected_intent TEXT NOT NULL,
                extracted_slots TEXT NOT NULL,
                memory_used_summary TEXT NOT NULL,
                draft_reply TEXT NOT NULL,
                risk_flags TEXT NOT NULL,
                status TEXT NOT NULL,
                created_at TEXT NOT NULL,
                updated_at TEXT NOT NULL
            );
            CREATE TABLE IF NOT EXISTS immutable_audit_events (
                id TEXT PRIMARY KEY,
                sequence INTEGER NOT NULL UNIQUE,
                actor_id TEXT NOT NULL,
                event_type TEXT NOT NULL,
                payload TEXT NOT NULL,
                previous_hash TEXT NOT NULL,
                event_hash TEXT NOT NULL,
                created_at TEXT NOT NULL
            );
            CREATE TRIGGER IF NOT EXISTS immutable_audit_events_no_update
            BEFORE UPDATE ON immutable_audit_events
            BEGIN
                SELECT RAISE(ABORT, 'immutable audit events are append-only');
            END;
            CREATE TRIGGER IF NOT EXISTS immutable_audit_events_no_delete
            BEFORE DELETE ON immutable_audit_events
            BEGIN
                SELECT RAISE(ABORT, 'immutable audit events are append-only');
            END;
            CREATE TABLE IF NOT EXISTS subscription_drafts (
                id TEXT PRIMARY KEY,
                tenant_id TEXT NOT NULL,
                landlord_id TEXT NOT NULL,
                property_id TEXT NOT NULL,
                tenancy_id TEXT NOT NULL,
                subscription_period TEXT NOT NULL,
                amount REAL NOT NULL,
                idempotency_key TEXT NOT NULL UNIQUE,
                status TEXT NOT NULL,
                created_at TEXT NOT NULL,
                updated_at TEXT NOT NULL
            );
            CREATE TABLE IF NOT EXISTS upload_records (
                id TEXT PRIMARY KEY,
                owner_id TEXT NOT NULL,
                owner_type TEXT NOT NULL,
                purpose TEXT NOT NULL,
                file_name TEXT NOT NULL,
                mime_type TEXT NOT NULL,
                size_bytes INTEGER NOT NULL,
                storage_provider TEXT NOT NULL,
                storage_path TEXT NOT NULL,
                scan_status TEXT NOT NULL,
                status TEXT NOT NULL,
                rejection_reason TEXT,
                created_at TEXT NOT NULL
            );
            CREATE TABLE IF NOT EXISTS upload_rate_limits (
                actor_id TEXT NOT NULL,
                window_start TEXT NOT NULL,
                upload_count INTEGER NOT NULL,
                rejected_count INTEGER NOT NULL,
                updated_at TEXT NOT NULL,
                PRIMARY KEY(actor_id, window_start)
            );
            CREATE TABLE IF NOT EXISTS upload_review_flags (
                id TEXT PRIMARY KEY,
                actor_id TEXT NOT NULL,
                reason TEXT NOT NULL,
                status TEXT NOT NULL,
                created_at TEXT NOT NULL
            );
            CREATE TABLE IF NOT EXISTS memory_timeline_events (
                id TEXT PRIMARY KEY,
                entity_id TEXT NOT NULL,
                entity_type TEXT NOT NULL,
                event_type TEXT NOT NULL,
                summary TEXT NOT NULL,
                source TEXT NOT NULL,
                related_id TEXT,
                metadata TEXT NOT NULL,
                created_at TEXT NOT NULL
            );
            CREATE TABLE IF NOT EXISTS rental_lifecycles (
                id TEXT PRIMARY KEY,
                tenancy_id TEXT NOT NULL UNIQUE,
                tenant_id TEXT NOT NULL,
                property_id TEXT NOT NULL,
                stage TEXT NOT NULL,
                lease_start TEXT,
                lease_end TEXT,
                last_activity_at TEXT NOT NULL,
                maintenance_open_count INTEGER NOT NULL DEFAULT 0,
                health_status TEXT NOT NULL,
                health_summary TEXT NOT NULL,
                created_at TEXT NOT NULL,
                updated_at TEXT NOT NULL
            );
            CREATE TABLE IF NOT EXISTS rental_lifecycle_events (
                id TEXT PRIMARY KEY,
                tenancy_id TEXT NOT NULL,
                event_type TEXT NOT NULL,
                stage TEXT NOT NULL,
                summary TEXT NOT NULL,
                payload TEXT NOT NULL,
                created_at TEXT NOT NULL,
                FOREIGN KEY(tenancy_id) REFERENCES rental_lifecycles(tenancy_id)
            );
            CREATE TABLE IF NOT EXISTS rental_lifecycle_recommendations (
                id TEXT PRIMARY KEY,
                tenancy_id TEXT NOT NULL,
                recommendation_type TEXT NOT NULL,
                title TEXT NOT NULL,
                detail TEXT NOT NULL,
                priority TEXT NOT NULL,
                status TEXT NOT NULL,
                due_at TEXT,
                audit_trace TEXT NOT NULL,
                created_at TEXT NOT NULL,
                updated_at TEXT NOT NULL,
                FOREIGN KEY(tenancy_id) REFERENCES rental_lifecycles(tenancy_id)
            );
            CREATE TABLE IF NOT EXISTS conversations (
                id TEXT PRIMARY KEY,
                participant_id TEXT NOT NULL,
                participant_type TEXT NOT NULL,
                tenancy_id TEXT,
                property_id TEXT,
                messages TEXT NOT NULL DEFAULT '[]',
                created_at TEXT NOT NULL,
                updated_at TEXT NOT NULL
            );
            CREATE TABLE IF NOT EXISTS conversation_messages (
                id TEXT PRIMARY KEY,
                conversation_id TEXT NOT NULL,
                sender TEXT NOT NULL,
                timestamp TEXT NOT NULL,
                message_type TEXT NOT NULL,
                content TEXT NOT NULL,
                attachments TEXT NOT NULL,
                privacy_flags TEXT NOT NULL,
                created_at TEXT NOT NULL,
                FOREIGN KEY(conversation_id) REFERENCES conversations(id)
            );
            CREATE TABLE IF NOT EXISTS conversation_memory_events (
                id TEXT PRIMARY KEY,
                conversation_id TEXT NOT NULL,
                message_id TEXT NOT NULL,
                participant_id TEXT NOT NULL,
                participant_type TEXT NOT NULL,
                tenancy_id TEXT,
                property_id TEXT,
                summary TEXT NOT NULL,
                privacy_flags TEXT NOT NULL,
                created_at TEXT NOT NULL,
                FOREIGN KEY(conversation_id) REFERENCES conversations(id),
                FOREIGN KEY(message_id) REFERENCES conversation_messages(id)
            );
            CREATE TABLE IF NOT EXISTS reply_draft_edits (
                id TEXT PRIMARY KEY,
                draft_id TEXT NOT NULL,
                original_draft_text TEXT NOT NULL,
                edited_draft_text TEXT NOT NULL,
                edit_reason TEXT NOT NULL,
                edited_by TEXT NOT NULL,
                violations TEXT NOT NULL,
                status TEXT NOT NULL,
                edited_at TEXT NOT NULL,
                FOREIGN KEY(draft_id) REFERENCES reply_drafts(id)
            );
            CREATE TABLE IF NOT EXISTS roles (
                id TEXT PRIMARY KEY,
                name TEXT NOT NULL
            );
            CREATE TABLE IF NOT EXISTS permissions (
                id TEXT PRIMARY KEY,
                name TEXT NOT NULL
            );
            CREATE TABLE IF NOT EXISTS role_permissions (
                role_id TEXT NOT NULL,
                permission_id TEXT NOT NULL,
                PRIMARY KEY(role_id, permission_id),
                FOREIGN KEY(role_id) REFERENCES roles(id),
                FOREIGN KEY(permission_id) REFERENCES permissions(id)
            );
            CREATE TABLE IF NOT EXISTS users (
                id TEXT PRIMARY KEY,
                username TEXT NOT NULL UNIQUE,
                password_hash TEXT NOT NULL,
                role_id TEXT NOT NULL,
                status TEXT NOT NULL,
                created_at TEXT NOT NULL,
                updated_at TEXT NOT NULL,
                FOREIGN KEY(role_id) REFERENCES roles(id)
            );
            CREATE TABLE IF NOT EXISTS sessions (
                id TEXT PRIMARY KEY,
                user_id TEXT NOT NULL,
                session_token TEXT NOT NULL UNIQUE,
                created_at TEXT NOT NULL,
                expires_at TEXT NOT NULL,
                revoked_at TEXT,
                FOREIGN KEY(user_id) REFERENCES users(id)
            );
            CREATE TABLE IF NOT EXISTS auth_audit_events (
                id TEXT PRIMARY KEY,
                user_id TEXT,
                event_type TEXT NOT NULL,
                payload TEXT NOT NULL,
                created_at TEXT NOT NULL,
                FOREIGN KEY(user_id) REFERENCES users(id)
            );
            """
        )
        self._ensure_column("rag_intake_review_items", "priority", "TEXT NOT NULL DEFAULT 'medium'")
        self._ensure_column("rag_intake_review_items", "review_notes", "TEXT")
        self._ensure_column("rag_intake_review_items", "duplicate_of", "TEXT")
        self._ensure_column("rag_intake_review_items", "import_status", "TEXT NOT NULL DEFAULT 'review_ready'")
        self._ensure_column("rag_intake_review_items", "import_priority", "TEXT NOT NULL DEFAULT 'medium'")
        self._ensure_column("rag_intake_review_items", "source_recency_label", "TEXT NOT NULL DEFAULT 'fresh'")
        for column, definition in {
            "import_status": "TEXT NOT NULL DEFAULT 'imported'",
            "import_priority": "TEXT NOT NULL DEFAULT 'medium'",
            "first_seen_at": "TEXT",
            "last_seen_at": "TEXT",
            "imported_at": "TEXT",
            "processed_at": "TEXT",
            "next_refresh_at": "TEXT",
            "expires_at": "TEXT",
            "retry_count": "INTEGER NOT NULL DEFAULT 0",
            "failure_reason": "TEXT",
            "freshness_window_hours": "INTEGER NOT NULL DEFAULT 72",
            "source_recency_label": "TEXT NOT NULL DEFAULT 'fresh'",
        }.items():
            self._ensure_column("raw_sources", column, definition)
        self._seed_rbac()
        self.conn.commit()

    def _seed_rbac(self) -> None:
        role_permissions = {
            "super_admin": {"approve_rag_intake", "ignore_rag_intake", "edit_reply_draft", "mark_posted_manually", "create_task", "create_note", "approve_high_risk_item", "withdraw_consent", "manage_users", "manage_roles"},
            "admin": {"approve_rag_intake", "ignore_rag_intake", "edit_reply_draft", "mark_posted_manually", "create_task", "create_note", "approve_high_risk_item", "withdraw_consent"},
            "operator": {"approve_rag_intake", "ignore_rag_intake", "create_task", "create_note"},
            "reviewer": {"ignore_rag_intake"},
            "readonly": set(),
        }
        for role in role_permissions:
            self.conn.execute("INSERT OR IGNORE INTO roles (id, name) VALUES (?, ?)", (role, role))
        permissions = sorted({permission for values in role_permissions.values() for permission in values})
        for permission in permissions:
            self.conn.execute("INSERT OR IGNORE INTO permissions (id, name) VALUES (?, ?)", (permission, permission))
        for role, permissions_for_role in role_permissions.items():
            for permission in permissions_for_role:
                self.conn.execute("INSERT OR IGNORE INTO role_permissions (role_id, permission_id) VALUES (?, ?)", (role, permission))

    def _ensure_column(self, table: str, column: str, definition: str) -> None:
        existing = {row["name"] for row in self.conn.execute(f"PRAGMA table_info({table})").fetchall()}
        if column not in existing:
            self.conn.execute(f"ALTER TABLE {table} ADD COLUMN {column} {definition}")

    def importRagMemoryPacket(self, packet: dict[str, Any]) -> str:
        now = datetime.now(timezone.utc).isoformat()
        event_id = hashlib.sha1(f"rag-event:{packet['packetId']}:{packet['leadId']}".encode()).hexdigest()
        audit_trace = {
            "sourceTrace": packet.get("sourceTrace", {}),
            "approvedForUse": packet.get("approvedForUse", False),
            "rule": "governed-rag-packet->memory-os-enrichment-event",
            "raw_source_trace_public": False,
            "overwrite_existing_relationship_memory": False,
        }
        self.conn.execute(
            """
            INSERT OR REPLACE INTO rag_enrichment_events
            (id, packet_id, lead_id, entity_id, entity_type, summary, mapped_signals, suggested_notes, suggested_tasks,
             suggested_calendar_drafts, confidence, freshness, verification_status, sensitivity_level, status, audit_trace,
             created_at, updated_at)
            VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, 'imported', ?, COALESCE((SELECT created_at FROM rag_enrichment_events WHERE id=?), ?), ?)
            """,
            (
                event_id,
                packet["packetId"],
                packet["leadId"],
                packet["entityId"],
                packet["entityType"],
                packet["summary"],
                json.dumps(packet.get("mappedSignals", [])),
                json.dumps(packet.get("suggestedNotes", [])),
                json.dumps(packet.get("suggestedTasks", [])),
                json.dumps(packet.get("suggestedCalendarDrafts", [])),
                packet.get("confidence", 0.0),
                packet.get("freshness", 0.0),
                packet.get("verificationStatus", "unverified"),
                packet.get("sensitivityLevel", "internal"),
                json.dumps(audit_trace),
                event_id,
                now,
                now,
            ),
        )
        self.conn.commit()
        return event_id

    def listRagEnrichmentEvents(self, leadId: str) -> list[dict[str, Any]]:
        rows = self.conn.execute("SELECT * FROM rag_enrichment_events WHERE lead_id=? ORDER BY created_at DESC", (leadId,)).fetchall()
        return [self._rag_event_to_dict(row) for row in rows]

    def getRagContextForLead(self, leadId: str) -> dict[str, Any]:
        events = [event for event in self.listRagEnrichmentEvents(leadId) if event["status"] != "ignored"]
        return {
            "leadId": leadId,
            "events": events,
            "memoryPriority": ["user_agent_provided_memory", "verified_internal_memory", "rag_enrichment"],
            "ragReplacesExistingMemory": False,
        }

    def markRagEnrichmentUsed(self, eventId: str) -> dict[str, Any]:
        now = datetime.now(timezone.utc).isoformat()
        self.conn.execute("UPDATE rag_enrichment_events SET status='used', updated_at=? WHERE id=?", (now, eventId))
        self.conn.commit()
        return {"eventId": eventId, "status": "used"}

    def ignoreRagEnrichmentEvent(self, eventId: str, reason: str) -> dict[str, Any]:
        row = self.conn.execute("SELECT audit_trace FROM rag_enrichment_events WHERE id=?", (eventId,)).fetchone()
        audit = json.loads(row["audit_trace"] if row else "{}")
        audit["ignoreReason"] = reason
        now = datetime.now(timezone.utc).isoformat()
        self.conn.execute("UPDATE rag_enrichment_events SET status='ignored', audit_trace=?, updated_at=? WHERE id=?", (json.dumps(audit), now, eventId))
        self.conn.commit()
        return {"eventId": eventId, "status": "ignored", "reason": reason}

    def _rag_event_to_dict(self, row: sqlite3.Row) -> dict[str, Any]:
        return {
            "id": row["id"],
            "packetId": row["packet_id"],
            "leadId": row["lead_id"],
            "entityId": row["entity_id"],
            "entityType": row["entity_type"],
            "summary": row["summary"],
            "mappedSignals": json.loads(row["mapped_signals"] or "[]"),
            "suggestedNotes": json.loads(row["suggested_notes"] or "[]"),
            "suggestedTasks": json.loads(row["suggested_tasks"] or "[]"),
            "suggestedCalendarDrafts": json.loads(row["suggested_calendar_drafts"] or "[]"),
            "confidence": row["confidence"],
            "freshness": row["freshness"],
            "verificationStatus": row["verification_status"],
            "sensitivityLevel": row["sensitivity_level"],
            "status": row["status"],
            "auditTrace": json.loads(row["audit_trace"] or "{}"),
            "createdAt": row["created_at"],
            "updatedAt": row["updated_at"],
        }
