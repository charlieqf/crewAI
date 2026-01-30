#!/usr/bin/env python3
import argparse
import json
import sys
import urllib.request


def fetch_json(url: str):
    with urllib.request.urlopen(url) as resp:
        return json.loads(resp.read().decode("utf-8"))


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--base", default="http://localhost:4096")
    parser.add_argument("--session", help="Session ID")
    parser.add_argument("--status", action="store_true")
    parser.add_argument("--limit", type=int, default=10)
    args = parser.parse_args()

    base = args.base.rstrip("/")

    if args.status:
        data = fetch_json(f"{base}/session/status")
        print(json.dumps(data, indent=2))

    if args.session:
        msgs = fetch_json(f"{base}/session/{args.session}/message")
        print(f"total {len(msgs)}")
        for m in msgs[-args.limit :]:
            info = m.get("info", {})
            role = info.get("role")
            mid = info.get("id")
            pid = info.get("parentID") or info.get("parentId")
            text = ""
            for p in m.get("parts", []):
                if p.get("type") == "text":
                    text = p.get("text", "")[:120].replace("\n", " ")
                    break
            print(role, mid, "parent", pid, "text", text)

    if not args.status and not args.session:
        parser.print_help()
        return 2

    return 0


if __name__ == "__main__":
    raise SystemExit(main())
