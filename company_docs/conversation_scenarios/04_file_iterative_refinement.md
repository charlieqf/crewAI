# 场景 04：文件迭代改进

## 场景描述

用户生成文件后，希望基于之前的结果进行迭代改进，如"重做一版"、"改成金融科技风格"。

## 核心需求

1. **支持迭代改进**：用户可以基于之前的文件进行修改
2. **保留完整上下文**：AI 知道之前生成了什么
3. **理解改进指令**：如"重做"、"改进"、"换个风格"

## 对话示例

### 迭代改进流程
```
用户：@gemini /file-html 制作一个登录页面
Gemini：云端链接: http://wecomfile.medmeeting.com/wecom/v1.html

用户：@gemini /file-html 重做一版，风格改为金融科技风
Gemini：云端链接: http://wecomfile.medmeeting.com/wecom/v2.html
# AI 基于之前的登录页面，改为金融科技风格

用户：@gemini /file-html 再改一下，按钮用渐变色
Gemini：云端链接: http://wecomfile.medmeeting.com/wecom/v3.html
# AI 在金融科技风格基础上，把按钮改为渐变色
```

### 混合对话与文件生成
```
用户：@gemini 金融科技风格一般有什么特点？
Gemini：金融科技风格通常具有以下特点：
        1. 深色背景配合亮色点缀
        2. 科技感的渐变...
        （纯文本回复）

用户：@gemini /file-html 按照这个风格重新设计登录页面
Gemini：云端链接: http://wecomfile.medmeeting.com/wecom/v4.html
# AI 结合之前讨论的金融科技风格特点生成
```

## 上下文中的文件信息

### 文件上下文保存
```python
# 当生成文件时，保存到上下文
context_manager.save_file(
    chat_id=chat_id,
    sender_id=f"bot_{bot_type}",
    sender_name=bot_type,
    file_uri=cloud_url,       # 云端链接
    filename=filename,         # output.html
    mime_type="text/html",
)

# 同时保存为消息
context_manager.add_message(
    chat_id=chat_id,
    content=f"云端链接: {cloud_url}",  # 回复内容
    role="assistant",
)
```

### LLM 看到的上下文
```python
messages = [
    {"role": "system", "content": "..."},
    {"role": "user", "content": "制作一个登录页面"},
    {"role": "assistant", "content": "云端链接: http://.../v1.html"},
    {"role": "user", "content": "重做一版，风格改为金融科技风"},  # 当前
]
```

## 关键问题

### 问题 1：AI 如何"记住"之前生成的文件内容？

**当前方案**：
- AI 只看到"云端链接: xxx"这个文本回复
- AI 不能访问文件的实际 HTML 内容
- 但 AI 有完整的对话历史，知道用户之前要求什么

**潜在问题**：
```
用户：@gemini /file-html 把标题从"欢迎"改成"登录系统"
# AI 不知道当前标题是"欢迎"，可能无法准确修改
```

**改进方案 A - 保存 HTML 摘要**：
```python
# 生成文件时，保存内容摘要
context_manager.add_message(
    content=f"[生成了HTML文件]\n摘要: 登录页面，蓝色主题，包含标题'欢迎'、表单...",
    role="assistant",
)
```

**改进方案 B - 引用文件内容**：
```python
# 用户可以 Quote 文件，让 AI 读取内容
用户：[引用之前的云端链接消息]
用户：@gemini /file-html 基于这个文件，把标题改成"登录系统"
```

### 问题 2：多个文件如何区分？

```
用户：@gemini /file-html 登录页面
Gemini：云端链接: http://.../login.html

用户：@gemini /file-html 注册页面
Gemini：云端链接: http://.../register.html

用户：@gemini /file-html 改进登录页面
# AI 如何知道要改进哪个？
```

**解决方案**：
1. 明确指定："改进前一个登录页面"
2. 引用消息：Quote 登录页面的云端链接

## 设计决策

| 决策点 | 当前方案 | 备选方案 |
|-------|---------|---------|
| 文件内容保留 | 仅保存链接 | 保存 HTML 摘要 |
| 迭代识别 | 依赖对话历史 | 显式文件版本号 |
| 多文件区分 | 用户明确指定 | 文件标签系统 |

## 待实现

1. **文件内容摘要**：生成文件时自动生成摘要保存到上下文
2. **版本关联**：同一文件的多个版本关联起来
3. **diff 预览**：改进时显示改动点
