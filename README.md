# autoresearch

Autoresearch is a **Python-first experimental alignment/governance framework for autonomous LLM experimentation**.

## What this is

A local-first, prototype-scoped system for bounded autonomous model iteration with policy-gated governance.

Core concerns:
- bounded train/evaluate loops,
- trust-aware promotion,
- fail-closed governance,
- rollback semantics,
- lineage/provenance tracking,
- attention-direction and representation telemetry (experimental).

## What is implemented today (concrete)

Implemented and runnable in this repo today:
- a Python orchestrator that runs a bounded train/evaluate/keep-discard loop,
- policy-based trust scoring with hard-fail and fail-closed behavior,
- result/state logging with lineage fields,
- optional telemetry inputs passed into trust scoring,
- lightweight telemetry utilities and calibration scripts for research experiments.

Important implementation note:
- attention/representation telemetry is currently **adapter-driven or mock-driven** (JSON/env/probe inputs),
- this repo does **not** yet include deep model-internal instrumentation for a production model backend.

## Core flow

```text
proposal
-> train
-> evaluate
-> representation telemetry
-> attention-direction checks
-> calibration signals
-> trust gate
-> keep/discard
-> rollback
-> lineage tracking
-> log
```

## Attention-Direction Governance

This project treats alignment as attention-direction awareness during bounded experimentation.

The governance layer monitors whether representation/attention appears to move toward an intended alignment direction or toward unsafe attention directions.

Attention drift may provide early warning signals before obviously harmful output appears, but this is still an experimental interpretability-inspired signal.

**This project explores whether representation-space telemetry and attention-direction signals can contribute useful governance information during bounded autonomous model iteration.**

**This repository does not claim that attention telemetry alone can reliably determine alignment or safety.**

**Attention-direction governance remains an experimental research area requiring empirical validation.**

## Telemetry and calibration

Telemetry layer (lightweight, backend-agnostic):
- `telemetry/representation_probe.py`
- `telemetry/drift_metrics.py`
- `telemetry/telemetry_types.py`

Calibration artifacts:
- `experiments/calibration/` prompt sets + `run_calibration.py`
- `examples/drift_cases/` illustrative drift patterns

These are prototype research tools, not validated guarantees.

In current implementation, telemetry signals are optional governance inputs and may be defaults or adapter-provided values unless a real telemetry producer is connected.

## Trust governance

Trust scoring (`trust_score.py`) + policy (`trust_policy.json`) supports:
- metric-discard override enforcement,
- hard-fail discard semantics,
- fail-closed fallback,
- optional telemetry-informed penalties/warnings.

## Why bounded iteration?

Bounded iteration is itself a governance primitive:
- constrains runaway optimization pressure,
- improves run comparability,
- enables gradual trust escalation,
- makes rollback and lineage reasoning tractable.

## What this is not

- not solved alignment,
- not AGI safety,
- not production superalignment,
- not a claim of reliable internal alignment detection.

## Quickstart

```bash
make demo
make test
make lint-shell
```

Trust sample only:

```bash
make trust-sample
```

Optional local training (requires NVIDIA GPU + prepared data):

```bash
uv run prepare.py
uv run train.py
```

Python orchestrator:

```bash
python3 -m autoresearch.orchestrator --dry-run
```

Shell compatibility wrapper:

```bash
./run_intent_autoresearch.sh --dry-run
```


## Attention-Direction Governance

This project treats alignment as attention-direction awareness during bounded experimentation.

The governance layer monitors whether representation/attention appears to move toward an intended alignment direction or toward unsafe attention directions.

Attention drift may provide early warning signals before obviously harmful output appears, but this is still an experimental interpretability-inspired signal.

**This project explores whether representation-space telemetry and attention-direction signals can contribute useful governance information during bounded autonomous model iteration.**

**This repository does not claim that attention telemetry alone can reliably determine alignment or safety.**

**Attention-direction governance remains an experimental research area requiring empirical validation.**

## Telemetry and calibration

Telemetry layer (lightweight, backend-agnostic):
- `telemetry/representation_probe.py`
- `telemetry/drift_metrics.py`
- `telemetry/telemetry_types.py`

Calibration artifacts:
- `experiments/calibration/` prompt sets + `run_calibration.py`
- `examples/drift_cases/` illustrative drift patterns

