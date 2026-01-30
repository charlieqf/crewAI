import os

from fastapi import APIRouter, HTTPException
from fastapi.responses import FileResponse, HTMLResponse

from src.crewai_enterprise.server.task_config import get_task_config

router = APIRouter()


@router.get("/task/{task_id}", response_class=HTMLResponse)
def task_page(task_id: int):
    html = f"""<!doctype html>
<html lang=\"en\">
  <head>
    <meta charset=\"utf-8\" />
    <meta name=\"viewport\" content=\"width=device-width, initial-scale=1\" />
    <title>Task {task_id}</title>
    <style>
      body {{ font-family: Arial, sans-serif; margin: 24px; color: #111; }}
      .header {{ margin-bottom: 16px; }}
      .title {{ font-size: 20px; font-weight: 600; }}
      .meta {{ color: #666; font-size: 13px; margin-top: 4px; }}
      .section {{ margin-top: 20px; }}
      .messages {{ border: 1px solid #ddd; padding: 12px; border-radius: 6px; }}
      .msg {{ margin-bottom: 12px; }}
      .role {{ font-weight: 600; text-transform: uppercase; font-size: 11px; color: #888; }}
      .content {{ white-space: pre-wrap; font-size: 14px; }}
      .files a {{ display: block; margin: 4px 0; }}
      .status {{ display: inline-block; padding: 2px 8px; border-radius: 10px; background: #f2f2f2; font-size: 12px; }}
      .error {{ color: #b00020; }}
    </style>
  </head>
  <body>
    <div class=\"header\">
      <div class=\"title\">Task #{task_id}</div>
      <div class=\"meta\" id=\"meta\">Loading...</div>
    </div>
    <div class=\"section\">
      <div class=\"status\" id=\"status\">loading</div>
    </div>
    <div class=\"section\">
      <h3>Messages</h3>
      <div class=\"messages\" id=\"messages\">Loading...</div>
    </div>
    <div class=\"section\">
      <h3>Files</h3>
      <div class=\"files\" id=\"files\">No files</div>
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
    files_dir = os.path.join(cfg.storage_root, f"task-{task_id}", "files")
    if not os.path.isdir(files_dir):
        return {"files": []}
    return {"files": sorted(os.listdir(files_dir))}


@router.get("/api/task/{task_id}/files/{filename}")
def download_task_file(task_id: int, filename: str):
    if ".." in filename or "/" in filename or "\\" in filename:
        raise HTTPException(status_code=400, detail="invalid filename")
    cfg = get_task_config()
    path = os.path.join(cfg.storage_root, f"task-{task_id}", "files", filename)
    if not os.path.exists(path):
        raise HTTPException(status_code=404, detail="not found")
    return FileResponse(path)
