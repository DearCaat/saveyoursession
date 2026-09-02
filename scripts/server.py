#!/usr/bin/env python3
"""Dependency-free server for agent-facing native session management."""
import json, os, sys, hashlib, shutil, tempfile, subprocess, sqlite3, uuid
from pathlib import Path
from datetime import datetime, timezone
from urllib.parse import quote

ROOT = Path(os.environ.get("SAVEYOURSESSION_ROOT", Path.home() / ".saveyoursession"))
METADATA = ROOT / "metadata"
INDEX = ROOT / "index.json"
SOURCE = ROOT / "source.json"
CONTROL = ROOT / "control.json"
INDEX_SCHEMA_VERSION = 2
CONTROL_SCHEMA_VERSION = 1
REMOTE_CONTROL_PATH = "control/exclusions.v1.json"

HARNESS_ROOTS = {
    "codex": [Path(os.environ.get("CODEX_HOME", Path.home() / ".codex")) / "sessions"],
    "claude": [Path(os.environ.get("CLAUDE_HOME", Path.home() / ".claude")) / "projects"],
    "grok-build": [Path(os.environ.get("GROK_BUILD_HOME", Path.home() / ".grok-build"))],
    "dsh": [Path(os.environ.get("DSH_HOME", Path.home() / ".dsh"))],
}

def _load():
    """Load the v2 index without collapsing entries from the old key scheme."""
    if INDEX.exists():
        try:
            data = json.loads(INDEX.read_text())
            if data.get("schema_version") == INDEX_SCHEMA_VERSION:
                data.setdefault("sessions", {})
                data.setdefault("legacy_sessions", {})
                return data
            # v1 keyed sessions as ``harness:session_id``.  Keeping them
            # separately is deliberate: a new source-aware key must never
            # silently merge two old locations that happened to share an ID.
            return {
                "schema_version": INDEX_SCHEMA_VERSION,
                "sessions": {},
                "legacy_sessions": data.get("sessions", {}),
                "migrated_from_schema": data.get("schema_version", 1),
                "updated_at": data.get("updated_at"),
            }
        except (OSError, json.JSONDecodeError): pass
    return {"schema_version": INDEX_SCHEMA_VERSION, "sessions": {}, "legacy_sessions": {}, "updated_at": None}

def _save(db):
    ROOT.mkdir(parents=True, exist_ok=True)
    db["updated_at"] = datetime.now(timezone.utc).isoformat()
    tmp = INDEX.with_suffix(".tmp")
    tmp.write_text(json.dumps(db, ensure_ascii=False, indent=2))
    tmp.replace(INDEX)

