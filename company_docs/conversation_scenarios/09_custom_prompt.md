# 场景 09：自定义 Prompt

## 场景描述

用户通过命令自定义 AI 的角色和行为。

## 核心命令

| 命令 | 功能 |
|-----|------|
| `/show_prompt` | 查看当前 Prompt |
| `/set_prompt <内容>` | 设置自定义 Prompt |
| `/reset_prompt` | 恢复默认 Prompt |

## 对话示例

### 设置自定义 Prompt
```
用户：@gemini /set_prompt 你是一个专业的 Python 开发专家，擅长代码优化和最佳实践。请用中文回答，并尽可能提供代码示例。

Gemini：✅ 已设置自定义 Prompt

        预览：
        你是一个专业的 Python 开发专家，擅长代码优化和最佳实践。请用中文回答...

        💡 使用 /show_prompt 查看完整内容

用户：@gemini 如何优化列表推导式？
Gemini：作为 Python 专家，我来介绍列表推导式的优化技巧：
        
        ```python
        # 基础写法
        result = [x * 2 for x in range(1000)]
        
        # 优化：使用生成器表达式（节省内存）
        result = (x * 2 for x in range(1000))
        ```
```

### 查看当前 Prompt
```
用户：@gemini /show_prompt
Gemini：📝 当前使用的自定义 Prompt：

        你是一个专业的 Python 开发专家，擅长代码优化和最佳实践...

        💡 使用 /reset_prompt 可以恢复默认设置
```

### 重置 Prompt
```
用户：@gemini /reset_prompt
Gemini：✅ 已恢复默认 Prompt

        You are a helpful assistant. Respond naturally to conversations...

用户：@gemini 如何优化列表推导式？
Gemini：列表推导式是 Python 的一个强大特性...
        # 回复风格回到默认
```

## Prompt 优先级

```
自定义 Prompt (用户设置)  →  优先级最高
            ↓
默认 Prompt (系统配置)  →  最低优先级
```

### 代码实现
```python
# 获取 Prompt
custom_prompt = context_manager.get_custom_prompt(chat_id, bot_type)
if custom_prompt:
    system_prompt = custom_prompt
else:
    system_prompt = BOT_CONFIGS[bot_type]["system_prompt"]
```

## Prompt 模板示例

### 技术专家
```
你是一个资深的全栈开发工程师，擅长：
- Python/JavaScript/TypeScript
- 系统架构设计
- 代码审查和优化

回答要求：
1. 提供具体的代码示例
2. 解释技术原理
3. 分析优缺点
4. 使用中文回答
```

### 产品经理
```
你是一个经验丰富的产品经理，擅长：
- 需求分析和文档编写
- 用户体验设计
- 项目管理

回答时请从产品角度思考，关注用户价值和商业价值。
```

### 翻译助手
```
你是一个专业的中英翻译，请：
1. 保持原文语义
2. 使用自然流畅的目标语言表达
3. 对于专业术语提供解释
```

## Prompt 存储

### 数据库结构
```python
# chat_prompts 表
{
    "chat_id": "group_xxx",
    "bot_type": "gemini",
    "prompt": "你是一个专业的...",
    "updated_at": "2024-01-07 10:00:00"
}
```

### 存储逻辑
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

## 多 Bot 场景

```
用户：@gemini /set_prompt 你是 Python 专家
Gemini：✅ 已设置

用户：@chatgpt /set_prompt 你是前端专家
ChatGPT：✅ 已设置

用户：@gemini Python 问题...
Gemini：（使用 Python 专家 Prompt）

用户：@chatgpt React 问题...
ChatGPT：（使用前端专家 Prompt）
```

## 限制与验证

| 限制项 | 当前值 |
|-------|-------|
| 最小长度 | 10 字符 |
| 最大长度 | 2000 字符 |
| 每群每 Bot | 1 个自定义 Prompt |

## 关键决策

| 决策点 | 当前方案 | 备选方案 |
|-------|---------|---------|
| 作用范围 | 按 chat_id + bot_type | 全局账户级别 |
| 权限控制 | 无（群内任何人可改） | 仅管理员 |
| 历史版本 | 不保留 | 版本历史 |
| Prompt 模板 | 不支持 | 预设模板选择 |

## 待考虑

1. **权限控制**：谁可以修改群聊的 Prompt？
2. **Prompt 模板**：提供预设模板选择？
3. **Prompt 验证**：是否需要过滤敏感内容？
4. **导出/导入**：允许导出 Prompt 配置？
