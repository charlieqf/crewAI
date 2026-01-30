param(
  [string]$Host = "104.238.213.119",
  [string]$User = "root",
  [string]$Key = "~/.ssh/kamatera"
)

$remote = "$User@$Host"
ssh -i $Key $remote "bash -lc 'ls -t /root/.local/share/opencode/log/*.log | head -1'"