These are prototype research tools, not validated guarantees.

## Trust governance

Trust scoring (`trust_score.py`) + policy (`trust_policy.json`) supports:
- metric-discard override enforcement,
- hard-fail discard semantics,
- fail-closed fallback,
- optional telemetry-informed penalties/warnings.

## Why bounded iteration?

Bounded iteration is itself a governance primitive:
- constrains runaway optimization pressure,
- improves run comparability,
- enables gradual trust escalation,
- makes rollback and lineage reasoning tractable.

## What this is not

- not solved alignment,
- not AGI safety,
- not production superalignment,
- not a claim of reliable internal alignment detection.

## Quickstart

```bash
make demo
make test
make lint-shell
```

Trust sample only:

```bash
make trust-sample
```

Optional local training (requires NVIDIA GPU + prepared data):

```bash
uv run prepare.py
uv run train.py
```

Python orchestrator:

```bash
python3 -m autoresearch.orchestrator --dry-run
```

Shell compatibility wrapper:

```bash
./run_intent_autoresearch.sh --dry-run
```

## Documentation

- `docs/architecture.md`
- `docs/trust_governance.md`
- `docs/threat_model.md`
- `docs/calibration.md`
- `docs/open_source_boundary.md`

## License

MIT

## Governed enrichment and Rental Intent Network adaptation

`autoresearch.enrichment` is the existing governed enrichment/RAG module. It is intentionally **not** a user-answering RAG system. Retrieved data must follow this governed-memory path before any runtime/task system uses it:

```text
retrieved source
-> extracted signal
-> verified signal
-> confidence + decay scoring
-> governed memory packet
-> rental profile draft / review task / match support
```

The module still supports the original company/GTM signals (`hiring_signal`, `funding_signal`, `product_launch`, `buyer_intent`, etc.) and now also supports Rental Intent Network entity types:

- `tenant`
- `landlord`
- `property`
- `area`
- `source_channel`

Rental-specific signal types include:

- `tenant_intent`
- `landlord_supply`
- `property_availability`
- `rental_budget`
- `move_in_timeline`
- `area_preference`
- `property_type_preference`
- `viewing_intent`
- `lease_duration`
- `furnishing_preference`
- `household_profile`
- `pet_requirement`
- `school_or_work_location`
- `landlord_preference`
- `document_readiness`
- `verification_need`
- `maintenance_signal`
- `dispute_signal`
- `renewal_signal`
- `buying_interest`
- `risk_signal`

Rental source types include `expat_forum`, `relocation_group`, `facebook_group`, `landlord_ad`, `property_listing`, `whatsapp_message`, `manual_import`, `referral`, `official_property_source`, and `third_party_listing`. Search providers are only prepared through the existing provider abstraction; the module does not auto-scrape, auto-post, or send WhatsApp messages.

### Tenant acquisition use case

Tenant-side text such as manual imports, referral notes, or reviewed channel posts can be converted into a governed Tenant Intent Profile draft. Conservative fallback extraction looks for concrete observed details such as budget, move-in timing, preferred area, property type, household profile, pet requirement, lease duration, work/school location, and contact/viewing intent. Missing fields are not hallucinated.

### Landlord acquisition use case

Landlord/property-side text can be converted into governed Property Profile or Landlord Profile drafts. Conservative fallback extraction looks for observed rent, area, property type, availability, furnishing, lease duration, owner/direct-landlord indication, preferred tenant notes, and viewing availability.

### Runtime drafts and review queue

Verified rental memory can be transformed into review-first artifacts:

- Tenant Intent Profile draft
- Landlord Profile draft
- Property Profile draft
- Area Intelligence note
- Acquisition follow-up task
- Match candidate suggestion

These artifacts are drafts/review items only. They do not create final tenant/property records unless an explicit rental-store workflow later approves them. The `RAG Intake Review` payload is marked as a collapsed secondary admin section with `approve`, `ignore`, and `needs review` actions so it does not clutter the main rental dashboard.

### Privacy and sanitization

Tenant/landlord-facing drafts must not expose raw phone numbers, emails, private addresses, private trust/risk labels, internal confidence scores, or raw source traces. Contact details may be stored internally in raw source storage for review, but public-facing draft content is sanitized before being returned by runtime hooks or memory context helpers.

