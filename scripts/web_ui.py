#!/usr/bin/env python3
"""Dependency-free localhost UI for logical sessions."""
import argparse, json, sys
from datetime import datetime, timezone
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path
from urllib.parse import parse_qs, urlparse
sys.path.insert(0, str(Path(__file__).resolve().parent))
import server

HOST = "127.0.0.1"
def _codex_children():
    out = {}
    for db in Path(server.HARNESS_ROOTS["codex"][0]).parent.glob("state_*.sqlite"):
        try:
            import sqlite3
            with sqlite3.connect(f"file:{db}?mode=ro", uri=True) as c:
                for parent, child, *_ in c.execute("SELECT parent_thread_id, child_thread_id FROM thread_spawn_edges"):
                    out[str(child)] = str(parent)
        except Exception: pass
    def root(child):
        seen=set()
        while child in out and child not in seen: seen.add(child); child=out[child]
        return child
    return {child: root(parent) for child,parent in out.items()}

def _codex_nicknames():
    out={}
    try:
        import sqlite3
        for db in Path(server.HARNESS_ROOTS["codex"][0]).parent.glob("state_*.sqlite"):
            with sqlite3.connect(f"file:{db}?mode=ro",uri=True) as c:
                out.update({str(i):_s(n) for i,n in c.execute("SELECT id, agent_nickname FROM threads") if n})
    except Exception: pass
    return out

def _stats(path):
    users=assistants=records=0
    try:
        for line in Path(path).open(encoding="utf-8", errors="replace"):
            records+=1
            try: r=json.loads(line)
            except json.JSONDecodeError: continue
            p=r.get("payload",r); role=p.get("role") if isinstance(p,dict) else None
            if not role and isinstance(p,dict) and isinstance(p.get("message"),dict): role=p["message"].get("role")
            if role=="user": users+=1
            elif role=="assistant": assistants+=1
    except OSError: pass
    try: size=Path(path).stat().st_size
    except OSError: size=0
    return {"record_count":records,"user_count":users,"assistant_count":assistants,"rounds":min(users,assistants),"size_bytes":size}
def _s(v): return "" if v is None else str(v).strip()

def _recap_annotations():
    found = {}
    for path in sorted((server.METADATA / "recap").glob("terra-recap-*.json")):
        try: report = json.loads(path.read_text(encoding="utf-8"))
        except (OSError, json.JSONDecodeError): continue
        for group in ("sessions", "codex_main_sessions", "codex_subagents", "claude_sessions"):
            for item in report.get(group, []) or []:
                if isinstance(item, dict) and item.get("session_id"):
                    found[(item.get("harness", "codex"), _s(item["session_id"]))] = {"recommendation": item.get("recommendation") or item.get("classification"), "reason": item.get("reason"), "summary": item.get("summary"), "report": str(path)}
    return found

def _title(meta): return _s(meta.get("title")) or _s(meta.get("first_user_message")) or _s(meta.get("preview")) or _s(meta.get("summary"))
def _summary(meta, recap=None): return _s(meta.get("first_user_message")) or _s(meta.get("preview")) or _s(meta.get("summary")) or _s((recap or {}).get("summary"))

def _low_info(harness, path, meta, title, summary):
    if title or summary: return False, ""
    if harness in ("codex", "claude"):
        try:
            for line in Path(path).read_text(encoding="utf-8", errors="replace").splitlines():
                try: record = json.loads(line)
                except json.JSONDecodeError: continue
                payload = record.get("payload", record); role = payload.get("role") if isinstance(payload, dict) else None
                if not role and isinstance(payload, dict) and isinstance(payload.get("message"), dict): role = payload["message"].get("role")
                if role in ("user", "assistant"): return False, ""
        except OSError: pass
    return True, "empty/metadata-only"

