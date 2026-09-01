#!/usr/bin/env python3
"""Dependency-free MCP server for agent-facing native session management."""
import json, os, sys, hashlib, shutil, tarfile, tempfile, subprocess
from pathlib import Path
from datetime import datetime, timezone

ROOT = Path(os.environ.get("SAVEYOURSESSION_ROOT", Path.home() / ".saveyoursession"))
ARCHIVE = ROOT / "archive"
INDEX = ROOT / "index.json"

HARNESS_ROOTS = {
    "codex": [Path(os.environ.get("CODEX_HOME", Path.home() / ".codex")) / "sessions"],
    "claude": [Path(os.environ.get("CLAUDE_HOME", Path.home() / ".claude")) / "projects"],
    "grok-build": [Path(os.environ.get("GROK_BUILD_HOME", Path.home() / ".grok-build"))],
    "dsh": [Path(os.environ.get("DSH_HOME", Path.home() / ".dsh"))],
}

def _load():
    if INDEX.exists():
        try: return json.loads(INDEX.read_text())
        except (OSError, json.JSONDecodeError): pass
    return {"sessions": {}, "updated_at": None}

def _save(db):
    ROOT.mkdir(parents=True, exist_ok=True)
    db["updated_at"] = datetime.now(timezone.utc).isoformat()
    tmp = INDEX.with_suffix(".tmp")
    tmp.write_text(json.dumps(db, ensure_ascii=False, indent=2))
    tmp.replace(INDEX)

def _files(root):
    if not root.exists(): return []
    return [p for p in root.rglob("*") if p.is_file() and p.stat().st_size <= 512 * 1024 * 1024]

def _session_id(harness, path):
    # Native IDs are retained where discoverable; otherwise use a stable path ID.
    if harness == "grok-build":
        # Grok stores summary.json/updates.jsonl inside .../<session-id>/.
        # Keep the session directory name instead of collapsing every file to
        # the same stem ("summary" or "updates").
        return path.parent.name
    stem = path.stem
    return stem or hashlib.sha256(str(path).encode()).hexdigest()[:16]

def discover(harness=None):
    names = [harness] if harness else list(HARNESS_ROOTS)
    out = []
    for h in names:
        if h not in HARNESS_ROOTS: continue
        for root in HARNESS_ROOTS[h]:
            for p in _files(root):
                if h == "codex" and p.suffix != ".jsonl": continue
                if h == "claude" and p.suffix != ".jsonl": continue
                if h == "grok-build" and p.name not in {"summary.json", "updates.jsonl"}: continue
                sid = _session_id(h, p)
                st = p.stat()
                out.append({"harness": h, "session_id": sid, "path": str(p),
                            "updated_at": datetime.fromtimestamp(st.st_mtime, timezone.utc).isoformat(),
                            "size": st.st_size})
    return sorted(out, key=lambda x: x["updated_at"], reverse=True)

def sync(harness=None, session_id=None):
    db = _load(); ARCHIVE.mkdir(parents=True, exist_ok=True); count = 0
    for item in discover(harness):
        if session_id and item["session_id"] != session_id: continue
        p = Path(item["path"]); raw = p.read_bytes(); digest = hashlib.sha256(raw).hexdigest()
        dest = ARCHIVE / item["harness"] / item["session_id"] / p.name
        dest.parent.mkdir(parents=True, exist_ok=True)
        previous = dest.read_bytes() if dest.exists() else b""
        if not dest.exists() or hashlib.sha256(previous).hexdigest() != digest:
            shutil.copy2(p, dest); count += 1
            _upload_hf(dest, item["harness"], item["session_id"], previous)
        item.update({"remote_path": str(dest), "content_hash": digest, "size": len(raw), "synced_at": datetime.now(timezone.utc).isoformat()})
        db["sessions"][f'{item["harness"]}:{item["session_id"]}'] = item
    _save(db); return {"synced_files": count, "sessions": len(db["sessions"]), "archive": str(ARCHIVE)}

