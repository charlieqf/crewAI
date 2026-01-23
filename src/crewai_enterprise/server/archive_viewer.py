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

DB_PATH = os.getenv("ARCHIVE_DB_PATH", os.getenv("CHAT_DB_PATH", "/var/lib/wecom-callback/chat_history.db"))
STORAGE_DB_PATH = "/var/lib/wecom-callback/chat_storage.db"


def get_db():
    conn = sqlite3.connect(DB_PATH, timeout=30)
    conn.execute("PRAGMA journal_mode=WAL")
    return conn


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
            SELECT m.id, m.seq, m.msgid, m.msgtype, m.sender_id, m.room_id, m.content, m.created_at, f.file_uri
            FROM archived_messages m
            LEFT JOIN chat_files f ON m.msgid = f.msgid
            WHERE m.room_id = ?
            ORDER BY m.seq DESC
            LIMIT ? OFFSET ?
        """, (room_id, limit, offset))
    else:
        cursor.execute("""
            SELECT m.id, m.seq, m.msgid, m.msgtype, m.sender_id, m.room_id, m.content, m.created_at, f.file_uri
            FROM archived_messages m
            LEFT JOIN chat_files f ON m.msgid = f.msgid
            ORDER BY m.seq DESC
            LIMIT ? OFFSET ?
        """, (limit, offset))
    
    rows = cursor.fetchall()
    messages = []
    for row in rows:
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
            "created_at": row[7],
            "file_uri": row[8]  # Joined from chat_files
        })
    
    # Get total count
    if room_id:
        cursor.execute("SELECT COUNT(*) FROM archived_messages WHERE room_id = ?", (room_id,))
    else:
        cursor.execute("SELECT COUNT(*) FROM archived_messages")
    total = cursor.fetchone()[0]
    
    conn.close()
    return {"messages": messages, "limit": limit, "offset": offset, "total": total}


@router.get("/archive/api/files")
async def list_files(room_id: Optional[str] = None, limit: int = 100, offset: int = 0):
    """Get files, optionally filtered by room."""
    conn = get_db()
    cursor = conn.cursor()
    
    if room_id:
        cursor.execute(f"ATTACH DATABASE '{STORAGE_DB_PATH}' AS storage_db")
        cursor.execute("""
            SELECT f.id, f.msgid, f.room_id, f.sender_id, f.filename, f.file_size, f.file_uri, f.created_at, s.extracted_text
            FROM chat_files f
            LEFT JOIN storage_db.file_contents s ON f.msgid = s.wecom_msg_id
            WHERE f.room_id = ?
            ORDER BY f.created_at DESC
            LIMIT ? OFFSET ?
        """, (room_id, limit, offset))
    else:
        cursor.execute(f"ATTACH DATABASE '{STORAGE_DB_PATH}' AS storage_db")
        cursor.execute("""
            SELECT f.id, f.msgid, f.room_id, f.sender_id, f.filename, f.file_size, f.file_uri, f.created_at, s.extracted_text
            FROM chat_files f
            LEFT JOIN storage_db.file_contents s ON f.msgid = s.wecom_msg_id
            ORDER BY f.created_at DESC
            LIMIT ? OFFSET ?
        """, (limit, offset))
    
    rows = cursor.fetchall()
    files = []
    for row in rows:
        files.append({
            "id": row[0],
            "msgid": row[1],
            "room_id": row[2],
            "sender_id": row[3],
            "filename": row[4],
            "file_size": row[5],
            "file_uri": row[6],
            "created_at": row[7],
            "extracted_text": row[8]
        })
    
    # Get total count
    if room_id:
        cursor.execute("SELECT COUNT(*) FROM chat_files WHERE room_id = ?", (room_id,))
    else:
        cursor.execute("SELECT COUNT(*) FROM chat_files")
    total = cursor.fetchone()[0]
    
    conn.close()
    return {"files": files, "limit": limit, "offset": offset, "total": total}


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
    <title>Archive Viewer | AI Data Hub</title>
    <link href="https://fonts.googleapis.com/css2?family=Inter:wght@300;400;500;600;700&display=swap" rel="stylesheet">
    <style>
        * { box-sizing: border-box; margin: 0; padding: 0; }
        body { 
            font-family: 'Inter', -apple-system, BlinkMacSystemFont, sans-serif; 
            background: linear-gradient(135deg, #f8fafc 0%, #e2e8f0 100%);
            color: #1e293b;
            min-height: 100vh;
        }
        .container { display: flex; height: 100vh; }
        
        /* Sidebar */
        .sidebar { 
            width: 300px; 
            background: white;
            padding: 24px; 
            overflow-y: auto; 
            border-right: 1px solid #e2e8f0;
            box-shadow: 4px 0 24px rgba(0,0,0,0.03);
        }
        .logo { 
            display: flex; 
            align-items: center; 
            gap: 12px; 
            margin-bottom: 32px;
            padding-bottom: 24px;
            border-bottom: 1px solid #e2e8f0;
        }
        .logo-icon {
            width: 40px;
            height: 40px;
            background: linear-gradient(135deg, #3b82f6 0%, #1d4ed8 100%);
            border-radius: 10px;
            display: flex;
            align-items: center;
            justify-content: center;
            color: white;
            font-size: 20px;
        }
        .logo-text { font-size: 18px; font-weight: 600; color: #1e293b; }
        .logo-sub { font-size: 12px; color: #64748b; font-weight: 400; }
        
        /* Stats Cards */
        .stats-grid { 
            display: grid; 
            grid-template-columns: 1fr 1fr; 
            gap: 12px; 
            margin-bottom: 24px; 
        }
        .stat-card {
            background: linear-gradient(135deg, #f1f5f9 0%, #f8fafc 100%);
            border: 1px solid #e2e8f0;
            border-radius: 12px;
            padding: 16px;
            text-align: center;
        }
        .stat-value { 
            font-size: 24px; 
            font-weight: 700; 
            color: #3b82f6; 
            margin-bottom: 4px;
        }
        .stat-label { font-size: 11px; color: #64748b; text-transform: uppercase; letter-spacing: 0.5px; }
        
        /* Section Title */
        .section-title {
            font-size: 12px;
            font-weight: 600;
            color: #64748b;
            text-transform: uppercase;
            letter-spacing: 1px;
            margin-bottom: 12px;
        }
        
        /* Room List */
        .room-list { list-style: none; }
        .room-item { 
            padding: 12px 16px; 
            margin: 6px 0; 
            background: #f8fafc;
            border: 1px solid #e2e8f0;
            border-radius: 10px; 
            cursor: pointer; 
            transition: all 0.2s ease;
        }
        .room-item:hover { 
            background: #eff6ff;
            border-color: #3b82f6;
            transform: translateX(4px);
        }
        .room-item.active { 
            background: linear-gradient(135deg, #3b82f6 0%, #1d4ed8 100%);
            border-color: transparent;
            color: white;
        }
        .room-item.active .room-count { color: rgba(255,255,255,0.8); }
        .room-name { font-size: 14px; font-weight: 500; margin-bottom: 4px; }
        .room-count { font-size: 12px; color: #64748b; }
        
        .all-btn { 
            width: 100%; 
            padding: 14px; 
            margin-bottom: 16px; 
            background: linear-gradient(135deg, #3b82f6 0%, #1d4ed8 100%);
            border: none;
            color: white; 
            cursor: pointer; 
            border-radius: 10px;
            font-weight: 500;
            font-size: 14px;
            transition: all 0.2s;
        }
        .all-btn:hover { 
            transform: translateY(-2px);
            box-shadow: 0 4px 12px rgba(59, 130, 246, 0.4);
        }
        
        /* Main Content */
        .main { flex: 1; padding: 32px; overflow-y: auto; }
        .header { display: flex; justify-content: space-between; align-items: center; margin-bottom: 24px; }
        .page-title { font-size: 24px; font-weight: 600; color: #1e293b; }
        
        /* Tabs */
        .tabs { display: flex; gap: 8px; }
        .tab { 
            padding: 10px 20px; 
            background: white;
            border: 1px solid #e2e8f0;
            color: #64748b; 
            cursor: pointer; 
            border-radius: 8px;
            font-size: 14px;
            font-weight: 500;
            transition: all 0.2s;
        }
        .tab:hover { background: #f1f5f9; color: #1e293b; }
        .tab.active { 
            background: #3b82f6;
            border-color: #3b82f6;
            color: white;
        }
        
        /* Table */
        .table-container {
            background: white;
            border-radius: 16px;
            box-shadow: 0 4px 24px rgba(0,0,0,0.06);
            overflow: hidden;
        }
        table { width: 100%; border-collapse: collapse; font-size: 14px; }
        th { 
            padding: 16px 20px; 
            text-align: left; 
            background: #f8fafc;
            font-weight: 600;
            color: #64748b;
            font-size: 12px;
            text-transform: uppercase;
            letter-spacing: 0.5px;
            border-bottom: 1px solid #e2e8f0;
        }
        td { 
            padding: 16px 20px; 
            border-bottom: 1px solid #f1f5f9;
            color: #1e293b;
        }
        tr:hover { background: #fafbfc; }
        tr:last-child td { border-bottom: none; }
        
        .content-cell { max-width: 400px; overflow: hidden; text-overflow: ellipsis; white-space: nowrap; }
        .msgtype-badge {
            display: inline-block;
            padding: 4px 10px;
            border-radius: 20px;
            font-size: 12px;
            font-weight: 500;
        }
        .msgtype-text { background: #dbeafe; color: #1d4ed8; }
        .msgtype-file { background: #dcfce7; color: #15803d; }
        .msgtype-image { background: #fef3c7; color: #b45309; }
        .msgtype-other { background: #f1f5f9; color: #64748b; }
        
        .file-link { 
            color: #3b82f6; 
            text-decoration: none;
            font-weight: 500;
            display: inline-flex;
            align-items: center;
            gap: 4px;
        }
        .file-link:hover { text-decoration: underline; }
        
        .loading { 
            text-align: center; 
            padding: 60px; 
            color: #94a3b8;
            font-size: 15px;
        }
        .empty { 
            text-align: center; 
            padding: 60px; 
            color: #94a3b8;
        }
        .empty-icon { font-size: 48px; margin-bottom: 16px; }
        
        .sender-name { font-weight: 500; color: #1e293b; }
        .sender-id { font-size: 12px; color: #94a3b8; }
        .time-cell { color: #64748b; font-size: 13px; white-space: nowrap; }
        
        /* Image Preview */
        .img-preview { 
            max-width: 200px; 
            max-height: 200px; 
            border-radius: 8px; 
            margin-top: 8px; 
            cursor: pointer;
            border: 1px solid #e2e8f0;
            transition: transform 0.2s;
        }
        .img-preview:hover { transform: scale(1.02); }
        /* Pagination */
        .pagination {
            display: flex;
            justify-content: center;
            align-items: center;
            gap: 16px;
            padding: 24px;
            background: #f8fafc;
            border-top: 1px solid #e2e8f0;
        }
        .page-btn {
            padding: 8px 16px;
            background: white;
            border: 1px solid #e2e8f0;
            border-radius: 6px;
            cursor: pointer;
            font-size: 14px;
            font-weight: 500;
            transition: all 0.2s;
        }
        .page-btn:hover:not(:disabled) {
            background: #f1f5f9;
            border-color: #cbd5e1;
        }
        .page-btn:disabled {
            opacity: 0.5;
            cursor: not-allowed;
        }
        .page-info {
            font-size: 14px;
            color: #64748b;
        }
    </style>
</head>
<body>
    <div class="container">
        <div class="sidebar">
            <div class="logo">
                <div class="logo-icon">📊</div>
                <div>
                    <div class="logo-text">Archive Viewer</div>
                    <div class="logo-sub">AI Data Hub</div>
                </div>
            </div>
            
            <div class="stats-grid" id="stats">
                <div class="stat-card"><div class="stat-value">-</div><div class="stat-label">消息</div></div>
                <div class="stat-card"><div class="stat-value">-</div><div class="stat-label">文件</div></div>
                <div class="stat-card"><div class="stat-value">-</div><div class="stat-label">群聊</div></div>
                <div class="stat-card"><div class="stat-value">-</div><div class="stat-label">序号</div></div>
            </div>
            
            <div class="section-title">群聊列表</div>
            <button class="all-btn" onclick="selectRoom(null)">📋 查看所有消息</button>
            <ul class="room-list" id="room-list"></ul>
        </div>
        
        <div class="main">
            <div class="header">
                <h1 class="page-title" id="page-title">消息存档</h1>
                <div class="tabs">
                    <button class="tab active" onclick="showTab('messages')">💬 消息</button>
                    <button class="tab" onclick="showTab('files')">📁 文件</button>
                </div>
            </div>
            <div class="table-container">
                <div id="content">
                    <div class="loading">选择左侧群聊或点击"查看所有消息"开始浏览</div>
                </div>
                <div id="pagination" class="pagination" style="display: none;">
                    <button id="prev-btn" class="page-btn" onclick="changePage(-1)">◀️ 上一页</button>
                    <span id="page-info" class="page-info">第 1 页</span>
                    <button id="next-btn" class="page-btn" onclick="changePage(1)">下一页 ▶️</button>
                </div>
            </div>
        </div>
    </div>
    <script>
        let currentRoom = null;
        let currentTab = 'messages';
        let currentOffset = 0;
        const pageSize = 100;
        let totalCount = 0;
        const roomNames = {};  // Cache for room display names
        
        function escapeHtml(str) {
            if (!str) return '';
            const map = {
                '&': '&amp;',
                '<': '&lt;',
                '>': '&gt;',
                '"': '&quot;',
                "'": '&#039;'
            };
            return String(str).replace(/[&<>"']/g, m => map[m]);
        }
        
        async function loadStats() {
            const res = await fetch('/archive/api/stats');
            const data = await res.json();
            document.getElementById('stats').innerHTML = `
                <div class="stat-card"><div class="stat-value">${data.total_messages}</div><div class="stat-label">消息</div></div>
                <div class="stat-card"><div class="stat-value">${data.total_files}</div><div class="stat-label">文件</div></div>
                <div class="stat-card"><div class="stat-value">${data.total_rooms}</div><div class="stat-label">群聊</div></div>
                <div class="stat-card"><div class="stat-value">${data.current_seq}</div><div class="stat-label">序号</div></div>
            `;
        }
        
        function getRoomDisplayName(roomId) {
            if (!roomId) return '私聊';
            if (roomNames[roomId]) return roomNames[roomId];
            // Try to create a readable name from ID
            return '群聊 ' + roomId.substring(0, 8) + '...';
        }
        
        async function loadRooms() {
            const res = await fetch('/archive/api/rooms');
            const data = await res.json();
            const list = document.getElementById('room-list');
            
            list.innerHTML = data.rooms.map((r, i) => `
                <li class="room-item" data-room="${r.room_id}" onclick="selectRoom('${r.room_id}', this)">
                    <div class="room-name">群聊 ${i + 1}</div>
                    <div class="room-count">${r.msg_count} 条消息 · ${r.room_id.substring(0, 12)}...</div>
                </li>
            `).join('');
        }
        
        function selectRoom(roomId, el) {
            currentRoom = roomId;
            currentOffset = 0;
            document.querySelectorAll('.room-item').forEach(e => e.classList.remove('active'));
            if (el) el.classList.add('active');
            document.getElementById('page-title').textContent = roomId ? getRoomDisplayName(roomId) : '所有消息';
            loadContent();
        }
        
        function showTab(tab) {
            currentTab = tab;
            currentOffset = 0;
            document.querySelectorAll('.tab').forEach(el => el.classList.remove('active'));
            event.target.classList.add('active');
            loadContent();
        }
        
        function changePage(delta) {
            currentOffset += delta * pageSize;
            if (currentOffset < 0) currentOffset = 0;
            loadContent();
        }

        function updatePaginationUI(total) {
            totalCount = total;
            const hasPrev = currentOffset > 0;
            const hasNext = currentOffset + pageSize < total;
            const pageNum = Math.floor(currentOffset / pageSize) + 1;
            const totalPages = Math.ceil(total / pageSize);
            
            document.getElementById('pagination').style.display = total > 0 ? 'flex' : 'none';
            document.getElementById('prev-btn').disabled = !hasPrev;
            document.getElementById('next-btn').disabled = !hasNext;
            document.getElementById('page-info').textContent = `第 ${pageNum} / ${totalPages || 1} 页 (共 ${total} 条)`;
        }

        function getMsgTypeBadge(type) {
            const badges = {
                text: 'msgtype-text',
                file: 'msgtype-file',
                image: 'msgtype-image',
            };
            return badges[type] || 'msgtype-other';
        }
        
        function getSenderDisplay(msg) {
            // Try to get name from content
            const c = msg.content;
            const name = c?.from_chatroom_member_name || c?.from_name || msg.sender_id || '-';
            return `<div class="sender-name">${name}</div>`;
        }
        
        function formatExtractedPreview(text) {
            if (!text || text === '-') return '-';
            if (text.length <= 100) return escapeHtml(text);
            return escapeHtml(text.substring(0, 50)) + ' <span style="color:#94a3b8">...</span> ' + escapeHtml(text.substring(text.length - 30));
        }
        
        async function loadContent() {
            const content = document.getElementById('content');
            content.innerHTML = '<div class="loading">加载中...</div>';
            
            const roomParam = currentRoom ? `room_id=${currentRoom}&` : '';
            const offsetParam = `offset=${currentOffset}&`;
            
            if (currentTab === 'messages') {
                const res = await fetch(`/archive/api/messages?${roomParam}${offsetParam}limit=${pageSize}`);
                const data = await res.json();
                updatePaginationUI(data.total);
                
                if (data.messages.length === 0) {
                    content.innerHTML = '<div class="empty"><div class="empty-icon">📭</div>暂无消息记录</div>';
                    return;
                }
                
                content.innerHTML = `
                    <table>
                        <thead>
                            <tr>
                                <th style="width:60px">序号</th>
                                <th style="width:80px">类型</th>
                                <th style="width:150px">发送者</th>
                                <th>内容</th>
                                <th style="width:160px">时间</th>
                            </tr>
                        </thead>
                        <tbody>
                            ${data.messages.map(m => `
                                <tr>
                                    <td>${m.seq}</td>
                                    <td><span class="msgtype-badge ${getMsgTypeBadge(m.msgtype)}">${m.msgtype}</span></td>
                                    <td>${getSenderDisplay(m)}</td>
                                    <td class="content-cell" title="${escapeHtml(JSON.stringify(m.content))}">${getContentPreview(m)}</td>
                                    <td class="time-cell">${formatTime(m.created_at)}</td>
                                </tr>
                            `).join('')}
                        </tbody>
                    </table>
                `;
            } else {
                const res = await fetch(`/archive/api/files?${roomParam}${offsetParam}limit=${pageSize}`);
                const data = await res.json();
                updatePaginationUI(data.total);
                
                if (data.files.length === 0) {
                    content.innerHTML = '<div class="empty"><div class="empty-icon">📁</div>暂无文件记录</div>';
                    return;
                }
                
                content.innerHTML = `
                    <table>
                        <thead>
                            <tr>
                                <th>文件名</th>
                                <th style="width:100px">大小</th>
                                <th style="width:150px">发送者</th>
                                <th>提取内容</th>
                                <th style="width:100px">操作</th>
                                <th style="width:160px">时间</th>
                            </tr>
                        </thead>
                        <tbody>
                            ${data.files.map(f => `
                                <tr>
                                    <td>📄 ${f.filename}</td>
                                    <td>${formatSize(f.file_size)}</td>
                                    <td>${f.sender_id || '-'}</td>
                                    <td class="content-cell" title="${escapeHtml(f.extracted_text)}">${formatExtractedPreview(f.extracted_text)}</td>
                                    <td><a class="file-link" href="${escapeHtml(f.file_uri)}" target="_blank">⬇️ 下载</a></td>
                                    <td class="time-cell">${formatTime(f.created_at)}</td>
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
            if (c.image) {
                if (msg.file_uri) {
                    return `
                        <div>🖼️ 图片</div>
                        <a href="${escapeHtml(msg.file_uri)}" target="_blank">
                            <img src="${escapeHtml(msg.file_uri)}" class="img-preview" alt="Image preview">
                        </a>
                    `;
                }
                return '🖼️ 图片 (未下载)';
            }
            if (c.video) return '🎬 视频';
            if (c.voice) return '🎤 语音';
            if (c.emotion) return '😊 表情';
            if (c.link) return '🔗 ' + (c.link.title || '链接');
            return JSON.stringify(c).substring(0, 60) + '...';
        }
        
        function formatSize(bytes) {
            if (!bytes) return '-';
            if (bytes < 1024) return bytes + ' B';
            if (bytes < 1024*1024) return (bytes/1024).toFixed(1) + ' KB';
            return (bytes/1024/1024).toFixed(1) + ' MB';
        }
        
        function formatTime(timeStr) {
            if (!timeStr) return '-';
            return timeStr.replace('T', ' ').substring(0, 19);
        }
        
        loadStats();
        loadRooms();
    </script>
</body>
</html>
    """
    return HTMLResponse(content=html)