def _local(harness=None, query=""):
    q=query.lower().strip(); entries=server._load().get("sessions",{}); out={}; recaps=_recap_annotations(); children=_codex_children(); nicknames=_codex_nicknames(); pending_children={}
    for item in server.discover(harness):
        if item["harness"]=="codex" and item["session_id"] in children:
            st=_stats(item["path"]); pending_children.setdefault(children[item["session_id"]], []).append({**item,**st,"child_of":children[item["session_id"]],"nickname":nicknames.get(item["session_id"],item["session_id"])}); continue
        entry=entries.get(item["session_key"],{}); meta=dict(entry.get("metadata") or {}) or server._extract_metadata(item["harness"],Path(item["path"]))
        rec=recaps.get((item["harness"],item["session_id"])); title,summary=_title(meta),_summary(meta,rec); hidden,reason=_low_info(item["harness"],item["path"],meta,title,summary)
        st=_stats(item["path"]); obj={**item,"source":"local","title":title,"summary":summary,"metadata":meta,"hidden":hidden,"hidden_reason":reason,"entry":entry,"local_updated":item.get("updated_at"),**st,"child_of":None}
        obj["children"]=pending_children.pop(item["session_id"],[])
        obj["size_bytes"]=sum(c.get("size_bytes",0) for c in [obj]+obj["children"])
        if not q or q in json.dumps(obj,ensure_ascii=False).lower(): out[item["session_key"]]=obj
    for parent, kids in pending_children.items():
        if parent in {x.get("session_id") for x in out.values()}:
            target=next(x for x in out.values() if x.get("session_id")==parent); target.setdefault("children",[]).extend(kids); target["size_bytes"]=sum(c.get("size_bytes",0) for c in [target]+target["children"])
    return out

def _remote(harness=None, query=""):
    q=query.lower().strip(); out={}; recaps=_recap_annotations()
    children=_codex_children()
    for entry in server._load().get("sessions",{}).values():
        if harness and entry.get("harness")!=harness: continue
        if entry.get("harness")=="codex" and entry.get("session_id") in children: continue
        meta=dict(entry.get("metadata") or {}); rec=recaps.get((entry.get("harness"),_s(entry.get("session_id")))); title,summary=_title(meta),_summary(meta,rec)
        files=entry.get("files") or []; raw=[f.get("remote_path") for f in files if f.get("remote_path") and ((f.get("upload") or {}).get("uploaded") or (f.get("upload") or {}).get("skipped"))]
        obj={"source":"remote","source_id":entry.get("source_id"),"session_key":entry.get("session_key"),"harness":entry.get("harness"),"session_id":entry.get("session_id"),"native_locator":entry.get("native_locator"),"remote_path":entry.get("metadata_remote_path") or entry.get("remote_path"),"remote_objects":raw,"title":title,"summary":summary,"metadata":meta,"remote_updated":entry.get("updated_at"),"has_raw":bool(raw),"recap":rec,"entry":entry,"metadata_present":bool(entry.get("metadata_remote_path")),"raw_present":bool(raw),"raw_upload_confirmed":bool(raw),"child_of":None}
        obj.update({"size_bytes":sum(f.get("size",0) for f in files),"record_count":sum(f.get("record_count",0) for f in files)})
        obj["hidden"],obj["hidden_reason"]=(not title and not summary),("empty/metadata-only" if not title and not summary else "")
        if not q or q in json.dumps(obj,ensure_ascii=False).lower(): out[entry.get("session_key")]=obj
    return out

def _parse(v):
    try: d=datetime.fromisoformat(_s(v).replace("Z","+00:00")); return d if d.tzinfo else d.replace(tzinfo=timezone.utc)
    except (TypeError,ValueError): return None

