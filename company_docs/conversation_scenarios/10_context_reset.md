# 场景 10：上下文重置

## 场景描述

用户通过命令重置对话上下文，清除历史记录或文件关联。

## 核心命令

| 命令 | 功能 | 清除范围 |
|-----|------|---------|
| `/reset` | 完全重置 | 对话历史 + 文件上下文 + 代码库上下文 |
| `/new` | 清除文件上下文 | 仅文件关联，保留对话历史 |

## 对话示例

### /reset - 完全重置
```
[之前有 15 条对话]
用户：@gemini /reset
Gemini：✅ 已彻底重置所有对话历史和上下文（删除了 15 条历史记录）
        🔄 现在是一个全新的开始，机器人已不再记得之前的任何对话。

用户：@gemini 你还记得我们之前讨论什么吗？
Gemini：你好！这是我们的第一次对话，请问有什么可以帮助你的吗？
```

### /new - 清除文件上下文
```
用户：[发送 PDF: 报告.pdf]
用户：@gemini 总结这个文档
Gemini：这是一份关于...的报告

用户：@gemini /new
Gemini：✅ 已清除文件上下文，开始新对话
        💡 之前的文件将不再自动使用，如需引用请重新发送或 Quote

用户：@gemini 刚才那个报告说了什么来着？
Gemini：根据我们之前的对话，报告主要讨论了...
        # 对话历史保留，知道之前讨论过报告

用户：@gemini 继续分析报告的第三章
Gemini：你好！请先发送需要分析的文档，或引用之前的文件消息。
        # 文件上下文已清除，无法直接访问 PDF
```

## /reset 清除内容

```python
def handle_reset_command(chat_id):
    # 1. 清除消息历史
    deleted_count = context_manager.clear_context(chat_id)
    
    # 2. 清除文件上下文
    context_manager.clear_file_context(chat_id)
    
    # 3. 清除代码库上下文
    if chat_id in _user_project_context:
        del _user_project_context[chat_id]
    
    return f"删除了 {deleted_count} 条历史记录"
```

## /new 清除内容

```python
def handle_new_command(chat_id):
    # 仅清除文件关联
    success = context_manager.clear_file_context(chat_id)
    # 对话历史保留
    return success
```

## 使用场景

### 场景 1：切换话题
```
用户：[讨论 Python 项目]
用户：@gemini /new
用户：[发送新的 Java 文件]
用户：@gemini 分析这个 Java 代码
# 避免 Python 上下文干扰 Java 分析
```

### 场景 2：隐私清除
```
用户：[讨论敏感业务数据]
用户：@gemini 分析这些数据
Gemini：...

用户：@gemini /reset
# 确保敏感数据不再保留在上下文中
```

### 场景 3：调试
```
用户：@gemini 这个回答不对，你是不是被之前的上下文影响了？
用户：@gemini /reset
用户：@gemini [重新提问]
# 排除上下文干扰
```

## 清除确认

### 当前：无确认
```
用户：@gemini /reset
Gemini：✅ 已重置...
# 直接执行，无确认
```

### 备选：需要确认
```
用户：@gemini /reset
Gemini：⚠️ 将删除 15 条历史记录，确认吗？回复 Y 确认
用户：Y
Gemini：✅ 已重置...
```

## 自动清除策略

### 当前：无自动清除
```python
# 所有消息永久保留（除非手动 /reset）
```

### 备选：定期清理
```python
# 30 天前的消息自动清理
# 仅保留最近 100 条消息
```

## 关键决策

| 决策点 | 当前方案 | 备选方案 |
|-------|---------|---------|
| 确认机制 | 无需确认 | 敏感操作需确认 |
| 自动清理 | 无 | 定期清理 |
| 清除粒度 | 群聊级别 | 用户+群聊级别 |
| 撤销操作 | 不可撤销 | 7 天内可恢复 |

## 待考虑

1. **撤销功能**：是否需要 `/undo` 撤销删除？
2. **选择性清除**：只清除某个时间段的记录？
3. **导出功能**：清除前导出对话记录？
4. **自定义保留期**：允许设置自动清理周期？