### Local 5090 extraction note

The current integration remains provider-based and testable without a GPU. A future local RTX 5090 workflow can plug a local LLM into the existing `llm_extractor` hook for structured JSON extraction, but the governed-memory rule should remain unchanged and no embeddings/Qdrant layer is required yet.

### Rental RAG intake operating loop

The Rental Intent Network operating layer keeps enrichment import-first and review-first:

```text
Source Import
-> Governed Enrichment
-> RAG Intake Review
-> Approve / Ignore / Needs Review
-> Create Tenant Intent Draft or Property Profile Draft
-> Send to Matching Queue
```

Operators can import reviewed/manual source text with:

- `importManualRentalSource(text, sourceType)` for source-only intake.
- `importTenantInquiryText(text, sourceMeta)` for tenant inquiry intake.
- `importLandlordAdText(text, sourceMeta)` for landlord/property ad intake.
- `runRentalEnrichmentForSource(sourceId)` to run the existing governed enrichment flow for an already-imported source.

These functions do not auto-scrape, auto-post, or send WhatsApp messages. They call the existing governed enrichment module and persist a pending `RAG Intake Review` item.

Approval remains explicit:

- `approveRagIntakeItem(id)` creates the suggested draft record and bridge entry.
- `ignoreRagIntakeItem(id)` closes the review item without creating tenant/property profiles.
- `markRagIntakeNeedsReview(id, reason)` stores the operator reason and keeps the item out of creation flows.

On approval, tenant drafts enter `Waiting / Not Ready` or `Match Now` based on rule-based completeness. Property drafts enter the property matching pool. If both sides are matchable, an explicit `generateMatchRecommendations()` call can create a rule-based recommendation; approval itself does not auto-match or message either side.

The admin UI contract is a single collapsed secondary section named `RAG Intake Review`. It shows source type, short sanitized preview, extracted signal summary, suggested draft type, privacy flags, status, and actions (`Approve`, `Ignore`, `Needs Review`). No analytics panels are added, and raw source traces remain non-public.

Privacy is enforced before rendering review items: phone numbers, emails, private addresses, and private trust/risk labels are redacted. Raw source text can be stored internally for review, but tenant/landlord-facing drafts and review UI payloads use sanitized content.

A future local RTX 5090 extractor can plug into `llm_extractor` to improve structured extraction quality. The operating loop does not require GPU, Qdrant, or embeddings today, and the governed-memory rule remains mandatory.

### Refactored enrichment module layout

The governed enrichment code is split into focused modules while preserving the public `autoresearch.enrichment` API:

- `autoresearch/enrichment_types.py` — shared entity types, signal/source taxonomies, search providers, import templates, and review reason constants.
- `autoresearch/enrichment_store.py` — SQLite-backed governed memory, RAG intake review, draft, queue, and audit schemas.
- `autoresearch/enrichment_extractors.py` — source cleaning, privacy sanitization, conservative GTM/rental extraction, verification, confidence/decay scoring, and memory packet upsert helpers.
- `autoresearch/enrichment_runtime.py` — review UI payload contract, approval actions, draft creation, matching queue bridge, and rule-based recommendations.
- `autoresearch/rental_intake.py` — import-first rental source intake, template routing, duplicate detection, review item persistence, and audit events.
- `autoresearch/enrichment.py` — thin orchestrator/export layer that keeps the old `EnrichmentModule`, `EnrichmentStore`, `build_search_provider`, and `run_demo` imports working.

The daily operator workflow is intentionally simple:

```text
Paste source
-> Extract signals
-> Review card appears
-> Approve / Ignore / Needs Review
-> Tenant/property draft enters matching queue
```

Import templates are available for:

- `Paste Tenant Inquiry`
- `Paste Landlord Ad`
- `Paste Expat Forum Post`
- `Paste Property Listing`

Duplicate detection uses source URL, content hash, and similar extracted signal fingerprints. Duplicate intake does not create another active review card; it links to the existing item and records an audit event.

Review cards use priority labels (`high`, `medium`, `low`) and confidence/freshness labels instead of exposing numeric confidence scores. High-priority examples include tenants with budget + move-in date + area and properties with rent + area + availability. Low-priority examples include vague browsing text, missing budget/rent, non-Singapore context, or low-confidence extraction.