def _logical(harness=None, query="", show_hidden=False):
    q=query.lower().strip(); local,remote=_local(harness),_remote(harness); rows=[]; hidden=0
    for key in sorted(set(local)|set(remote)):
        l,r=local.get(key),remote.get(key); base=l or r; is_hidden=bool((l or r).get("hidden")); hidden+=is_hidden
        probe = {"harness": base.get("harness"), "session_id": base.get("session_id"), "title": base.get("title", ""), "summary": base.get("summary", ""), "session_key": key}
        if q and q not in json.dumps(probe, ensure_ascii=False).lower(): continue
        if is_hidden and not show_hidden: continue
        lu,ru=_parse((l or {}).get("local_updated")),_parse((r or {}).get("remote_updated")); lh=[f.get("content_hash") for f in ((l or {}).get("entry",{}).get("files") or []) if f.get("content_hash")]; rh=[f.get("content_hash") for f in ((r or {}).get("entry",{}).get("files") or []) if f.get("content_hash")]
        if not l: status="only-remote"
        elif not r: status="only-local"
        elif lh and rh and sorted(lh)==sorted(rh): status="synced"
        elif lu and ru and lu>ru: status="local-newer"
        elif lu and ru and ru>lu: status="remote-newer"
        elif lu and ru: status="conflict"
        else: status="conflict"
        delta=(lu-ru).total_seconds() if lu and ru else None
        ch=(l or {}).get("children",[]); rows.append({"session_key":key,"source":"logical","harness":base.get("harness"),"session_id":base.get("session_id"),"source_id":base.get("source_id"),"title":base.get("title",""),"cleanup_status":server.cleanup_gate(key).get("status","untagged"),"cleanup_tagged_at":(server._load_control().get("cleanup") or {}).get(key,{}).get("cleanup_tagged_at"),"cleanup_hours_remaining":server.cleanup_gate(key).get("hours_remaining"),"summary":base.get("summary",""),"local_exists":bool(l),"remote_exists":bool(r),"index_status":(l or {}).get("index_status", "indexed" if l else "remote-only"),"local_updated":(l or {}).get("local_updated"),"remote_updated":(r or {}).get("remote_updated"),"time_delta_seconds":delta,"sync_status":status,"local_metadata_present":bool(l and l.get("metadata")),"remote_metadata_present":bool(r and r.get("metadata_present")),"raw_present":bool(r and r.get("raw_present")),"raw_upload_confirmed":bool(r and r.get("raw_upload_confirmed")),"size_bytes":(l or r).get("size_bytes",0),"record_count":(l or r).get("record_count",0),"user_count":(l or r).get("user_count",0),"assistant_count":(l or r).get("assistant_count",0),"rounds":(l or r).get("rounds",0),"child_count":len(ch),"child_total_size":sum(c.get("size_bytes",0) for c in ch),"child_record_count":sum(c.get("record_count",0) for c in ch),"child_user_count":sum(c.get("user_count",0) for c in ch),"child_assistant_count":sum(c.get("assistant_count",0) for c in ch),"children":ch,"hidden":bool(is_hidden),"hidden_reason":(l or r).get("hidden_reason",""),"local":l,"remote":r})
    return {"sessions":rows,"hidden_count":hidden,"total_count":len(rows) if show_hidden else len(rows)+hidden,"shown_count":len(rows)}

def _json(h,v,status=200):
    b=json.dumps(v,ensure_ascii=False,indent=2).encode(); h.send_response(status); h.send_header("Content-Type","application/json; charset=utf-8"); h.send_header("Content-Length",str(len(b))); h.end_headers(); h.wfile.write(b)

