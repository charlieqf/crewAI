# Development Roadmap: WeCom-OpenCode Bridge

This refined roadmap aligns closely with the technical specifications in `opencode_integration_plan.md`.

## Phase 1: Infrastructure Foundation (Status: DONE)
> **Goal**: Establish the runtime environment on Kamatera.
1. [x] Install Bun & Node.js runtimes.
2. [x] Global install of `opencode-ai` CLI.
3. [x] Git clone `oh-my-opencode` to `/opt/oh-my-opencode`.
4. [x] Run `bun install` in OMO directory.
5. [x] Verify `opencode` CLI is accessible.

## Phase 2: Bridge Skeleton & Models (Current)
> **Goal**: Define the data contracts and storage interfaces.
1. **Pydantic Models**: Create `src/crewai_enterprise/server/models/opencode.py`.
   - Implement `WeComInbound`, `OpenCodePart`, and `BackfillChunk` per Appendix B.
2. **Metadata Mapping Logic**: Implement the transformation from WeCom fields to `OpenCodePart.metadata`.
   - Map `sender_name`, `msg_id`, `mentions`, `quoted_msg_id`, and `storage_key`.
3. **REST Client**: Implement `OpenCodeClient`.
   - `prompt_async`: 15s timeout, 3 retries (2s, 5s, 10s).
   - `prompt` (interactive): 60s timeout, no auto-retry.
   - `command` (OMO): 60s timeout, no auto-retry.
4. **Storage Layers**: Implement Protocol-based stores.
   - `DedupStore`: Redis-backed Set with 7d TTL.
   - `SessionStore`: Map `chat_id` (groups or 1:1) to `session_id`.
   - `SyncStateStore`: Track `(timestamp, msg_id)` per-chat.

## Phase 3: Background Sync & Backfill
> **Goal**: Implement the "Native Sync" pipeline.
1. **Real-time Pipeline**: Implement `handle_inbound` logic.
   - Normal messages: `prompt_async(noReply: true)`.
   - Mentions: Route to Interactive Handler.
2. **Deduplication & Sorting**:
   - Filter inbound by `DedupStore`.
   - Sort batches by `(msg_time, seq, msg_id)` to ensure narrative consistency.
3. **Aggregated Backfill**:
   - Implement the chunking algorithm: `count<=100`, `chars<=30k`, `window<=30m`.
   - Template: "Transcript Backfill" block per Appendix 2.2.

## Phase 4: Interaction & Command Parsing
> **Goal**: Map WeCom UX to OMO Brain.
1. **Trigger Logic**: Parse `@OpenCode` anywhere and slash commands.
   - *Note*: Slash commands are only honored if `@OpenCode` is present or in 1:1.
2. **Command Dispatcher**: Map `/plan`, `/start-work`, `/reset`, and `/resync` to OpenCode endpoints.
3. **Agent Routing (SDK Alignment)**:
   - Extract `@Agent` tags (e.g., `@Oracle`).
   - Use `AgentPartInput` in the `parts` list for routing to specific subagents.
   - Set the top-level `agent` field in the request body as the primary orchestrator (e.g., `sisyphus`). Avoid overriding unless explicitly requested.

## Phase 5: SSE Aggregation & Operational Polish
> **Goal**: High-fidelity feedback and stability.
1. **SSE Status Aggregator**:
   - Immediate first update for user feedback.
   - 10s throttling for subagent "thoughts".
   - Priority flush for completion, errors, and approvals.
2. **Failure Handling**:
   - Implement the Failure Matrix (Appendix F) for OpenCode/Archive outages.
3. **Systemd Integration**: Create `opencode-bridge.service` on Kamatera.