Ignore / Needs Review actions use structured reasons: `duplicate`, `missing_budget`, `missing_rent`, `missing_area`, `low_confidence`, `contact_unclear`, `not_singapore`, `spam`, or `other`, with optional sanitized notes.

### Import timing layer

Rental intake now has an import timing layer that controls when pasted/imported sources are queued, processed, refreshed, delayed, ignored, marked stale, or failed. Timing states are:

- `queued`
- `processing`
- `imported`
- `enriched`
- `review_ready`
- `delayed`
- `stale`
- `ignored`
- `failed`

Source timing metadata tracks import priority, first/last seen times, imported/processed times, next refresh, expiry, retry count, failure reason, freshness window, and source recency labels (`fresh`, `normal`, `stale`, `expired`).

Priority rules remain manual/import-first and do not trigger scraping. Tenant inquiries become high priority when they include move-in timing, budget, area, and contact intent. Landlord/property ads become high priority when they include rent, area, availability, and owner/direct-landlord signals. Expat forum and relocation group sources default to medium priority unless strong moving-to-Singapore housing intent is present.

Stale source handling marks sources stale when availability or move-in timing has passed, the source exceeds its freshness window, or a processed refresh finds no useful signals. Duplicate sources are not re-imported as new review cards: the existing source/review item gets `lastSeenAt` updates and duplicate/audit linkage.

Failed imports retry through `processNextImport()` up to three times, then move to `failed` with a stored failure reason. Operators can inspect timing via `getImportTimingQueue()` and high-priority sources via `getHighPriorityImports()`. The `Import Timing` UI contract is a small collapsed subsection inside `RAG Intake Review` and only surfaces high-priority, stale, failed, or delayed imports—no analytics panels, raw source trace, auto-posting, or WhatsApp sending.

### Consent-based person verification

Rental matching can use a privacy-first person verification layer for tenant and landlord safety inputs. The flow is consent-gated:

```text
submitted phone/email/name
-> consent check
-> verification checks
-> confidence signal
-> internal verification status
-> matching safety input
```

The system does not scrape private personal data, enrich sensitive personal attributes, expose phone/email publicly, create public scores, auto-reject users, or bypass consent. Raw phone/email are not stored by this layer; phone and email values are normalized and hashed for duplicate detection unless another user-profile system already requires raw contact storage.

Supported verification signal types include phone/WhatsApp/email reachability, identity document submission/name match, landlord ownership document submission, property-address match, duplicate contact detection, prior platform history, scam-pattern review flags, and manual-review requirements.

Consent functions:

- `requestVerificationConsent(personId, personType)`
- `recordVerificationConsent(personId, granted)`
- `createPersonVerification(personId, personType, phone=None, email=None, name=None)`

Verification functions:

- `addVerificationSignal(verificationId, signal)`
- `checkDuplicateContact(phoneOrEmail)`
- `evaluateVerificationStatus(verificationId)`
- `getInternalVerificationSummary(personId)`
- `sanitizeVerificationForPublic(summary)`

Internal statuses are `unverified`, `partial`, `verified`, `review_required`, or `rejected`. Public-facing labels stay neutral: `Verified`, `Verification pending`, or `Manual review required`. Matching may use verification internally as a trust boost, manual-review reduction, or admin-override requirement, but no public ranking/shaming labels such as “bad tenant” or “bad landlord” are produced.

All verification lookups and changes write audit events. Future provider integrations can be added behind the same consent-gated signal interface.

Layer ownership is intentionally strict:

- **Rental RAG Intake detects signals** from imported sources and creates review cards; it does not decide whether a person is real.
- **Person Verification checks whether a tenant/landlord signal is real** only after consent, then publishes a neutral internal `verification_need` memory signal.
- **Memory System owns identity, history, and intent evolution** through `entities`, `signals`, and `memory_packets`; approval marks intake memory as approved before downstream use.
- **Rental Matching consumes approved governed memory** and internal matching-safety inputs from memory, not raw retrieval text or public verification scores.

### Real Estate Memory OS adapter

The governed enrichment layer connects to Real Estate Memory OS through a narrow adapter, not by merging codebases:

