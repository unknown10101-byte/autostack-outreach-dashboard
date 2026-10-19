"""AutoStack outreach dashboard (hosted, two-way). No data or secrets in this repo.
Env: DATABASE_URL, DASH_USER, DASH_PASSWORD, BOT_TOKEN."""
import os, json, secrets, base64
from contextlib import contextmanager
import psycopg
from psycopg.rows import dict_row
from psycopg.types.json import Jsonb
from fastapi import FastAPI, Request, HTTPException, Body
from fastapi.responses import HTMLResponse, JSONResponse, Response

DB = os.environ['DATABASE_URL']
USER = os.environ.get('DASH_USER', 'riya'); PW = os.environ['DASH_PASSWORD']; TOKEN = os.environ['BOT_TOKEN']
ACTIONS = {'approve_draft', 'skip', 'edit_draft', 'research_more', 'mark_accepted', 'mark_replied', 'message_to_bot'}
HERE = os.path.dirname(__file__)
TEMPLATE = open(os.path.join(HERE, 'template.html'), encoding='utf-8').read()
EXTRA = open(os.path.join(HERE, 'extra.html'), encoding='utf-8').read()

@contextmanager
def db():
    with psycopg.connect(DB, row_factory=dict_row) as c: yield c

with db() as c:
    c.execute("""create table if not exists actions(id serial primary key, ts timestamptz not null default now(),
      contact text, action text not null, payload jsonb not null default '{}', status text not null default 'pending'
      check (status in ('pending','applied','rejected')), bot_response text, updated_at timestamptz)""")
    c.execute("create table if not exists dashboard_data(id int primary key, data jsonb not null, uploaded_at timestamptz not null default now())")

app = FastAPI(docs_url=None, redoc_url=None, openapi_url=None)

def bearer_ok(req):
    h = req.headers.get('authorization', '')
    return h.startswith('Bearer ') and secrets.compare_digest(h[7:], TOKEN)
def basic_ok(req):
    h = req.headers.get('authorization', '')
    if not h.startswith('Basic '): return False
    try: u, _, p = base64.b64decode(h[6:]).decode().partition(':')
    except Exception: return False
    return secrets.compare_digest(u, USER) & secrets.compare_digest(p, PW)

@app.middleware('http')
async def auth(req: Request, call_next):
    if req.url.path == '/healthz': return await call_next(req)
    bot = bearer_ok(req); human = basic_ok(req)
    if req.url.path.startswith('/api/bot') or req.url.path in ('/api/data',) and req.method == 'POST':
        if not bot: return JSONResponse({'detail': 'bearer token required'}, 401)
    elif req.url.path.startswith('/api/actions') and (bot or human): pass
    elif not human:
        return Response('Login required', 401, {'WWW-Authenticate': 'Basic realm="AutoStack outreach"'})
    resp = await call_next(req)
    resp.headers['Cache-Control'] = 'no-store'; resp.headers['X-Robots-Tag'] = 'noindex, nofollow'
    return resp

@app.get('/healthz')
def health(): return {'ok': True}

@app.get('/robots.txt')
def robots(): return Response('User-agent: *\nDisallow: /\n', media_type='text/plain')

@app.get('/', response_class=HTMLResponse)
def index():
    with db() as c: r = c.execute('select data from dashboard_data where id=1').fetchone()
    if not r: return HTMLResponse('<p>No data uploaded yet. The bot pushes it with sync_hosted.py.</p>')
    js = json.dumps(r['data'], ensure_ascii=False).replace('</', '<\\/')
    return HTMLResponse(TEMPLATE.replace('/*DATA*/null', js).replace('</body>', EXTRA + '</body>'))

@app.post('/api/data')
def upload(data: dict = Body(...)):
    if 'contacts' not in data: raise HTTPException(400, 'expected build_dashboard.py data JSON')
    with db() as c:
        c.execute("insert into dashboard_data(id,data) values(1,%s) on conflict(id) do update set data=excluded.data, uploaded_at=now()", (Jsonb(data),))
    return {'ok': True, 'contacts': len(data['contacts'])}

def ser(r): r = dict(r); r['ts'] = r['ts'].isoformat(); r['updated_at'] = r['updated_at'] and r['updated_at'].isoformat(); return r

@app.get('/api/actions')
def list_actions(status: str | None = None, contact: str | None = None):
    q, a = 'select * from actions where true', []
    if status: q += ' and status=%s'; a.append(status)
    if contact: q += ' and contact=%s'; a.append(contact)
    with db() as c: return [ser(r) for r in c.execute(q + ' order by id desc limit 500', a).fetchall()]

@app.post('/api/actions')
def create_action(req: Request, body: dict = Body(...)):
    act = body.get('action')
    if act not in ACTIONS: raise HTTPException(400, 'unknown action')
    payload = body.get('payload') or {}
    if not isinstance(payload, dict): raise HTTPException(400, 'payload must be an object')
    with db() as c:
        r = c.execute('insert into actions(contact,action,payload) values(%s,%s,%s) returning *', (body.get('contact') or None, act, Jsonb(payload))).fetchone()
    return ser(r)

@app.post('/api/actions/{aid}')
def update_action(aid: int, req: Request, body: dict = Body(...)):
    if not bearer_ok(req): raise HTTPException(401, 'bearer token required')
    st = body.get('status')
    if st not in ('pending', 'applied', 'rejected'): raise HTTPException(400, 'bad status')
    with db() as c:
        r = c.execute('update actions set status=%s, bot_response=%s, updated_at=now() where id=%s returning *', (st, body.get('bot_response'), aid)).fetchone()
    if not r: raise HTTPException(404)
    return ser(r)

@app.delete('/api/actions/{aid}')
def delete_action(aid: int, req: Request):
    if not bearer_ok(req): raise HTTPException(401, 'bearer token required')
    with db() as c: n = c.execute('delete from actions where id=%s', (aid,)).rowcount
    return {'deleted': n}