## Phase 6: Integration Testing & Verification
> **Goal**: End-to-end validation.
1. **Mock Environment**: Setup a mock WeCom server and OpenCode SDK simulator.
2. **Integration Tests**:
   - Verify `prompt_async` batching during large backfills.
   - Verify `Interactive Handler` stream passthrough.
   - Verify `Metadata Traceability` (Checking if WeCom fields arrive in OpenCode).
   - **Backfill Persistence**: Ensure backfill deduplication survives a bridge restart (no re-sending old messages).
3. **Live Validation**: Deploy to Kamatera and test in a restricted group chat.

## Technical Clarifications & Decisions (Refined for Team Review)

Based on internal alignment, we have finalized several architectural trade-offs. This section details the rationale and concrete implementation for each decision.

### 1. Deduplication Scope: Per-Chat Isolation
*   **Decision**: Deduplicate messages using a composite key: `chat_id + msg_id`.
*   **Rationale**: WeCom `msg_id` is unique globally, but users often forward the same message into multiple groups. If we deduplicate globally, the message will only appear in the history of the *first* group that processed it.
*   **Impact**: Ensures that every group chat (and its corresponding OpenCode session) has a complete, self-contained narrative. 
*   **Implementation**: A Redis Set `dedup:{chat_id}` storing seen `msg_id`s with a 7-day TTL.

### 2. Backfill Strategy for Non-Text Media: Hybrid Metadata + OCR
*   **Decision**: During aggregated backfills (last 6h), insert Markdown-style references instead of raw files.
*   **Format**: `[10:02] Alice: sent image (OCR: "Error 500 at /api/pay") [ID: storage_key_123]`
*   **Rationale**: Sending 100+ raw file parts in a single backfill payload would bloat the prompt window and hit the OpenCode rate limits. By including OCR text snippets, the AI can still "search" historical images without downloading them.
*   **Implementation**: Bridge will query the OCR results from the `file_contents` table in `chat_storage.db` during backfill generation.

### 3. SSE Update Aggregator: Parallel Concatenation
*   **Decision**: Concatenate parallel agent statuses into a single status line.
*   **Example**: "Librarian: searching stripe docs | Oracle: auditing auth_handler.py"
*   **Rationale**: OpenCode's value is multi-agent parallelization. Users should see that multiple experts are working simultaneously. Throttling to 10s prevents "status spam" while maintaining high-IQ transparency.

### 4. Session Keys: Strict Session Isolation
*   **Decision**: Use the WeCom-native `chat_id` (both for Groups and 1:1) as the mapping key for OpenCode sessions.
*   **Rationale**: While `user_id` allows AI memory to follow a user across chats, it violates the privacy expectations of 1:1 chat silos. User-level memory across chats is deferred/opt‑in.
*   **Implementation**: `SessionStore` maps `chat_id` -> `opencode_session_uuid`.

### 5. Mixed-Media Messages: Part Splitting
*   **Decision**: Split WeCom messages containing both text and images into a `parts` array in the OpenCode request.
*   **Rationale**: This is the native format for OpenCode SDK v2. Merging them into a single string (OCR only) would lose the ability for the AI to "view" the original high-res image if needed.

### 6. Admin Identification: Static Whitelist
*   **Decision**: Use an env-based array of `user_id`s for administrative command verification (`/reset`, `/resync`).
*   **Rationale**: Speed of implementation. Querying the WeCom "is_group_admin" API for every command adds latency and complexity for minimal gain in the initial phase.

### 7. Repository Directory Mapping: Strict 1:1
*   **Decision**: Each `chat_id` is tied to exactly one absolute server path.
*   **Example**: `Group_A` -> `/opt/oh-my-opencode`.
*   **Rationale**: Prevents accidental cross-repo pollution. If a team needs to work on a different repo, they must use a different group chat or have a different bot instance configured.

### 8. Git Write Permissions: Read-Only (Phase 1)
*   **Decision**: The AI can propose code changes but cannot `git push` or open Merge Requests.
*   **Rationale**: We have not yet provisioned SSH keys with write access on the Kamatera VM. Human approval and manual push (via the terminal or a developer) remains the safety barrier.