def _upload_hf(path, harness, session_id, previous=b""):
    """Optionally mirror a newly archived file to an HF Dataset repository."""
    bucket = os.environ.get("HF_BUCKET_URI", "hf://buckets/Dearcat/agent-session")
    repo = os.environ.get("HF_DATASET_REPO", "Dearcat/agent_session")
    token = os.environ.get("HF_TOKEN") or _read_token_file()
    if not repo or not token:
        return {"uploaded": False, "reason": "HF_DATASET_REPO/HF_TOKEN not configured"}
    if bucket:
        try:
            with tempfile.TemporaryDirectory(prefix="saveyoursession-hf-") as tmp:
                staged = Path(tmp) / path.name
                shutil.copy2(path, staged)
                target = f"{bucket.rstrip('/')}/{harness}/{session_id}"
                env = os.environ.copy(); env["HF_TOKEN"] = token
                result = subprocess.run(["hf", "sync", tmp, target, "--format", "agent"], env=env, stdout=subprocess.PIPE, stderr=subprocess.PIPE, text=True, timeout=120, check=False)
                if result.returncode == 0:
                    text = result.stdout + result.stderr
                    skipped = "Uploads: 0" in text and "Skips:" in text
                    return {"uploaded": not skipped, "skipped": skipped, "backend": "hf-storage-bucket", "target": target}
                return {"uploaded": False, "reason": result.stderr.strip() or result.stdout.strip(), "backend": "hf-storage-bucket"}
        except (OSError, subprocess.SubprocessError) as exc:
            return {"uploaded": False, "reason": str(exc), "backend": "hf-storage-bucket"}
    try:
        from huggingface_hub import HfApi
        remote_path = f"{harness}/{session_id}/{path.name}"
        raw = path.read_bytes()
        upload_path = path
        base_infos = HfApi(token=token).get_paths_info(repo_id=repo, paths=[remote_path], repo_type="dataset")
        if previous and base_infos and raw.startswith(previous) and len(raw) > len(previous):
            # JSONL sessions are append-only in normal operation. Upload only
            # the new bytes; the original file remains the base segment.
            start, end = len(previous), len(raw)
            delta = path.with_name(path.name + f".append-{start}-{end}.jsonl")
            delta.write_bytes(raw[start:])
            upload_path = delta
            remote_path = f"{harness}/{session_id}/{delta.name}"
            raw = raw[start:]
        infos = HfApi(token=token).get_paths_info(repo_id=repo, paths=[remote_path], repo_type="dataset")
        if infos:
            info = infos[0]
            remote_sha = getattr(getattr(info, "lfs", None), "sha256", None)
            if remote_sha == hashlib.sha256(raw).hexdigest():
                return {"uploaded": False, "skipped": True, "reason": "remote content unchanged"}
            blob_sha = hashlib.sha1(b"blob " + str(len(raw)).encode() + b"\0" + raw).hexdigest()
            if getattr(info, "blob_id", None) == blob_sha:
                return {"uploaded": False, "skipped": True, "reason": "remote content unchanged"}
        HfApi(token=token).upload_file(path_or_fileobj=str(upload_path),
            path_in_repo=remote_path,
            repo_id=repo, repo_type="dataset", commit_message="saveyoursession sync")
        return {"uploaded": True}
    except Exception as exc:
        # Local archive remains authoritative; a later scheduled scan can retry.
        return {"uploaded": False, "reason": str(exc)}

def _read_token_file():
    local_env = Path(__file__).resolve().parents[1] / "config" / "local.env"
    try:
        for line in local_env.read_text(encoding="utf-8").splitlines():
            if line.strip().startswith("HF_TOKEN="):
                value = line.split("=", 1)[1].strip().strip('"\'')
                if value: return value
    except OSError:
        pass
    configured = os.environ.get("HF_TOKEN_FILE")
    candidates = [Path(configured)] if configured else []
    for p in candidates:
        try:
            for line in p.read_text(encoding="utf-8").splitlines():
                value = line.strip()
                if value.startswith("hf_"):
                    return value
        except OSError:
            continue
    return None

