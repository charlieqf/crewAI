# Scenario 09: Custom Prompt

## Scenario Description

Users customize the AI's role and behavior through commands.

## Core Commands

| Command | Function |
|-----|------|
| `/show_prompt` | View the current Prompt |
| `/set_prompt <content>` | Set a custom Prompt |
| `/reset_prompt` | Restore default Prompt |

## Conversation Example

### Setting a Custom Prompt
```
User: @gemini /set_prompt You are a professional Python development expert, specializing in code optimization and best practices. Please respond in Chinese and provide code examples as much as possible.

Gemini: ✅ Custom Prompt set
        
        Preview:
        You are a professional Python development expert, specializing in code optimization and best practices. Please respond in Chinese...
        
        💡 Use /show_prompt to view the full content.

User: @gemini How to optimize list comprehensions?
Gemini: As a Python expert, let me introduce optimization techniques for list comprehensions:
        
        ```python
        # Basic approach
        result = [x * 2 for x in range(1000)]
        
        # Optimization: Use generator expression (saves memory)
        result = (x * 2 for x in range(1000))
        ```
```

### Viewing Current Prompt
```
User: @gemini /show_prompt
Gemini: 📝 Currently used custom Prompt:
        
        You are a professional Python development expert, specializing in code optimization and best practices...
        
        💡 Use /reset_prompt to restore default settings.
```

### Resetting Prompt
```
User: @gemini /reset_prompt
Gemini: ✅ Default Prompt restored
        
        You are a helpful assistant. Respond naturally to conversations...

User: @gemini How to optimize list comprehensions?
Gemini: List comprehension is a powerful feature in Python...
        # Reply style returns to default
```

## Prompt Priority

```
Custom Prompt (User set)  →  Highest Priority
            ↓
Default Prompt (System config)  →  Lowest Priority
```

### Code Implementation
```python
# Get Prompt
custom_prompt = context_manager.get_custom_prompt(chat_id, bot_type)
if custom_prompt:
    system_prompt = custom_prompt
else:
    system_prompt = BOT_CONFIGS[bot_type]["system_prompt"]
```

## Prompt Template Examples

### Technical Expert
```
You are a senior full-stack development engineer, specializing in:
- Python/JavaScript/TypeScript
- System architecture design
- Code review and optimization

Response Requirements:
1. Provide specific code examples
2. Explain technical principles
3. Analyze pros and cons
4. Respond in Chinese
```

### Product Manager
```
You are an experienced product manager, specializing in:
- Requirement analysis and documentation
- User experience design
- Project management

Please think from a product perspective, focusing on user value and business value.
```

### Translation Assistant
```
You are a professional Chinese-English translator, please:
1. Maintain the original semantics
2. Use natural and fluent target language expressions
3. Provide explanations for professional terminology
```

## Prompt Storage

### Database Structure
```python
# chat_prompts table
{
    "chat_id": "group_xxx",
    "bot_type": "gemini",
    "prompt": "You are a professional...",
    "updated_at": "2024-01-07 10:00:00"
}
```

### Storage Logic
```python
def set_custom_prompt(self, chat_id, user_id, bot_type, prompt):
    self.storage._run(
        action="save_prompt",
        chat_id=chat_id,
        user_id=user_id,
        bot_type=bot_type,
        prompt=prompt,
    )
```

## Multi-Bot Scenarios

```
User: @gemini /set_prompt You are a Python expert
Gemini: ✅ Set

User: @chatgpt /set_prompt You are a frontend expert
ChatGPT: ✅ Set

User: @gemini Python question...
Gemini: (Uses Python expert Prompt)

User: @chatgpt React question...
ChatGPT: (Uses frontend expert Prompt)
```

## Limits and Validation

| Item | Current Value |
|-------|-------|
| Minimum Length | 10 characters |
| Maximum Length | 2000 characters |
| Per Group Per Bot | 1 custom Prompt |

## Key Decisions

| Decision Point | Current Solution | Alternatives |
|-------|---------|---------|
| Scope | By chat_id + bot_type | Global account level |
| Permission | None (anyone in group can change) | Admin only |
| Version History | Not retained | Version history |
| Prompt Templates | Not supported | Preset template selection |

## To Be Considered

1. **Permission Control**: Who can modify the prompt of a group chat?
2. **Prompt Templates**: Provide preset template selection?
3. **Prompt Validation**: Need to filter sensitive content?
4. **Export/Import**: Allow exporting prompt configuration?
