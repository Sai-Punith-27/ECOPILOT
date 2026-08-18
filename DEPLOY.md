# Deploying EcoPilot

Two deployment options are documented below:

- **Option B — Streamlit Community Cloud + Render (recommended, no server to manage).**
  One public URL, both free-tier-capable. This is the path used for the SIH
  demo. See below.
- **Option A — Docker on your own VPS.** Everything's already containerized
  if you'd rather run it yourself. See the second half of this file.

---

# Option B: Streamlit Community Cloud (frontend) + Render (backend + simulator)

**End result:** one public URL — `https://<your-app-name>.streamlit.app` — is
what you give to anyone (including SIH judges). It's the only link a user
ever needs; the backend and simulator run invisibly behind it.

```
 Render (background worker)        Render (web service)         Streamlit Community Cloud
 backend/simulator/Dockerfile  →   backend/backend/Dockerfile → frontend/app.py
 posts telemetry every 2s          FastAPI + SQLite +           reads BACKEND_BASE_URL
                                    ML prediction (/api/predict) from st.secrets
                                    ↑ BACKEND_BASE_URL not
                                      needed here (simulator
                                      posts directly to it)
```

## Prerequisites

- Push this repo to GitHub (Streamlit Cloud and Render both deploy from a
  connected GitHub repo — neither needs anything installed on your machine).
- A free Render account (render.com) and a free Streamlit Community Cloud
  account (share.streamlit.io) — both let you sign in with GitHub directly.

## Step 1 — Deploy the backend on Render (Web Service)

1. Render dashboard → **New +** → **Web Service** → connect your GitHub repo.
2. Settings:
   - **Root Directory:** leave blank (repo root — needed so the Docker build
     context can see the sibling `ai-optimizers/` folder, same as local Docker).
   - **Runtime:** Docker
   - **Dockerfile Path:** `backend/backend/Dockerfile`
   - **Instance type:** Free (fine for a demo; see the cold-start note below)
3. No environment variables are required to start (the ML model artifacts are
   already committed under `ai-optimizers/ml/artifacts/`, so no training step
   runs at deploy time).
4. **Persistent storage (optional but recommended):** Render's free web
   services have an ephemeral filesystem — the SQLite telemetry history resets
   on every redeploy/restart unless you add a Render **Disk** mounted at
   `/app/backend/backend/data` (Render dashboard → your service → Disks). For
   a short SIH demo this is usually fine to skip; for a longer-running demo,
   add the disk.
5. Deploy. Render gives you a URL like:
   `https://ecopilot-backend-xxxx.onrender.com`
6. Verify it's alive: open `https://ecopilot-backend-xxxx.onrender.com/health`
   in a browser — should show `{"status":"ok","service":"ecopilot-backend"}`.
   Also check `/docs` for the interactive Swagger UI (includes the new
   `/api/predict/{appliance_id}` route).

**Free-tier cold start:** Render's free web services sleep after ~15 minutes
of no requests, and the next request takes ~30-50s to wake it up. For a live
judging demo, either (a) open the backend URL yourself a minute before
presenting to "warm it up," or (b) upgrade this one service to a paid
Starter instance for the day of judging (a few dollars), which removes sleep
entirely. This is a Render platform behavior, not something in the code.

## Step 2 — Deploy the simulator on Render (Background Worker)

1. Render dashboard → **New +** → **Background Worker** → same GitHub repo.
2. Settings:
   - **Root Directory:** `backend/simulator` (unlike the backend, the
     simulator has no dependency on `ai-optimizers/`, so it keeps its
     original, simpler build context — don't set this to repo root, the
     build will fail looking for `requirements.txt` in the wrong place).
   - **Runtime:** Docker
   - **Dockerfile Path:** `Dockerfile` (relative to the Root Directory above)
   - **Instance type:** Free
3. **Environment variable (required):**
   - `BACKEND_BASE_URL` = the backend URL from Step 1,
     e.g. `https://ecopilot-backend-xxxx.onrender.com`
4. Deploy. Check the worker's **Logs** tab — you should see the same
   `[AC] ... [OK] Telemetry sent successfully (HTTP 201 x4)` output you saw
   running it locally.

**Note:** if the backend is asleep (free tier, Step 1) when the simulator
posts, that POST will fail/timeout and retry on the next tick rather than
crash the worker — but the backend will also be "asleep" for judges opening
the dashboard cold, which is the main reason to warm it up or upgrade it
before a demo (see Step 1).

## Step 3 — Deploy the frontend on Streamlit Community Cloud

1. share.streamlit.io → **New app** → connect the same GitHub repo.
2. Settings:
   - **Main file path:** `frontend/app.py`
   - Streamlit Cloud auto-detects `frontend/requirements.txt` in the same
     folder as the main file — no extra config needed.
3. **Secrets (required)** — app **Settings → Secrets**, add:
   ```toml
   BACKEND_BASE_URL = "https://ecopilot-backend-xxxx.onrender.com"
   ```
   (`frontend/app.py` already bridges `st.secrets["BACKEND_BASE_URL"]` into
   the environment variable `backend_client.py` reads — this was already in
   the codebase before this change, not something added for ML.)
4. Deploy. Streamlit Cloud gives you:
   `https://<your-app-name>.streamlit.app`
   **This is the one URL you share.**

