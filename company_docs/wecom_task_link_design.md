# WeCom /task 链接式任务系统设计（草案）

> 目标：当用户在 WeCom 中发送 `/task <问题>`，系统立即创建任务并返回链接。OpenCode 在后台执行任务，所有输出持续写入任务页面。WeCom 只负责短消息与二次沟通入口。

## 1. 需求与范围

### 必须实现
- WeCom 输入 `/task <问题>` 后 **立即返回任务链接**（不等待完整结果）。
- OpenCode 在后台继续执行任务，**持续追加输出**到任务页面。
- WeCom 可通过 `/task 1234 <补充>` 进行 **同一任务的二次沟通**。
- **不考虑安全/权限**（后续再补）。
- **不做输出规范化**：保存最原始的输出内容即可。
- **不要求复杂状态机**：只要任务能持续沟通、继续产出即可。

### 暂不处理
- 复杂权限/鉴权体系
- 输出格式标准化（Markdown/JSON/代码分区）
- 细粒度任务状态机、失败恢复策略

## 2. 用户体验（WeCom）

### 2.1 创建任务
```
用户: /task 设计录音文件同步状态机
系统: 已创建任务 #1234
      查看进度: {TASK_BASE_URL}/task/1234
```

### 2.2 任务内追加问题（保持同一任务）
```
用户: /task 1234 补充：手机端需要离线状态
系统: 已追加到任务 #1234
      查看进度: {TASK_BASE_URL}/task/1234
```

### 2.3 不阻塞聊天
- 不在 WeCom 输出长文本
- 仅输出任务链接 + 简短状态提示（可选）

## 3. 系统架构（简化版）

```
WeCom -> wecom-callback -> Task Service -> OpenCode
                        -> Task Storage (DB + files)
                        -> Task Web UI
```

### 3.1 组件说明
- **Task Service**：任务创建、追加输入、持久化输出、任务页数据源。
- **OpenCode 执行器**：后台执行任务并持续写入输出。
- **Task Web UI**：展示任务输出、更新流、历史记录。

### 3.2 数据存储（低成本决策）
- **v1 使用 VM 本地 SQLite**（`{TASK_STORAGE_ROOT}/tasks.db`）。
- 后续再迁移到现有数据库或服务化存储。

## 4. 数据模型（最小可用）

### 4.1 Task 表
```
Task {
  id: int
  created_at: datetime
  updated_at: datetime
  wecom_chat_id: string
  wecom_user_id: string
  opencode_session_id: string
  title: string   # 从首条问题截断生成
  status: string  # 简化：queued/running/done/failed
  last_seen_message_id: string  # 输出去重（最后处理的 message id）
}
```

### 4.2 TaskMessage 表（原始输出流）
```
TaskMessage {
  id: int
  task_id: int
  created_at: datetime
  role: string        # user/assistant/system
  content: text       # 原始文本，保持原样
  source: string      # wecom/opencode/system
}
```

### 4.3 TaskEvent 表（可选）
```
TaskEvent {
  id: int
  task_id: int
  type: string       # status/log/error
  payload: text
  created_at: datetime
}
```

### 4.4 TaskInput 表（推荐）
用于串行化 `/task 1234 <补充>`，避免和正在执行的 worker 竞争。
```
TaskInput {
  id: int
  task_id: int
  created_at: datetime
  status: string    # pending/processing/done/failed
  content: text     # 追加内容（原样保存）
  source: string    # wecom/system
}
```

## 5. API 设计（最小可用）

### 5.1 创建任务
```
POST /api/task
body: { chat_id, user_id, text }
resp: { task_id, url }
```

### 5.2 追加任务输入
```
POST /api/task/{id}/append
body: { chat_id, user_id, text }
resp: { ok: true, url }
```

### 5.3 任务查询
```
GET /api/task/{id}
resp: { task, messages, events, files }
```

### 5.4 输出追加（OpenCode 执行器调用）
```
POST /api/task/{id}/output
body: { role, content, source }
```

### 5.5 文件写入（v1.5，非 v1 必需）
```
POST /api/task/{id}/file
body: { filename, content }
```

## 6. 任务执行流程

### 6.1 创建任务
1. WeCom `/task <text>` -> Task Service 创建任务记录。
2. 立即返回任务链接给 WeCom。
3. 触发 OpenCode 执行器开始任务。

### 6.2 执行器处理
1. 创建/复用 OpenCode session。
2. 把用户问题作为 prompt 发送给 OpenCode。
3. **持续轮询 session 消息**，将新的 assistant 输出写入 TaskMessage。
4. 任务页面实时刷新（轮询或 SSE）。

