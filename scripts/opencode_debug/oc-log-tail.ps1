param(
  [string]$Host = "104.238.213.119",
  [string]$User = "root",
  [string]$Key = "~/.ssh/kamatera",
  [int]$Lines = 200
)

$remote = "$User@$Host"
ssh -i $Key $remote "bash -lc 'tail -$Lines $(ls -t /root/.local/share/opencode/log/*.log | head -1)'"
