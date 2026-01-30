import os

from fastapi import APIRouter, HTTPException
from fastapi.responses import FileResponse, HTMLResponse

from src.crewai_enterprise.server.task_config import get_task_config
from src.crewai_enterprise.server.task_store import TaskStore

router = APIRouter()


@router.get("/task/{task_id}", response_class=HTMLResponse)
def task_page(task_id: int):
    html = f"""<!doctype html>
<html lang=\"en\">
  <head>
    <meta charset=\"utf-8\" />
    <meta name=\"viewport\" content=\"width=device-width, initial-scale=1\" />
    <title>Task {task_id}</title>
    <link rel=\"preconnect\" href=\"https://fonts.googleapis.com\" />
    <link rel=\"preconnect\" href=\"https://fonts.gstatic.com\" crossorigin />
    <link href=\"https://fonts.googleapis.com/css2?family=Manrope:wght@300;400;500;600;700&family=Newsreader:opsz,wght@6..72,400;600;700&display=swap\" rel=\"stylesheet\" />
    <style>
      :root {{
        --bg: #f4f2ef;
        --ink: #1f1c19;
        --muted: #6f6a64;
        --panel: #fbfaf8;
        --line: #e4dfd8;
        --accent: #b8a489;
        --accent-strong: #6a5f52;
        --shadow: 0 18px 45px rgba(44, 38, 32, 0.15);
      }}

      * {{ box-sizing: border-box; }}
      body {{
        margin: 0;
        font-family: "Manrope", "Segoe UI", sans-serif;
        color: var(--ink);
        background: radial-gradient(1200px 600px at 10% -10%, #efe7dc 0%, transparent 60%),
                    radial-gradient(1000px 500px at 90% 0%, #f0ece6 0%, transparent 55%),
                    var(--bg);
        min-height: 100vh;
      }}

      .page {{
        max-width: 980px;
        margin: 0 auto;
        padding: 32px 24px 64px;
      }}

      .nav {{
        display: flex;
        align-items: center;
        justify-content: space-between;
        margin-bottom: 28px;
      }}

      .brand {{
        font-family: "Newsreader", serif;
        font-size: 20px;
        letter-spacing: 0.12em;
        text-transform: uppercase;
        color: var(--accent-strong);
      }}

      .tag {{
        border: 1px solid var(--line);
        padding: 6px 12px;
        border-radius: 999px;
        font-size: 12px;
        color: var(--muted);
        background: rgba(255, 255, 255, 0.7);
      }}

      .hero {{
        display: grid;
        grid-template-columns: minmax(0, 1fr) auto;
        gap: 16px;
        align-items: center;
        padding: 22px 26px;
        background: var(--panel);
        border: 1px solid var(--line);
        border-radius: 18px;
        box-shadow: var(--shadow);
      }}

      .title {{
        font-family: "Newsreader", serif;
        font-size: 28px;
        margin: 0;
      }}

      .meta {{
        color: var(--muted);
        font-size: 13px;
        margin-top: 6px;
      }}

      .status {{
        padding: 8px 14px;
        border-radius: 999px;
        border: 1px solid var(--line);
        background: #fff;
        font-size: 12px;
        text-transform: uppercase;
        letter-spacing: 0.08em;
      }}

      .grid {{
        display: grid;
        grid-template-columns: minmax(0, 1fr) 260px;
        gap: 22px;
        margin-top: 26px;
      }}

      .panel {{
        background: var(--panel);
        border: 1px solid var(--line);
        border-radius: 16px;
        padding: 18px;
      }}

      .panel h3 {{
        margin: 0 0 12px;
        font-size: 14px;
        letter-spacing: 0.08em;
        text-transform: uppercase;
        color: var(--accent-strong);
      }}

      .messages {{
        display: grid;
        gap: 14px;
      }}

      .msg {{
        padding: 12px 14px;
        border-radius: 12px;
        border: 1px solid #efe9e2;
        background: #fff;
      }}

      .role {{
        font-size: 11px;
        letter-spacing: 0.1em;
        text-transform: uppercase;
        color: var(--muted);
        margin-bottom: 6px;
      }}

      .content {{
        white-space: pre-wrap;
        font-size: 14px;
        line-height: 1.55;
      }}

      .files a {{
        display: block;
        margin: 6px 0;
        color: var(--accent-strong);
        text-decoration: none;
      }}

      .files a:hover {{
        text-decoration: underline;
      }}

      .error {{
        color: #9c2f2f;
        font-size: 13px;
      }}

      @media (max-width: 900px) {{
        .hero {{
          grid-template-columns: 1fr;
        }}
        .grid {{
          grid-template-columns: 1fr;
        }}
      }}
    </style>
  </head>
  <body>
    <div class=\"page\">
      <div class=\"nav\">
        <div class=\"brand\">Open Jobs</div>
        <div class=\"tag\">Task Stream</div>
      </div>

      <div class=\"hero\">
        <div>
          <div class=\"title\">Task #{task_id}</div>
          <div class=\"meta\" id=\"meta\">Loading...</div>
        </div>
        <div class=\"status\" id=\"status\">loading</div>
      </div>

      <div class=\"grid\">
        <div class=\"panel\">
          <h3>Messages</h3>
          <div class=\"messages\" id=\"messages\">Loading...</div>
        </div>
        <div class=\"panel\">
          <h3>Files</h3>
          <div class=\"files\" id=\"files\">No files</div>
        </div>
      </div>
    </div>
    <script>
      const taskId = {task_id};
      const taskUrl = "/api/task/{task_id}";
      const filesUrl = "/api/task/{task_id}/files";
      const metaEl = document.getElementById('meta');
      const statusEl = document.getElementById('status');
      const messagesEl = document.getElementById('messages');
      const filesEl = document.getElementById('files');

      function renderMessages(items) {{
        if (!items || items.length === 0) {{
          messagesEl.textContent = 'No messages yet.';
          return;
        }}
        messagesEl.innerHTML = '';
        for (const msg of items) {{
          const wrap = document.createElement('div');
          wrap.className = 'msg';
          const role = document.createElement('div');
          role.className = 'role';
          role.textContent = msg.role || 'unknown';
          const content = document.createElement('div');
          content.className = 'content';
          content.textContent = msg.content || '';
          wrap.appendChild(role);
          wrap.appendChild(content);
          messagesEl.appendChild(wrap);
        }}
      }}

      function renderFiles(files) {{
        if (!files || files.length === 0) {{
          filesEl.textContent = 'No files';
          return;
        }}
        filesEl.innerHTML = '';
        for (const name of files) {{
          const link = document.createElement('a');
          link.href = `/api/task/${{taskId}}/files/${{encodeURIComponent(name)}}`;
          link.textContent = name;
          filesEl.appendChild(link);
        }}
      }}

      async function loadTask() {{
        try {{
          const res = await fetch(taskUrl);
          if (!res.ok) {{
            throw new Error(`Task fetch failed: ${{res.status}}`);
          }}
          const data = await res.json();
          const task = data.task || {{}};
          const created = task.created_at || 'unknown';
          const updated = task.updated_at || 'unknown';
          metaEl.textContent = `Created: ${{created}} | Updated: ${{updated}}`; 
          statusEl.textContent = task.status || 'unknown';
          renderMessages(data.messages || []);
        }} catch (err) {{
          messagesEl.innerHTML = `<div class=\"error\">${{err.message}}</div>`;
        }}
      }}

      async function loadFiles() {{
        try {{
          const res = await fetch(filesUrl);
          if (!res.ok) {{
            throw new Error(`Files fetch failed: ${{res.status}}`);
          }}
          const data = await res.json();
          renderFiles(data.files || []);
        }} catch (err) {{
          filesEl.innerHTML = `<div class=\"error\">${{err.message}}</div>`;
        }}
      }}

      function refresh() {{
        loadTask();
        loadFiles();
      }}

      refresh();
      setInterval(refresh, 3000);
    </script>
  </body>
</html>
"""
    return HTMLResponse(html)


@router.get("/api/task/{task_id}/files")
def list_task_files(task_id: int):
    cfg = get_task_config()
    store = TaskStore(cfg.db_path)
    task = store.get_task(task_id)
    chat_id = task.get("wecom_chat_id") if task else None
    if not chat_id:
        return {"files": []}
    files_dir = os.path.join(cfg.storage_root, chat_id, "tasks", str(task_id), "files")
    if not os.path.isdir(files_dir):
        return {"files": []}
    return {"files": sorted(os.listdir(files_dir))}


@router.get("/api/task/{task_id}/files/{filename}")
def download_task_file(task_id: int, filename: str):
    if ".." in filename or "/" in filename or "\\" in filename:
        raise HTTPException(status_code=400, detail="invalid filename")
    cfg = get_task_config()
    store = TaskStore(cfg.db_path)
    task = store.get_task(task_id)
    chat_id = task.get("wecom_chat_id") if task else None
    if not chat_id:
        raise HTTPException(status_code=404, detail="not found")
    path = os.path.join(
        cfg.storage_root, chat_id, "tasks", str(task_id), "files", filename
    )
    if not os.path.exists(path):
        raise HTTPException(status_code=404, detail="not found")
    return FileResponse(path)
