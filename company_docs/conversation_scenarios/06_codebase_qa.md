# 场景 06：代码库问答 (/codebase)

## 场景描述

用户设置代码库上下文后，可以直接提问代码相关问题。

## 核心命令

### /codebase - 设置代码库上下文
```
/codebase <gitlab_url_or_project_path> [branch]
```

## 对话示例

### 基础使用
```
用户：@gemini /codebase https://gitlab.example.com/myproject
Gemini：✅ 已设置代码库上下文: `myproject`
        📌 当前分支: `main`
        
        现在你可以直接提问，例如：
        - "这些表名在哪些文件中出现过？"
        - "creditor_code 字段是在哪里处理的？"

用户：@gemini 用户认证逻辑在哪里实现的？
Gemini：根据代码分析，用户认证逻辑主要分布在以下位置：
        
        1. `src/auth/authenticator.py` - 主要认证类
        2. `src/middleware/auth_middleware.py` - 中间件
        3. ...

用户：@gemini 认证失败时返回什么错误码？
Gemini：根据 `src/auth/authenticator.py` 第 78-92 行...
        认证失败时返回 401 错误码...
```

### 指定分支
```
用户：@gemini /codebase myproject develop
Gemini：✅ 已设置代码库上下文: `myproject`
        📌 当前分支: `develop`
```

### 内联问题
```
用户：@gemini /codebase myproject 这个项目用的什么框架？
Gemini：🔍 正在分析 `myproject` 代码库 (分支: `main`)...
        
        该项目使用 FastAPI 框架，主要依赖：
        - FastAPI 0.100.0
        - SQLAlchemy 2.0
        - ...
```

### 截图 + 代码库
```
用户：[发送错误截图]
用户：@gemini 这个错误是代码哪里的问题？
Gemini：根据截图中的错误信息 "ConnectionResetError"...
        这个错误出现在 `src/database/connection.py` 第 45 行...
        建议添加重试机制...
```

## 代码库 QA Flow

### 架构
```
用户问题
    │
    ▼
┌─────────────────┐
│ 检测代码库上下文│
│ (缓存 10 分钟)  │
└────────┬────────┘
         │
         ▼
┌─────────────────┐
│ CodebaseQAFlow  │
│ (CrewAI Agent)  │
└────────┬────────┘
         │
    ┌────┴────┐
    ▼         ▼
┌───────┐ ┌────────┐
│代码   │ │项目    │
│搜索   │ │结构    │
└───┬───┘ └───┬────┘
    │         │
    └────┬────┘
         ▼
┌─────────────────┐
│ LLM 分析代码    │
│ 回答用户问题    │
└────────┬────────┘
         │
         ▼
    分析结果
```

### 上下文缓存
```python
# 代码库上下文缓存
_user_project_context = {
    "chat_id_xxx": {
        "project_path": "myproject",
        "gitlab_url": "https://gitlab.example.com",
        "branch": "main",
        "timestamp": 1234567890,
    }
}

# 10 分钟过期
CONTEXT_EXPIRE_MINUTES = 10
```

## 上下文保存

### 问题保存
```python
context_manager.add_message(
    chat_id=chat_id,
    content="用户认证逻辑在哪里实现的？",
    role="user",
)
```

### 回答保存
```python
context_manager.add_message(
    chat_id=chat_id,
    content="根据代码分析...",
    role="assistant",
)
```

## 多轮追问

```
用户：@gemini /codebase myproject
Gemini：✅ 已设置代码库上下文

用户：@gemini 项目的数据库模型在哪里定义的？
Gemini：数据库模型定义在 `src/models/` 目录下...

用户：@gemini User 模型有哪些字段？
Gemini：根据 `src/models/user.py`，User 模型包含以下字段：
        - id: Integer, 主键
        - username: String(50)
        - email: String(100)
        ...

用户：@gemini 如何修改来添加手机号字段？
Gemini：要添加手机号字段，需要修改以下文件：
        1. `src/models/user.py` - 添加 phone_number 字段
        2. `migrations/` - 创建数据库迁移
        3. `src/schemas/user.py` - 更新 Pydantic Schema
        ...
```

## 关键决策

| 决策点 | 当前方案 | 备选方案 |
|-------|---------|---------|
| 上下文缓存 | 10 分钟 | 可配置 |
| 代码索引 | 实时获取 | 预索引 + 增量更新 |
| 跨分支查询 | 需重新设置 | 支持临时切换 |
| 私有仓库 | GitLab Token | OAuth 授权 |

## 待考虑

1. **代码索引**：大型仓库是否需要预索引？
2. **RAG 集成**：是否使用向量数据库提升检索质量？
3. **多仓库支持**：同时设置多个代码库上下文？
