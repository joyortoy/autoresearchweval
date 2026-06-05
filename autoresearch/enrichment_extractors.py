from __future__ import annotations

import hashlib
import json
import re
import sqlite3
from datetime import datetime, timedelta, timezone
from html import unescape
from typing import Any
from urllib.request import Request, urlopen

from .enrichment_types import (
    ENTITY_TYPES,
    RENTAL_ENTITY_TYPES,
    RENTAL_SIGNAL_TYPES,
    SIGNAL_TYPES,
    SINGAPORE_AREA_HINTS,
    SOURCE_TYPES,
    SOURCE_WEIGHTS,
    EnrichmentEntity,
)


class EnrichmentExtractionMixin:
    def _clean_content(self, text: str) -> str:
        text = re.sub(r"<script[^>]*>.*?</script>", " ", text, flags=re.DOTALL | re.IGNORECASE)
        text = re.sub(r"<style[^>]*>.*?</style>", " ", text, flags=re.DOTALL | re.IGNORECASE)
        text = re.sub(r"<[^>]+>", " ", text)
        return re.sub(r"\s+", " ", unescape(text)).strip()

    def sanitizePublicText(self, text: str) -> str:
        text = re.sub(r"[A-Z0-9._%+-]+@[A-Z0-9.-]+\.[A-Z]{2,}", "[redacted-email]", text, flags=re.IGNORECASE)
        text = re.sub(r"(?:\+?\d[\d\s().-]{7,}\d)", "[redacted-phone]", text)
        text = re.sub(r"\b\d{1,5}\s+[A-Za-z0-9 .'-]+\s(?:Street|St|Road|Rd|Avenue|Ave|Lane|Ln|Drive|Dr|Block|Blk)\b", "[redacted-address]", text, flags=re.IGNORECASE)
        text = re.sub(r"\b(?:high risk|blacklist|do not rent|bad tenant|bad landlord)\b", "[redacted-private-label]", text, flags=re.IGNORECASE)
        return text

    def fetchSource(self, url: str) -> dict[str, Any]:
        req = Request(url, headers={"User-Agent": "NanoClaw-Enrichment/3.1"})
        with urlopen(req, timeout=10) as response:
            body = response.read().decode("utf-8", errors="ignore")
        return {"source_url": url, "raw_text": self._clean_content(body)[:12000], "fetched_at": datetime.now(timezone.utc).isoformat()}

    def storeRawSource(self, entityId: str, source: dict[str, Any]) -> str:
        source_type = source.get("source_type", "third_party_scrape")
        if source_type not in SOURCE_TYPES:
            source_type = "third_party_scrape"
        content_hash = hashlib.sha256(source["raw_text"].encode("utf-8")).hexdigest()
        now = datetime.now(timezone.utc).isoformat()
        existing = self.store.conn.execute("SELECT id FROM raw_sources WHERE entity_id=? AND content_hash=?", (entityId, content_hash)).fetchone()
        if existing:
            self.store.conn.execute(
                "UPDATE raw_sources SET last_seen_at=?, source_recency_label='fresh' WHERE id=?",
                (now, existing["id"]),
            )
            self.store.conn.commit()
            return str(existing["id"])
        row_id = hashlib.sha1(f"{entityId}:{source['source_url']}:{content_hash}".encode()).hexdigest()
        self.store.conn.execute(
            """
            INSERT INTO raw_sources
            (id, entity_id, source_url, source_type, raw_text, fetched_at, content_hash, import_status, import_priority,
             first_seen_at, last_seen_at, imported_at, retry_count, freshness_window_hours, source_recency_label)
            VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, 0, ?, ?)
            """,
            (
                row_id,
                entityId,
                source["source_url"],
                source_type,
                source["raw_text"],
                source["fetched_at"],
                content_hash,
                source.get("import_status", "imported"),
                source.get("import_priority", "medium"),
                source.get("first_seen_at", now),
                source.get("last_seen_at", now),
                source.get("imported_at", now),
                source.get("freshness_window_hours", 72),
                source.get("source_recency_label", "fresh"),
            ),
        )
        self.store.conn.commit()
        return row_id

    def extractSignals(self, rawSource: dict[str, Any]) -> list[dict[str, Any]]:
        entity_type = rawSource.get("entity_type") or rawSource.get("type")
        allowed_types = sorted(SIGNAL_TYPES)
        if entity_type in RENTAL_ENTITY_TYPES or rawSource.get("rental_context"):
            allowed_types = sorted(RENTAL_SIGNAL_TYPES)
        payload = {
            "text": rawSource["raw_text"],
            "allowed_signal_types": allowed_types,
            "allowed_rental_signal_types": sorted(RENTAL_SIGNAL_TYPES),
            "output_contract": {"signals": [{"signal_type": "...", "content": "conservative observed fact only"}]},
        }
        if self.llm_extractor:
            return self._validate_signals(self.llm_extractor(payload), set(allowed_types))
        parsed = self._parse_json_signals(rawSource["raw_text"], set(allowed_types))
        if parsed:
            return parsed
        if entity_type in RENTAL_ENTITY_TYPES or rawSource.get("rental_context"):
            return self._extract_rental_signals(rawSource["raw_text"], entity_type)
        return self._extract_gtm_signals(rawSource["raw_text"])

    def _validate_signals(self, signals: list[dict[str, Any]], allowed_types: set[str]) -> list[dict[str, Any]]:
        return [
            {**signal, "content": self.sanitizePublicText(str(signal["content"]))}
            for signal in signals
            if signal.get("signal_type") in allowed_types and signal.get("content")
        ]

    def _parse_json_signals(self, text: str, allowed_types: set[str]) -> list[dict[str, Any]]:
        match = re.search(r"\{.*\}", text, flags=re.DOTALL)
        if not match:
            return []
        try:
            signals = json.loads(match.group(0)).get("signals", [])
        except json.JSONDecodeError:
            return []
        return self._validate_signals(signals, allowed_types)

    def _extract_gtm_signals(self, text: str) -> list[dict[str, Any]]:
        lower = text.lower()
        rules = [
            ("hiring", "hiring_signal", "Company appears to be hiring."),
            ("funding", "funding_signal", "Company mentioned funding."),
            ("launch", "product_launch", "Product launch signal detected."),
            ("competitor", "competitor_signal", "Competitive positioning mention."),
            ("pricing", "buyer_intent", "Potential buyer intent around pricing."),
        ]
        return [{"signal_type": signal_type, "content": content} for keyword, signal_type, content in rules if keyword in lower] or [
            {"signal_type": "communication_context", "content": "General communication context."}
        ]

    def _extract_rental_signals(self, text: str, entity_type: str | None) -> list[dict[str, Any]]:
        clean = self.sanitizePublicText(text)
        lower = clean.lower()
        signals: list[dict[str, Any]] = []

        budget = re.search(r"(?:budget|asking|rent|from|around)?\s*(?:s\$|\$|sgd)\s?\d+(?:\.\d+)?\s?k?(?:\s*[-–to]+\s*(?:s\$|\$|sgd)?\s?\d+(?:\.\d+)?\s?k?)?", clean, re.IGNORECASE)
        if budget:
            signals.append({"signal_type": "rental_budget", "content": f"Observed rental budget/rent: {budget.group(0).strip()}"})

        month = re.search(r"\b(?:move[- ]?in|moving|relocating|available|availability|start(?:ing)?|from)\b(?:\s+to\s+[A-Za-z ]+?)?\s+(?:by\s+|on\s+|in\s+)?((?:jan|feb|mar|apr|may|jun|jul|aug|sep|oct|nov|dec)[a-z]*\s*(?:\d{1,2})?(?:,?\s*\d{4})?)", clean, re.IGNORECASE)
        if month:
            signal_type = "move_in_timeline" if entity_type == "tenant" or "looking" in lower else "property_availability"
            signals.append({"signal_type": signal_type, "content": f"Observed timing: {month.group(1).strip()}"})

        for area in SINGAPORE_AREA_HINTS:
            if area.lower() in lower:
                signals.append({"signal_type": "area_preference", "content": f"Observed area preference/location: {area}"})
                break

        property_match = re.search(r"\b(\d\s?br|1br|2br|3br|studio|condo|hdb|room|common room|master room|whole unit|landed)\b", clean, re.IGNORECASE)
        if property_match:
            signals.append({"signal_type": "property_type_preference", "content": f"Observed property/room requirement: {property_match.group(1)}"})

        household = re.search(r"\b(family of \d+|couple|single professional|household of \d+|\d+ pax)\b", clean, re.IGNORECASE)
        if household:
            signals.append({"signal_type": "household_profile", "content": f"Observed household profile: {household.group(1)}"})

        pet = re.search(r"\b(no pets|pet friendly|with (?:a )?(?:dog|cat)|have (?:a )?(?:dog|cat))\b", clean, re.IGNORECASE)
        if pet:
            signals.append({"signal_type": "pet_requirement", "content": f"Observed pet requirement: {pet.group(1)}"})

        lease = re.search(r"\b(\d{1,2}\s*(?:month|months|mth|mths|year|years)|short term|long term)\s+lease\b|\blease\s+(?:for\s+)?(\d{1,2}\s*(?:month|months|mth|mths|year|years))", clean, re.IGNORECASE)
        if lease:
            signals.append({"signal_type": "lease_duration", "content": f"Observed lease duration: {lease.group(0).strip()}"})

        if re.search(r"\b(viewing|view|can view|schedule a visit)\b", lower):
            signals.append({"signal_type": "viewing_intent", "content": "Observed viewing intent or viewing availability."})
        if "contact me" in lower or "[redacted-email]" in clean or "[redacted-phone]" in clean:
            signals.append({"signal_type": "viewing_intent", "content": f"Observed contact intent with sanitized contact details: {self.sanitizePublicText(clean)}"})

        furnishing = re.search(r"\b(fully furnished|partially furnished|unfurnished)\b", clean, re.IGNORECASE)
        if furnishing:
            signals.append({"signal_type": "furnishing_preference", "content": f"Observed furnishing: {furnishing.group(1)}"})

        if re.search(r"\b(owner|direct landlord|landlord direct|no agent)\b", lower):
            signals.append({"signal_type": "landlord_supply", "content": "Observed owner/direct-landlord supply indication."})
            signals.append({"signal_type": "landlord_preference", "content": "Observed preference for direct landlord/owner interaction."})

        if re.search(r"\b(work|office|school|campus|university)\b", lower):
            work_school = re.search(r"(?:near|close to|around)\s+([A-Za-z ]{3,40})\s+(?:office|school|campus|university|mrt)", clean, re.IGNORECASE)
            content = f"Observed work/school location: {work_school.group(1).strip()}" if work_school else "Observed work/school location consideration."
            signals.append({"signal_type": "school_or_work_location", "content": content})

        if re.search(r"\b(pass|ep|employment pass|documents ready|stamp duty|proof of income)\b", lower):
            signals.append({"signal_type": "document_readiness", "content": "Observed rental document readiness or verification detail."})

        if entity_type == "tenant" and any(word in lower for word in ("looking", "need", "moving", "relocating", "interested")):
            signals.append({"signal_type": "tenant_intent", "content": "Observed tenant housing intent."})
        if entity_type in {"landlord", "property"} and any(word in lower for word in ("available", "renting", "for rent", "asking", "owner")):
            signals.append({"signal_type": "property_availability", "content": "Observed rental property availability/supply."})

        # Conservative fallback: no generic rental signal if no concrete evidence was observed.
        return self._dedupe_signal_dicts(signals)

    def _dedupe_signal_dicts(self, signals: list[dict[str, Any]]) -> list[dict[str, Any]]:
        seen: set[tuple[str, str]] = set()
        out: list[dict[str, Any]] = []
        for signal in signals:
            key = (signal["signal_type"], signal["content"].strip().lower())
            if key not in seen:
                seen.add(key)
                out.append(signal)
        return out

    def resolveEntity(self, entity: dict[str, Any]) -> EnrichmentEntity:
        now = datetime.now(timezone.utc).isoformat()
        entity_type = entity.get("type", "company")
        if entity_type not in ENTITY_TYPES:
            entity_type = "company"
        entity_id = hashlib.sha1(f"{entity.get('name', '')}:{entity.get('canonical_url', '')}:{entity_type}".encode()).hexdigest()
        self.store.conn.execute(
            """
            INSERT OR REPLACE INTO entities (id, type, name, canonical_url, created_at, updated_at)
            VALUES (?, ?, ?, ?, COALESCE((SELECT created_at FROM entities WHERE id=?), ?), ?)
            """,
            (entity_id, entity_type, entity.get("name", entity_id), entity.get("canonical_url", ""), entity_id, now, now),
        )
        self.store.conn.commit()
        return EnrichmentEntity(id=entity_id, type=entity_type, name=entity.get("name", entity_id), canonical_url=entity.get("canonical_url", ""))

    def verifySignals(self, signals: list[dict[str, Any]], existingMemory: list[sqlite3.Row]) -> list[dict[str, Any]]:
        out, seen = [], set()
        for signal in signals:
            key = (signal["signal_type"], signal["content"].strip().lower())
            if key in seen:
                continue
            seen.add(key)
            status, boost = "verified", 0.0
            for mem in existingMemory:
                if mem["signal_type"] == signal["signal_type"] and mem["content"].strip().lower() == key[1]:
                    boost += 0.1
                elif mem["signal_type"] == signal["signal_type"]:
                    status, boost = "conflict", boost - 0.2
            signal["verification_status"], signal["verification_boost"] = status, boost
            out.append(signal)
        return out

    def scoreConfidence(self, signal: dict[str, Any], source_type: str = "third_party_scrape") -> float:
        base = SOURCE_WEIGHTS.get(source_type, SOURCE_WEIGHTS["third_party_scrape"])[0]
        penalty = -0.15 if signal.get("freshness_score", 1.0) < 0.3 else 0.0
        return round(max(0.1, min(0.99, base + signal.get("verification_boost", 0.0) + penalty)), 3)

    def assignDecayRate(self, signal: dict[str, Any], source_type: str = "third_party_scrape") -> float:
        ttl_days = SOURCE_WEIGHTS.get(source_type, SOURCE_WEIGHTS["third_party_scrape"])[1]
        if signal.get("verification_status") == "conflict":
            ttl_days = max(3, int(ttl_days * 0.5))
        return round(1 / ttl_days, 4)

    def _freshness_score(self, fetched_at: str) -> float:
        days = (datetime.now(timezone.utc) - datetime.fromisoformat(fetched_at)).total_seconds() / 86400
        return round(max(0.0, min(1.0, 1 - days / 60)), 3)

    def _summarize_signals(self, entity_type: str, signals: list[dict[str, Any]]) -> str:
        by_type = {signal["signal_type"]: signal["content"] for signal in signals}
        if entity_type == "tenant":
            parts = [by_type.get(key) for key in ("property_type_preference", "area_preference", "rental_budget", "move_in_timeline") if by_type.get(key)]
            return "Tenant intent: " + "; ".join(parts) if parts else "Tenant intent memory packet."
        if entity_type in {"landlord", "property"}:
            parts = [by_type.get(key) for key in ("property_type_preference", "area_preference", "property_availability", "rental_budget", "furnishing_preference") if by_type.get(key)]
            return "Property supply: " + "; ".join(parts) if parts else "Property supply memory packet."
        if entity_type == "area":
            parts = [by_type.get(key) for key in ("area_preference", "rental_budget", "viewing_intent") if by_type.get(key)]
            return "Area intelligence: " + "; ".join(parts) if parts else "Area intelligence memory packet."
        return "; ".join(sorted({s["signal_type"] for s in signals}))

    def upsertMemoryPacket(self, entityId: str, signals: list[dict[str, Any]]) -> str:
        now = datetime.now(timezone.utc)
        entity_row = self.store.conn.execute("SELECT type FROM entities WHERE id=?", (entityId,)).fetchone()
        entity_type = entity_row["type"] if entity_row else "company"
        ids: list[str] = []
        for signal in signals:
            signal_id = hashlib.sha1(f"{entityId}:{signal['source_id']}:{signal['signal_type']}:{signal['content']}".encode()).hexdigest()
            ttl_days = max(1, int(1 / signal["decay_rate"]))
            self.store.conn.execute(
                """
                INSERT OR REPLACE INTO signals
                (id, entity_id, source_id, signal_type, content, confidence, freshness_score, decay_rate,
                 verification_status, sensitivity_level, observed_at, expires_at, created_at)
                VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
                """,
                (
                    signal_id,
                    entityId,
                    signal["source_id"],
                    signal["signal_type"],
                    signal["content"],
                    signal["confidence"],
                    signal["freshness_score"],
                    signal["decay_rate"],
                    signal["verification_status"],
                    signal.get("sensitivity_level", "internal"),
                    now.isoformat(),
                    (now + timedelta(days=ttl_days)).isoformat(),
                    now.isoformat(),
                ),
            )
            ids.append(signal_id)
        packet_id = hashlib.sha1(f"{entityId}:{now.isoformat()}".encode()).hexdigest()
        summary = self.sanitizePublicText(self._summarize_signals(entity_type, signals))
        audit = {
            "created_at": now.isoformat(),
            "entity_type": entity_type,
            "signal_count": len(signals),
            "rule": "retrieved-source->extracted-signal->verified-signal->scored-signal->governed-memory-packet",
            "direct_response_blocked": True,
        }
        self.store.conn.execute(
            """
            INSERT INTO memory_packets (id, entity_id, signal_ids, summary, weight, status, audit_trace, updated_at)
            VALUES (?, ?, ?, ?, ?, 'active', ?, ?)
            """,
            (
                packet_id,
                entityId,
                json.dumps(ids),
                summary,
                round(sum(s["confidence"] for s in signals) / max(1, len(signals)), 3),
                json.dumps(audit),
                now.isoformat(),
            ),
        )
        self.store.conn.commit()
        return packet_id

    def refreshIfStale(self, entityId: str) -> bool:
        row = self.store.conn.execute("SELECT updated_at FROM memory_packets WHERE entity_id=? ORDER BY updated_at DESC LIMIT 1", (entityId,)).fetchone()
        return row is None or datetime.now(timezone.utc) - datetime.fromisoformat(row["updated_at"]) > timedelta(days=7)

    def getMemoryContext(self, entityId: str) -> dict[str, Any]:
        now = datetime.now(timezone.utc)
        rows = self.store.conn.execute("SELECT * FROM signals WHERE entity_id=? ORDER BY created_at DESC", (entityId,)).fetchall()
        packets = self.store.conn.execute("SELECT * FROM memory_packets WHERE entity_id=? ORDER BY updated_at DESC", (entityId,)).fetchall()
        return {
            "signals": [
                {
                    "signal_type": s["signal_type"],
                    "content": self.sanitizePublicText(s["content"]),
                    "status": "fresh" if datetime.fromisoformat(s["expires_at"]) > now else "stale",
                    "verification_status": s["verification_status"],
                    "confidence": s["confidence"],
                }
                for s in rows
            ],
            "memory_packets": [
                {"id": p["id"], "summary": self.sanitizePublicText(p["summary"]), "status": p["status"], "updated_at": p["updated_at"]}
                for p in packets
            ],
            "runtime_rule": "Never answer from retrieval directly. Use governed memory packets only.",
        }
