import asyncio
import html
import json
from pathlib import Path
import secrets
from urllib.parse import urlparse

from fastapi import APIRouter, HTTPException, Query, Request
from fastapi.responses import HTMLResponse
from sqlalchemy import select

from ..database import GraphicsInstance, Resource
from .library import document
from .schemas import GraphicsConfig


BRIDGE = r'''<!doctype html><html><head><meta charset="utf-8"><style>
html,body{margin:0;background:transparent!important;overflow:hidden;color:white;font-family:Arial,sans-serif}#overlay{position:absolute;inset:0}iframe{border:0;width:100vw;height:100vh;background:transparent}#card{position:absolute;bottom:7%;left:5%;padding:22px 32px;background:var(--background,#111d);border-left:6px solid var(--accent,#4a9eff);font-size:36px;white-space:pre-line}#sub{font-size:23px;opacity:.85;margin-top:9px}.logo #card{left:auto;right:4%;top:5%;bottom:auto;background:transparent;border:0;font-weight:bold;font-size:32px}.countdown #card{font-variant-numeric:tabular-nums}#offline{display:none}
</style></head><body><div id="overlay"><div id="card"><div id="title"></div><div id="sub"></div></div></div><script>
const config=CONFIG, overlay=document.getElementById('overlay');document.body.className=config.layout;
for(const [key,value] of Object.entries(config.theme||{}))if(['accent','background','color'].includes(key)&&/^#[0-9a-fA-F]{3,8}$/.test(value))document.documentElement.style.setProperty('--'+key,value);
let child=null,lastAck=Date.now();
if(config.source!=='builtin'){overlay.textContent='';child=document.createElement('iframe');child.sandbox='allow-scripts';if(config.source==='remote'){child.sandbox='allow-scripts allow-same-origin';child.src=config.url;}else child.srcdoc=config.content;overlay.appendChild(child);}
addEventListener('message',event=>{if(child&&event.source===child.contentWindow&&event.data?.type==='openplayout.ack')lastAck=Date.now();});
async function update(){try{const result=await fetch(location.pathname+'/context'+location.search,{cache:'no-store',signal:AbortSignal.timeout(2500)});if(!result.ok)throw Error('offline');const c=await result.json(),p=c.variables;
if(child){child.contentWindow.postMessage({type:'openplayout.context',context:c},config.source==='remote'?new URL(config.url).origin:'*');if(config.source==='remote'&&Date.now()-lastAck>5000&&config.offline==='hide')overlay.style.visibility='hidden';else overlay.style.visibility='visible';}
else{overlay.style.visibility='visible';let title=p.title||p.text||c.channel.name,sub=p.subtitle||'';
if(config.layout==='now_next'){title='NOW  '+(c.now?.title||'');sub='NEXT  '+(c.next?.title||'');}
if(config.layout==='lower_third')title=p.title||c.now?.title||c.channel.name;
if(config.layout==='countdown'){let s=p.deadline?Math.max(0,(Date.parse(p.deadline)-Date.now())/1000):c.now?.remaining_seconds||0;title=[Math.floor(s/3600),Math.floor(s/60)%60,Math.floor(s)%60].map(v=>String(v).padStart(2,'0')).join(':');}
document.getElementById('title').textContent=title;document.getElementById('sub').textContent=sub;}}
catch(e){if(config.offline==='hide')overlay.style.visibility='hidden';}}
update();setInterval(update,250);
</script></body></html>'''


class GraphicsService:
    def __init__(self, sessions, get_controller, read_settings, settings, engine_factory):
        self.sessions, self.controller, self.read_settings, self.settings = sessions, get_controller, read_settings, settings
        self.engine_factory = engine_factory
        self.lock = asyncio.Lock()
        self.engine = None

    async def close(self):
        async with self.lock:
            if self.engine:
                await self.engine.disconnect()
                self.engine = None

    async def command(self, instance_id: str, action: str, parameters: dict | None = None):
        async with self.lock:
            cfg = self.read_settings()
            with self.sessions() as db:
                row = db.get(GraphicsInstance, instance_id)
                if not row:
                    raise ValueError("Unknown graphics instance")
                if row.layer <= cfg.layer:
                    raise ValueError("Graphics layers must be above the program layer")
                template = document(db, row.template_id, "graphics")
                GraphicsConfig.model_validate(template.payload)
                if parameters:
                    row.parameters = row.parameters | parameters
                if self.engine is None:
                    self.engine = self.engine_factory(cfg)
                try:
                    if not self.engine.is_connected():
                        await self.engine.connect()
                    url = f"{self.settings.graphics_base_url.rstrip('/')}/graphics/render/{row.id}?key={row.access_key}"
                    await self.engine.graphic(action, row.layer, {"url": url})
                    row.state, row.error = ("active" if action == "show" else "inactive"), None
                except Exception as exc:
                    row.state, row.error = "error", str(exc)
                    db.commit()
                    raise
                db.commit()

    def context(self, row):
        status = self.controller().status()
        observed = status["observation"]
        current = status["current"]
        next_item = status["next"]
        cfg = self.read_settings()
        end = observed.get("clip_in_seconds", 0) + (observed.get("clip_duration_seconds") or observed.get("duration_seconds") or 0)
        return {"channel": {"id": "main", "name": cfg.name}, "now": {"title": current["media"]["title"] if current else "", "remaining_seconds": max(0, end - (observed.get("position_seconds") or 0))},
            "next": {"title": next_item["media"]["title"] if next_item else ""}, "variables": row.parameters,
            "playback_state": observed["state"]}

    def active(self):
        with self.sessions() as db:
            return [{"id": r.id, "template_id": r.template_id, "layer": r.layer, "parameters": r.parameters, "state": r.state, "error": r.error} for r in db.scalars(select(GraphicsInstance))]


def public_router(service: GraphicsService):
    router = APIRouter(tags=["Read-only graphics bridge"])

    def authorized(db, instance_id, key):
        row = db.get(GraphicsInstance, instance_id)
        if not row or not secrets.compare_digest(row.access_key.encode(), key.encode()):
            raise HTTPException(403, "Invalid graphics read capability")
        return row

    @router.get("/graphics/render/{instance_id}/context")
    def context(instance_id: str, key: str = Query(max_length=200)):
        with service.sessions() as db:
            row = authorized(db, instance_id, key)
            return service.context(row)

    @router.get("/graphics/render/{instance_id}", response_class=HTMLResponse)
    def render(instance_id: str, key: str = Query(max_length=200)):
        with service.sessions() as db:
            row = authorized(db, instance_id, key)
            template = document(db, row.template_id, "graphics")
            config = GraphicsConfig.model_validate(template.payload).model_dump()
            if config["source"] == "remote":
                parsed = urlparse(config["url"])
                if parsed.scheme != "https" or not parsed.hostname or parsed.username or parsed.password:
                    raise HTTPException(400, "Remote overlays require a credential-free HTTPS URL")
            if config["source"] == "file":
                root = (service.settings.data_dir / "graphics").resolve()
                path = (root / config["filename"]).resolve()
                if not path.is_relative_to(root) or path.suffix.lower() not in (".html", ".htm") or not path.is_file():
                    raise HTTPException(400, "Place the HTML template inside data/graphics and use its relative filename")
                config["content"] = path.read_text(encoding="utf-8")
            serialized = json.dumps(config).replace("<", "\\u003c").replace(">", "\\u003e").replace("&", "\\u0026")
            return HTMLResponse(BRIDGE.replace("CONFIG", serialized), headers={"Cache-Control": "no-store", "Referrer-Policy": "no-referrer", "X-Content-Type-Options": "nosniff"})
    return router
