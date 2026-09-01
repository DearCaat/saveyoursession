#!/usr/bin/env python3
"""Harness-neutral command entry point used by native harness plugins."""
import argparse, json, os, sys
from pathlib import Path
sys.path.insert(0, str(Path(__file__).parent))
import server

def main():
    p = argparse.ArgumentParser(prog="saveyoursession")
    sub = p.add_subparsers(dest="command", required=True)
    q = sub.add_parser("list"); q.add_argument("--harness"); q.add_argument("--limit", type=int, default=50)
    q = sub.add_parser("search"); q.add_argument("query")
    q = sub.add_parser("sync"); q.add_argument("--harness"); q.add_argument("--session-id")
    q = sub.add_parser("status"); q.add_argument("harness"); q.add_argument("session_id")
    q = sub.add_parser("restore"); q.add_argument("harness"); q.add_argument("session_id"); q.add_argument("--target-root")
    a = p.parse_args()
    if a.command == "list": out = server.discover(a.harness)[:a.limit]
    elif a.command == "search": out = server.search(a.query)
    elif a.command == "sync": out = server.sync(a.harness, a.session_id)
    elif a.command == "status": out = server._load().get("sessions", {}).get(f"{a.harness}:{a.session_id}", {"found": False})
    else: out = server.restore(a.harness, a.session_id, a.target_root)
    print(json.dumps(out, ensure_ascii=False, indent=2))
if __name__ == "__main__": main()
