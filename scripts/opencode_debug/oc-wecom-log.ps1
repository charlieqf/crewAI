param(
  [string]$Host = "104.238.213.119",
  [string]$User = "root",
  [string]$Key = "~/.ssh/kamatera",
  [int]$Minutes = 10
)

$remote = "$User@$Host"
ssh -i $Key $remote "bash -lc 'journalctl -u wecom-callback --since \"$Minutes min ago\" --no-pager | tail -200'"