## Step 4 — Verify the full deployed chain

- Open the Streamlit URL. Sidebar should show "🔌 Backend Connection: connected."
- Live Dashboard tab should show live-updating readings within a couple of
  poll cycles (simulator posts every 2s).
- Switch to **⚙️ Technical View** — the "🤖 ML Energy Prediction" section
  should show a predicted Wh figure with an RMSE caption for AC and Cooler.
  If it instead shows "Prediction unavailable," check the Render backend's
  `/api/predict/ac_01` endpoint directly in a browser to see the `error`
  field — almost always either the backend is still asleep (cold start) or
  no telemetry has arrived yet.

## Costs

Both Render's free web service + free background worker, and Streamlit
Community Cloud, are free. The only optional cost is upgrading the Render
backend off the free tier to avoid cold-start sleep during judging.

---

# Option A: Docker on your own VPS

Three containers, one `docker-compose.yml`:

- **backend** — FastAPI + SQLite + ML prediction, on port 8000
- **simulator** — posts fake telemetry to the backend every 2s, no exposed port
- **frontend** — Streamlit dashboard, on port 8501

## What changed from your local setup
- `backend/backend/app/database.py` now reads `SQLITE_DB_PATH` from the environment
  (falls back to `./ecopilot.db` for local dev, unchanged). In Docker this points at
  a named volume (`backend_data`) so your telemetry history survives container
  restarts and redeploys.
- Added a `Dockerfile` to each of `backend/backend/`, `backend/simulator/`, and
  `frontend/`, plus a root `.dockerignore`.
- `frontend/Dockerfile` builds from the **repo root** (not the `frontend/` folder)
  because `app.py` imports the sibling `ai-optimizers/ai` package via a relative
  path — the build context needs both folders.
- **New:** `backend/backend/Dockerfile` now ALSO builds from the repo root
  (previously it built from `backend/backend/` only), because the new ML
  prediction route imports the sibling `ai-optimizers/ml` package the same
  way. `docker-compose.yml`'s `backend` service was updated to match
  (`context: .`, `dockerfile: backend/backend/Dockerfile`), and the SQLite
  data volume's container-side mount path changed from `/app/data` to
  `/app/backend/backend/data` as a result. **If you have an existing VPS
  deployment from before this change, `docker compose down && docker compose
  up -d --build` will start with a fresh (empty) database** unless you
  manually copy the old volume's `ecopilot.db` into the new mount path first.

Nothing else in your app code changed. All three services already read their
peer's URL from `BACKEND_BASE_URL`, so no hardcoded `localhost` issues.

## Deploy on your VPS

1. Install Docker + the Compose plugin if you don't have them:
   ```bash
   curl -fsSL https://get.docker.com | sh
   sudo apt-get install -y docker-compose-plugin   # if compose isn't bundled
   ```

2. Copy this `EcoPilot/` folder to the server (scp, git clone, rsync — whatever
   you use), then from inside it:
   ```bash
   docker compose up -d --build
   ```

3. Check everything's healthy:
   ```bash
   docker compose ps
   docker compose logs -f simulator   # should show telemetry being sent, no errors
   docker compose logs -f backend     # should show no ML-load errors on startup
   ```

4. Open `http://<your-server-ip>:8501` for the dashboard,
   `http://<your-server-ip>:8000/docs` for the backend's Swagger UI (includes
   the new `/api/predict/{appliance_id}` route).

## Exposing it publicly (recommended)

Right now ports 8000 and 8501 are open directly. For a real deployment, put a
reverse proxy (Caddy or Nginx) in front so you get a domain + HTTPS instead of
a bare IP:port, and so only the frontend is public (the backend API doesn't
need to be reachable from outside the Docker network — only `frontend` and
`simulator` need to reach it, and they do so over the internal `ecopilot`
compose network by service name).

Minimal Caddy example (`Caddyfile`):
```
dashboard.yourdomain.com {
    reverse_proxy frontend:8501
}
```
If you add Caddy, drop the `ports:` mapping on `backend` in
`docker-compose.yml` (keep it on `frontend` only, or also proxy it) so the
API isn't exposed directly.

## Day-to-day operations

```bash
docker compose logs -f backend      # tail backend logs
docker compose restart simulator    # restart just one service
docker compose down                 # stop everything (data persists in the volume)
docker compose down -v              # stop AND wipe the telemetry database
docker compose up -d --build        # rebuild + redeploy after a code change
```

## Data persistence

Telemetry lives in the `backend_data` named Docker volume, mounted at
`/app/backend/backend/data/ecopilot.db` inside the backend container (see the
note above if migrating from a pre-ML deployment). It survives
`docker compose down` / `up` and rebuilds. Only `docker compose down -v`
or manually deleting the volume erases it.

## Training/updating the ML model

`ai-optimizers/ml/artifacts/model.joblib` and `metrics.json` are committed to
the repo and loaded read-only at backend startup — the deployed backend never
trains anything itself. To retrain with fresh data:
```bash
cd ai-optimizers/ml
pip install -r requirements.txt
# download the dataset — see data/README.md
python train.py --data data/energydata_complete.csv --out artifacts
```
Commit the updated `artifacts/model.joblib` + `artifacts/metrics.json`, then
redeploy (`docker compose up -d --build` for Option A, or push to trigger a
redeploy on Render for Option B).

