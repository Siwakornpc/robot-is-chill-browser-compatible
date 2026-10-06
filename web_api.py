import asyncio
import hashlib
import mimetypes
import os
import shutil
import sys
import tempfile
import time
from collections import deque
from pathlib import Path

from quart import Quart, Response, jsonify, request, send_from_directory

ROOT = Path(__file__).resolve().parent
CACHE_DIR = ROOT / "cache"
WEB_DIR = ROOT / "web"
CACHE_DIR.mkdir(exist_ok=True)

RATE_SECONDS = int(os.environ.get("RATE_SECONDS", "0"))
RENDER_TIMEOUT = float(os.environ.get("RENDER_TIMEOUT", "2"))
ALLOWED_ORIGIN = os.environ.get("ALLOWED_ORIGIN", "*")
TRUST_PROXY = os.environ.get("TRUST_PROXY", "0") == "1"
MAX_CONCURRENT = int(os.environ.get("MAX_CONCURRENT", "2"))
MAX_SCENE_LEN =  2 ** 22
MAX_SCENE_LINES = 20
MAX_FAILS_PER_MIN = 10
CACHE_MAX_FILES = 2000

app = Quart(__name__)
cooldown: dict[str, float] = {}      # ip -> time of next allowed render
failures: dict[str, deque] = {}      # ip -> timestamps of recent failed renders
inflight: set[str] = set()
slots = asyncio.Semaphore(MAX_CONCURRENT)

if not (ROOT / "robot.db").exists():
    print("WARNING: robot.db not found - run build_db.py first.", file=sys.stderr)

def client_ip() -> str:
    if TRUST_PROXY:  # last entry = the one our own proxy appended
        forwarded = request.headers.get("X-Forwarded-For", "")
        if forwarded:
            return forwarded.split(",")[-1].strip()
    return request.remote_addr or "unknown"

def error(status: int, message: str, retry_after: float | None = None):
    resp = jsonify({"error": message})
    resp.status_code = status
    if retry_after is not None:
        resp.headers["Retry-After"] = str(max(1, int(retry_after)))
    return resp

@app.after_request
async def add_headers(resp):
    resp.headers["Access-Control-Allow-Origin"] = ALLOWED_ORIGIN
    resp.headers["Access-Control-Allow-Methods"] = "GET, OPTIONS"
    resp.headers["Access-Control-Allow-Headers"] = "Content-Type"
    resp.headers["Access-Control-Expose-Headers"] = "Retry-After"
    resp.headers["X-Content-Type-Options"] = "nosniff"
    return resp

def cache_lookup(key: str):
    for path in CACHE_DIR.glob(f"{key}.*"):
        return path
    return None

def cache_store(key: str, src: Path) -> Path:
    files = sorted(CACHE_DIR.iterdir(), key=lambda p: p.stat().st_mtime)

    for old in files[: max(0, len(files) - CACHE_MAX_FILES + 1)]:
        old.unlink(missing_ok=True)

    dest = CACHE_DIR / f"{key}{src.suffix}"
    shutil.move(str(src), dest)
    return dest

def image_response(path: Path, cached: bool):
    ctype = mimetypes.guess_type(path.name)[0] or "application/octet-stream"
    resp = Response(path.read_bytes(), mimetype=ctype)
    resp.headers["Cache-Control"] = "public, max-age=86400"
    resp.headers["X-Cache"] = "HIT" if cached else "MISS"
    return resp

@app.get("/")
async def index():
    return await send_from_directory(WEB_DIR, "index.html")

@app.get("/health")
async def health():
    return jsonify({"ok": True})

@app.get("/render")
async def render_route():
    mode = request.args.get("mode", "r")
    scene = (request.args.get("scene") or "").strip()

    if mode not in ("t", "r"):
        return error(400, "mode must be 't' (tile) or 'r' (text/rule).")
    if not scene:
        return error(400, "scene is empty.")
    if len(scene) > MAX_SCENE_LEN or scene.count("\n") >= MAX_SCENE_LINES:
        return error(400, f"scene is too long (max {MAX_SCENE_LEN} characters, {MAX_SCENE_LINES} lines).")

    key = hashlib.sha256(f"{mode}\n{scene}".encode()).hexdigest()[:32]

    ip, now = client_ip(), time.time()
    if cooldown.get(ip, 0) > now:
        return error(429, "Too many requests: one render per minute.", cooldown[ip] - now)

    hit = cache_lookup(key)
    if hit:
        cooldown[ip] = now + RATE_SECONDS
        return image_response(hit, cached=True)

    ip, now = client_ip(), time.time()
    if cooldown.get(ip, 0) > now:
        return error(429, "Too many requests: one render per minute.", cooldown[ip] - now)
    recent = failures.setdefault(ip, deque())

    while recent and recent[0] < now - 60:
        recent.popleft()
    if len(recent) >= MAX_FAILS_PER_MIN:
        return error(429, "Too many failed renders. Wait a minute.", recent[0] + 60 - now)
    if ip in inflight:
        return error(429, "A render from your address is already running.", 2)
    if slots.locked():
        return error(503, "The renderer is busy. Try again shortly.", 5)

    inflight.add(ip)
    try:
        async with slots:
            return await run_render(mode, scene, key, ip)
    finally:
        inflight.discard(ip)

async def run_render(mode: str, scene: str, key: str, ip: str):
    tmp = Path(tempfile.mkdtemp(prefix="render_"))

    try:
        proc = await asyncio.create_subprocess_exec(
            sys.executable, "render_cli.py", f"={mode} {scene}", "-o", str(tmp / "out"),
            cwd=str(ROOT), stdout=asyncio.subprocess.PIPE, stderr=asyncio.subprocess.PIPE,
        )

        try:
            _, err = await asyncio.wait_for(proc.communicate(), RENDER_TIMEOUT)
        except asyncio.TimeoutError:
            proc.kill()

            await proc.wait()

            failures.setdefault(ip, deque()).append(time.time())
            return error(504, f"Render took longer than {RENDER_TIMEOUT:g}s and was stopped.")

        outputs = list(tmp.glob("out.*"))

        if proc.returncode != 0 or not outputs:
            failures.setdefault(ip, deque()).append(time.time())

            text = err.decode("utf-8", "replace").strip().splitlines()
            last = text[-1] if text else ""

            if last.startswith("Render error:"):
                return error(400, last.removeprefix("Render error:").strip()[:300])
            
            print(f"render failed (code {proc.returncode}):\n" + "\n".join(text[-15:]), file=sys.stderr)
            return error(500, "The renderer failed on this input.")

        cooldown[ip] = time.time() + RATE_SECONDS           # only successes count

        if len(cooldown) > 10000:                           # drop expired entries
            for k in [k for k, v in cooldown.items() if v < time.time()]:
                del cooldown[k]
                
        return image_response(cache_store(key, outputs[0]), cached=False)
    finally:
        shutil.rmtree(tmp, ignore_errors=True)

if __name__ == "__main__":
    app.run(host="127.0.0.1", port=int(os.environ.get("PORT", "8000")))
