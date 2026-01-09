# Cross-Scenario Impact Analysis

## Implementation: Daily Report Generation (Scenario F from `11_mixed_scenarios.md`)

This document analyzes how the proposed implementation affects other documented scenarios.

---

## Summary Matrix

| Scenario | Document | Impact | Reason |
|----------|----------|--------|--------|
| **12. Archive Integration** | `12_archive_integration.md` | ✅ **HELPS** | Implements the core Archive Tool requirement |
| **02. Context Management** | `02_context_management.md` | ✅ **HELPS** | Clarifies Hot/Cold boundary in practice |
| **11. Mixed Scenarios** | `11_mixed_scenarios.md` | ✅ **HELPS** | Implements Scenario F directly, sets pattern for B/C/D/E |
| **13. LLM vs Agent** | `13_llm_vs_agent.md` | ✅ **HELPS** | Demonstrates intent-based tool triggering |
| **03. File HTML Gen** | `03_file_html_generation.md` | ✅ **HELPS** | Extends `/file-html` with structured output |
| **04. File Iterative** | `04_file_iterative_refinement.md` | ➖ **Unrelated** | File refinement is a separate flow |
| **05. GitLab Code Review** | `05_gitlab_code_review.md` | ➖ **Unrelated** | Different trigger & tool chain |
| **06. Codebase QA** | `06_codebase_qa.md` | ➖ **Unrelated** | Different data source (Git, not Archive) |
| **07. File Analysis** | `07_file_analysis.md` | ➖ **Unrelated** | PDF/Image processing is independent |
| **08. File Quote Context** | `08_file_quote_context.md` | ➖ **Unrelated** | Quote handling unchanged |
| **09. Custom Prompt** | `09_custom_prompt.md` | ➖ **Unrelated** | Prompt persistence unchanged |
| **10. Context Reset** | `10_context_reset.md` | ➖ **Unrelated** | Reset commands unchanged |
| **01. Basic Conversation** | `01_basic_conversation.md` | ➖ **Unrelated** | Basic flow unchanged |
| **14. Error Handling** | `14_error_handling_fallbacks.md` | ⚠️ **Needs Update** | Should add Archive Tool failure handling |
| **15. System Policies** | `15_system_policies.md` | ⚠️ **Needs Update** | Should document Archive access policy |

---

## Detailed Impact Analysis

### ✅ Scenarios That Benefit

#### 1. Scenario 12: Archive Integration
- **Why it helps**: Our implementation directly fulfills the `search_archive` tool requirement defined at line 105.
- **Shared components**: `get_archive_messages()` function enables Scenarios A (Historical Recall), B (Daily Summary), C (Topic Tracking), D (New Member Onboarding).

#### 2. Scenario 02: Context Management
- **Why it helps**: Clarifies the practical boundary between Hot (Context) and Cold (Archive) data access.
- **Decision rule implementation**: Our intent detection implements the documented rule: "Summarize..." → Archive.

#### 3. Scenario 11: Mixed Scenarios
- **Why it helps**: Scenario F is the first implementation; the pattern (Intent → Tool → LLM → Template → Upload) can be reused for Scenarios B, C, D, E.

#### 4. Scenario 13: LLM vs Agent
- **Why it helps**: Demonstrates that Archive retrieval is a "tool call" triggered by intent, not a full-blown CrewAI Agent task.

#### 5. Scenario 03: File HTML Generation
- **Why it helps**: The JSON-first output approach improves `/file-html` stability for all file generation requests, not just reports.

---

### ⚠️ Scenarios That Need Updates

#### 14. Error Handling Fallbacks
**New failure case to document**:
```
### Archive Tool Failure
- **Trigger**: Archive DB is locked or unreachable
- **Fallback**: Bot replies: "⚠️ I'm unable to access the historical archive right now. Please try again later."
```

#### 15. System Policies
**New policy to add**:
```
| **Archive Access** | LLM may only query archive for the current group chat (room_id). Cross-group queries are prohibited. |
```

---

### ➖ Unrelated Scenarios

The following scenarios are **unaffected** by this implementation:
- **04 File Iterative Refinement**: Different workflow (multi-turn file editing)
- **05 GitLab Code Review**: Separate trigger (URL detection), different tools (GitLab API)
- **06 Codebase QA**: Uses `/codebase` context, not Archive
- **07/08 File Analysis & Quote**: PDF/Image handling is independent
- **09/10 Prompt & Reset**: Command handlers unchanged
- **01 Basic Conversation**: No impact on basic multi-turn flow

---

## Risk Assessment

| Risk | Likelihood | Mitigation |
|------|------------|------------|
| **Archive Tool slowness** | Medium | Add timeout, show "loading" status |
| **Token explosion (>500 msgs)** | High | Map-Reduce in plan addresses this |
| **Lock file deadlock** | Low | Already fixed with proper cleanup |

---

## Recommendation

**Proceed with implementation.** The Daily Report feature:
1. **Directly enables** 4 related Archive scenarios (12-A, 12-B, 12-C, 12-D)
2. **Improves** `/file-html` reliability for all users
3. **Does not break** any existing functionality
4. **Requires minor doc updates** to Error Handling and System Policies
