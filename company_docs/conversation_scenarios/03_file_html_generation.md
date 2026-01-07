# 场景 03：HTML 文件生成 (/file-html)

## 场景描述

用户通过 `/file-html` 指令请求 AI 生成 HTML 文件，输出为云端链接。

## 核心需求

1. **使用完整上下文**：`/file-html` 不应缩减对话历史
2. **仅改变输出格式**：从文本回复变为文件链接
3. **不影响后续对话**：使用 `/file-html` 后，后续普通对话正常

## 对话示例

### 基础文件生成
```
用户：@gemini /file-html 制作一个登录页面
Gemini：云端链接: http://wecomfile.medmeeting.com/wecom/xxx.html
```

### 基于上下文生成
```
用户：@gemini 我们公司的品牌色是蓝色 #2563EB，Logo 是一个金色盾牌
Gemini：好的，已记录你们的品牌信息...

用户：@gemini /file-html 帮我做一个符合品牌调性的登录页面
Gemini：云端链接: http://wecomfile.medmeeting.com/wecom/xxx.html
# 生成的页面使用了蓝色 #2563EB 和金色盾牌元素
```

### 无 /file-html 的普通请求
```
用户：@gemini 帮我设计一个登录页面的布局方案
Gemini：好的，这是一个登录页面的布局建议：
        1. 左侧：品牌展示区...
        2. 右侧：登录表单...
        （纯文本回复，不生成文件）
```

## 实现机制

### 指令检测
```python
# 在 _handle_prompt_command 中
elif command == "file-html":
    return {
        "file_output_mode": True,
        "user_request": args.strip(),
        "continue_with_llm": True,  # 不是终端命令，继续 LLM 流程
    }
```

### System Prompt 增强
```python
# 当 file_output_mode == True 时
if file_output_mode:
    file_instruction = (
        "\n\n[重要：文件输出模式]\n"
        "用户请求以HTML文件形式输出。请：\n"
        "1. 将回复内容生成为一个完整的HTML文件\n"
        "2. 使用 <FILE name=\"output.html\">...</FILE> 标签包裹HTML内容\n"
        "3. 使用 Tailwind CSS CDN 进行样式设计\n"
        "4. 只输出文件，不要添加额外的解释"
    )
    system_prompt = system_prompt + file_instruction
```

### 响应处理
```python
# 在 _process_llm_file_output 中
if file_only_mode:
    return f"云端链接: {qiniu_url_display}"
else:
    return f"\n\n[已生成文件: {filename}]\n云端链接: {qiniu_url_display}"
```

## 消息流程图

```
用户: "@gemini /file-html 做个登录页面"
           │
           ▼
┌─────────────────────────┐
│ 检测 /file-html 指令    │
│ file_output_mode = True │
│ content = "做个登录页面"│
└───────────┬─────────────┘
           │
           ▼
┌─────────────────────────┐
│ 获取完整对话历史        │
│ (使用正常上下文流程)    │
└───────────┬─────────────┘
           │
           ▼
┌─────────────────────────┐
│ System Prompt + 文件指令│
│ + 历史消息 + 当前请求   │
└───────────┬─────────────┘
           │
           ▼
┌─────────────────────────┐
│ 调用 LLM                │
│ 输出: <FILE>...</FILE>  │
└───────────┬─────────────┘
           │
           ▼
┌─────────────────────────┐
│ _process_llm_file_output│
│ file_only_mode = True   │
│ → 只返回云端链接        │
└───────────┬─────────────┘
           │
           ▼
用户看到: "云端链接: http://..."
```

## 预期行为表

| 用户输入 | 预期输出 |
|---------|---------|
| `/file-html 登录页面` | 云端链接 |
| `帮我做个登录页面` | 文字描述（无文件） |
| `/file-html` (无参数) | 错误提示：请提供生成需求 |

## 待确认

1. **文件命名**：是否支持 `/file-html:mypage.html` 自定义文件名？
2. **文件类型扩展**：是否需要 `/file-css`、`/file-js` 等？
3. **错误处理**：LLM 未生成 `<FILE>` 标签时如何处理？
