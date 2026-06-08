from __future__ import annotations

import hashlib
import json
from datetime import datetime, timezone
from typing import Any


class ConversationRuntimeMixin:
    """WhatsApp/bot conversation memory runtime.

    Stores tenant/landlord conversation messages as internal memory events and
    exposes sanitized history/timeline/search APIs. This runtime never sends,
    auto-replies, or posts messages.
    """

    def createConversation(
        self,
        participantId: str,
        participantType: str,
        tenancyId: str | None = None,
        propertyId: str | None = None,
        conversationId: str | None = None,
    ) -> dict[str, Any]:
        if participantType not in {"tenant", "landlord", "person", "admin", "unknown"}:
            raise ValueError("participantType must be tenant, landlord, person, admin, or unknown")
        now = datetime.now(timezone.utc).isoformat()
        conv_id = conversationId or hashlib.sha1(f"conversation:{participantType}:{participantId}:{tenancyId}:{propertyId}".encode()).hexdigest()
        self.store.conn.execute(
            """
            INSERT INTO conversations (id, participant_id, participant_type, tenancy_id, property_id, messages, created_at, updated_at)
            VALUES (?, ?, ?, ?, ?, '[]', ?, ?)
            ON CONFLICT(id) DO UPDATE SET tenancy_id=COALESCE(excluded.tenancy_id, tenancy_id),
                                          property_id=COALESCE(excluded.property_id, property_id),
                                          updated_at=excluded.updated_at
            """,
            (conv_id, participantId, participantType, tenancyId, propertyId, now, now),
        )
        self.store.conn.commit()
        self._ensure_conversation_memory_identity(participantId, participantType)
        return self._conversation_to_dict(self.store.conn.execute("SELECT * FROM conversations WHERE id=?", (conv_id,)).fetchone(), include_messages=True)

    def addConversationMessage(
        self,
        conversationId: str,
        sender: str,
        content: str,
        messageType: str = "text",
        attachments: list[dict[str, Any]] | None = None,
        timestamp: str | None = None,
    ) -> dict[str, Any]:
        conversation = self.store.conn.execute("SELECT * FROM conversations WHERE id=?", (conversationId,)).fetchone()
        if conversation is None:
            raise ValueError(f"Unknown conversation: {conversationId}")
        now = datetime.now(timezone.utc).isoformat()
        ts = timestamp or now
        privacy_flags = self._detect_privacy_flags(content)
        safe_content = self.sanitizePublicText(content)
        safe_attachments = self._sanitize_conversation_attachments(attachments or [])
        message_id = hashlib.sha1(f"message:{conversationId}:{sender}:{ts}:{safe_content}".encode()).hexdigest()
        self.store.conn.execute(
            """
            INSERT OR REPLACE INTO conversation_messages
            (id, conversation_id, sender, timestamp, message_type, content, attachments, privacy_flags, created_at)
            VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?)
            """,
            (message_id, conversationId, sender, ts, messageType, safe_content, json.dumps(safe_attachments), json.dumps(privacy_flags), now),
        )
        stored_messages = json.loads(conversation["messages"] or "[]") if "messages" in conversation.keys() else []
        stored_messages.append(
            {
                "messageId": message_id,
                "sender": sender,
                "timestamp": ts,
                "messageType": messageType,
                "content": safe_content,
                "attachments": safe_attachments,
                "privacyFlags": privacy_flags,
            }
        )
        self.store.conn.execute("UPDATE conversations SET messages=?, updated_at=? WHERE id=?", (json.dumps(stored_messages), now, conversationId))
        event_id = hashlib.sha1(f"conversation-event:{message_id}".encode()).hexdigest()
        summary = safe_content[:240]
        self.store.conn.execute(
            """
            INSERT OR REPLACE INTO conversation_memory_events
            (id, conversation_id, message_id, participant_id, participant_type, tenancy_id, property_id, summary,
             privacy_flags, created_at)
            VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
            """,
            (
                event_id,
                conversationId,
                message_id,
                conversation["participant_id"],
                conversation["participant_type"],
                conversation["tenancy_id"],
                conversation["property_id"],
                summary,
                json.dumps(privacy_flags),
                ts,
            ),
        )
        self.store.conn.commit()
        return {
            "messageId": message_id,
            "conversationId": conversationId,
            "sender": sender,
            "timestamp": ts,
            "messageType": messageType,
            "content": safe_content,
            "attachments": safe_attachments,
            "privacyFlags": privacy_flags,
            "sideEffects": {"autoSend": False, "autoReply": False, "autoPost": False},
        }

    def attachConversationToTenancy(self, conversationId: str, tenancyId: str) -> dict[str, Any]:
        return self._attach_conversation(conversationId, tenancy_id=tenancyId)

    def attachConversationToProperty(self, conversationId: str, propertyId: str) -> dict[str, Any]:
        return self._attach_conversation(conversationId, property_id=propertyId)

    def getConversationHistory(self, conversationId: str, includePrivate: bool = False) -> dict[str, Any]:
        conversation = self.store.conn.execute("SELECT * FROM conversations WHERE id=?", (conversationId,)).fetchone()
        if conversation is None:
            raise ValueError(f"Unknown conversation: {conversationId}")
        return self._conversation_to_dict(conversation, include_messages=True, include_private=includePrivate)

    def listParticipantConversations(self, participantId: str) -> list[dict[str, Any]]:
        rows = self.store.conn.execute("SELECT * FROM conversations WHERE participant_id=? ORDER BY updated_at DESC", (participantId,)).fetchall()
        return [self._conversation_to_dict(row, include_messages=False) for row in rows]

    def listConversationsForParticipant(self, participantId: str) -> list[dict[str, Any]]:
        return self.listParticipantConversations(participantId)

    def getConversationTimeline(
        self,
        participantId: str | None = None,
        tenancyId: str | None = None,
        propertyId: str | None = None,
    ) -> dict[str, Any]:
        where, params = self._conversation_filter(participantId, tenancyId, propertyId, table_alias="")
        rows = self.store.conn.execute(
            f"SELECT * FROM conversation_memory_events {where} ORDER BY created_at ASC",
            params,
        ).fetchall()
        return {
            "timeline": [self._event_to_dict(row) for row in rows],
            "filters": {"participantId": participantId, "tenancyId": tenancyId, "propertyId": propertyId},
            "sideEffects": {"autoSend": False, "autoReply": False, "autoPost": False},
        }

    def searchConversationHistory(
        self,
        query: str,
        participantId: str | None = None,
        tenancyId: str | None = None,
        propertyId: str | None = None,
    ) -> list[dict[str, Any]]:
        where, params = self._conversation_filter(participantId, tenancyId, propertyId, table_alias="c")
        prefix = f"{where} AND" if where else "WHERE"
        rows = self.store.conn.execute(
            f"""
            SELECT m.*, c.participant_id, c.participant_type, c.tenancy_id, c.property_id
            FROM conversation_messages m
            JOIN conversations c ON c.id=m.conversation_id
            {prefix} lower(m.content) LIKE ?
            ORDER BY m.timestamp ASC
            """,
            (*params, f"%{query.lower()}%"),
        ).fetchall()
        return [
            {
                "conversationId": row["conversation_id"],
                "messageId": row["id"],
                "participantId": row["participant_id"],
                "participantType": row["participant_type"],
                "tenancyId": row["tenancy_id"],
                "propertyId": row["property_id"],
                "sender": row["sender"],
                "timestamp": row["timestamp"],
                "messageType": row["message_type"],
                "content": self.sanitizePublicText(row["content"]),
                "privacyFlags": json.loads(row["privacy_flags"] or "[]"),
            }
            for row in rows
        ]

    def _attach_conversation(self, conversation_id: str, tenancy_id: str | None = None, property_id: str | None = None) -> dict[str, Any]:
        row = self.store.conn.execute("SELECT * FROM conversations WHERE id=?", (conversation_id,)).fetchone()
        if row is None:
            raise ValueError(f"Unknown conversation: {conversation_id}")
        now = datetime.now(timezone.utc).isoformat()
        self.store.conn.execute(
            "UPDATE conversations SET tenancy_id=COALESCE(?, tenancy_id), property_id=COALESCE(?, property_id), updated_at=? WHERE id=?",
            (tenancy_id, property_id, now, conversation_id),
        )
        self.store.conn.execute(
            "UPDATE conversation_memory_events SET tenancy_id=COALESCE(?, tenancy_id), property_id=COALESCE(?, property_id) WHERE conversation_id=?",
            (tenancy_id, property_id, conversation_id),
        )
        self.store.conn.commit()
        return self._conversation_to_dict(self.store.conn.execute("SELECT * FROM conversations WHERE id=?", (conversation_id,)).fetchone(), include_messages=False)

    def _conversation_filter(self, participant_id: str | None, tenancy_id: str | None, property_id: str | None, table_alias: str = "") -> tuple[str, tuple[Any, ...]]:
        prefix = f"{table_alias}." if table_alias else ""
        clauses, params = [], []
        if participant_id:
            clauses.append(f"{prefix}participant_id=?")
            params.append(participant_id)
        if tenancy_id:
            clauses.append(f"{prefix}tenancy_id=?")
            params.append(tenancy_id)
        if property_id:
            clauses.append(f"{prefix}property_id=?")
            params.append(property_id)
        return ("WHERE " + " AND ".join(clauses), tuple(params)) if clauses else ("", tuple())

    def _conversation_to_dict(self, row: Any, include_messages: bool = False, include_private: bool = False) -> dict[str, Any]:
        messages = []
        if include_messages:
            msg_rows = self.store.conn.execute("SELECT * FROM conversation_messages WHERE conversation_id=? ORDER BY timestamp ASC", (row["id"],)).fetchall()
            messages = [self._message_to_dict(msg, include_private=include_private) for msg in msg_rows]
        return {
            "conversationId": row["id"],
            "participantId": row["participant_id"],
            "participantType": row["participant_type"],
            "tenancyId": row["tenancy_id"],
            "propertyId": row["property_id"],
            "messages": messages,
            "createdAt": row["created_at"],
            "updatedAt": row["updated_at"],
            "sideEffects": {"autoSend": False, "autoReply": False, "autoPost": False},
        }

    def _message_to_dict(self, row: Any, include_private: bool = False) -> dict[str, Any]:
        # The runtime never renders private contact details, even for admin views.
        content = self.sanitizePublicText(row["content"])
        return {
            "messageId": row["id"],
            "sender": row["sender"],
            "timestamp": row["timestamp"],
            "messageType": row["message_type"],
            "content": content,
            "attachments": json.loads(row["attachments"] or "[]"),
            "privacyFlags": json.loads(row["privacy_flags"] or "[]"),
        }

    def _sanitize_conversation_attachments(self, attachments: list[dict[str, Any]]) -> list[dict[str, Any]]:
        sanitized: list[dict[str, Any]] = []
        for attachment in attachments:
            sanitized.append(
                {
                    "name": self.sanitizePublicText(str(attachment.get("name", "attachment"))),
                    "type": self.sanitizePublicText(str(attachment.get("type", "file"))),
                    "stored": False,
                }
            )
        return sanitized

    def _event_to_dict(self, row: Any) -> dict[str, Any]:
        return {
            "eventId": row["id"],
            "conversationId": row["conversation_id"],
            "messageId": row["message_id"],
            "participantId": row["participant_id"],
            "participantType": row["participant_type"],
            "tenancyId": row["tenancy_id"],
            "propertyId": row["property_id"],
            "summary": self.sanitizePublicText(row["summary"]),
            "privacyFlags": json.loads(row["privacy_flags"] or "[]"),
            "createdAt": row["created_at"],
        }

    def _ensure_conversation_memory_identity(self, participant_id: str, participant_type: str) -> None:
        now = datetime.now(timezone.utc).isoformat()
        self.store.conn.execute(
            """
            INSERT INTO entities (id, type, name, canonical_url, created_at, updated_at)
            VALUES (?, ?, ?, '', ?, ?)
            ON CONFLICT(id) DO UPDATE SET updated_at=excluded.updated_at
            """,
            (participant_id, participant_type if participant_type in {"tenant", "landlord"} else "person", participant_id, now, now),
        )
        self.store.conn.commit()