```text
Governed RAG Enrichment
-> Verified Memory Packet
-> RealEstateRagAdapter
-> Memory OS Enrichment Event
-> Lead/Relationship Memory Update
-> Work Queue Recommendation
```

The shared `GovernedMemoryPacketInput` contract contains `packetId`, `entityId`, `entityType`, `summary`, structured `signals`, packet-level `confidence`, `freshness`, `verificationStatus`, `sensitivityLevel`, internal `sourceTrace`, `approvedForUse`, `createdAt`, and `updatedAt`. Each `Signal` carries `signalType`, sanitized `content`, `confidence`, `freshness`, `verificationStatus`, `sourceType`, `observedAt`, and `expiresAt`.

`RealEstateRagAdapter` provides `canImportPacket()`, `mapEntityToLead()`, `mapSignalsToRelationshipMemory()`, `mapSignalsToLeadNotes()`, `mapSignalsToTasks()`, `mapSignalsToCalendarDrafts()`, and `importPacketToMemoryOs()`. It imports only packets where `approvedForUse` is true, rejects stale/expired packets by default, respects sensitivity levels, redacts contact details/private labels, keeps source trace internal, and appends a Memory OS enrichment event instead of overwriting existing relationship memory.

The Memory OS store integration persists `rag_enrichment_events` and exposes `importRagMemoryPacket(packet)`, `listRagEnrichmentEvents(leadId)`, `getRagContextForLead(leadId)`, `markRagEnrichmentUsed(eventId)`, and `ignoreRagEnrichmentEvent(eventId, reason)`. Event audit trace preserves internal source trace and the rule `governed-rag-packet->memory-os-enrichment-event`; raw source trace is never rendered in UI payloads.

RAG enrichment can support suggested messages, next-best questions, task suggestions, meeting preparation, and lead notes. It must not replace the close-probability engine, deal-risk engine, existing relationship memory, or agent-entered meeting notes. Memory priority is: user/agent-provided memory, then verified internal memory, then RAG enrichment.

The Today’s Work Queue remains clean: no large RAG panel is added. Lead Workspace gets a collapsed secondary section named `External Context` showing short summaries, signal labels, freshness/confidence labels, and actions (`Use in note`, `Create task`, `Ignore`) without raw source traces, private contact details, numeric confidence values, or private risk labels.

### User data consent and privacy notice layer

Rental Intent Network intake now includes a consent-before-processing layer for tenant, landlord, property/contact, verification, message, document, tenancy-memory, renewal, and RAG/manual-source workflows. The platform must not collect or process personal data without the relevant consent, must not run verification without consent, must not expose private contact details, must not create public scores/rankings, must not auto-send WhatsApp messages, must not auto-post, must not manage funds, and must not provide legal advice.

Consent notices are available for tenant intake, landlord intake, verification, WhatsApp/bot-mediated communication, document generation, tenancy memory, renewal reminders, and RAG/manual source import. Tenant intake uses: “By continuing, you agree that the information you provide may be stored and used to match you with suitable rental options, facilitate bot-mediated communication, maintain rental records, verify information you voluntarily provide, support renewals, and improve matching quality.” Landlord intake uses: “By continuing, you agree that your property, contact, communication, and listing information may be stored and used to match you with suitable tenants, facilitate bot-mediated communication, prepare document drafts, support renewals, verify information you voluntarily provide, and improve platform matching quality.”

`ConsentRecord` is persisted with `personId`, `personType`, `consentType`, `consentVersion`, `status` (`pending`, `accepted`, `declined`, `withdrawn`), notice text, timestamps for acceptance/decline/withdrawal, source, optional IP address, optional user agent, and audit timestamps. Supported consent types are `data_storage`, `matching`, `bot_communication`, `verification`, `document_generation`, `tenancy_memory`, `renewal_reminder`, and `rag_source_import`.

Consent policy gates are explicit: `data_storage` is required before saving tenant/landlord personal data; `matching` before profile matching; `bot_communication` before relaying messages; `verification` plus `data_storage` before verification checks; `document_generation` before personal document drafts; `tenancy_memory` before lease/tenancy-history memory; `renewal_reminder` before renewal reminders; and `rag_source_import` before importing manually submitted personal source text.

