# Walkthrough: WeCom-OpenCode Bridge Implementation (Phase 2)

This document provides a technical summary of the components implemented for the WeCom-OpenCode integration, their locations, and how the architecture evolved during development.

## 1. Implemented Components & Locations

### A. Data Layer (The Language of the Bridge)
*   **File**: [opencode.py](file:///c:/work/code/crewAI/src/crewai_enterprise/server/models/opencode.py)
*   **Purpose**: Defines Pydantic models that bridge WeCom's raw JSON with OpenCode's SDK v2 specifications.
*   **Key Models**:
    *   `WeComInbound`: A normalized representation of a WeCom message (text or media).
    *   `OpenCodePart`: Strictly follows the `TextPartInput` / `FilePartInput` schema for OpenCode sessions.

### B. Cold Storage Interface (Archive Reader)
*   **File**: [archive_reader.py](file:///c:/work/code/crewAI/src/crewai_enterprise/server/archive_reader.py)
*   **Purpose**: Connects to the existing Kamatera SQLite databases.
*   **Logic**:
    *   Fetches the last $N$ messages from `chat_history.db`.
    *   Cross-references `msg_id` with `chat_storage.db` to pull extracted OCR text for images/files.

### C. OpenCode REST Client
*   **File**: [opencode_client.py](file:///c:/work/code/crewAI/src/crewai_enterprise/server/opencode_client.py)
*   **Purpose**: Encapsulates all HTTP interactions with the OpenCode server (Bun runtime).
*   **Reliability**: Implements a 3-retry strategy with exponential backoff for `prompt_async` to survive transient network issues on the VM.

### D. The Orchestrator (Bridge Brain)
*   **File**: [opencode_bridge.py](file:///c:/work/code/crewAI/src/crewai_enterprise/server/opencode_bridge.py)
*   **Purpose**: Manages the "Force Sync" lifecycle and differential history catch-up.
*   **Implementation**:
    *   Tracks a `last_sync_ts` per chat to prevent history redundancy.
    *   Triggers the [archive_sync_worker.py](file:///c:/work/code/crewAI/scripts/archive_sync_worker.py) on-demand to ensure the AI "sees" the latest human chatter.

### E. Handler & Routing Integration
*   **Entry Point**: [opencode_handler.py](file:///c:/work/code/crewAI/src/crewai_enterprise/server/handlers/opencode_handler.py)
*   **Routing**:
    *   [wecom_callback.py](file:///c:/work/code/crewAI/src/crewai_enterprise/server/wecom_callback.py): Added logic to detect `@OpenCode` bot mentions and route to the new handler.
    *   [text_handler.py](file:///c:/work/code/crewAI/src/crewai_enterprise/server/handlers/text_handler.py): Registered the `opencode` bot type.

---

## 2. Deviations from Original Plan/Roadmap

During implementation, we pivoted on several key architectural points to align with the physical reality of the WeCom API and your task requirements.

### Deviation 1: Sync Strategy (From Real-time to Trigger-Driven)
*   **Original Plan**: Bridge silently syncs *every* message in real-time.
*   **Problem**: WeCom bots only receive callbacks for messages where they are explicitly mentioned.
*   **Solution (Pivoted)**: **Hybrid Catch-up**. We now trigger a "Force Sync" of the archive the moment a mention occurs. The bridge then performs a "Differential Sync" to feed all missing human conversation to the AI before it processes the query. This ensures full context without requiring a global listener.

### Deviation 2: Path Handling (Hardcoded to Dynamic)
*   **Original Plan**: Use absolute Linux paths (e.g., `/opt/wecom-callback/...`).
*   **Adjustment**: Refactored the bridge and worker script to use **Dynamic Root Discovery**. This ensures that even if you move the project directory on the Kamatera server, the system can still find its own scripts and databases without code changes.

### Deviation 3: Session Persistence (Bookmark over State)
*   **Original Plan**: Maintain complex state in Redis for session mapping.
*   **Adjustment**: Switched to a **Persistent JSON Bookmark System** using `opencode_sync_state.json`. This ensures that context synchronization survives server restarts without redelivery of old messages.

## 3. Bug Fixes & Architectural Hardening
We have addressed several critical issues identified during our deep-dive audit:
- **Schema Alignment**: Corrected all SQL queries to match the actual `archived_messages` schema (`msgid`, `room_id`, etc.).
- **Timestamp Integrity**: Resolved `TypeError` issues by standardizing on string-based ISO comparisons across the database and bridge.
- **OCR Reliability**: Fixed the OCR status query to support both `extracted` and `partial` results.
- **Import Resolution**: Fixed missing handler exports in `wecom_callback.py`.

## 4. Current Status
*   **Phase 2 (Bridge Core)**: **COMPLETE**.
*   **Phase 3 (Message Sync)**: **COMPLETE** (via the Hybrid Catch-up mechanism).
*   **Next (Phase 4)**: Implementing **Command Parsing** (`/plan`, `/start-work`) and **SSE Status Aggregation** for real-time progress feedback.
