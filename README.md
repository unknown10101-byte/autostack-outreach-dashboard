# AutoStack outreach dashboard (hosted)
FastAPI app. No contact data or secrets in this repo; data is uploaded at runtime via `POST /api/data`.
Render: runtime python, build `pip install -r requirements.txt`, start `uvicorn app:app --host 0.0.0.0 --port $PORT`, health `/healthz`.
Env vars: DATABASE_URL (Render Postgres internal URL), DASH_USER=riya, DASH_PASSWORD, BOT_TOKEN.
template.html is regenerated with `python3 /workspace/outreach/build_dashboard.py --export-template template.html`.