The public API includes `createConsentNotice(personType, consentTypes)`, `recordConsentAcceptance(personId, consentTypes, source, metadata)`, `recordConsentDecline(personId, consentTypes, source, metadata)`, `withdrawConsent(personId, consentType)`, `hasActiveConsent(personId, consentType)`, `requireConsentOrBlock(personId, consentType, actionName)`, `getConsentStatus(personId)`, and `getConsentAuditTrail(personId)`. Bot relay uses draft-only consent requests when consent is missing; tenant WhatsApp drafts ask the user to reply YES before continuing, and landlord WhatsApp drafts do the same for property/contact/listing workflows.

RAG/manual source import remains governed: public/non-personal sources can be imported with source audit, but identifiable personal data requires a consent basis (`user_submitted`, `public_post`, `legitimate_review`, or `consent_required`). If consent is required, the system creates a `needs_review` RAG intake item and blocks profile creation until consent exists.

The UI contract adds a collapsed secondary admin section named `Consent & Privacy` showing pending, declined, and withdrawn consent records plus actions blocked due to missing consent. RAG Intake Review cards expose consent status, whether profile creation is allowed, and the blocked reason when consent is missing without rendering raw contact details or private labels.

Privacy/retention placeholders are available for data access, data correction, data deletion, and consent withdrawal requests. These are model/status placeholders only; review Singapore PDPA obligations and get legal counsel before production launch.

### Rendered Rental Intent Network admin UI

The backend UI contracts are rendered through the Rental Intent Network admin renderer on `EnrichmentModule`. The main dashboard remains focused on the primary operator workflow only: `Match Now`, `Waiting / Not Ready`, `At Risk`, `Tenancy Activation`, and `Renewal Queue`. RAG, consent, reply, import, and external-context tooling is kept in collapsed secondary sections and no analytics panels are added.

Rendered secondary sections are:

- `RAG Intake Review` — collapsed by default; shows source type, sanitized preview, extracted signals, suggested draft type, priority, confidence/freshness labels, privacy flags, consent status, blocked reason, and actions (`Approve`, `Ignore`, `Needs Review`).
- `Import Timing` — nested inside RAG Intake Review and collapsed by default; shows only high-priority, delayed, stale, and failed imports.
- `Reply Drafts` — collapsed by default; shows original message preview, detected intent, extracted slots, memory-used summary, draft reply, neutral risk flags, and actions (`Approve`, `Edit`, `Ignore`, `Mark Posted Manually`). Reply rendering never auto-posts or sends messages.
- `Consent & Privacy` — collapsed by default; shows pending, declined, and withdrawn consent records, blocked actions due to missing consent, and privacy request placeholders.
- `External Context` — collapsed inside the lead/person workspace; shows summary, signal labels, freshness/confidence labels, and actions (`Use in Note`, `Create Task`, `Ignore`).

All rendered sections use privacy-safe text: raw phone numbers, emails, private addresses, raw source traces, private trust labels, and numeric internal scores are withheld. Public/operator labels stay neutral: `Verified`, `Verification pending`, `Manual review required`, `Consent required`, or `Needs review`.

UI actions are thin handlers around existing backend methods: RAG intake actions call `approveRagIntakeItem()`, `ignoreRagIntakeItem()`, and `markRagIntakeNeedsReview()`; reply draft actions call `approveReplyDraft()`, `ignoreReplyDraft()`, `markReplyDraftNeedsReview()`, and `markReplyDraftPostedManually()`; consent actions use the existing consent record methods; External Context actions call `markRagEnrichmentUsed()` and `ignoreRagEnrichmentEvent()`. Production gaps remain around front-end styling, operator authentication/authorization, and edit-form implementation for reply drafts, but the backend-rendered payloads and handlers are wired and test-covered.

### Production admin UI polish

The rendered Rental Intent Network admin payload now includes production-oriented operator polish without adding new top-level product panels. The main dashboard still only exposes `Match Now`, `Waiting / Not Ready`, `At Risk`, `Tenancy Activation`, and `Renewal Queue`; RAG Intake Review, nested Import Timing, Reply Drafts, Consent & Privacy, and External Context remain collapsed secondary tools.

