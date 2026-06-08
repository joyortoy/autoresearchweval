from __future__ import annotations

import hashlib
import json
from datetime import datetime, timezone
from typing import Any, Protocol


DEFAULT_ALLOWED_MIME_TYPES = {
    "application/pdf",
    "image/jpeg",
    "image/png",
    "image/webp",
}
DEFAULT_MAX_UPLOAD_SIZE_BYTES = 10 * 1024 * 1024
DEFAULT_MAX_UPLOADS_PER_HOUR = 20
DEFAULT_MAX_FAILED_UPLOADS_PER_HOUR = 5
UPLOAD_PURPOSES = {
    "verification",
    "property_photo",
    "payment_proof",
    "maintenance",
    "dispute_evidence",
    "document",
}


class UploadStorageProvider(Protocol):
    storageProvider: str

    def build_path(self, owner_id: str, upload_id: str, file_name: str) -> str: ...


class LocalUploadStorageProvider:
    storageProvider = "local"

    def __init__(self, base_path: str = "local://uploads") -> None:
        self.base_path = base_path.rstrip("/")

    def build_path(self, owner_id: str, upload_id: str, file_name: str) -> str:
        return f"{self.base_path}/{owner_id}/{upload_id}/{file_name}"


class S3UploadStorageProvider:
    storageProvider = "s3"

    def __init__(self, bucket: str = "rental-intent-network", prefix: str = "uploads") -> None:
        self.bucket = bucket
        self.prefix = prefix.strip("/")

    def build_path(self, owner_id: str, upload_id: str, file_name: str) -> str:
        return f"s3://{self.bucket}/{self.prefix}/{owner_id}/{upload_id}/{file_name}"


class VirusScanProvider(Protocol):
    def scan(self, storage_path: str, metadata: dict[str, Any]) -> dict[str, Any]: ...


class StubVirusScanProvider:
    """Production-safe stub: leaves uploads pending; it never fakes a clean scan."""

    def scan(self, storage_path: str, metadata: dict[str, Any]) -> dict[str, Any]:
        return {"scanStatus": "pending", "provider": "stub", "accepted": False}


class FixedVirusScanProvider:
    def __init__(self, scan_status: str) -> None:
        self.scan_status = scan_status

    def scan(self, storage_path: str, metadata: dict[str, Any]) -> dict[str, Any]:
        return {"scanStatus": self.scan_status, "provider": "fixed", "accepted": self.scan_status == "clean"}