HTML=r'''<!doctype html><meta charset="utf-8"><title>saveyoursession</title><style>body{font:14px system-ui,sans-serif;max-width:1500px;margin:2em auto;padding:0 1em}button,input,select{padding:.4em;margin:.2em}table{border-collapse:collapse;width:100%;margin-top:1em}th,td{padding:.45em;border-bottom:1px solid #ddd;text-align:left;vertical-align:top}tr.detail{background:#f7f7f7}.badge{padding:.15em .4em;border-radius:4px;background:#eee}small{color:#666}</style><h1>saveyoursession</h1><p><small>One row per logical session (source-aware session_key). Local and Remote metadata stay separate. localhost only.</small></p><div><input id="q" placeholder="Search title, summary, ID…" oninput="load()"><select id="h" onchange="load()"><option value="">All harnesses</option><option>codex</option><option>claude</option><option>grok-build</option><option>dsh</option></select><label><input type="checkbox" id="show" onchange="load()"> Show hidden/low-info</label><button onclick="load()">Refresh</button></div><p id="msg"></p><table><thead><tr><th>Harness / ID</th><th>Title / summary</th><th>Local</th><th>Remote</th><th>Sync status</th><th>Local updated</th><th>Remote updated</th><th>Δ time</th><th>Actions</th></tr></thead><tbody id="rows"></tbody></table><script>
const q=document.getElementById('q'),h=document.getElementById('h'),show=document.getElementById('show'),msg=document.getElementById('msg'),rows=document.getElementById('rows');
function esc(s){return String(s??'').replace(/[&<>\"]/g,c=>({'&':'&amp;','<':'&lt;','>':'&gt;','\\':'&#92;','"':'&quot;'}[c]))} function key(x){return encodeURIComponent(x.session_key||'')}
async function load(){try{let p=new URLSearchParams({q:q.value,harness:h.value,show_hidden:show.checked?'1':'0'}),d=await(await fetch('/api/sessions?'+p)).json(),list=Array.isArray(d)?d:(Array.isArray(d.sessions)?d.sessions:[]);msg.textContent=`${d.shown_count??list.length} shown · ${d.hidden_count??0} hidden · ${d.total_count??list.length} total`;rows.innerHTML=list.map(x=>`<tr onclick="detail(this,'${key(x)}')"><td><b>${esc(x.harness)}</b><br><code>${esc(x.session_id)}</code><br><small>${esc(x.source_id||'')}</small></td><td><b>${esc(x.title||'—')}</b><br><small>${esc(x.summary||'—')}</small><br><small>${(x.size_bytes/1048576).toFixed(2)} MiB · records:${x.record_count||0} rounds:${x.rounds||0} u:${x.user_count||0}/a:${x.assistant_count||0} children:${x.child_count||0}</small></td><td>${x.local_exists?'exists':'—'}<br><small>${esc(x.index_status||'')}</small></td><td>${x.remote_exists?'exists':'—'}</td><td><span class="badge">${esc(x.sync_status)}</span></td><td>${esc(x.local_updated||'—')}</td><td>${esc(x.remote_updated||'—')}</td><td>${x.time_delta_seconds==null?'—':esc(Math.round(x.time_delta_seconds))+'s'}</td><td><button onclick="event.stopPropagation();meta('${key(x)}')">Details</button>${x.local_exists?`<button onclick="event.stopPropagation();syncOne('${key(x)}')">Sync</button>`:''}${x.remote_exists?`<button onclick="event.stopPropagation();restoreOne('${key(x)}')">Restore</button>`:''}</td></tr>`).join('')}catch(e){msg.textContent='UI error: '+e;rows.innerHTML='<tr><td colspan="9">JavaScript/API error; inspect browser console and server log.</td></tr>'}}
async function detail(el,k){let old=el.nextElementSibling;if(old&&old.classList.contains('detail')){old.remove();return}let d=await(await fetch('/api/session?key='+k)).json(),children=((d.local||{}).children||[]),childHtml=children.length?`<h4>Child sessions (${children.length})</h4><ul>${children.map(c=>`<li><code>${esc(c.session_id)}</code> · ${(c.size_bytes/1048576).toFixed(2)} MiB · records:${c.record_count||0} · rounds:${c.rounds||0} · u:${c.user_count||0}/a:${c.assistant_count||0}</li>`).join('')}</ul>`:'<small>No child sessions</small>',tr=document.createElement('tr');tr.className='detail';tr.innerHTML=`<td colspan="9"><b>Local metadata</b> <small>raw:${d.local?'yes':'no'} · meta:${d.local&&d.local.metadata?'yes':'no'}</small><pre>${esc(JSON.stringify((d.local||{}).metadata||null,null,2))}</pre><b>Remote metadata</b> <small>raw:${d.remote&&d.remote.raw_present?'yes':'no'} · meta:${d.remote&&d.remote.metadata_present?'yes':'no'}</small><pre>${esc(JSON.stringify((d.remote||{}).metadata||null,null,2))}</pre>${childHtml}</td>`;el.after(tr)} async function meta(k){alert(JSON.stringify(await(await fetch('/api/session?key='+k)).json(),null,2))} async function syncOne(k){let d=await(await fetch('/api/session?key='+k)).json(),x=d.local;alert(JSON.stringify(await(await fetch('/api/sync',{method:'POST',headers:{'Content-Type':'application/json'},body:JSON.stringify({session_key:x.session_key,harness:x.harness,session_id:x.session_id,locator_hash:x.locator_hash})})).json(),null,2));load()} async function restoreOne(k){let d=await(await fetch('/api/session?key='+k)).json(),x=d.remote;alert(JSON.stringify(await(await fetch('/api/restore',{method:'POST',headers:{'Content-Type':'application/json'},body:JSON.stringify({session_key:x.session_key,harness:x.harness,session_id:x.session_id})})).json(),null,2))} load();</script>'''