def _source_identity(create=True):
    """Return the installation-specific identity used in all new remote keys."""
    try:
        data = json.loads(SOURCE.read_text(encoding="utf-8"))
        value = data.get("source_id")
        if isinstance(value, str) and value:
            return data
    except (OSError, json.JSONDecodeError):
        pass
    if not create:
        return None
    data = {
        "schema_version": 1,
        "source_id": str(uuid.uuid4()),
        "created_at": datetime.now(timezone.utc).isoformat(),
    }
    ROOT.mkdir(parents=True, exist_ok=True)
    tmp = SOURCE.with_suffix(".tmp")
    tmp.write_text(json.dumps(data, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    tmp.replace(SOURCE)
    return data

def _load_control():
    """Load local exclusion state; remote control is intentionally read-only-plan only."""
    default = {
        "schema_version": CONTROL_SCHEMA_VERSION,
        "exclusions": {},
        "remote_control": {
            "path": REMOTE_CONTROL_PATH,
            "read_status": "not_implemented",
            "write_status": "not_implemented",
        },
    }
    try:
        data = json.loads(CONTROL.read_text(encoding="utf-8"))
        if isinstance(data, dict):
            default.update(data)
            default["exclusions"] = data.get("exclusions", {}) if isinstance(data.get("exclusions", {}), dict) else {}
    except (OSError, json.JSONDecodeError):
        pass
    return default

def _save_control(control):
    """Persist control state atomically; control is metadata only."""
    CONTROL.parent.mkdir(parents=True, exist_ok=True)
    tmp = CONTROL.with_suffix(".tmp")
    tmp.write_text(json.dumps(control, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    tmp.replace(CONTROL)

def _entry_fingerprint(entry, live=True):
    """Return a deterministic fingerprint for the native transcript set.

    Cleanup tags pin this value.  When *live* is true, existing native files
    are hashed again so a transcript changed after tagging is detected even
    if the scheduled sync has not run yet.
    """
    records = []
    for record in sorted(entry.get("files") or [], key=lambda item: str(item.get("native_path", ""))):
        native_path = str(record.get("native_path", ""))
        digest = record.get("content_hash", "")
        size = record.get("size")
        if live and native_path:
            try:
                path = Path(native_path)
                if path.exists() and path.is_file():
                    hasher = hashlib.sha256()
                    with path.open("rb") as handle:
                        for chunk in iter(lambda: handle.read(1024 * 1024), b""):
                            hasher.update(chunk)
                    digest = hasher.hexdigest()
                    size = path.stat().st_size
                else:
                    digest = "missing"
                    size = None
            except OSError:
                digest = "unreadable"
                size = None
        records.append({"native_path": native_path, "content_hash": digest or "", "size": size})
    payload = json.dumps(records, ensure_ascii=False, sort_keys=True, separators=(",", ":")).encode("utf-8")
    return hashlib.sha256(payload).hexdigest()

def _is_excluded(session_key, control=None):
    record = (control or _load_control()).get("exclusions", {}).get(session_key)
    return isinstance(record, dict) and record.get("status") == "excluded"

def tag_cleanup(session_key, reason="cleanup candidate"):
    """Write a reversible cleanup tag; deletion requires a later explicit gate."""
    db=_load(); entry=db.get("sessions",{}).get(session_key)
    if not entry: raise ValueError("session not found")
    if entry.get("index_status", "indexed") != "indexed":
        raise ValueError("session is discovered but not indexed; run sync first")
    control=_load_control(); now=datetime.now(timezone.utc).isoformat()
    control.setdefault("cleanup",{})[session_key]={
        "status":"tagged", "cleanup_tagged_at":now, "tag_reason":reason,
        "updated_at":entry.get("updated_at"),
        "fingerprint":_entry_fingerprint(entry, live=True),
    }
    _save_control(control)
    return control["cleanup"][session_key]

def cleanup_gate(session_key, now=None, minimum_age_hours=72):
    control=_load_control(); tag=(control.get("cleanup") or {}).get(session_key)
    if not tag: return {"allowed":False,"status":"untagged"}
    entry=_load().get("sessions",{}).get(session_key,{})
    tagged=_parse_timestamp(tag.get("cleanup_tagged_at")); current=now or datetime.now(timezone.utc)
    current_fingerprint = _entry_fingerprint(entry, live=True)
    tagged_fingerprint = tag.get("fingerprint")
    if not tagged_fingerprint and "content_hashes" in tag:
        # Upgrade tags produced by 0.1.4 while retaining their original tag
        # time.  A mismatch is treated as an update and requires re-review.
        legacy_hashes = sorted(f.get("content_hash", "") for f in entry.get("files", []))
        if legacy_hashes == sorted(tag.get("content_hashes") or []):
            tag["fingerprint"] = current_fingerprint
            tagged_fingerprint = current_fingerprint
            _save_control(control)
        else:
            tagged_fingerprint = ""
    changed = (not tagged_fingerprint or current_fingerprint != tagged_fingerprint or
               entry.get("updated_at") != tag.get("updated_at"))
    if changed:
        tag.update({"status":"re-review","re_review_reason":"session updated after cleanup tag"}); _save_control(control); return {"allowed":False,**tag}
    age=(current-tagged).total_seconds()/3600 if tagged else 0
    allowed = tag.get("status") == "tagged" and bool(tagged) and age >= minimum_age_hours
    return {"allowed":allowed,"status":tag.get("status"),"hours_remaining":max(0,minimum_age_hours-age),**tag}

def _files(root):
    if not root.exists(): return []
    return [p for p in root.rglob("*") if p.is_file() and p.stat().st_size <= 512 * 1024 * 1024]

def _session_id(harness, path):
    # Native IDs are retained where discoverable; otherwise use a stable path ID.
    if harness == "codex":
        # Codex rollout filenames contain a timestamp and a UUID, but the
        # SessionEnd hook supplies the native UUID.  Prefer the current
        # rollout's ``id`` from session_meta; older files may only expose
        # ``session_id`` and still need the compatibility fallback.
        try:
            with path.open("r", encoding="utf-8", errors="replace") as handle:
                first = json.loads(handle.readline())
            payload = first.get("payload", {}) if isinstance(first, dict) else {}
            if first.get("type") == "session_meta" and isinstance(payload, dict):
                native_id = payload.get("id") or payload.get("session_id")
                if native_id:
                    return str(native_id)
        except (OSError, json.JSONDecodeError):
            pass
    if harness == "grok-build":
        # Grok stores summary.json/updates.jsonl inside .../<session-id>/.
        # Keep the session directory name instead of collapsing every file to
        # the same stem ("summary" or "updates").
        return path.parent.name
    stem = path.stem
    return stem or hashlib.sha256(str(path).encode()).hexdigest()[:16]

def _native_locator(harness, path, root):
    """Return the native artifact that identifies this session within one source.

    Grok has multiple native files per session, so its directory—not each file—is
    the locator.  Other adapters currently expose one native transcript per
    session and use that file path.  The locator is only hashed; it is not
    uploaded as a separate copy of the transcript.
    """
    locator = path.parent if harness == "grok-build" else path
    try:
        return str(locator.relative_to(root))
    except ValueError:
        return str(locator.resolve())

def _locator_hash(harness, path, root):
    locator = _native_locator(harness, path, root)
    return hashlib.sha256(locator.encode("utf-8")).hexdigest()[:24]

def _session_key(source_id, harness, session_id, locator_hash):
    return ":".join(("v1", source_id, harness, session_id, locator_hash))

def _remote_session_prefix(source_id, harness, session_id, locator_hash):
    # Quote each component so unexpected native IDs cannot escape its object
    # prefix.  The readable harness and source identity remain visible.
    parts = ("v1", source_id, harness, session_id, locator_hash)
    return "/".join(quote(str(part), safe="-_.") for part in parts)

def discover(harness=None):
    source_id = _source_identity()["source_id"]
    indexed_sessions = _load().get("sessions", {})
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
                locator_hash = _locator_hash(h, p, root)
                session_key = _session_key(source_id, h, sid, locator_hash)
                out.append({"source_id": source_id, "harness": h, "session_id": sid, "path": str(p),
                            "native_locator": _native_locator(h, p, root),
                            "locator_hash": locator_hash,
                            "session_key": session_key,
                            # Discovery is read-only.  An artifact can exist
                            # natively before its first sync; expose that
                            # condition instead of implying it is indexed or
                            # remotely available.
                            "index_status": "indexed" if session_key in indexed_sessions else "discovered-unindexed",
                            "indexed": session_key in indexed_sessions,
                            "created_at": datetime.fromtimestamp(st.st_ctime, timezone.utc).isoformat(),
                            "updated_at": datetime.fromtimestamp(st.st_mtime, timezone.utc).isoformat(),
                            "size": st.st_size})
    return sorted(out, key=lambda x: x["updated_at"], reverse=True)

def _empty_metadata(harness):
    if harness == "codex":
        return {"title": "", "preview": "", "first_user_message": "", "created_at": "", "updated_at": ""}
    if harness == "grok-build":
        return {"title": "", "summary": "", "created_at": "", "updated_at": ""}
    if harness == "claude":
        return {"title": "", "created_at": "", "updated_at": ""}
    return {}

def _iso_timestamp(value):
    if value is None or value == "":
        return ""
    if isinstance(value, str):
        try:
            value = float(value)
        except ValueError:
            return value
    if isinstance(value, (int, float)):
        # Codex has used both seconds and millisecond timestamps in state DBs.
        if abs(value) > 100_000_000_000:
            value /= 1000
        try:
            return datetime.fromtimestamp(value, timezone.utc).isoformat()
        except (OverflowError, OSError, ValueError):
            return str(value)
    return str(value)

def _codex_metadata(path):
    metadata = _empty_metadata("codex")
    codex_home = Path(os.environ.get("CODEX_HOME", Path.home() / ".codex"))
    # State databases are local indexes; open read-only and tolerate schema/version
    # differences so a missing title never prevents the native transcript sync.
    for state_db in sorted(codex_home.glob("state_*.sqlite")):
        try:
            uri = "file:" + str(state_db).replace("?", "%3F") + "?mode=ro"
            with sqlite3.connect(uri, uri=True) as conn:
                columns = {row[1] for row in conn.execute("PRAGMA table_info(threads)")}
                time_columns = [name for name in ("created_at_ms", "updated_at_ms", "created_at", "updated_at") if name in columns]
                selected = ["title", "preview", "first_user_message", *time_columns]
                row = conn.execute(
                    f"SELECT {', '.join(selected)} FROM threads "
                    "WHERE rollout_path = ? LIMIT 1", (str(path),)
                ).fetchone()
            if row:
                values = dict(zip(selected, row))
                for key in ("title", "preview", "first_user_message"):
                    metadata[key] = str(values.get(key) or "")
                for key in ("created_at", "updated_at"):
                    metadata[key] = _iso_timestamp(values.get(f"{key}_ms", values.get(key)))
                return metadata
        except (OSError, sqlite3.Error):
            continue
    return metadata

def _claude_metadata(path):
    metadata = _empty_metadata("claude")
    try:
        with path.open("r", encoding="utf-8", errors="replace") as handle:
            for line in handle:
                try:
                    record = json.loads(line)
                except json.JSONDecodeError:
                    continue
                if record.get("type") == "ai-title" and record.get("aiTitle") is not None:
                    metadata["title"] = str(record["aiTitle"])
                    break
    except OSError:
        pass
    return metadata

def _grok_metadata(path):
    metadata = _empty_metadata("grok-build")
    summary_path = path.parent / "summary.json"
    try:
        data = json.loads(summary_path.read_text(encoding="utf-8"))
        if isinstance(data, dict):
            for key in ("title", "summary"):
                if data.get(key) is not None:
                    metadata[key] = str(data[key])
    except (OSError, json.JSONDecodeError):
        pass
    return metadata

def _extract_metadata(harness, path):
    if harness == "codex":
        return _codex_metadata(path)
    if harness == "claude":
        return _claude_metadata(path)
    if harness == "grok-build":
        return _grok_metadata(path)
    return _empty_metadata(harness)

def _has_transcript_content(harness, path):
    """Structural upload guard: ignore empty/metadata-only native artifacts.

    This intentionally does not classify test or probe conversations; any
    actual user/assistant message is uploaded regardless of semantic value.
    """
    try:
        if harness == "grok-build" and path.name == "summary.json":
            return False
        if path.stat().st_size == 0:
            return False
        if path.suffix != ".jsonl":
            return True
        for line in path.open("r", encoding="utf-8", errors="replace"):
            try:
                record = json.loads(line)
            except json.JSONDecodeError:
                continue
            payload = record.get("payload", record)
            role = payload.get("role") if isinstance(payload, dict) else None
            if not role and isinstance(payload, dict) and isinstance(payload.get("message"), dict):
                role = payload["message"].get("role")
            if role in ("user", "assistant"):
                return True
        return False
    except OSError:
        return False

def _codex_child_map():
    """Return child-thread ID -> parent-thread ID edges from Codex state."""
    edges={}
    codex_home=Path(os.environ.get("CODEX_HOME", Path.home()/".codex"))
    for db in codex_home.glob("state_*.sqlite"):
        try:
            with sqlite3.connect(f"file:{db}?mode=ro", uri=True) as conn:
                for parent, child in conn.execute("SELECT parent_thread_id, child_thread_id FROM thread_spawn_edges"):
                    edges[str(child)] = str(parent)
        except Exception: continue
    return edges


def _codex_child_ids():
    return set(_codex_child_map())
def _remote_object_path(remote_prefix, filename):
    """Path relative to the configured HF bucket, never a local archive path."""
    return f"{remote_prefix}/{quote(filename, safe='-_.')}"

def _write_metadata(source_id, harness, session_id, locator_hash, remote_prefix, metadata):
    """Keep only lightweight metadata locally; native transcripts stay in-place."""
    metadata_path = METADATA / source_id / harness / session_id / locator_hash / "metadata.json"
    metadata_path.parent.mkdir(parents=True, exist_ok=True)
    serialized = json.dumps(metadata, ensure_ascii=False, indent=2) + "\n"
    encoded = serialized.encode("utf-8")
    previous = metadata_path.read_bytes() if metadata_path.exists() else None
    if previous != encoded:
        metadata_path.write_bytes(encoded)
    # Always let the remote backend compare it.  A local equality check cannot
    # prove that a previously uploaded object still exists remotely.
    return metadata_path, _upload_hf(metadata_path, remote_prefix)

def sync(harness=None, session_id=None, locator_hash=None):
    db = _load()
    source = _source_identity()
    source_id = source["source_id"]
    control = _load_control()
    grouped = {}; child_ids = _codex_child_ids()
    for item in discover(harness):
        if (not session_id or item["session_id"] == session_id) and (not locator_hash or item["locator_hash"] == locator_hash):
            if item["harness"] == "codex" and item["session_id"] in child_ids: continue
            if not _has_transcript_content(item["harness"], Path(item["path"])):
                continue
            # The locator is part of the identity.  Never group two native
            # paths merely because a harness reused/collided a session ID.
            key = (item["harness"], item["session_id"], item["locator_hash"])
            grouped.setdefault(key, []).append(item)

    uploaded = skipped = pending = excluded = 0
    errors = []
    for (item_harness, item_session_id, locator_hash), items in grouped.items():
        session_key = _session_key(source_id, item_harness, item_session_id, locator_hash)
        remote_prefix = _remote_session_prefix(source_id, item_harness, item_session_id, locator_hash)
        previous = db["sessions"].get(session_key, {})
        old_files = {f.get("native_path"): f for f in previous.get("files", [])}
        files = dict(old_files)
        created_values, updated_values = [], []
        primary = max(items, key=lambda value: value["updated_at"])

        if _is_excluded(session_key, control):
            excluded += len(items)
            db["sessions"][session_key] = {
                **previous,
                "schema_version": INDEX_SCHEMA_VERSION,
                "session_key": session_key,
                "source_id": source_id,
                "harness": item_harness,
                "session_id": item_session_id,
                "locator_hash": locator_hash,
                "index_status": "indexed",
                "native_locator": primary["native_locator"],
                "path": primary["path"],
                "created_at": min(item["created_at"] for item in items),
                "updated_at": max(item["updated_at"] for item in items),
                "policy": {"status": "excluded", "control_path": str(CONTROL)},
            }
            continue

        # Upload from the original harness location.  The temporary staging
        # directory inside _upload_hf is only required by ``hf sync`` and is
        # removed immediately; no raw copy is retained under ROOT.
        for item in items:
            native_path = Path(item["path"])
            raw = native_path.read_bytes()
            result = _upload_hf(native_path, remote_prefix)
            if result.get("uploaded"):
                uploaded += 1
            elif result.get("skipped"):
                skipped += 1
            else:
                pending += 1
                errors.append({"path": str(native_path), "reason": result.get("reason", "upload failed")})
            remote_path = _remote_object_path(remote_prefix, native_path.name)
            files[str(native_path)] = {
                "native_path": str(native_path),
                "remote_path": remote_path,
                "content_hash": hashlib.sha256(raw).hexdigest(),
                "size": len(raw),
                "synced_at": datetime.now(timezone.utc).isoformat(),
                "upload": result,
            }
            created_values.append(item["created_at"])
            updated_values.append(item["updated_at"])

        metadata = _extract_metadata(item_harness, Path(primary["path"]))
        metadata["created_at"] = metadata.get("created_at") or min(created_values)
        metadata["updated_at"] = metadata.get("updated_at") or max(updated_values)
        metadata_path, metadata_upload = _write_metadata(
            source_id, item_harness, item_session_id, locator_hash, remote_prefix, metadata
        )
        if not metadata_upload.get("uploaded") and not metadata_upload.get("skipped"):
            errors.append({"path": str(metadata_path), "reason": metadata_upload.get("reason", "metadata upload failed")})
        entry = {
            "schema_version": INDEX_SCHEMA_VERSION,
            "session_key": session_key,
            "source_id": source_id,
            "harness": item_harness,
            "session_id": item_session_id,
            "locator_hash": locator_hash,
            "index_status": "indexed",
            "native_locator": primary["native_locator"],
            # Kept for compatibility with existing callers.  It is the
            # original native path, never a local archive copy.
            "path": primary["path"],
            "remote_path": next(iter(files.values()))["remote_path"],
            "files": list(files.values()),
            "metadata_path": str(metadata_path),
            "metadata_remote_path": _remote_object_path(remote_prefix, "metadata.json"),
            "metadata": metadata,
            "created_at": metadata["created_at"],
            "updated_at": metadata["updated_at"],
            "synced_at": datetime.now(timezone.utc).isoformat(),
        }
        db["sessions"][session_key] = entry
    _save(db)
    return {
        "synced_files": uploaded,
        "skipped_files": skipped,
        "pending_files": pending,
        "excluded_files": excluded,
        "sessions": len(db["sessions"]),
        "legacy_sessions": len(db.get("legacy_sessions", {})),
        "source_id": source_id,
        "metadata": str(METADATA),
        "errors": errors,
    }

def _hf_settings():
    # An explicitly empty HF_BUCKET_URI disables the bucket rather than
    # silently falling back to the default.  This makes offline errors clear.
    bucket = os.environ.get("HF_BUCKET_URI")
    if bucket is None:
        bucket = "hf://buckets/Dearcat/agent-session"
    repo = os.environ.get("HF_DATASET_REPO", "Dearcat/agent_session")
    token = os.environ.get("HF_TOKEN") or _read_token_file()
    return bucket.rstrip("/"), repo, token

def _upload_hf(path, remote_prefix):
    """Mirror one native file to HF without retaining a local transcript copy."""
    bucket, repo, token = _hf_settings()
    if not token:
        return {"uploaded": False, "reason": "HF_TOKEN is not configured"}
    remote_path = _remote_object_path(remote_prefix, path.name)
    if bucket:
        try:
            with tempfile.TemporaryDirectory(prefix="saveyoursession-hf-") as tmp:
                staged = Path(tmp) / path.name
                shutil.copy2(path, staged)
                target = f"{bucket.rstrip('/')}/{remote_prefix}"
                env = os.environ.copy(); env["HF_TOKEN"] = token
                result = subprocess.run(["hf", "sync", tmp, target, "--format", "agent"], env=env, stdout=subprocess.PIPE, stderr=subprocess.PIPE, text=True, timeout=120, check=False)
                if result.returncode == 0:
                    text = result.stdout + result.stderr
                    skipped = "Uploads: 0" in text and "Skips:" in text
                    return {"uploaded": not skipped, "skipped": skipped, "backend": "hf-storage-bucket", "remote_path": remote_path}
                return {"uploaded": False, "reason": result.stderr.strip() or result.stdout.strip(), "backend": "hf-storage-bucket", "remote_path": remote_path}
        except (OSError, subprocess.SubprocessError) as exc:
            return {"uploaded": False, "reason": str(exc), "backend": "hf-storage-bucket", "remote_path": remote_path}
    if not repo:
        return {"uploaded": False, "reason": "HF_BUCKET_URI or HF_DATASET_REPO is not configured"}
    try:
        from huggingface_hub import HfApi
        raw = path.read_bytes()
        infos = HfApi(token=token).get_paths_info(repo_id=repo, paths=[remote_path], repo_type="dataset")
        if infos:
            info = infos[0]
            remote_sha = getattr(getattr(info, "lfs", None), "sha256", None)
            if remote_sha == hashlib.sha256(raw).hexdigest():
                return {"uploaded": False, "skipped": True, "reason": "remote content unchanged"}
            blob_sha = hashlib.sha1(b"blob " + str(len(raw)).encode() + b"\0" + raw).hexdigest()
            if getattr(info, "blob_id", None) == blob_sha:
                return {"uploaded": False, "skipped": True, "reason": "remote content unchanged"}
        HfApi(token=token).upload_file(path_or_fileobj=str(path),
            path_in_repo=remote_path,
            repo_id=repo, repo_type="dataset", commit_message="saveyoursession sync")
        return {"uploaded": True, "remote_path": remote_path}
    except Exception as exc:
        # The original harness file remains authoritative; a later scheduled
        # scan can retry without needing an archive copy.
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
    db = _load()
    # Legacy records stay searchable but are never conflated with v2 records.
    for item in [*db.get("sessions", {}).values(), *db.get("legacy_sessions", {}).values()]:
        if q in json.dumps(item, ensure_ascii=False).lower(): hits.append(item)
        else:
            try:
                if q in Path(item["path"]).read_text(errors="ignore").lower(): hits.append(item)
            except OSError: pass
    return hits[:100]

def _parse_timestamp(value):
    if not isinstance(value, str) or not value:
        return None
    try:
        parsed = datetime.fromisoformat(value.replace("Z", "+00:00"))
        return parsed if parsed.tzinfo else parsed.replace(tzinfo=timezone.utc)
    except ValueError:
        return None

def _entry_was_uploaded(entry):
    """Only nominate records whose index has successful raw-object outcomes."""
    files = entry.get("files") or []
    if not files:
        return False
    for item in files:
        outcome = item.get("upload") or {}
        if not item.get("remote_path") or not (outcome.get("uploaded") or outcome.get("skipped")):
            return False
    return bool(entry.get("metadata_remote_path"))


def _logical_session_groups(entries, child_map):
    """Group indexed entries into logical parents and Codex children.

    ``thread_spawn_edges`` stores native IDs, while the index is keyed by a
    source-aware session key.  Resolve the edge by native ID and retain the
    parent entry as the group representative; this keeps child transcripts
    available as evidence without counting them as separate sessions.
    """
    groups = {}
    for entry in entries:
        sid = str(entry.get("session_id") or "")
        harness = entry.get("harness")
        root = sid
        if harness == "codex":
            seen = set()
            while root in child_map and root not in seen:
                seen.add(root)
                root = str(child_map[root])
        # Non-Codex IDs are already logical roots. Include harness/source in
        # the key to avoid accidental cross-harness ID collisions.
        group_key = (entry.get("source_id"), harness, root)
        groups.setdefault(group_key, []).append(entry)
    result = []
    for (source_id, harness, root), members in groups.items():
        parent = next((e for e in members if str(e.get("session_id")) == root), None)
        if parent is None:
            # If a parent transcript is absent, retain the first entry as a
            # visible orphan rather than silently discarding data.
            parent = max(members, key=lambda e: e.get("updated_at") or "")
        children = [e for e in members if e is not parent]
        result.append((parent, children))
    return result

def _agent_recap_not_script(*_args, **_kwargs):
    """Compatibility guard: semantic recap is performed by the agent skill."""
    raise RuntimeError("recap must be performed by the Terra recap skill; scripts expose only mechanical session data and cleanup gates")
    """
    source = _source_identity()
    control = _load_control()
    current = now or datetime.now(timezone.utc)
    # Count discovered Codex children separately so reports explain why the
    # visible logical-session total differs from raw transcript-file counts.
    codex_child_ids = _codex_child_ids()
    codex_child_map = _codex_child_map()
    child_session_count = sum(
        1 for item in discover()
        if item.get("harness") == "codex" and item.get("session_id") in codex_child_ids
    )
    cutoff = current.timestamp() - (minimum_age_hours * 3600)
    db = _load()
    logical_groups = _logical_session_groups(list(db.get("sessions", {}).values()), codex_child_map)
    candidates = []
    for entry, children in logical_groups:
        session_key = entry.get("session_key")
        # A logical session is eligible only when its newest parent/child
        # transcript is older than the cutoff.  This avoids tagging a parent
        # while an indexed child is still changing.
        latest_updated = max(
            (_parse_timestamp(item.get("updated_at")) for item in [entry, *children]),
            default=None,
        )
        updated = latest_updated
        if updated is None or updated.timestamp() > cutoff:
            continue
        if entry.get("policy", {}).get("status") == "excluded" or _is_excluded(session_key, control):
            continue
        if not _entry_was_uploaded(entry) or any(not _entry_was_uploaded(child) for child in children):
            continue
        remote_objects = [record["remote_path"] for record in entry.get("files", []) if record.get("remote_path")]
        if entry.get("metadata_remote_path"):
            remote_objects.append(entry["metadata_remote_path"])
        children_evidence = []
        for child in children:
            remote_objects.extend(record["remote_path"] for record in child.get("files", []) if record.get("remote_path"))
            if child.get("metadata_remote_path"):
                remote_objects.append(child["metadata_remote_path"])
            if child.get("path"):
                children_evidence.append({
                    "session_id": child.get("session_id"),
                    "session_key": child.get("session_key"),
                    "evidence": recap_evidence(child["path"]),
                })
        candidates.append({
            "source_id": entry.get("source_id", source["source_id"]),
            "session_key": session_key,
            "harness": entry.get("harness"),
            "native_session_id": entry.get("session_id"),
            "locator_hash": entry.get("locator_hash"),
            "created_at": entry.get("created_at"),
            "updated_at": entry.get("updated_at"),
            "child_count": len(children),
            "children": children_evidence,
            "remote_objects": sorted(set(remote_objects)),
            "suggested_action": "review",
            "available_actions": {
                "keep": {"remote_action": "keep"},
                "exclude": {
                    "control_action": "write exclusion for session_key",
                    "remote_action": "delete remote_objects",
                },
            },
            # Deterministic evidence is prepared here; semantic title/recap
            # and keep/cleanup decision are deliberately left to the review
            # agent.  Missing native files remain reviewable without guessing.
            "review_evidence": recap_evidence(entry["path"]) if entry.get("path") else {
                "evidence_type": "native-transcript-unavailable",
                "message_count": 0,
                "user_messages": 0,
                "assistant_messages": 0,
                "messages": [],
            },
        })
    report = {
        "schema_version": 1,
        "dry_run": True,
        "generated_at": current.isoformat(),
        "minimum_age_hours": minimum_age_hours,
        "cutoff_at": datetime.fromtimestamp(cutoff, timezone.utc).isoformat(),
        "source_id": source["source_id"],
        "candidate_count": len(candidates),
        "logical_session_count": len(logical_groups),
        "indexed_session_count": len(db.get("sessions", {})),
        "child_session_count": child_session_count,
        "scan_started_at": current.isoformat(),
        "review_contract": {
            "reviewer": "Terra agent (or explicitly selected review agent)",
            "input_filter": [
                "include native user/assistant messages only",
                "exclude harness/system injection and recommended plugins",
                "exclude environment context and local-command-caveat",
                "exclude exact test echoes such as Reply with exactly OK.",
            ],
            "required_output": ["title", "recap", "decision", "reason", "evidence"],
            "decision_values": ["keep", "cleanup-candidate", "uncertain"],
            "codex_children": "fold into parent session; do not count as independent logical sessions",
            "cleanup_policy": "tag first, wait 72 hours, re-review if transcript fingerprint changes; user confirmation required before deletion",
        },
        "legacy_session_count": len(db.get("legacy_sessions", {})),
        "legacy_sessions_not_reviewed": bool(db.get("legacy_sessions")),
        "candidates": candidates,
        "control": {
            "local_path": str(CONTROL),
            "remote_path": REMOTE_CONTROL_PATH,
            "remote_writes_performed": False,
            "remote_deletes_performed": False,
        },
    }
    report_dir = METADATA / "recap"
    report_dir.mkdir(parents=True, exist_ok=True)
    stamp = current.strftime("%Y%m%dT%H%M%SZ")
    report_path = report_dir / f"recap-dry-run-{stamp}.json"
    report["report_path"] = str(report_path)
    report_path.write_text(json.dumps(report, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    return report
    """

def _download_session(remote_prefix, destination):
    """Download one remote session directory into a short-lived staging area."""
    bucket, repo, token = _hf_settings()
    if not token:
        raise RuntimeError("cannot restore: HF_TOKEN is not configured")
    if bucket:
        source = f"{bucket}/{remote_prefix}"
        env = os.environ.copy(); env["HF_TOKEN"] = token
        try:
            result = subprocess.run(
                ["hf", "sync", source, str(destination), "--format", "agent"],
                env=env, stdout=subprocess.PIPE, stderr=subprocess.PIPE,
                text=True, timeout=120, check=False,
            )
        except (OSError, subprocess.SubprocessError) as exc:
            raise RuntimeError(f"cannot restore from HF Storage Bucket: {exc}") from exc
        if result.returncode:
            detail = result.stderr.strip() or result.stdout.strip()
            raise RuntimeError(f"cannot restore from HF Storage Bucket: {detail}")
        return
    if not repo:
        raise RuntimeError("cannot restore: HF_BUCKET_URI or HF_DATASET_REPO is not configured")
    try:
        from huggingface_hub import snapshot_download
        snapshot_download(
            repo_id=repo, repo_type="dataset", token=token,
            allow_patterns=f"{remote_prefix}/*", local_dir=str(destination),
        )
    except Exception as exc:
        raise RuntimeError(f"cannot restore from HF Dataset: {exc}") from exc

def _staged_remote_file(staging, remote_path):
    """Support both hf sync's prefix-relative and nested download layouts."""
    name = Path(remote_path).name
    direct = staging / name
    if direct.exists():
        return direct
    nested = staging / remote_path
    if nested.exists():
        return nested
    matches = list(staging.rglob(name))
    return matches[0] if len(matches) == 1 else None

def _find_session(harness, session_id):
    """Resolve old CLI arguments only when exactly one v2 record matches."""
    matches = [
        item for item in _load().get("sessions", {}).values()
        if item.get("harness") == harness and item.get("session_id") == session_id
    ]
    if not matches:
        raise ValueError("session not found; run sync first")
    if len(matches) != 1:
        raise ValueError("session ID is ambiguous across native locations; use the session_key-aware API")
    return matches[0]

def session_status(harness, session_id):
    matches = [
        item for item in _load().get("sessions", {}).values()
        if item.get("harness") == harness and item.get("session_id") == session_id
    ]
    if len(matches) == 1:
        return matches[0]
    if len(matches) > 1:
        return {"found": True, "ambiguous": True, "matches": matches}
    legacy = _load().get("legacy_sessions", {}).get(f"{harness}:{session_id}")
    return legacy or {"found": False}

def restore(harness, session_id, target_root=None, session_key=None):
    item = _load().get("sessions", {}).get(session_key) if session_key else _find_session(harness, session_id)
    if item is None:
        raise ValueError("session not found; run sync first")
    if item.get("harness") != harness:
        raise ValueError("session belongs to a different harness")
    files = item.get("files") or [{
        "native_path": item.get("path", ""),
        "remote_path": item.get("remote_path", ""),
    }]
    if not all(record.get("remote_path") for record in files):
        raise ValueError("session has no remote object paths; sync it again before restore")

    restored, skipped, missing = [], [], []
    with tempfile.TemporaryDirectory(prefix="saveyoursession-restore-") as tmp:
        staging = Path(tmp)
        remote_prefix = str(Path(files[0]["remote_path"]).parent).replace("\\", "/")
        _download_session(remote_prefix, staging)
        for record in files:
            source = _staged_remote_file(staging, record["remote_path"])
            if source is None:
                missing.append(record["remote_path"])
                continue
            target = Path(target_root) if target_root else Path(record["native_path"]).parent
            target.mkdir(parents=True, exist_ok=True)
            destination = target / Path(record["native_path"]).name
            # The normal restore target is the live harness directory.  Do not
            # overwrite it accidentally; an explicit target root is an opt-in
            # to replacement behavior.
            if destination.exists() and target_root is None:
                skipped.append(str(destination))
                continue
            shutil.copy2(source, destination)
            restored.append(str(destination))
    if missing:
        raise RuntimeError("remote session is incomplete: " + ", ".join(missing))
    return {
        "restored": restored,
        "skipped_existing": skipped,
        "harness": harness,
        "session_id": session_id,
    }

TOOLS = {
 "list_sessions": ({"type":"object", "properties":{"harness":{"type":"string"},"limit":{"type":"integer"}}}, "List native sessions across harnesses."),
 "sync_all": ({"type":"object"}, "Scan and sync native sessions from all configured harnesses."),
 "sync_session": ({"type":"object", "properties":{"harness":{"type":"string"},"session_id":{"type":"string"},"locator_hash":{"type":"string"}},"required":["harness","session_id"]}, "Sync one native session; locator_hash disambiguates duplicate native IDs."),
 "search_sessions": ({"type":"object", "properties":{"query":{"type":"string"}},"required":["query"]}, "Search the cross-harness session index and local content."),
 "session_status": ({"type":"object", "properties":{"harness":{"type":"string"},"session_id":{"type":"string"}},"required":["harness","session_id"]}, "Inspect sync status for one session."),
 "restore_session": ({"type":"object", "properties":{"harness":{"type":"string"},"session_id":{"type":"string"},"session_key":{"type":"string"},"target_root":{"type":"string"}},"required":["harness","session_id"]}, "Restore a remote native session into its matching harness directory; session_key disambiguates duplicate IDs."),
}

def call(name, a):
    if name == "list_sessions": return discover(a.get("harness"))[:a.get("limit", 50)]
    if name == "sync_all": return sync()
    if name == "sync_session": return sync(a["harness"], a["session_id"], a.get("locator_hash"))
    if name == "search_sessions": return search(a["query"])
    if name == "session_status": return session_status(a["harness"], a["session_id"])
    if name == "restore_session": return restore(a["harness"], a["session_id"], a.get("target_root"), a.get("session_key"))
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
