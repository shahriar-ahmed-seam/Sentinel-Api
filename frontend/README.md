# QueueStorm Investigator — Frontend

A zero-build static showcase UI for the `POST /analyze-ticket` API. Load any of
the 10 official sample cases (or write your own complaint + transaction
history), hit **Analyze ticket**, and see the structured investigation result:
case type, evidence verdict, severity, department, the safe customer reply, and
reason codes — plus the raw JSON and round-trip latency.

No framework, no build step — just `index.html`, `styles.css`, `app.js`,
`presets.js`.

## Run locally

Open `index.html` directly, or serve the folder:

```bash
# from the frontend/ directory
python -m http.server 5173
# then open http://localhost:5173
```

Set the **API base URL** field (top right) to your running API, e.g.
`http://localhost:8000`. It's saved in the browser, and the dot shows live
`/health` status.

## Deploy to Vercel

This is a static site, so deployment is one step.

**Option A — Vercel dashboard**
1. Push the repo to GitHub.
2. In Vercel: **Add New → Project**, import the repo.
3. Set **Root Directory** to `frontend`.
4. Framework preset: **Other** (no build command, output is the directory).
5. Deploy.

**Option B — Vercel CLI**
```bash
npm i -g vercel
cd frontend
vercel        # preview
vercel --prod # production
```

After deploy, open the site and paste your API's public URL into the **API base
URL** field.

## Connecting to the API (CORS)

The API allows browser calls via CORS. By default it allows all origins. To lock
it to your Vercel domain, set on the API host:

```
CORS_ALLOW_ORIGINS=https://your-frontend.vercel.app
```

(Comma-separate multiple origins.)