Each secondary section includes an empty state, count badge, neutral status labels, role-aware action metadata, and sanitized previews only. Supported UI roles are `admin`, `operator`, `reviewer`, and `readonly`: admins can approve/edit/ignore/mark needs review/mark posted manually; operators can approve low-risk items and create draft/task actions; reviewers can mark needs review or ignore but cannot approve high-risk items; readonly users can view only. This is UI gating metadata only and does not replace real authentication/authorization.

Reply drafts support an editable workflow through `editReplyDraft(id, editedText, reason, editedBy)` and `getReplyDraftEditHistory(id)`. Edits are stored as draft history, never post or send WhatsApp messages, and pass through `validatePublicReplyDraft(text)`, which sanitizes edited text, flags contact details/private addresses/raw source traces/private trust labels, and requires review for unsafe claims such as guaranteed housing.

Sensitive UI actions include confirmation metadata (`actionName`, `itemId`, `riskLevel`, `confirmationRequired`, and `confirmationMessage`) for approving high-risk RAG intake, marking replies posted manually, withdrawing consent, ignoring consent-blocked items, and using medium/high-sensitivity External Context in notes.

Remaining production gaps: real auth/RBAC enforcement, frontend styling and edit forms, deployment security hardening, and final legal/privacy review before launch.

### Authentication and RBAC

Rental Intent Network admin UI actions now use enforced RBAC permissions instead of role metadata alone. The store seeds `users`, `roles`, `permissions`, `role_permissions`, `sessions`, and `auth_audit_events` tables. Supported roles are `super_admin`, `admin`, `operator`, `reviewer`, and `readonly`.

Seeded permissions are `approve_rag_intake`, `ignore_rag_intake`, `edit_reply_draft`, `mark_posted_manually`, `create_task`, `create_note`, `approve_high_risk_item`, `withdraw_consent`, `manage_users`, and `manage_roles`. `super_admin` receives all permissions; `admin` receives all operator/review permissions plus high-risk approval, reply editing/post marking, and consent withdrawal; `operator` can approve low-risk intake and create notes/tasks; `reviewer` can ignore or mark needs review; `readonly` can view only.

The auth API includes `createUser()`, `login()`, `logout()`, `getSessionUser()`, `getUserRole()`, `getPermissionsForRole()`, `hasPermission()`, `requirePermission()`, and `getAuthAuditLog()`. Login creates revocable sessions, logout revokes sessions, and permission checks write audit events. Existing UI action handlers now accept optional `sessionToken` values and enforce permissions when provided while preserving internal backend calls that do not represent UI-user actions.

RBAC is intentionally lightweight and local to the SQLite-backed admin payload layer. Remaining production gaps: password hashing should move to a hardened password KDF, sessions should be bound to secure cookies/JWT infrastructure, auth should be integrated with deployment identity providers, and authorization should be reviewed with production security requirements.

### WhatsApp conversation runtime

The Rental Intent Network now includes a WhatsApp/bot conversation runtime that stores tenant and landlord conversations as internal memory events while preserving the platform rule that no messages are auto-sent, auto-replied, or auto-posted. The runtime is for history, timeline, and search only; operators must still approve and manually execute any outbound communication.

Conversation persistence uses three SQLite tables:

- `conversations` stores `conversationId`, `participantId`, `participantType`, optional `tenancyId`, optional `propertyId`, a JSON `messages` snapshot, and audit timestamps.
- `conversation_messages` stores each message with `sender`, `timestamp`, `messageType`, sanitized `content`, sanitized attachment metadata, privacy flags, and creation time.
- `conversation_memory_events` attaches conversation summaries to person, tenancy, and property memory so timelines can be generated without exposing raw private contact details.

The conversation API is available on `EnrichmentModule`:

- `createConversation(participantId, participantType, tenancyId=None, propertyId=None, conversationId=None)`
- `addConversationMessage(conversationId, sender, content, messageType="text", attachments=None, timestamp=None)`
- `attachConversationToTenancy(conversationId, tenancyId)`
- `attachConversationToProperty(conversationId, propertyId)`
- `getConversationHistory(conversationId)`
- `listParticipantConversations(participantId)` / `listConversationsForParticipant(participantId)`
- `getConversationTimeline(participantId=None, tenancyId=None, propertyId=None)`
- `searchConversationHistory(query, participantId=None, tenancyId=None, propertyId=None)`

