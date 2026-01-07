# Team SSH Debugging Playbook (Kamatera / WeCom Project)

This document is a collection of real-world SSH commands used during the development and maintenance of the WeCom AI Bot. Every team member should be familiar with these diagnostic scenarios.

> [!NOTE]
> All commands assume your private key is at `$env:USERPROFILE\.ssh\kamatera`.

## Scenario 1: "User sent a message, but there's no reply"
Check if the server is receiving the callback and if any errors occurred during LLM processing.

* **Check live POST traffic and Bot detection:**
  ```bash
  ssh -i $env:USERPROFILE\.ssh\kamatera root@104.238.213.119 "journalctl -u wecom-callback -f | grep -E 'POST|AIBOT'"
  ```
* **Verify Service Status (Is it even running?):**
  ```bash
  ssh -i $env:USERPROFILE\.ssh\kamatera root@104.238.213.119 "systemctl status wecom-callback"
  ```
* **Check for Out-of-Memory (OOM) or system crashes:**
  ```bash
  ssh -i $env:USERPROFILE\.ssh\kamatera root@104.238.213.119 "dmesg | tail -n 50"
  ```

---

## Scenario 2: "Archive page is out of sync or missing records"
When the web viewer doesn't show recent messages, the background sync worker might be stuck or pointing to the wrong DB.

* **Check the sync cursor (where is the worker currently?):**
  ```bash
  ssh -i $env:USERPROFILE\.ssh\kamatera root@104.238.213.119 "sqlite3 /var/lib/wecom-callback/chat_history.db 'SELECT * FROM archive_cursor;'"
  ```
* **Check the latest message actually saved in the DB:**
  ```bash
  ssh -i $env:USERPROFILE\.ssh\kamatera root@104.238.213.119 "sqlite3 /var/lib/wecom-callback/chat_history.db 'SELECT MAX(seq) FROM archived_messages;'"
  ```
* **Manually trigger a full sync catch-up (using the project venv):**
  ```bash
  ssh -i $env:USERPROFILE\.ssh\kamatera root@104.238.213.119 "/opt/wecom-callback/venv/bin/python /opt/wecom-callback/scripts/archive_sync_worker.py 0"
  ```

---

## Scenario 3: "File analysis is failing or images don't display"
Investigate file downloads from WeCom and uploads to Qiniu storage.

* **Watch File Processing Logs:**
  ```bash
  ssh -i $env:USERPROFILE\.ssh\kamatera root@104.238.213.119 "journalctl -u wecom-callback -f | grep -i file"
  ```
* **Verify Qiniu Upload Records:**
  ```bash
  ssh -i $env:USERPROFILE\.ssh\kamatera root@104.238.213.119 "sqlite3 /var/lib/wecom-callback/chat_history.db 'SELECT filename, file_uri FROM chat_files ORDER BY id DESC LIMIT 5;'"
  ```
* **Check Disk Space (Large attachments can fill /var/log/ or /tmp/):**
  ```bash
  ssh -i $env:USERPROFILE\.ssh\kamatera root@104.238.213.119 "df -h"
  ```

---

## Scenario 4: "GitLab Code Review or VPN issues"
If the bot can't reach the internal GitLab server, usually the VPN or /etc/hosts is the culprit.

* **Test connectivity to internal GitLab:**
  ```bash
  ssh -i $env:USERPROFILE\.ssh\kamatera root@104.238.213.119 "curl -i http://gitlab.goldenstand.com/health"
  ```
* **Verify VPN Interface (Look for 'ppp0' or 'tun0'):**
  ```bash
  ssh -i $env:USERPROFILE\.ssh\kamatera root@104.238.213.119 "ip addr show"
  ```

---

## Scenario 5: "Context Reset or Bot Configuration Check"
Verify shared context and custom prompts stored in SQLite.

* **View short-term context (Hot window):**
  ```bash
  ssh -i $env:USERPROFILE\.ssh\kamatera root@104.238.213.119 "sqlite3 /var/lib/wecom-callback/chat_storage.db 'SELECT sender_name, content FROM chat_messages ORDER BY id DESC LIMIT 10;'"
  ```
* **Check Custom Prompts (/set_prompt):**
  ```bash
  ssh -i $env:USERPROFILE\.ssh\kamatera root@104.238.213.119 "sqlite3 /var/lib/wecom-callback/chat_history.db 'SELECT bot_type, custom_prompt FROM custom_prompts;'"
  ```

---

## Scenario 6: "API Usage & Latency"
Check if the bot is actually hitting the API and how long it's taking.

* **Check real-time latency stats:**
  ```bash
  ssh -i $env:USERPROFILE\.ssh\kamatera root@104.238.213.119 "journalctl -u wecom-callback -n 500 --no-pager | grep elapsed"
  ```
* **Verify current server time (crucial for log matching):**
  ```bash
  ssh -i $env:USERPROFILE\.ssh\kamatera root@104.238.213.119 "date"
  ```