class ProductionHardeningMixin:
    def appendImmutableAuditEvent(self, actorId: str, eventType: str, payload: dict[str, Any]) -> dict[str, Any]:
        created_at = datetime.now(timezone.utc).isoformat()
        previous = self.store.conn.execute("SELECT event_hash FROM immutable_audit_events ORDER BY sequence DESC LIMIT 1").fetchone()
        previous_hash = previous["event_hash"] if previous else "GENESIS"
        safe_payload = json.dumps(payload, sort_keys=True)
        event_hash = hashlib.sha256(f"{previous_hash}:{safe_payload}:{created_at}".encode()).hexdigest()
        event_id = hashlib.sha1(f"immutable-audit:{actorId}:{eventType}:{created_at}:{event_hash}".encode()).hexdigest()
        self.store.conn.execute(
            """
            INSERT INTO immutable_audit_events
            (id, sequence, actor_id, event_type, payload, previous_hash, event_hash, created_at)
            VALUES (?, COALESCE((SELECT MAX(sequence) + 1 FROM immutable_audit_events), 1), ?, ?, ?, ?, ?, ?)
            """,
            (event_id, actorId, eventType, safe_payload, previous_hash, event_hash, created_at),
        )
        self.store.conn.commit()
        return {"id": event_id, "actorId": actorId, "eventType": eventType, "previousHash": previous_hash, "eventHash": event_hash, "createdAt": created_at}

    def verifyAuditChain(self) -> dict[str, Any]:
        rows = self.store.conn.execute("SELECT * FROM immutable_audit_events ORDER BY sequence ASC").fetchall()
        previous_hash = "GENESIS"
        for row in rows:
            expected = hashlib.sha256(f"{previous_hash}:{row['payload']}:{row['created_at']}".encode()).hexdigest()
            if row["previous_hash"] != previous_hash or row["event_hash"] != expected:
                return {"valid": False, "failedEventId": row["id"], "checkedEvents": row["sequence"]}
            previous_hash = row["event_hash"]
        return {"valid": True, "checkedEvents": len(rows)}

    def createSubscriptionDraft(
        self,
        tenantId: str,
        landlordId: str,
        propertyId: str,
        tenancyId: str,
        subscriptionPeriod: str,
        amount: float,
        idempotencyKey: str | None = None,
        simulateFailure: bool = False,
    ) -> dict[str, Any]:
        if amount <= 0 or not all([tenantId, landlordId, propertyId, tenancyId, subscriptionPeriod]):
            return {"created": False, "status": "invalid", "reason": "invalid_subscription_draft"}
        key = idempotencyKey or self._subscription_idempotency_key(tenantId, landlordId, propertyId, tenancyId, subscriptionPeriod)
        existing = self.store.conn.execute("SELECT * FROM subscription_drafts WHERE idempotency_key=?", (key,)).fetchone()
        if existing:
            return {**self._subscription_draft_to_dict(existing), "created": False, "idempotentReplay": True}
        if simulateFailure:
            return {"created": False, "status": "failed", "idempotencyKey": key, "reason": "simulated_failure_before_persist"}
        now = datetime.now(timezone.utc).isoformat()
        draft_id = hashlib.sha1(f"subscription-draft:{key}".encode()).hexdigest()
        self.store.conn.execute(
            """
            INSERT OR IGNORE INTO subscription_drafts
            (id, tenant_id, landlord_id, property_id, tenancy_id, subscription_period, amount, idempotency_key, status, created_at, updated_at)
            VALUES (?, ?, ?, ?, ?, ?, ?, ?, 'draft', ?, ?)
            """,
            (draft_id, tenantId, landlordId, propertyId, tenancyId, subscriptionPeriod, amount, key, now, now),
        )
        self.store.conn.commit()
        row = self.store.conn.execute("SELECT * FROM subscription_drafts WHERE idempotency_key=?", (key,)).fetchone()
        return {**self._subscription_draft_to_dict(row), "created": row["id"] == draft_id, "idempotentReplay": row["id"] != draft_id}

    def submitUpload(
        self,
        ownerId: str,
        ownerType: str,
        purpose: str,
        fileName: str,
        mimeType: str,
        sizeBytes: int,
        actorId: str | None = None,
        storageProvider: UploadStorageProvider | None = None,
        virusScanProvider: VirusScanProvider | None = None,
    ) -> dict[str, Any]:
        actor_id = actorId or ownerId
        rate = self._check_upload_rate(actor_id)
        if rate.get("blocked"):
            return {"accepted": False, "status": "blocked", "reason": rate["reason"], "rateLimit": rate, "publicRawFileUrl": None}
        now = datetime.now(timezone.utc).isoformat()
        upload_id = hashlib.sha1(f"upload:{ownerId}:{purpose}:{fileName}:{now}".encode()).hexdigest()
        allowed = getattr(self, "allowed_upload_mime_types", DEFAULT_ALLOWED_MIME_TYPES)
        max_size = getattr(self, "max_upload_size_bytes", DEFAULT_MAX_UPLOAD_SIZE_BYTES)
        status, scan_status, rejection_reason = "pending", "pending", None
        if purpose not in UPLOAD_PURPOSES:
            status, scan_status, rejection_reason = "rejected", "failed", "unsupported_purpose"
        elif sizeBytes > max_size:
            status, scan_status, rejection_reason = "rejected", "failed", "oversized_file"
        elif mimeType not in allowed:
            status, scan_status, rejection_reason = "rejected", "failed", "unsupported_file_type"
        safe_file_name = self._safe_file_name(fileName)
        provider = storageProvider or getattr(self, "upload_storage_provider", LocalUploadStorageProvider())
        storage_path = provider.build_path(ownerId, upload_id, safe_file_name)
        if status != "rejected":
            scanner = virusScanProvider or getattr(self, "virus_scan_provider", StubVirusScanProvider())
            scan_result = scanner.scan(storage_path, {"mimeType": mimeType, "sizeBytes": sizeBytes, "purpose": purpose})
            scan_status = scan_result.get("scanStatus", "pending")
            if scan_status == "infected":
                status, rejection_reason = "rejected", "infected_upload"
            elif scan_status == "clean":
                status = "accepted"
        self.store.conn.execute(
            """
            INSERT INTO upload_records
            (id, owner_id, owner_type, purpose, file_name, mime_type, size_bytes, storage_provider,
             storage_path, scan_status, status, rejection_reason, created_at)
            VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
            """,
            (upload_id, ownerId, ownerType, purpose, safe_file_name, mimeType, sizeBytes, provider.storageProvider, storage_path, scan_status, status, rejection_reason, now),
        )
        self._increment_upload_rate(actor_id, rejected=status == "rejected")
        if status == "rejected":
            self._maybe_create_upload_review_flag(actor_id, rejection_reason or "rejected_upload")
        self.store.conn.commit()
        return {
            "id": upload_id,
            "ownerId": ownerId,
            "purpose": purpose,
            "status": status,
            "scanStatus": scan_status,
            "rejectionReason": rejection_reason,
            "storageProvider": provider.storageProvider,
            "storagePath": storage_path,
            "publicRawFileUrl": None,
            "accepted": status == "accepted",
        }

    def acceptUpload(self, uploadId: str) -> dict[str, Any]:
        row = self.store.conn.execute("SELECT * FROM upload_records WHERE id=?", (uploadId,)).fetchone()
        if row is None:
            raise ValueError(f"Unknown upload: {uploadId}")
        if row["scan_status"] != "clean" or row["status"] == "rejected":
            return {"accepted": False, "status": row["status"], "reason": "upload_not_clean"}
        self.store.conn.execute("UPDATE upload_records SET status='accepted' WHERE id=?", (uploadId,))
        self.store.conn.commit()
        return {"accepted": True, "status": "accepted", "uploadId": uploadId}

    def validatePaymentProofEvidence(
        self,
        uploadId: str,
        expectedAmount: float,
        submittedAmount: float,
        paymentDate: str,
        requestDate: str | None = None,
        dueDate: str | None = None,
        invoiceId: str | None = None,
        payer: str | None = None,
        payee: str | None = None,
    ) -> dict[str, Any]:
        reasons: list[str] = []
        upload = self.store.conn.execute("SELECT * FROM upload_records WHERE id=?", (uploadId,)).fetchone()
        if upload is None:
            reasons.append("missing_upload")
        else:
            if upload["purpose"] != "payment_proof":
                reasons.append("not_payment_proof")
            if upload["scan_status"] == "infected" or upload["status"] == "rejected":
                reasons.append("upload_not_acceptable")
        if not invoiceId:
            reasons.append("missing_invoice_or_request")
        if expectedAmount != submittedAmount:
            reasons.append("amount_mismatch")
        if not payer or not payee:
            reasons.append("missing_payer_payee")
        if requestDate and paymentDate < requestDate:
            reasons.append("payment_date_too_early")
        if dueDate and paymentDate > dueDate:
            reasons.append("payment_date_too_late")
        return {
            "accepted": not reasons,
            "status": "needs_review" if reasons else "validated",
            "reasons": reasons,
            "decision": None,
            "recommendationOnly": True,
            "noFundsManaged": True,
            "noLegalAdvice": True,
            "botMessageDraft": None,
        }

    def reviewLandlordRejectionAfterAcknowledgement(self, tenancyId: str, tenantAcknowledged: bool, landlordAcknowledged: bool) -> dict[str, Any]:
        if tenantAcknowledged and landlordAcknowledged:
            return {"status": "needs_review", "reason": "mutual_acknowledgement_exists", "autoReverse": False, "decision": None, "noLegalAdvice": True}
        return {"status": "recorded", "reason": "acknowledgement_incomplete", "autoReverse": False, "decision": None, "noLegalAdvice": True}

    def recordDisputeEvidence(self, uploadId: str, summary: str) -> dict[str, Any]:
        row = self.store.conn.execute("SELECT * FROM upload_records WHERE id=?", (uploadId,)).fetchone()
        if row is None:
            raise ValueError(f"Unknown upload: {uploadId}")
        safe_summary = self.sanitizePublicText(summary)
        return {
            "stored": True,
            "uploadId": uploadId,
            "summary": safe_summary,
            "decision": None,
            "decidesWhoIsRight": False,
            "botMessageDraft": "Thanks, this evidence has been saved for neutral human review.",
            "threatensParty": False,
            "legalAdviceGenerated": False,
        }

    def _check_upload_rate(self, actor_id: str) -> dict[str, Any]:
        window = datetime.now(timezone.utc).replace(minute=0, second=0, microsecond=0).isoformat()
        max_uploads = getattr(self, "max_uploads_per_actor_per_hour", DEFAULT_MAX_UPLOADS_PER_HOUR)
        max_failed = getattr(self, "max_failed_uploads_per_actor_per_hour", DEFAULT_MAX_FAILED_UPLOADS_PER_HOUR)
        row = self.store.conn.execute("SELECT * FROM upload_rate_limits WHERE actor_id=? AND window_start=?", (actor_id, window)).fetchone()
        if row and row["upload_count"] >= max_uploads:
            return {"blocked": True, "reason": "too_many_uploads", "actorId": actor_id, "windowStart": window}
        if row and row["rejected_count"] >= max_failed:
            self._create_upload_review_flag(actor_id, "repeated_rejected_uploads")
            self.store.conn.commit()
            return {"blocked": True, "reason": "too_many_failed_uploads", "actorId": actor_id, "windowStart": window}
        return {"blocked": False, "actorId": actor_id, "windowStart": window}

    def _increment_upload_rate(self, actor_id: str, rejected: bool) -> None:
        window = datetime.now(timezone.utc).replace(minute=0, second=0, microsecond=0).isoformat()
        self.store.conn.execute(
            """
            INSERT INTO upload_rate_limits (actor_id, window_start, upload_count, rejected_count, updated_at)
            VALUES (?, ?, 1, ?, ?)
            ON CONFLICT(actor_id, window_start) DO UPDATE SET upload_count=upload_count + 1,
                                                               rejected_count=rejected_count + excluded.rejected_count,
                                                               updated_at=excluded.updated_at
            """,
            (actor_id, window, 1 if rejected else 0, datetime.now(timezone.utc).isoformat()),
        )

    def _maybe_create_upload_review_flag(self, actor_id: str, reason: str) -> None:
        row = self.store.conn.execute("SELECT rejected_count FROM upload_rate_limits WHERE actor_id=? ORDER BY window_start DESC LIMIT 1", (actor_id,)).fetchone()
        max_failed = getattr(self, "max_failed_uploads_per_actor_per_hour", DEFAULT_MAX_FAILED_UPLOADS_PER_HOUR)
        if row and row["rejected_count"] >= max_failed:
            self._create_upload_review_flag(actor_id, reason)

    def _create_upload_review_flag(self, actor_id: str, reason: str) -> None:
        now = datetime.now(timezone.utc).isoformat()
        flag_id = hashlib.sha1(f"upload-review:{actor_id}:{reason}:{now}".encode()).hexdigest()
        self.store.conn.execute(
            "INSERT OR IGNORE INTO upload_review_flags (id, actor_id, reason, status, created_at) VALUES (?, ?, ?, 'needs_review', ?)",
            (flag_id, actor_id, reason, now),
        )

    def _subscription_idempotency_key(self, tenant_id: str, landlord_id: str, property_id: str, tenancy_id: str, period: str) -> str:
        return hashlib.sha256(f"{tenant_id}:{landlord_id}:{property_id}:{tenancy_id}:{period}".encode()).hexdigest()

    def _subscription_draft_to_dict(self, row: Any) -> dict[str, Any]:
        return {
            "id": row["id"],
            "tenantId": row["tenant_id"],
            "landlordId": row["landlord_id"],
            "propertyId": row["property_id"],
            "tenancyId": row["tenancy_id"],
            "subscriptionPeriod": row["subscription_period"],
            "amount": row["amount"],
            "idempotencyKey": row["idempotency_key"],
            "status": row["status"],
        }

    def _safe_file_name(self, file_name: str) -> str:
        return "".join(char for char in file_name if char.isalnum() or char in {".", "-", "_"})[:120] or "upload.bin"
