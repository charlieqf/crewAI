# Scenario 15: System Policies

## Scenario Description

This document formalizes the internal design logic and core policies that govern the AI Bot's behavior across all scenarios.

---

## 1. Message Deduplication Policy

WeCom often retries callbacks if the server doesn't respond within 5 seconds. To prevent the Bot from answering the same question multiple times, we implement a **Deduplication Policy**.

- **Mechanism**: Use `wecom_msg_id` as a unique key.
- **Behavior**:
  - If a `wecom_msg_id` is received that is already being processed, the system returns the **cached stream link** or ignores the duplicate.
  - User sees only one active response in the chat.
- **Example**:
  ```
  Callback A (msg_id: 123) -> Start processing...
  Callback B (msg_id: 123) -> [Retry] -> Detect duplicate -> Map to same task.
  ```

---

## 2. Mixed Modality Merging Policy

When a single user turn contains multiple types of input, the system merges them into a structured prompt.

### Modality Merging Sequence (Prompt Construction)
When the system prepares the prompt for the LLM, it follows this order:
1. **Quoted Text**: `[User quoted message: {content}]` (Prepended as context).
2. **File Contents**: `[File Attachment: {filename} ({mime_type})]` (Extracted text or Vision data).
3. **Primary Text**: `{cleaned_text}` (The actual message sent by the user, after @mention and command removal).

### Instruction Priority: Text > File > Quote
While the prompt is constructed in the sequence above, the **Primary User Text** always has the highest **instruction priority**. If there is a conflict in instructions (e.g., text says "Do A" but a quoted file suggests "Do B"), the LLM is instructed to prioritize the user's direct text.

> [!NOTE]
> Commands (e.g., `/reset`, `/set_prompt`) are extracted and executed **before** the remaining text is processed as "Primary Text".

---

## 3. Memory Model Decision Policy

The system maintains a clear boundary between **Context** and **Archive**.

| Threshold | Rule |
| :--- | :--- |
| **Turns < 20** | Rely on **Short-term Context**. Fast, automatic. |
| **Time > 10 Min** | File context expires. Must quote or resend. |
| **Multi-file** | **Explicitly allowed** for comparisons (up to 10 files if quoted or within context). |
| **History Request**| Explicitly check **Archive**. Triggers `search_archive` tool. |

### Decision logic: "Search vs. Recall"
- If the LLM identifies a temporal keyword (e.g., "last week", "yesterday morning"), it **must** check its Archive tool rather than attempting to hallucinate from short-term memory.

---

## 4. Cross-Bot Interaction Policy

- **Shared Context**: Bots in the same group share the same `chat_id` and therefore the same message history.
- **Environment Persistence**:
  - `/set_prompt` persists for that specific bot in that chat.
  - `/codebase` persists for the entire chat session (all bots see the active project).
  - `/reset` clears **all** bot history and configurations for that chat.

---

## 5. Summary Table of Core Rules

| Feature | Rule |
| :--- | :--- |
| **Retry Handling** | msg_id based dedup. |
| **Multi-file** | Quote > Most recent. |
| **Command Conflict** | Priority: Reset > Config > Task. |
| **Bot Fallback** | Suggest @gemini for native files. |
| **Privacy** | Archive access is restricted to the current group chat only. |
