"""
Archive Viewer - Web interface for viewing archived messages and files.

Provides a simple web page to browse all archived WeCom messages and files.
"""
import os
import sqlite3
import json
from typing import Optional
from fastapi import APIRouter, Request
from fastapi.responses import HTMLResponse

router = APIRouter()

DB_PATH = os.getenv("CHAT_DB_PATH", "/var/lib/wecom-callback/chat_history.db")


def get_db():
    return sqlite3.connect(DB_PATH)


@router.get("/archive/api/rooms")
async def list_rooms():
    """Get list of unique room IDs."""
    conn = get_db()
    cursor = conn.cursor()
    cursor.execute("""
        SELECT DISTINCT room_id, COUNT(*) as msg_count 
        FROM archived_messages 
        WHERE room_id != '' 
        GROUP BY room_id 
        ORDER BY msg_count DESC
    """)
    rooms = [{"room_id": row[0], "msg_count": row[1]} for row in cursor.fetchall()]
    conn.close()
    return {"rooms": rooms}


@router.get("/archive/api/messages")
async def list_messages(room_id: Optional[str] = None, limit: int = 100, offset: int = 0):
    """Get messages, optionally filtered by room."""
    conn = get_db()
    cursor = conn.cursor()
    
    if room_id:
        cursor.execute("""
            SELECT id, seq, msgid, msgtype, sender_id, room_id, content, created_at
            FROM archived_messages
            WHERE room_id = ?
            ORDER BY seq DESC
            LIMIT ? OFFSET ?
        """, (room_id, limit, offset))
    else:
        cursor.execute("""
            SELECT id, seq, msgid, msgtype, sender_id, room_id, content, created_at
            FROM archived_messages
            ORDER BY seq DESC
            LIMIT ? OFFSET ?
        """, (limit, offset))
    
    messages = []
    for row in cursor.fetchall():
        content = row[6]
        try:
            content_parsed = json.loads(content) if content else {}
        except:
            content_parsed = {"raw": content}
        
        messages.append({
            "id": row[0],
            "seq": row[1],
            "msgid": row[2],
            "msgtype": row[3],
            "sender_id": row[4],
            "room_id": row[5],
            "content": content_parsed,
            "created_at": row[7]
        })
    
    conn.close()
    return {"messages": messages, "limit": limit, "offset": offset}


@router.get("/archive/api/files")
async def list_files(room_id: Optional[str] = None, limit: int = 100, offset: int = 0):
    """Get files, optionally filtered by room."""
    conn = get_db()
    cursor = conn.cursor()
    
    if room_id:
        cursor.execute("""
            SELECT id, msgid, room_id, sender_id, filename, file_size, file_uri, created_at
            FROM chat_files
            WHERE room_id = ?
            ORDER BY created_at DESC
            LIMIT ? OFFSET ?
        """, (room_id, limit, offset))
    else:
        cursor.execute("""
            SELECT id, msgid, room_id, sender_id, filename, file_size, file_uri, created_at
            FROM chat_files
            ORDER BY created_at DESC
            LIMIT ? OFFSET ?
        """, (limit, offset))
    
    files = []
    for row in cursor.fetchall():
        files.append({
            "id": row[0],
            "msgid": row[1],
            "room_id": row[2],
            "sender_id": row[3],
            "filename": row[4],
            "file_size": row[5],
            "file_uri": row[6],
            "created_at": row[7]
        })
    
    conn.close()
    return {"files": files, "limit": limit, "offset": offset}


@router.get("/archive/api/stats")
async def get_stats():
    """Get overall statistics."""
    conn = get_db()
    cursor = conn.cursor()
    
    cursor.execute("SELECT COUNT(*) FROM archived_messages")
    msg_count = cursor.fetchone()[0]
    
    cursor.execute("SELECT COUNT(*) FROM chat_files")
    file_count = cursor.fetchone()[0]
    
    cursor.execute("SELECT COUNT(DISTINCT room_id) FROM archived_messages WHERE room_id != ''")
    room_count = cursor.fetchone()[0]
    
    cursor.execute("SELECT seq FROM archive_cursor WHERE id = 1")
    row = cursor.fetchone()
    current_seq = row[0] if row else 0
    
    conn.close()
    return {
        "total_messages": msg_count,
        "total_files": file_count,
        "total_rooms": room_count,
        "current_seq": current_seq
    }


