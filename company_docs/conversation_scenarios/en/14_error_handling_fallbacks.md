# Scenario 14: Error Handling and Fallbacks

## Scenario Description

This scenario outlines how the system handles common errors and what fallback messages or behaviors the user should expect.

---

## 1. File Access Failures

### Missing File URL / Download Failure
- **Trigger**: User sends a file but the WeCom CDN URL is invalid or the download fails.
- **Bot Behavior**: 
  - Friendly error message explaining the failure.
  - Suggests retrying or resending the file.
- **Example**:
  ```
  User: [Sends file: Data.xlsx]
  User: @gemini Summarize this.
  
  Gemini: ❌ Received file: "Data.xlsx", but I was unable to retrieve it from the server. Please try resending the file or wait a moment.
  ```

### Unsupported File Type
- **Trigger**: Non-Gemini bot receives a format it cannot parse (e.g., `.docx`).
- **Bot Behavior**: 
  - Explains the limitation.
  - Suggests using `@gemini` or converting to PDF.
- **Example**:
  ```
  User: [Sends file: Design.docx]
  User: @chatgpt Analyze this.
  
  ChatGPT: ⚠️ Received "Design.docx". As ChatGPT, I cannot analyze Docx files directly. Please try @gemini or send as PDF/plain text.
  ```

---

## 2. Infrastructure Failures

### Archive Service Offline
- **Trigger**: User asks a historical question but the `chat_history.db` is unavailable or the sync worker is down.
- **Bot Behavior**: 
  - Alerts the user that historical search is temporarily unavailable.
  - Offers to answer based on current context.
- **Example**:
  ```
  User: @gemini What did we say last month?
  
  Gemini: 🔍 Attempting to search history...
  Gemini: ⚠️ I'm sorry, the historical archive service is currently offline. I can only answer based on our current conversation.
  ```

### Codebase/GitLab Not Found
- **Trigger**: User enters an invalid project name with `/codebase`.
- **Bot Behavior**: 
  - Lists available projects (if possible) or asks for clarification.
- **Example**:
  ```
  User: @gemini /codebase wrong_project
  
  Gemini: ❌ Codebase `wrong_project` not found. Please check the name or ensure you have access.
  ```

---

## 3. Configuration & API Failures

### Missing GitLab Token
- **Trigger**: System attempts a Code Review but the `GITLAB_TOKEN` is missing.
- **Bot Behavior**: 
  - Logs a critical error.
  - Informs the user about the configuration issue.
- **Example**:
  ```
  User: [Sends GitLab MR link]
  
  Gemini: 🛠 Starting Code Review...
  Gemini: ❌ Configuration Error: GitLab access token is missing. Please contact the administrator.
  ```

### LLM Timeout / API Error
- **Trigger**: Gemini or OpenAI API returns a 500 or times out.
- **Bot Behavior**: 
  - Retries once (internal logic).
  - If it still fails, notifies the user to wait and retry.
- **Example**:
  ```
  User: @gemini [Complex request]
  
  Gemini: ⏳ [Delay...]
  Gemini: 抱歉，发生了意外错误 (LLM Timeout)。请稍后再试。
  ```

---

## Summary of Fallback Policies

| Error Type | Bot Strategy |
| :--- | :--- |
| **Transient (5xx, Timeout)** | Silent retry once -> User error notify. |
| **Logic (No file, Wrong path)** | Explain the issue + suggest fix. |
| **Capability (Unsupported file)** | Suggest bot switch (@gemini). |
| **Security (No access)** | Reject with minimal detail. |