### 6.3 追加沟通
1. 用户发送 `/task 1234 <补充>`。
2. Task Service 写入 `TaskInput(status=pending)`。
3. Worker 串行读取 pending 输入，标记 processing。
4. 将输入发送到同一 session。
5. 输出继续写入任务页。

### 6.3.1 并发控制（最小方案）
**规则**：同一 task 只允许一个 worker 处理 `processing` 输入。
- 追加输入永远进入 `TaskInput` 队列。
- worker 一次处理一条 pending，完成后标记 done。
- 这样可以避免 append 和正在运行的 OpenCode 互相打架。

#### 轻量锁实现（v1, SQLite）

- `try_mark_task_running(task_id)` 使用 **Task.status 的 CAS 更新**：
  - `UPDATE task SET status='running' WHERE id=? AND status!='running'`
  - 受影响行数为 1 视为获取锁成功。
- `mark_task_idle(task_id)` 在处理完成后：
  - 若仍有 pending 输入，保持 `running` 以继续处理。
  - 若队列为空，则切回 `done`（或 `idle` 作为中间态）。

## 6.4 上下文与 session 说明

### 关键原则
- **session 还在 ≠ 上下文完整**。OpenCode 可能会自动压缩或裁剪历史。
- 我们的“真·上下文来源”是 **TaskMessage**（任务内保存的所有原始消息）。

### session 正常时
- 追加问题直接发送到已有 session。
- OpenCode 可能只看到压缩后的上下文，但足够维持连续对话。

### session 失效时（推荐恢复策略）
如果 `session_id` 失效或查不到：
1. 新建 session
2. 用 TaskMessage 重放上下文（原始输出+用户输入拼接）
3. 再发送最新追加问题

伪流程：
```
if session_id invalid:
  new_session = create_session()
  replay = concat(task.messages ordered by time)
  send(replay)
  send(latest_append)
```

### 现实权衡
- **优点**：上下文连续、不会丢任务记忆
- **缺点**：token 成本高、原始输出可能包含噪声
- **低成本约束**：只回放最近 N 条或最近 X 字符（例如 50 条或 30k 字符）

## 6.5 输出接入方式（第一版）

### 方案：直接读取 OpenCode 本地存储（first attempt）
OpenCode 在 Kamatera 本地持久化 session 到：
```
/root/.local/share/opencode/storage/message/<session_id>/*.json
/root/.local/share/opencode/storage/part/<message_id>/*.json
```

**第一版采用此方式**：
1. 任务执行器轮询消息目录（按文件时间/文件名排序）。
2. 对每个 assistant message，读取其 `part` 目录。
3. 拼接 `type == "text"` 的内容，追加到 TaskMessage / output.log。
4. 使用 `last_seen_message_id` 去重，避免重复写入。

**优点**：实现最快，不改 OpenCode。  
**缺点**：耦合 OpenCode 内部存储格式，升级需复核。

### 后续可替换的方案（仅记录）
- OpenCode API polling (`/session/{id}/message`)
- SSE 事件流
- OpenCode/OMO webhook

### 输出数据源（低成本选择）
- **单一真源**：以 `TaskMessage` 为准。
- `output.log` 仅作为顺序追加日志（可选），不作为 UI 的主数据源。

### 配置项（低成本但必须外置）
- `TASK_BASE_URL`（如 `http://104.238.213.119:8080`）
- `TASK_STORAGE_ROOT`（如 `/var/lib/wecom-tasks`）
- `OPENCODE_STORAGE_ROOT`（如 `/root/.local/share/opencode/storage`）

## 7. 页面结构（最小可用）

```
任务标题
任务 ID / 创建时间 / 最近更新时间

输出区域（按时间流）
- user: 原始问题
- assistant: 原始输出（长文本逐段追加）
- user: 追加问题
- assistant: 后续输出
```

说明：先不做格式规范化，全部展示原始文本。

## 7.1 任务文件目录与管理（新增）

### 目录约定（Kamatera VM）
```
{TASK_STORAGE_ROOT}/
  task-1234/
    meta.json            # 任务元信息（session_id、创建人、标题等）
    output.log           # 原始输出流（按时间追加）
    files/               # 产出文件目录
      report.md
      diagram.mmd
      summary.html
```

### 文件写入原则
- **所有产出物落盘**到 `files/`。
- 原始输出流追加写入 `output.log`，保持完整、可追溯。
- 文件名避免冲突：使用时间戳或递增序号（如 `20260129-001-report.md`）。
- **文件名安全规则（低成本）**：只允许 `[A-Za-z0-9._-]`，其他替换为 `_`，并禁止 `../`。

### 文件浏览与下载
- Web UI 只做 **文件列表 + 下载**。
- 直接读取 `files/` 目录并生成链接。
- 暂不处理权限（后续补）。

## 8. WeCom 命令规范

### 8.1 创建任务
```
/task <问题>
```

