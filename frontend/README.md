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

Set the **API endpoint** in the connection bar at the top of the workbench to
your running API, e.g. `http://localhost:8000` (this is the default during local
dev). The status dot shows live `/health` connectivity, and the value is saved
in the browser.

## Deploy to Vercel

The repo root ships a `vercel.json` that builds this `frontend/` folder as a
static site and routes all traffic to it, so importing the repository as-is just
works — no Root Directory change, no framework preset, no build settings.

1. Push the repo to GitHub.
2. In Vercel: **Add New → Project**, import the repo, and **Deploy**.

The site root serves `frontend/index.html`. After deploy, open the site and
paste your API's public URL into the **API endpoint** field in the workbench
connection bar.

## Connecting to the API (CORS)

The API allows browser calls via CORS. By default it allows all origins. To lock
it to your Vercel domain, set on the API host:

```
CORS_ALLOW_ORIGINS=https://your-frontend.vercel.app
```

(Comma-separate multiple origins.)
