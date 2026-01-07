# Scenario 12: Conversation Archive Integration and "Deep Memory"

## Scenario Description

Leverage the full historical data provided by the WeCom Archive Service to give the Bot "long-term memory" and a "global perspective".

## Architectural Foundation

### Data Flow
1. **WeCom Archive API** → **Archive Callback** → **SQLite/Postgres DB** (Full storage)
2. **WeCom Chat Window** → **AIBot Callback** → **LLM** (Interaction interface)

### Capability Differences
- **Short-term Memory (Context)**: Recent 20 messages, stored in memory/lightweight DB, used for direct conversation fluency.
- **Long-term Memory (Archive)**: All historical messages, stored in the full DB, accessed via "retrieval tools".

## Scenario A: Historical Recall

Users ask for information from a long time ago.

```
User: @gemini What was the API Key we discussed last Friday?
Gemini: (Triggers Archive search tool)
        🔍 Search time range: Last Friday
        🔍 Keyword: API Key
        
        Found the following relevant record:
        [2024-01-05 14:30] Zhang San: The API Key is `sk-123456...`
        
        Gemini: According to records, the API Key sent by Zhang San last Friday was `sk-123456...`.
```

## Scenario B: Automated Meeting Minutes (Daily Summary)

The Bot automatically summarizes the day's group chat content.

```
[Triggered automatically at 18:00 daily or manually]
User: @gemini Summarize today's discussion content.
Gemini: (Reads today's full messages from Archive)
        
        📅 **Today's Discussion Summary (2025-01-07)**
        
        **1. Requirements Review**
        - Confirmed the design style of the login page as fintech.
        - Decided to use Keycloak as the authentication service.
        
        **2. Bug Fixes**
        - Fixed the image upload failure on iOS (@Li Si)
        - Resolved the Token validation error in Archive Callback (@Wang Wu)
        
        **3. To-dos**
        - [ ] @Zhang San: Submit API definition document tomorrow
```

## Scenario C: Topic Tracking

Clarify the complete discussion timeline of a certain topic.

```
User: @gemini Help me track the complete resolution process regarding the "WeCom Callback" issue.
Gemini: (Searches for "WeCom Callback" related messages in Archive and sorts them by time)
        
        **WeCom Callback Issue Processing Timeline:**
        
        1. **Issue Discovery (12-25 10:00)**: @UserA first reported a 404 error on callback.
        2. **Investigation (12-25 10:30)**: @UserB found the Nginx configuration missing the `/wecom` path forwarding.
        3. **Fix Attempt (12-25 11:00)**: Modified Nginx configuration, but a 500 error occurred.
        4. **Final Resolution (12-25 14:00)**: Found it was an RSA private key path configuration error; verified after correction.
```

## Scenario D: New Member Onboarding

New members join the group chat and quickly catch up on context.

```
[New member joins the group]
New User: @gemini I just joined the group; what has everyone been talking about lately?
Gemini: (Gets Archive summary of the last 3 days)
        Welcome! Over the last 3 days, the group has mainly been discussing:
        1. Deployment and debugging of the WeCom Archive service
        2. Testing of the new AI Bot `/file-html` feature
        
        Key related documents:
        - `Design_Mockup_v3.png`
        - `api_docs_v2.pdf`
```

## Key Technical Points

### 1. Intent Recognition
The Bot needs to recognize whether the user is asking about "history" (requires Archive query) or "now" (requires only Context).
- "Last week..." → Archive
- "Just now..." → Context
- "Summarize..." → Archive (usually involves many messages)

### 2. Permission Boundaries
- The Bot can only read the Archive of the **group chat it is in**.
- Must strictly comply with WeCom data privacy specifications.

### 3. Toolification (Tool Use)
Archive queries are not just a "context supplement" but should be a **Tool** for the LLM.
```python
@tool
def search_archive(query: str, time_range: str, sender: str = None):
    """Search group chat history"""
    ...
```

## Data Architecture

### Why two databases? (Hot vs Cold)

There are currently two sets of databases in the system, and data overlap does exist, but this is an intentional **"Lambda Architecture"** design:

| Database | Role | Write Path | Characteristics | Use Cases |
| :--- | :--- | :--- | :--- | :--- |
| **chat_storage.db** | **Hot Data** | Real-time API Callback (@Bot) | **Low latency**, lightweight, contains only relevant messages | Context maintenance, second-level responses |
| **chat_history.db** | **Cold Data** | Asynchronous SDK Fetch (Archive) | **Full volume**, contains files/complex schema, higher latency | Historical recall, auditing, daily report generation |

**Reasons for not merging**:
1.  **Performance Isolation**: Archive synchronization involves large file downloads and decryption, which easily leads to long transaction table locks; the Bot needs millisecond responses and cannot be slowed down by the Archive.
2.  **Permission Boundaries**: The Bot DB contains only content users "explicitly" interact with, adhering to the principle of least privilege; the Archive DB contains private history, and access requires strict authentication.
3.  **Lifecycle**: Bot Context is a sliding window (storing only the most recent 20 messages); Archive is permanent storage.