class Handler(BaseHTTPRequestHandler):
    def log_message(self,fmt,*args): sys.stderr.write("[saveyoursession] "+(fmt%args)+"\n")
    def do_GET(self):
        u=urlparse(self.path); p=parse_qs(u.query); h=p.get("harness",[""])[0] or None; q=p.get("q",[""])[0]
        try:
            if u.path=="/": b=HTML.encode(); self.send_response(200); self.send_header("Content-Type","text/html; charset=utf-8"); self.send_header("Content-Length",str(len(b))); self.end_headers(); self.wfile.write(b); return
            if u.path=="/api/sessions": return _json(self,_logical(h,q,p.get("show_hidden",["0"])[0] in ("1","true","yes")))
            if u.path=="/api/local": return _json(self,list(_local(h,q).values()))
            if u.path=="/api/remote": return _json(self,list(_remote(h,q).values()))
            if u.path=="/api/session":
                k=p.get("key",[""])[0]; row=next((x for x in _logical(show_hidden=True)["sessions"] if x["session_key"]==k),None)
                return _json(self,row or {"error":"session not found"},200 if row else 404)
            return _json(self,{"error":"not found"},404)
        except Exception as e: return _json(self,{"error":str(e)},500)
    def do_POST(self):
        try:
            x=json.loads(self.rfile.read(int(self.headers.get("Content-Length","0"))) or b"{}"); k=x.get("session_key"); e=server._load().get("sessions",{}).get(k,{})
            if self.path=="/api/sync": return _json(self,server.sync(x.get("harness") or e.get("harness"),x.get("session_id") or e.get("session_id"),x.get("locator_hash") or e.get("locator_hash")))
            if self.path=="/api/restore": return _json(self,server.restore(x.get("harness") or e.get("harness"),x.get("session_id") or e.get("session_id"),x.get("target_root"),k))
            if self.path=="/api/tag-cleanup": return _json(self,server.tag_cleanup(k,x.get("reason") or "cleanup candidate"))
            return _json(self,{"error":"not found"},404)
        except Exception as e: return _json(self,{"error":str(e)},400)

def main():
    p=argparse.ArgumentParser(); p.add_argument("--host",default=HOST); p.add_argument("--port",type=int,default=8765); a=p.parse_args(); s=ThreadingHTTPServer((a.host,a.port),Handler); print(f"saveyoursession UI: http://{a.host}:{a.port}",flush=True)
    try: s.serve_forever()
    except KeyboardInterrupt: pass
    finally: s.server_close()
if __name__=="__main__": main()
