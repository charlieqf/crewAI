#!/usr/bin/env python3
"""
Remote Log Query Tool for Kamatera VM.

Query and tail logs from the WeCom callback server deployed on Kamatera.

Usage:
    python ops_logs.py tail            # Follow live logs
    python ops_logs.py recent          # Last 100 lines
    python ops_logs.py errors          # Last 50 errors
    python ops_logs.py search "pattern" # Search logs
    python ops_logs.py llm             # Filter LLM-related logs
    python ops_logs.py status          # Service status

Environment Variables:
    KAMATERA_HOST: Kamatera VM IP or hostname (required)
    KAMATERA_USER: SSH username (default: root)
    KAMATERA_KEY: Path to SSH private key (required for key-based auth)

Note: This script uses SSH key authentication. Password auth is not supported.
      Set up SSH keys first: ssh-keygen -t ed25519 -f ~/.ssh/kamatera
"""

from __future__ import annotations

import argparse
import os
import subprocess
import sys


# Configuration
DEFAULT_LOG_PATH = "/var/log/wecom-callback/wecom_callback.log"
ERROR_LOG_PATH = "/var/log/wecom-callback/wecom_callback_error.log"
SERVICE_NAME = "wecom-callback"


def get_ssh_config() -> dict[str, str]:
    """Get SSH configuration from environment."""
    host = os.getenv("KAMATERA_HOST")
    if not host:
        print("Error: KAMATERA_HOST environment variable not set")
        print("Set it with: export KAMATERA_HOST=your.server.ip")
        sys.exit(1)

    key = os.getenv("KAMATERA_KEY", "")
    if not key:
        print("Warning: KAMATERA_KEY not set, SSH may prompt for password")

    return {
        "host": host,
        "user": os.getenv("KAMATERA_USER", "root"),
        "key": key,
    }


def run_ssh_command(command: str, interactive: bool = False) -> int:
    """Run command on remote server via SSH."""
    config = get_ssh_config()

    ssh_args = ["ssh"]

    # Add key or password auth
    if config["key"]:
        ssh_args.extend(["-i", config["key"]])

    # Common SSH options
    ssh_args.extend(
        [
            "-o",
            "StrictHostKeyChecking=no",
            "-o",
            "ConnectTimeout=10",
            f"{config['user']}@{config['host']}",
            command,
        ]
    )

    try:
        if interactive:
            return subprocess.call(ssh_args)
        else:
            result = subprocess.run(ssh_args, capture_output=True, text=True)
            if result.stdout:
                print(result.stdout)
            if result.stderr:
                print(result.stderr, file=sys.stderr)
            return result.returncode
    except KeyboardInterrupt:
        print("\nInterrupted")
        return 130


def cmd_tail(args: argparse.Namespace) -> int:
    """Follow live logs."""
    lines = args.lines or 50
    log_path = ERROR_LOG_PATH if args.errors else DEFAULT_LOG_PATH

    print(f"Following logs from {log_path}...")
    print("Press Ctrl+C to stop\n")

    return run_ssh_command(f"tail -n {lines} -f {log_path}", interactive=True)


def cmd_recent(args: argparse.Namespace) -> int:
    """Show recent log entries."""
    lines = args.lines or 100
    log_path = ERROR_LOG_PATH if args.errors else DEFAULT_LOG_PATH

    return run_ssh_command(f"tail -n {lines} {log_path}")


def cmd_errors(args: argparse.Namespace) -> int:
    """Show recent errors."""
    lines = args.lines or 50

    # Check error log first
    print(f"=== Last {lines} lines from error log ===")
    run_ssh_command(f"tail -n {lines} {ERROR_LOG_PATH}")

    # Also grep for errors in main log
    print(f"\n=== Error patterns in main log ===")
    return run_ssh_command(
        f"grep -E '\\[(LLM_ERR|WEBHOOK_ERR|FATAL)\\]|ERROR' {DEFAULT_LOG_PATH} | tail -n {lines}"
    )


def cmd_search(args: argparse.Namespace) -> int:
    """Search logs for pattern."""
    pattern = args.pattern
    lines = args.lines or 50

    return run_ssh_command(f"grep -i '{pattern}' {DEFAULT_LOG_PATH} | tail -n {lines}")


def cmd_llm(args: argparse.Namespace) -> int:
    """Show LLM-related logs."""
    lines = args.lines or 50

    return run_ssh_command(
        f"grep -E '\\[LLM_REQ\\]|\\[LLM_RES\\]|\\[LLM_ERR\\]' {DEFAULT_LOG_PATH} | tail -n {lines}"
    )