### 8.2 追加任务
```
/task <task_id> <补充内容>
```

### 8.3 返回文案（统一简洁）
- 创建：`已创建任务 #1234 查看进度: http://tasks/1234`
- 追加：`已追加到任务 #1234 查看进度: {TASK_BASE_URL}/task/1234`

### 8.4 任务链接（低成本默认）
- 先使用固定 base URL（如 `{TASK_BASE_URL}/task/{id}`）。
- 后续再替换成正式域名。

## 9. 风险与限制（接受版）

1. 输出完全原始，可能杂乱、重复、片段化。
2. 无权限控制，任何知道链接的人可访问。
3. 任务无严格状态机，可能出现“无输出但仍在运行”的状态。
4. 二次沟通如果过多，可能导致 OpenCode session 冗长。

## 10. 实施建议（最小可用优先）

### MVP 顺序
1. Task Service：创建、追加、保存原始输出。
2. WeCom `/task` 路由：返回链接。
3. OpenCode 执行器：把 session 输出写入 TaskMessage。
4. Task Web UI：展示输出流。

### 后续可选增强
- 任务权限和 token 链接
- 输出格式规范化
- 任务状态机与重试机制
- 文件输出与下载区

---

## 11. 开发清单（可执行）

### A. 后端（Task Service）
1. 创建数据表（Task / TaskMessage / TaskEvent）。
2. 创建 TaskInput 表（用于串行追加）。
2. 实现 API：
   - `POST /api/task`
   - `POST /api/task/{id}/append`
   - `GET /api/task/{id}`
   - `POST /api/task/{id}/output`
   - `POST /api/task/{id}/file`（v1.5）
3. 实现 Task ID 生成（自增或雪花）。
4. 基础日志（创建/追加/输出）。

### B. WeCom 回调改造
1. 命令解析：
   - `/task <问题>` -> 创建任务
   - `/task <id> <补充>` -> 追加任务
2. 返回短消息：
   - `已创建任务 #id 查看进度: http://tasks/id`
   - `已追加到任务 #id 查看进度: http://tasks/id`
3. 任务创建后异步触发 OpenCode 执行器。

### C. OpenCode 执行器
1. `task_id -> session_id` 映射（新任务新 session）。
2. 从 TaskInput 队列取 pending 输入（按创建时间）。
3. 标记 processing -> 发送到 OpenCode。
4. 轮询 session 消息：
   - 把新增 assistant 文本写入 `TaskMessage`。
5. 完成后标记 done，继续下一条输入。

### D. Web UI（最简）
1. 任务详情页 `/task/{id}`：
   - 标题、时间、消息流
2. 文件区域：
   - `files/` 文件列表
   - 点击下载
3. 轮询/刷新：
   - 每 3–5 秒更新一次输出流（先不用 SSE）。

### E. 任务文件管理
1. 任务创建时初始化目录 `/var/lib/wecom-tasks/task-{id}`。
2. `meta.json` 保存 session_id、创建人、标题。
3. 原始输出追加写入 `output.log`。
4. 产出文件写入 `files/`。

---

## 12. 接口实现草图（Python/FastAPI）

### 12.1 路由定义
```python
from fastapi import FastAPI
from pydantic import BaseModel

app = FastAPI()

class CreateTaskIn(BaseModel):
    chat_id: str
    user_id: str
    text: str

class AppendTaskIn(BaseModel):
    chat_id: str
    user_id: str
    text: str

class OutputIn(BaseModel):
    role: str
    content: str
    source: str

class FileWriteIn(BaseModel):
    filename: str
    content: str

@app.post("/api/task")
def create_task(body: CreateTaskIn):
    ...

@app.post("/api/task/{task_id}/append")
def append_task(task_id: int, body: AppendTaskIn):
    ...

@app.get("/api/task/{task_id}")
def get_task(task_id: int):
    ...

@app.post("/api/task/{task_id}/output")
def append_output(task_id: int, body: OutputIn):
    ...

@app.post("/api/task/{task_id}/file")
def write_file(task_id: int, body: FileWriteIn):
    ...
```

### 12.2 伪代码：任务创建
```python
def create_task(body):
    task_id = db.insert_task(...)
    db.insert_message(task_id, role="user", content=body.text, source="wecom")
    trigger_opencode_worker(task_id, body.text)
    return {"task_id": task_id, "url": f"http://tasks/{task_id}"}
```

### 12.3 伪代码：追加输入
```python
def append_task(task_id, body):
    db.insert_message(task_id, role="user", content=body.text, source="wecom")
    trigger_opencode_append(task_id, body.text)
    return {"ok": True, "url": f"http://tasks/{task_id}"}
```