def search(query):
    q = query.lower(); hits = []
    for item in _load().get("sessions", {}).values():
        if q in json.dumps(item, ensure_ascii=False).lower(): hits.append(item)
        else:
            try:
                if q in Path(item["path"]).read_text(errors="ignore").lower(): hits.append(item)
            except OSError: pass
    return hits[:100]

def restore(harness, session_id, target_root=None):
    item = _load().get("sessions", {}).get(f"{harness}:{session_id}")
    if not item: raise ValueError("session not found; run sync_all or sync_session first")
    src = Path(item["remote_path"]); target = Path(target_root) if target_root else Path(item["path"]).parent
    target.mkdir(parents=True, exist_ok=True); dest = target / src.name; shutil.copy2(src, dest)
    return {"restored": str(dest), "harness": harness, "session_id": session_id}

TOOLS = {
 "list_sessions": ({"type":"object", "properties":{"harness":{"type":"string"},"limit":{"type":"integer"}}}, "List native sessions across harnesses."),
 "sync_all": ({"type":"object"}, "Scan and archive sessions from all configured harnesses."),
 "sync_session": ({"type":"object", "properties":{"harness":{"type":"string"},"session_id":{"type":"string"}},"required":["harness","session_id"]}, "Archive one native session."),
 "search_sessions": ({"type":"object", "properties":{"query":{"type":"string"}},"required":["query"]}, "Search the cross-harness session index and local content."),
 "session_status": ({"type":"object", "properties":{"harness":{"type":"string"},"session_id":{"type":"string"}},"required":["harness","session_id"]}, "Inspect sync status for one session."),
 "restore_session": ({"type":"object", "properties":{"harness":{"type":"string"},"session_id":{"type":"string"},"target_root":{"type":"string"}},"required":["harness","session_id"]}, "Restore an archived session into its native harness directory."),
}

def call(name, a):
    if name == "list_sessions": return discover(a.get("harness"))[:a.get("limit", 50)]
    if name == "sync_all": return sync()
    if name == "sync_session": return sync(a["harness"], a["session_id"])
    if name == "search_sessions": return search(a["query"])
    if name == "session_status": return _load().get("sessions", {}).get(f'{a["harness"]}:{a["session_id"]}', {"found": False})
    if name == "restore_session": return restore(a["harness"], a["session_id"], a.get("target_root"))
    raise ValueError("unknown tool")

def reply(i, result=None, error=None):
    out = {"jsonrpc":"2.0", "id":i, "result":result} if error is None else {"jsonrpc":"2.0", "id":i, "error":{"code":-32000,"message":str(error)}}
    sys.stdout.write(json.dumps(out, ensure_ascii=False)+"\n"); sys.stdout.flush()

def main():
    for line in sys.stdin:
        try:
            req=json.loads(line); method=req.get("method"); i=req.get("id")
            if method == "initialize": reply(i,{"protocolVersion":"2024-11-05","capabilities":{"tools":{}},"serverInfo":{"name":"saveyoursession","version":"0.1.0"}})
            elif method == "notifications/initialized": continue
            elif method == "tools/list": reply(i,{"tools":[{"name":n,"description":d,"inputSchema":s} for n,(s,d) in TOOLS.items()]})
            elif method == "tools/call":
                try: reply(i,{"content":[{"type":"text","text":json.dumps(call(req["params"]["name"],req["params"].get("arguments",{})),ensure_ascii=False,indent=2)}]})
                except Exception as e: reply(i,error=e)
            else: reply(i,error="method not supported")
        except Exception as e: reply(None,error=e)

if __name__ == "__main__":
    main()