def cmd_messages(args: argparse.Namespace) -> int:
    """Show message processing logs."""
    lines = args.lines or 50

    return run_ssh_command(
        f"grep -E '\\[RECV\\]|\\[PROCESS\\]|\\[SENT\\]' {DEFAULT_LOG_PATH} | tail -n {lines}"
    )


def cmd_status(args: argparse.Namespace) -> int:
    """Show service status and health."""
    print("=== Service Status ===")
    run_ssh_command(f"systemctl status {SERVICE_NAME} --no-pager")

    print("\n=== Recent Journal Logs ===")
    run_ssh_command(f"journalctl -u {SERVICE_NAME} -n 20 --no-pager")

    print("\n=== Log File Stats ===")
    run_ssh_command(f"ls -la /var/log/wecom-callback/")

    print("\n=== Health Check ===")
    return run_ssh_command(
        "curl -s http://localhost:8000/health | python3 -m json.tool 2>/dev/null || echo 'Health check failed'"
    )


def cmd_restart(args: argparse.Namespace) -> int:
    """Restart the service."""
    print("Restarting service...")
    run_ssh_command(f"systemctl restart {SERVICE_NAME}")
    print("\nWaiting 3 seconds...")
    run_ssh_command("sleep 3")
    return cmd_status(args)


def cmd_db_stats(args: argparse.Namespace) -> int:
    """Show database statistics."""
    db_path = os.getenv("CHAT_DB_PATH", "/var/lib/wecom-callback/chat_history.db")

    print("=== Database Stats ===")
    run_ssh_command(f"ls -la {db_path}")

    print("\n=== Message Count ===")
    run_ssh_command(
        f"sqlite3 {db_path} 'SELECT COUNT(*) as total_messages FROM chat_messages;'"
    )

    print("\n=== Messages by Role ===")
    run_ssh_command(
        f"sqlite3 {db_path} 'SELECT role, COUNT(*) FROM chat_messages GROUP BY role;'"
    )

    print("\n=== Recent Messages ===")
    return run_ssh_command(
        f"sqlite3 {db_path} 'SELECT timestamp, sender_name, role, substr(content, 1, 50) FROM chat_messages ORDER BY timestamp DESC LIMIT 10;'"
    )


def main() -> int:
    """Main entry point."""
    parser = argparse.ArgumentParser(
        description="Remote Log Query Tool for Kamatera VM",
        formatter_class=argparse.RawDescriptionHelpFormatter,
        epilog=__doc__,
    )

    subparsers = parser.add_subparsers(dest="command", help="Available commands")

    # tail command
    tail_parser = subparsers.add_parser("tail", help="Follow live logs")
    tail_parser.add_argument("-n", "--lines", type=int, help="Initial lines to show")
    tail_parser.add_argument(
        "-e", "--errors", action="store_true", help="Follow error log"
    )
    tail_parser.set_defaults(func=cmd_tail)

    # recent command
    recent_parser = subparsers.add_parser("recent", help="Show recent log entries")
    recent_parser.add_argument("-n", "--lines", type=int, help="Number of lines")
    recent_parser.add_argument(
        "-e", "--errors", action="store_true", help="Show error log"
    )
    recent_parser.set_defaults(func=cmd_recent)

    # errors command
    errors_parser = subparsers.add_parser("errors", help="Show recent errors")
    errors_parser.add_argument("-n", "--lines", type=int, help="Number of lines")
    errors_parser.set_defaults(func=cmd_errors)

    # search command
    search_parser = subparsers.add_parser("search", help="Search logs for pattern")
    search_parser.add_argument("pattern", help="Search pattern")
    search_parser.add_argument("-n", "--lines", type=int, help="Max results")
    search_parser.set_defaults(func=cmd_search)

    # llm command
    llm_parser = subparsers.add_parser("llm", help="Show LLM-related logs")
    llm_parser.add_argument("-n", "--lines", type=int, help="Number of lines")
    llm_parser.set_defaults(func=cmd_llm)

    # messages command
    msg_parser = subparsers.add_parser("messages", help="Show message processing logs")
    msg_parser.add_argument("-n", "--lines", type=int, help="Number of lines")
    msg_parser.set_defaults(func=cmd_messages)

    # status command
    status_parser = subparsers.add_parser("status", help="Show service status")
    status_parser.set_defaults(func=cmd_status)

    # restart command
    restart_parser = subparsers.add_parser("restart", help="Restart the service")
    restart_parser.set_defaults(func=cmd_restart)

    # db-stats command
    db_parser = subparsers.add_parser("db-stats", help="Show database statistics")
    db_parser.set_defaults(func=cmd_db_stats)

    args = parser.parse_args()

    if not args.command:
        parser.print_help()
        return 1

    return args.func(args)


if __name__ == "__main__":
    sys.exit(main())
