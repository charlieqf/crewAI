---
description: Deploy wecom-callback to Kamatera server
---

# Deploy to Kamatera Server

## Prerequisites

- SSH key at `$env:USERPROFILE\.ssh\kamatera` (Windows) or `~/.ssh/kamatera` (Linux/Mac)
- Target backend server: `104.238.213.119`

## Quick Deploy (Update Existing)

// turbo-all

1. Push code to GitHub:
```powershell
git push origin feat-wecom
```

2. Deploy to server (Safer reset):
```powershell
ssh -i $env:USERPROFILE\.ssh\kamatera root@104.238.213.119 "cd /opt/wecom-callback && git fetch origin && git reset --hard origin/feat-wecom && systemctl restart wecom-callback && echo '✅ Deployed and Restarted'"
```

3. Check service status:
```powershell
ssh -i $env:USERPROFILE\.ssh\kamatera root@104.238.213.119 "systemctl status wecom-callback"
```

4. View real-time logs:
```powershell
ssh -i $env:USERPROFILE\.ssh\kamatera root@104.238.213.119 "journalctl -u wecom-callback -n 50 -f"
```

## Full Redeploy (New Setup / Fresh Clone)

Use the automated deployment script:
```powershell
scp -i $env:USERPROFILE\.ssh\kamatera scripts/deploy_kamatera.sh root@104.238.213.119:/tmp/
ssh -i $env:USERPROFILE\.ssh\kamatera root@104.238.213.119 "bash /tmp/deploy_kamatera.sh"
```

## Configure Environment Variables

Edit the secure env file on the server:
```powershell
ssh -i $env:USERPROFILE\.ssh\kamatera root@104.238.213.119 "nano /etc/wecom-callback/env"
# Or append a specific key:
ssh -i $env:USERPROFILE\.ssh\kamatera root@104.238.213.119 "echo 'NEW_KEY=value' >> /etc/wecom-callback/env && systemctl restart wecom-callback"
```

## Server Topology

| Item | Value | Description |
|------|-------|-------------|
| **Backend IP** | `104.238.213.119` | Main application hosting (Kamatera) |
| **Nginx IP** | `113.125.202.173` | Public-facing proxy/forwarder |
| **App Dir** | `/opt/wecom-callback` | Git root on server |
| **Env File** | `/etc/wecom-callback/env` | Sensitive credentials (not in Git) |
| **Service** | `wecom-callback` | Managed via `systemctl` |
| **Python** | `/opt/wecom-callback/venv` | Isolated virtual environment |