Rendered history, timelines, and search results redact phone numbers, emails, private addresses, and private trust/risk labels. Conversation message and timeline responses explicitly state `autoSend=false`, `autoReply=false`, and `autoPost=false` so the runtime remains a memory/history layer rather than a messaging automation layer.

### Rental lifecycle engine

The Rental Intent Network now includes a recommendation-only lifecycle engine for matched tenancies. It tracks lifecycle state after matching without changing the governed RAG flow, matching logic, consent rules, or WhatsApp runtime. It must not auto-send messages, auto-renew a tenancy, or auto-adjust rent.

Supported lifecycle stages are `inquiry`, `viewing`, `application`, `tenancy_active`, `maintenance`, `renewal_window`, `renewal_offered`, `renewed`, `exited`, and `buying_interest`. Supported triggers are `lease_start`, `lease_end`, `renewal_window`, `maintenance_request`, `inactivity`, and `buying_interest`.

Lifecycle persistence uses three SQLite tables:

- `rental_lifecycles` stores the tenancy, tenant, property, stage, lease dates, last activity timestamp, open maintenance count, health status, health summary, and audit timestamps.
- `rental_lifecycle_events` stores lifecycle timeline events with stage, summary, trigger payload, and timestamp.
- `rental_lifecycle_recommendations` stores reminder and renewal recommendation records with priority, due date, status, and audit metadata that records no automatic sending, renewal, or rent adjustment.

The lifecycle API is available on `EnrichmentModule`:

- `createRentalLifecycle(tenancyId, tenantId, propertyId, leaseStart=None, leaseEnd=None, stage="inquiry")`
- `getRentalLifecycle(tenancyId)`
- `advanceLifecycleStage(tenancyId, stage, reason="manual_update")`
- `recordLifecycleTrigger(tenancyId, triggerType, payload=None)`
- `recordMaintenanceRequest(tenancyId, summary, reportedAt=None, payload=None)`
- `evaluateRentalLifecycle(tenancyId, asOf=None)`
- `listLifecycleRecommendations(tenancyId)`
- `getTenancyHealthSummary(tenancyId)`
- `getRentalLifecycleTimeline(tenancyId, includeConversations=True)`

Lease-start, lease-end, renewal-window, maintenance, and inactivity triggers generate operator reminders, renewal recommendations, or tenancy-health summaries only. Lifecycle timelines can include sanitized WhatsApp/conversation memory events for the same tenancy, but private contact details and private addresses remain redacted. Every lifecycle response returns recommendation-only side-effect metadata: `autoSend=false`, `autoReply=false`, `autoPost=false`, `autoRenew=false`, and `autoAdjustRent=false`.

### Unified memory timeline

The Rental Intent Network now provides a privacy-safe Timeline tab for a tenant, landlord, property, or tenancy. The timeline aggregates governed platform history without exposing raw source traces, private contact details, private addresses, or internal score fields.

Timeline sources include intake review events, consent records, person-verification events, WhatsApp/conversation memory, lifecycle tenancy events, viewing events, maintenance requests, renewal recommendations, matching queue/recommendation events, and Real Estate Memory OS enrichment events. The timeline stores optional first-party/manual timeline entries in `memory_timeline_events` and dynamically merges them with existing governed tables.

The timeline API is available on `EnrichmentModule`:

- `recordMemoryTimelineEvent(entityId, entityType, eventType, summary, source, relatedId=None, timestamp=None, metadata=None)`
- `recordViewingEvent(entityId, entityType, summary, timestamp=None, tenancyId=None, propertyId=None)`
- `getUnifiedMemoryTimeline(entityId, entityType, filters=None)`
- `renderTimelineTab(entityId, entityType, filters=None, role="admin", sessionToken=None)`

The Timeline tab shows only `timestamp`, `event type`, `summary`, and `source`. Supported filters are `conversations`, `tenancy`, `matching`, `verification`, and `consent`; the `tenancy` filter includes lifecycle, viewing, maintenance, and renewal timeline sources. Timeline payloads set `raw_source_trace_public=false` and `internal_scores_public=false`, and the admin UI exposes the timeline as a workspace tab rather than a new dashboard panel.
