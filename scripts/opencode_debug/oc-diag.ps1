param(
  [string]$Host = "104.238.213.119",
  [string]$User = "root",
  [string]$Key = "~/.ssh/kamatera",
  [int]$Minutes = 10,
  [int]$Lines = 200,
  [int]$Limit = 10
)

$remote = "$User@$Host"

Write-Host "== Latest OpenCode log =="
ssh -i $Key $remote "bash -lc 'ls -t /root/.local/share/opencode/log/*.log | head -1'"

Write-Host "== Tail OpenCode log =="
ssh -i $Key $remote "bash -lc 'tail -$Lines $(ls -t /root/.local/share/opencode/log/*.log | head -1)'"

Write-Host "== Tail wecom-callback log =="
ssh -i $Key $remote "bash -lc 'journalctl -u wecom-callback --since \"$Minutes min ago\" --no-pager | tail -200'"

Write-Host "== Session status =="
ssh -i $Key $remote "bash -lc 'curl -s http://localhost:4096/session/status | python3 -m json.tool'"

Write-Host "== Latest session messages =="
$sessionId = ssh -i $Key $remote "bash -lc 'journalctl -u wecom-callback --since \"$Minutes min ago\" --no-pager | grep -i OPENCODE | grep \"Starting prompt\" | tail -1 | sed -E \"s/.*session=([^ ]+).*/\\1/\"'"
$sessionId = $sessionId.Trim()
if ($sessionId) {
  Write-Host "session_id=$sessionId"
  ssh -i $Key $remote "bash -lc 'curl -s http://localhost:4096/session/$sessionId/message | python3 -c \"import sys,json; msgs=json.load(sys.stdin); print(\\\"total\\\", len(msgs)); limit=$Limit; \nfor m in msgs[-limit:]:\n info=m.get(\\\"info\\\",{}); role=info.get(\\\"role\\\"); mid=info.get(\\\"id\\\"); pid=info.get(\\\"parentID\\\") or info.get(\\\"parentId\\\"); text=\\\"\\\";\n for p in m.get(\\\"parts\\\",[]):\n  if p.get(\\\"type\\\")==\\\"text\\\":\n   text=p.get(\\\"text\\\",\\\"\\\")[:120].replace(\\\"\\\\n\\\",\\\" \\"); break;\n print(role, mid, \\\"parent\\\", pid, \\\"text\\\", text)\"'"
} else {
  Write-Host "No recent session found in wecom-callback logs."
}
