# SSH & PowerShell Quoting Guide

This document explains how to avoid common quoting issues when running remote commands via `ssh` from a Windows PowerShell environment.

## The Problem
When you run a command like:
```powershell
ssh user@host "sqlite3 db 'UPDATE table SET col=\"val\";'"
```
PowerShell tries to be "helpful" by parsing the string before passing it to the `ssh` executable. This often leads to errors like:
- `\ : The term '\' is not recognized as the name of a cmdlet`
- `unexpected EOF while looking for matching "'`

## Best Practices

### 1. Use Script Files for Complex SQL/Commands
Instead of trying to escape nested quotes in a single line, write the command to a temporary file on the remote server and execute that file.

**Example (SQL):**
```powershell
# Instead of this:
# ssh host "sqlite3 db \"UPDATE table SET status='done' WHERE id=1;\""

# Do this:
ssh host "echo \"UPDATE table SET status='done' WHERE id=1;\" > /tmp/query.sql; sqlite3 db < /tmp/query.sql; rm /tmp/query.sql"
```

### 2. Avoid Backticks/Backslashes for Line Continuation in SSH Strings
PowerShell and Bash both use different escape characters. Passing a backslash from PowerShell to a remote Bash shell is extremely error-prone.

### 3. Use Single Quotes for the Outer SSH Command
If the remote command itself doesn't contain single quotes, wrap it in single quotes in PowerShell to prevent any variable expansion or parsing.

```powershell
ssh host 'ls -l /var/log | grep error'
```

### 4. Double-Check Semicolons
Semicolons `;` are command separators in both PowerShell and Bash. If you use an unquoted semicolon, PowerShell might try to run the second half of the command locally.

**Bad:**
```powershell
ssh host "echo hello" ; uptime  # uptime runs LOCALLY
```

**Good:**
```powershell
ssh host "echo hello; uptime"   # Both run REMOTELY
```

## Troubleshooting Checklist
1. **Did PowerShell truncate the command?** Check if you see "The term '\' is not recognized".
2. **Are the quotes balanced?** Count your `"` and `'`.
3. **Is it too complex?** If yes, use the "Echo to temporary file" method.