### 12.4 伪代码：写入输出
```python
def append_output(task_id, body):
    db.insert_message(task_id, role=body.role, content=body.content, source=body.source)
    return {"ok": True}
```

### 12.5 伪代码：写入文件
```python
def write_file(task_id, body):
    task_dir = f"{TASK_STORAGE_ROOT}/task-{task_id}/files"
    ensure_dir(task_dir)
    path = safe_join(task_dir, sanitize_filename(body.filename))
    write_text(path, body.content)
    return {"ok": True}
```

---

## 15. 任务平台 Web UI（前后端设计）

### 15.1 后端职责
- 任务详情 API：`GET /api/task/{id}`
- 输出流读取：**只读 TaskMessage 列表**
- 文件列表与下载：读取 `files/` 并返回可下载链接

### 15.2 前端页面（最小可用）
页面：`/task/{id}`
- 顶部信息：
  - 任务标题
  - 任务 ID / 创建时间 / 最近更新时间
- 输出流区域：
  - 原始输出按时间追加显示
  - 3–5 秒轮询刷新
- 文件区域：
  - 文件列表 + 下载按钮

### 15.4 低成本保底：简单状态更新
- 任务创建 -> `queued`
- worker 开始处理 -> `running`
- 处理完一条 TaskInput -> 若队列为空则 `done`
- 发生异常 -> `failed`

### 15.5 低成本清理策略
- 每日 cron 清理 30 天前的 `task-*` 目录和数据库记录（可选）。

### 15.3 示例路由
```
GET /task/{id}          # 页面
GET /api/task/{id}      # JSON 数据
GET /api/task/{id}/files
GET /api/task/{id}/files/{filename}
```

---

## 13. OpenCode 执行器草图

### 13.1 新任务执行
```
task_id -> create session
send user prompt
poll session messages
for each new assistant text:
  POST /api/task/{id}/output
```

### 13.2 追加任务执行
```
task_id -> reuse session
send user append
poll session messages
append new assistant text to task
```

---

## 14. WeCom 命令解析草图

### 14.1 创建任务
```
if text startswith "/task " and next token not numeric:
  create task -> respond with link
```

### 14.2 追加任务
```
if text startswith "/task " and next token is numeric:
  append to task -> respond with link
```

---

## 16. SQL Schema（最小可用）

### 16.1 TaskInput
```sql
CREATE TABLE task_input (
  id INTEGER PRIMARY KEY AUTOINCREMENT,
  task_id INTEGER NOT NULL,
  created_at DATETIME DEFAULT CURRENT_TIMESTAMP,
  status TEXT NOT NULL DEFAULT 'pending', -- pending/processing/done/failed
  content TEXT NOT NULL,
  source TEXT NOT NULL DEFAULT 'wecom',
  FOREIGN KEY (task_id) REFERENCES task(id)
);
CREATE INDEX idx_task_input_task_status ON task_input(task_id, status, created_at);
```

### 16.2 TaskMessage（补充索引建议）
```sql
CREATE INDEX idx_task_message_task_time ON task_message(task_id, created_at);
```

### 16.3 Task（补充字段）
```sql
ALTER TABLE task ADD COLUMN last_seen_message_id TEXT;
```

---

## 17. Worker Loop（伪代码）

### 17.1 输入串行处理
```python
while True:
    inp = db.fetch_one(
        "SELECT * FROM task_input WHERE status='pending' ORDER BY created_at LIMIT 1"
    )
    if not inp:
        sleep(1)
        continue

    # 任务级别轻量锁，避免同一 task 并发处理
    if not db.try_mark_task_running(inp.task_id):
        sleep(0.2)
        continue

    db.update("UPDATE task_input SET status='processing' WHERE id=?", inp.id)
    task = db.get_task(inp.task_id)

    session_id = ensure_session(task)
    send_to_opencode(session_id, inp.content)

    # 持续拉取输出（见 6.5）
    for chunk in poll_storage(session_id, last_seen_id=task.last_seen_message_id):
        db.insert_task_message(task.id, role="assistant", content=chunk.text, source="opencode")
        task.last_seen_message_id = chunk.message_id
        db.update_task_last_seen(task.id, task.last_seen_message_id)

    db.update("UPDATE task_input SET status='done' WHERE id=?", inp.id)
    if db.pending_count(task.id) == 0:
        db.update_task_status(task.id, "done")
    db.mark_task_idle(task.id)
```

### 17.2 输出轮询（存储读取）
```python
def poll_storage(session_id, last_seen_id):
    # 读取 {OPENCODE_STORAGE_ROOT}/message/<session_id>/*.json
    # 按文件名排序，跳过 <= last_seen_id 的 message
    # 对每条 assistant message，读取 part 目录，拼接 text parts
    # yield chunk(text, message_id)
    pass
```