@router.get("/archive", response_class=HTMLResponse)
@router.get("/archive/", response_class=HTMLResponse)
async def archive_viewer(request: Request):
    """Main archive viewer page."""
    html = """
<!DOCTYPE html>
<html lang="zh-CN">
<head>
    <meta charset="UTF-8">
    <meta name="viewport" content="width=device-width, initial-scale=1.0">
    <title>WeCom Archive Viewer</title>
    <style>
        * { box-sizing: border-box; margin: 0; padding: 0; }
        body { font-family: -apple-system, BlinkMacSystemFont, 'Segoe UI', Roboto, sans-serif; background: #1a1a2e; color: #eee; }
        .container { display: flex; height: 100vh; }
        .sidebar { width: 280px; background: #16213e; padding: 20px; overflow-y: auto; border-right: 1px solid #0f3460; }
        .main { flex: 1; padding: 20px; overflow-y: auto; }
        h1 { font-size: 18px; margin-bottom: 20px; color: #e94560; }
        h2 { font-size: 16px; margin-bottom: 15px; color: #0f3460; background: #e94560; padding: 8px 12px; border-radius: 4px; }
        .stats { background: #0f3460; padding: 15px; border-radius: 8px; margin-bottom: 20px; }
        .stats div { margin: 5px 0; font-size: 14px; }
        .stats span { color: #e94560; font-weight: bold; }
        .room-list { list-style: none; }
        .room-item { padding: 10px; margin: 5px 0; background: #0f3460; border-radius: 4px; cursor: pointer; transition: all 0.2s; }
        .room-item:hover, .room-item.active { background: #e94560; }
        .room-item small { opacity: 0.7; }
        .tabs { display: flex; gap: 10px; margin-bottom: 15px; }
        .tab { padding: 8px 16px; background: #0f3460; border: none; color: #eee; cursor: pointer; border-radius: 4px; }
        .tab.active { background: #e94560; }
        table { width: 100%; border-collapse: collapse; font-size: 13px; }
        th, td { padding: 10px; text-align: left; border-bottom: 1px solid #0f3460; }
        th { background: #0f3460; position: sticky; top: 0; }
        tr:hover { background: rgba(233, 69, 96, 0.1); }
        .content-cell { max-width: 400px; overflow: hidden; text-overflow: ellipsis; white-space: nowrap; }
        .file-link { color: #4fc3f7; text-decoration: none; }
        .file-link:hover { text-decoration: underline; }
        .loading { text-align: center; padding: 40px; color: #666; }
        .all-btn { width: 100%; padding: 10px; margin-bottom: 10px; background: #0f3460; border: 1px dashed #e94560; color: #e94560; cursor: pointer; border-radius: 4px; }
        .all-btn:hover { background: #e94560; color: white; border-style: solid; }
    </style>
</head>
<body>
    <div class="container">
        <div class="sidebar">
            <h1>📁 WeCom Archive</h1>
            <div class="stats" id="stats">Loading...</div>
            <h2>群聊列表</h2>
            <button class="all-btn" onclick="selectRoom(null)">查看所有消息</button>
            <ul class="room-list" id="room-list"></ul>
        </div>
        <div class="main">
            <div class="tabs">
                <button class="tab active" onclick="showTab('messages')">消息</button>
                <button class="tab" onclick="showTab('files')">文件</button>
            </div>
            <div id="content">
                <div class="loading">选择一个群聊或点击"查看所有消息"</div>
            </div>
        </div>
    </div>
    <script>
        let currentRoom = null;
        let currentTab = 'messages';
        
        async function loadStats() {
            const res = await fetch('/archive/api/stats');
            const data = await res.json();
            document.getElementById('stats').innerHTML = `
                <div>消息总数: <span>${data.total_messages}</span></div>
                <div>文件总数: <span>${data.total_files}</span></div>
                <div>群聊数量: <span>${data.total_rooms}</span></div>
                <div>当前序号: <span>${data.current_seq}</span></div>
            `;
        }
        
        async function loadRooms() {
            const res = await fetch('/archive/api/rooms');
            const data = await res.json();
            const list = document.getElementById('room-list');
            list.innerHTML = data.rooms.map(r => `
                <li class="room-item" onclick="selectRoom('${r.room_id}')">
                    ${r.room_id.substring(0, 20)}...
                    <br><small>${r.msg_count} 条消息</small>
                </li>
            `).join('');
        }
        
        function selectRoom(roomId) {
            currentRoom = roomId;
            document.querySelectorAll('.room-item').forEach(el => el.classList.remove('active'));
            if (roomId) {
                event.target.closest('.room-item')?.classList.add('active');
            }
            loadContent();
        }
        
        function showTab(tab) {
            currentTab = tab;
            document.querySelectorAll('.tab').forEach(el => el.classList.remove('active'));
            event.target.classList.add('active');
            loadContent();
        }
        
        async function loadContent() {
            const content = document.getElementById('content');
            content.innerHTML = '<div class="loading">加载中...</div>';
            
            const roomParam = currentRoom ? `room_id=${currentRoom}&` : '';
            
            if (currentTab === 'messages') {
                const res = await fetch(`/archive/api/messages?${roomParam}limit=200`);
                const data = await res.json();
                content.innerHTML = `
                    <table>
                        <thead>
                            <tr><th>Seq</th><th>类型</th><th>发送者</th><th>群ID</th><th>内容</th><th>时间</th></tr>
                        </thead>
                        <tbody>
                            ${data.messages.map(m => `
                                <tr>
                                    <td>${m.seq}</td>
                                    <td>${m.msgtype}</td>
                                    <td>${m.sender_id}</td>
                                    <td title="${m.room_id}">${m.room_id?.substring(0, 15) || '-'}...</td>
                                    <td class="content-cell" title="${JSON.stringify(m.content).replace(/"/g, '&quot;')}">${getContentPreview(m)}</td>
                                    <td>${m.created_at}</td>
                                </tr>
                            `).join('')}
                        </tbody>
                    </table>
                `;
            } else {
                const res = await fetch(`/archive/api/files?${roomParam}limit=200`);
                const data = await res.json();
                content.innerHTML = `
                    <table>
                        <thead>
                            <tr><th>文件名</th><th>大小</th><th>发送者</th><th>群ID</th><th>链接</th><th>时间</th></tr>
                        </thead>
                        <tbody>
                            ${data.files.map(f => `
                                <tr>
                                    <td>${f.filename}</td>
                                    <td>${formatSize(f.file_size)}</td>
                                    <td>${f.sender_id}</td>
                                    <td title="${f.room_id}">${f.room_id?.substring(0, 15) || '-'}...</td>
                                    <td><a class="file-link" href="${f.file_uri}" target="_blank">下载</a></td>
                                    <td>${f.created_at}</td>
                                </tr>
                            `).join('')}
                        </tbody>
                    </table>
                `;
            }
        }
        
        function getContentPreview(msg) {
            const c = msg.content;
            if (c.text?.content) return c.text.content;
            if (c.file?.filename) return '📎 ' + c.file.filename;
            if (c.image) return '🖼️ 图片';
            if (c.video) return '🎬 视频';
            if (c.voice) return '🎤 语音';
            return JSON.stringify(c).substring(0, 50) + '...';
        }
        
        function formatSize(bytes) {
            if (!bytes) return '-';
            if (bytes < 1024) return bytes + ' B';
            if (bytes < 1024*1024) return (bytes/1024).toFixed(1) + ' KB';
            return (bytes/1024/1024).toFixed(1) + ' MB';
        }
        
        loadStats();
        loadRooms();
    </script>
</body>
</html>
    """
    return HTMLResponse(content=html)
