param(
  [Parameter(Mandatory = $true)][string]$SessionId,
  [string]$Host = "104.238.213.119",
  [string]$User = "root",
  [string]$Key = "~/.ssh/kamatera",
  [int]$Limit = 10
)

$remote = "$User@$Host"
ssh -i $Key $remote "bash -lc 'curl -s http://localhost:4096/session/$SessionId/message | python3 -c \"import sys,json; msgs=json.load(sys.stdin); print(\\\"total\\\", len(msgs)); limit=$Limit; \nfor m in msgs[-limit:]:\n info=m.get(\\\"info\\\",{}); role=info.get(\\\"role\\\"); mid=info.get(\\\"id\\\"); pid=info.get(\\\"parentID\\\") or info.get(\\\"parentId\\\"); text=\\\"\\\";\n for p in m.get(\\\"parts\\\",[]):\n  if p.get(\\\"type\\\")==\\\"text\\\":\n   text=p.get(\\\"text\\\",\\\"\\\")[:120].replace(\\\"\\\\n\\\",\\\" \\"); break;\n print(role, mid, \\\"parent\\\", pid, \\\"text\\\", text)\"'"
