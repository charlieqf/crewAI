# Prompt Management and File Generation Enhancement

## 目标

1. 为 ChatGPT 和 Grok 添加文件生成能力
2. 实现 prompt 管理命令系统

---

## 任务清单

### Phase 1: 扩展文件生成能力
- [x] 分析当前 Gemini 的文件生成 prompt
- [x] 更新 ChatGPT 的 system_prompt，添加 FILE 标签指令
- [x] 更新 Grok 的 system_prompt，添加 FILE 标签指令
- [ ] 测试验证 ChatGPT 和 Grok 的文件生成功能

### Phase 2: Prompt 管理命令设计
- [x] 设计命令格式和参数
  - `/show_prompt` - 显示当前 prompt
  - `/set_prompt <新的prompt内容>` - 设置自定义 prompt
  - `/reset_prompt` - 恢复默认 prompt
- [x] 设计数据库表结构（存储用户自定义 prompt）
- [x] 设计 prompt 优先级逻辑（自定义 > 默认）

### Phase 3: 数据库扩展
- [x] 创建 `custom_prompts` 表
  - `chat_id` (TEXT, PRIMARY KEY)
  - `user_id` (TEXT)
  - `bot_type` (TEXT)
  - `custom_prompt` (TEXT)
  - `created_at` (TIMESTAMP)
  - `updated_at` (TIMESTAMP)
- [x] 在 `ChatContextManager` 中添加 prompt 管理方法
  - `get_custom_prompt(chat_id, bot_type)`
  - `set_custom_prompt(chat_id, user_id, bot_type, prompt)`
  - `delete_custom_prompt(chat_id, bot_type)`

### Phase 4: 命令处理器实现
- [x] 在 `aibot_callback.py` 中添加命令检测逻辑
- [x] 实现 `/show_prompt` 处理器
  - 获取当前使用的 prompt（自定义 or 默认）
  - 格式化回复消息
- [x] 实现 `/set_prompt` 处理器
  - 解析命令参数
  - 验证 prompt 内容（长度限制、安全检查）
  - 保存到数据库
  - 发送确认消息
- [x] 实现 `/reset_prompt` 处理器
  - 删除自定义 prompt
  - 发送确认消息
- [x] 集成到主消息处理流程
  - 在调用 LLM 前检查是否为命令
  - 命令处理完后直接返回，不调用 LLM

### Phase 5: Prompt 加载逻辑
- [x] 修改 `_call_llm_async` 函数
- [x] 在获取 `system_prompt` 时，优先使用自定义 prompt
- [x] 添加日志记录（使用的是默认还是自定义 prompt）

### Phase 6: 测试验证
- [ ] 测试 ChatGPT 文件生成
- [ ] 测试 Grok 文件生成
- [ ] 测试 `/show_prompt` 命令
- [ ] 测试 `/set_prompt` 命令
- [ ] 测试 `/reset_prompt` 命令
- [ ] 测试 prompt 持久化（重启后是否保留）
- [ ] 测试多用户场景（不同用户的自定义 prompt 互不干扰）

### Phase 7: 部署和文档
- [ ] 更新 `task.md` 文档
- [ ] 提交代码到 GitHub
- [ ] 部署到服务器
- [ ] 更新用户文档，说明新命令的用法

---

## 技术细节

### 命令格式示例

**显示当前 prompt:**
```
@gemini /show_prompt
```

**设置自定义 prompt:**
```
@gemini /set_prompt 你是一个专业的Python开发专家，擅长代码审查和性能优化。请用技术性强的语言回答问题。
```

**重置 prompt:**
```
@gemini /reset_prompt
```

### 数据库 Schema

```sql
CREATE TABLE IF NOT EXISTS custom_prompts (
    chat_id TEXT NOT NULL,
    user_id TEXT NOT NULL,
    bot_type TEXT NOT NULL,
    custom_prompt TEXT NOT NULL,
    created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
    updated_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
    PRIMARY KEY (chat_id, bot_type)
);
```

### Prompt 优先级逻辑

```python
def get_system_prompt(bot_type: str, chat_id: str) -> str:
    # 1. 尝试获取自定义 prompt
    custom_prompt = context_manager.get_custom_prompt(chat_id, bot_type)
    if custom_prompt:
        logger.info(f"[PROMPT] Using custom prompt for {bot_type} in {chat_id}")
        return custom_prompt
    
    # 2. 使用默认 prompt
    default_prompt = BOT_CONFIGS[bot_type]["system_prompt"]
    logger.info(f"[PROMPT] Using default prompt for {bot_type}")
    return default_prompt
```

---

## 安全考虑

1. **Prompt 注入防护**
   - 限制自定义 prompt 长度（例如最大 2000 字符）
   - 检测恶意指令（如试图覆盖文件生成标签）

2. **访问控制**
   - 每个 chat_id 的 prompt 独立
   - 群聊中的 prompt 设置仅影响该群

3. **日志审计**
   - 记录所有 prompt 修改操作
   - 便于追踪和调试

---

## 状态

**当前阶段**: Phase 6 - 测试验证  
**进度**: 21/27 任务完成
