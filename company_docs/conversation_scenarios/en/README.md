# Multi-turn Conversation Scenarios Overview

This directory contains design documents for all multi-turn conversation scenarios of the WeCom AI bot.

## Purpose

- Exhaustively cover all conversation scenarios
- Clarify context management strategies
- Define command behaviors
- Clarify Agent collaboration logic

## Architectural Perspective

- [13_llm_vs_agent.md](13_llm_vs_agent.md) - **Core: Differences between LLM Conversations vs Agent Tasks**

## Scenario Classification

### Basic Conversation
- [01_basic_conversation.md](01_basic_conversation.md) - Basic multi-turn conversation
- [02_context_management.md](02_context_management.md) - Context management and limits

### File Generation
- [03_file_html_generation.md](03_file_html_generation.md) - HTML file generation
- [04_file_iterative_refinement.md](04_file_iterative_refinement.md) - Iterative file refinement

### Code Analysis
- [05_gitlab_code_review.md](05_gitlab_code_review.md) - GitLab code review
- [06_codebase_qa.md](06_codebase_qa.md) - Codebase QA

### File Processing
- [07_file_analysis.md](07_file_analysis.md) - File analysis (PDF/Images)
- [08_file_quote_context.md](08_file_quote_context.md) - File quoting and context

### Prompt Management
- [09_custom_prompt.md](09_custom_prompt.md) - Custom Prompts
- [10_context_reset.md](10_context_reset.md) - Context reset

### Complex Scenarios
- [11_mixed_scenarios.md](11_mixed_scenarios.md) - Mixed complex scenarios (Vision+Codebase, Multi-Bot)
- [12_archive_integration.md](12_archive_integration.md) - Conversation archive integration and "Deep Memory"
- [14_error_handling_fallbacks.md](14_error_handling_fallbacks.md) - **Failure & Fallback Mechanisms**
- [15_system_policies.md](15_system_policies.md) - **Deduplication, Modality, & Core System Policies**

## Design Principles

1. **Context Isolation**: Context for different group chats is completely isolated.
2. **Sliding Window + Deep Retrieval**: Short-term memory relies on a sliding window, long-term memory relies on Archive retrieval.
3. **Command Priority**: Explicit commands > Implicit behaviors.
4. **Least Surprise**: Behavior should meet user expectations.
