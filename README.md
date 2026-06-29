# QueueStorm Investigator

An internal support-copilot API for a digital-finance platform. It ingests a
single customer complaint plus a short slice of that customer's transaction
history, **investigates** what actually happened, routes the case to the right
team, and drafts a **safe** customer reply — one that never requests credentials
and never promises a refund it cannot authorize.

The service exposes two endpoints — `GET /health` and `POST /analyze-ticket` —
and ships with a static frontend for demos.

---

## Contents

- [Design overview](#design-overview)
- [Architecture](#architecture)
- [Concurrency & latency model](#concurrency--latency-model)
- [API reference](#api-reference)
- [Project structure](#project-structure)
- [Getting started](#getting-started)
- [Configuration](#configuration)
- [Safety model](#safety-model)
- [Testing](#testing)
- [Frontend](#frontend)
- [Deployment](#deployment)
- [Assumptions & limitations](#assumptions--limitations)

---

## Design overview

The system is a **rule-authoritative hybrid**.

A deterministic rule engine decides every scored field — the relevant
transaction, evidence verdict, case type, department, severity, and escalation.
It is explainable, runs in single-digit milliseconds, and has no external
dependency or failure surface. An optional LLM layer (Google Gemini 2.5 Flash
via OpenRouter) only *rewrites* the customer reply and agent-facing text more
fluently in the customer's language. It never touches a scored field, and every
draft it produces is validated and safety-scrubbed in code before it can be
returned.

The consequences of this split:

- **Determinism.** The same input yields the same decision every time.
- **Reliability.** With the LLM disabled (or on any LLM timeout/error), the
  service is a pure rule engine with identical decisions.
- **Safety by construction.** Credential requests, unauthorized financial
  promises, and third-party redirects are removed by a final scrubber regardless
  of who authored the text.

---

## Architecture

The request pipeline (`app/pipeline.py`) is a pure function from a validated
request to a response dict:

```
parse history (lenient) → extract features → classify case type
   → match transaction + evidence verdict → severity / department / human review
   → render text (EN/BN) → safety scrub → response
```

| Module | Responsibility |
|---|---|
| `main.py` | FastAPI app, routes, exception handlers, body-size guard, CORS |
| `schemas.py` | Pydantic request model (lenient) + strict response enums + transaction parser |
| `config.py` | Enums, keyword lexicons, thresholds, routing tables |
| `extract.py` | Language, amount (incl. Bangla digits), phone, keyword, and injection extraction |
| `classify.py` | Case-type priority cascade |
| `matching.py` | Transaction scoring and evidence verdict |
| `routing.py` | Severity, department, human-review, confidence |
| `responses.py` | English/Bangla agent summary, next action, customer reply |
| `safety.py` | Final safety scrubber and vetted fallbacks |
| `llm.py` | Optional assist layer (sync + async clients) |
| `settings.py` | Environment-driven runtime settings |
| `pipeline.py` | Orchestrator (`analyze`, `analyze_async`) |

Matching scores each candidate transaction (amount +3, counterparty +2,
expected status +1); a single strong match becomes the relevant transaction,
while a tie resolves to `insufficient_data` rather than a guess. Duplicates
resolve to the later charge. The verdict is `consistent` by default, flipping to
`inconsistent` when the data contradicts the claim (for example, an
established-recipient pattern on a "wrong transfer", or a "failed" payment that
actually completed).

---

## Concurrency & latency model

`POST /analyze-ticket` is an **async** handler. The deterministic pipeline runs
inline (CPU-light, ~3 ms), and only the optional LLM enrichment performs I/O.

That I/O goes through a single shared, connection-pooled `httpx.AsyncClient`
(keep-alive — no per-request TCP/TLS handshake) and is bounded by a module-level
semaphore (`LLM_MAX_CONCURRENCY`). When the cap is reached, additional requests
skip the LLM immediately and return the always-ready rule answer instead of
queueing behind a rate-limited provider. This keeps the event loop free to
service many concurrent connections and keeps p95 latency bounded under load.

A synchronous `analyze()` is retained for tests and non-async callers; the live
server uses `analyze_async()`.

---

## API reference

### `GET /health`

```
200 {"status": "ok"}
```

### `POST /analyze-ticket`

Required: `ticket_id`, `complaint`. Everything else is optional.

```json
{
  "ticket_id": "TKT-001",
  "complaint": "I sent 5000 taka to a wrong number around 2pm today.",
  "language": "en",
  "channel": "in_app_chat",
  "user_type": "customer",
  "campaign_context": "boishakh_bonanza_day_1",
  "transaction_history": [
    {
      "transaction_id": "TXN-9101",
      "timestamp": "2026-04-14T14:08:22Z",
      "type": "transfer",
      "amount": 5000,
      "counterparty": "+8801719876543",
      "status": "completed"
    }
  ],
  "metadata": {}
}
```

Response:

```json
{
  "ticket_id": "TKT-001",
  "relevant_transaction_id": "TXN-9101",
  "evidence_verdict": "consistent",
  "case_type": "wrong_transfer",
  "severity": "high",
  "department": "dispute_resolution",
  "agent_summary": "Customer reports sending 5000 BDT via TXN-9101 ...",
  "recommended_next_action": "Verify TXN-9101 details with the customer ...",
  "customer_reply": "We have noted your concern about transaction TXN-9101 ...",
  "human_review_required": true,
  "confidence": 0.9,
  "reason_codes": ["wrong_transfer", "transaction_match", "human_review"]
}
```

Worked outputs for all ten public samples are in
[`sample_outputs.json`](sample_outputs.json).

### Status codes

| Code | When |
|---|---|
| 200 | Successful analysis |
| 400 | Invalid JSON, or missing/wrong-typed required field (`ticket_id` / `complaint`) |
| 422 | Schema valid but semantically invalid (empty/whitespace `complaint`) |
| 413 | Request body exceeds the configured limit (default 256 KB) |
| 500 | Internal error — generic body, no input/trace/secret leakage |

The service does not crash on malformed input: bad optional fields are coerced
or dropped, and junk transaction rows are skipped rather than rejected.

---

## Project structure

```
app/                 application package (see Architecture table)
frontend/            static showcase UI (deploys to Vercel)
tests/
  test_samples.py    the 10 public sample cases
  test_edges.py      malformed input, robustness, edge reasoning
  test_llm.py        mocked assist-layer behaviour
  data/              sample case pack
  load/              stress_test.py, manual_smoke_test.py (black-box)
docs/                problem statement PDFs + sample cases
Dockerfile
requirements.txt     runtime deps
requirements-dev.txt test deps
sample_outputs.json  service output for the 10 public samples
```

---

## Getting started

### Local (Python 3.12)

```bash
pip install -r requirements.txt
uvicorn app.main:app --host 0.0.0.0 --port 8000
```

### Docker

```bash
docker build -t queuestorm .
docker run -p 8000:8000 queuestorm
```

### Verify

```bash
curl http://localhost:8000/health

curl -X POST http://localhost:8000/analyze-ticket \
  -H "content-type: application/json" \
  -d '{"ticket_id":"TKT-001","complaint":"I sent 5000 taka to a wrong number around 2pm today.","transaction_history":[{"transaction_id":"TXN-9101","timestamp":"2026-04-14T14:08:22Z","type":"transfer","amount":5000,"counterparty":"+8801719876543","status":"completed"}]}'
```

---

## Configuration

All configuration is via environment variables; see [`.env.example`](.env.example).

| Variable | Default | Purpose |
|---|---|---|
| `PORT` | `8000` | Bind port |
| `MAX_BODY_BYTES` | `262144` | Request body size cap (256 KB) |
| `USE_LLM` | `false` | Enable the LLM assist layer |
| `OPENROUTER_API_KEY` | — | Required only when `USE_LLM=true` |
| `LLM_MODEL` | `google/gemini-2.5-flash` | OpenRouter model id |
| `LLM_BASE_URL` | `https://openrouter.ai/api/v1` | OpenRouter base URL |
| `LLM_TIMEOUT_SECONDS` | `4.5` | Total per-call budget |
| `LLM_CONNECT_TIMEOUT_SECONDS` | `2.0` | Connect budget (fail fast on slow handshake) |
| `LLM_MAX_CONCURRENCY` | `8` | Cap on simultaneous outbound LLM calls |
| `CORS_ALLOW_ORIGINS` | `*` | Comma-separated origin allowlist for the frontend |

With `USE_LLM=false` (or no key) the service runs as a pure rule engine and
requires no secrets.

---

## Safety model

Three guarantees are enforced in code, independent of who authored the text:

- **Never request credentials.** Replies only ever warn against sharing PIN/OTP/
  password/card. The scrubber detects an imperative credential request and
  replaces the reply with a vetted fallback.
- **Never promise unauthorized financial action.** No "we will refund/reverse/
  unblock". The approved phrasing is *"any eligible amount will be returned
  through official channels"*. Checked in both `customer_reply` and
  `recommended_next_action`.
- **Official channels only.** No redirects to external numbers, handles, or links.

Additional guardrails:

- **The LLM is never trusted blindly.** Its drafts pass through the same scrubber
  as rule text; an unsafe draft is discarded in favor of the rule template, and
  the LLM cannot change any scored field.
- **Prompt injection** in the complaint cannot alter routing or safety — the
  reasoning is rule-based, injected instructions are flagged
  (`prompt_injection_ignored`) and never executed or echoed.
- **Templates inject only structured transaction data**, never raw complaint
  text, so embedded instructions cannot reach the output.
- All regexes are linear (no nested quantifiers) to avoid ReDoS.

---

## Testing

```bash
pip install -r requirements-dev.txt
pytest -q
```

The suite covers the ten public sample cases, malformed-input and robustness
edges, multilingual and adversarial complaints, and the mocked assist layer
(safe draft used / unsafe draft rejected / failure falls back to rules).

Black-box load and smoke scripts (HTTP-only, independent of `app/`) live in
`tests/load/` and run against a live instance:

```bash
python tests/load/manual_smoke_test.py --base-url http://127.0.0.1:8000
python tests/load/stress_test.py --concurrency 32 --rounds 10
```

---

## Frontend

A zero-build static UI in [`frontend/`](frontend/) loads the ten official sample
cases (and an injection case), calls the API, and renders the structured verdict,
routing, safety-scrubbed reply, reason codes, raw JSON, and round-trip latency.
Set the API base URL in the top bar; a live `/health` indicator shows
connectivity. See [`frontend/README.md`](frontend/README.md) for deploy steps.

---

## Deployment

**API.** The container binds `0.0.0.0:$PORT`, runs as a non-root user, and
includes a stdlib health probe. Deploy to any container host (Render, Railway,
Fly, or a VM). Set `USE_LLM` and `OPENROUTER_API_KEY` via the host's environment
if you want the assist layer; leave them unset for a pure rule engine. Verify
`/health` and `/analyze-ticket` from outside the network before relying on it.

**Frontend.** Deploy `frontend/` to Vercel (root directory `frontend`, framework
preset "Other", no build step), then point its API base URL field at the
deployed API. Restrict `CORS_ALLOW_ORIGINS` to the Vercel domain in production.

---

## Assumptions & limitations

- Complaints and transaction histories are synthetic, per the brief.
- The high-value escalation threshold is 50,000 BDT (15,000 stays medium).
- Time references are heuristic only — timestamps are synthetic with no real
  "now" to anchor against — so matching relies on amount and counterparty.
- `mixed`-language complaints are answered in English; replies switch to Bangla
  when the complaint is written in Bangla script.
- Understanding is keyword/rule-bounded: very novel phrasing outside the lexicons
  falls back to `other` / `insufficient_data` (a safe non-guess) rather than a
  forced classification.
- The service identifies and routes; it never executes a financial action.
