# 90-Second Architecture Video Script

Use this as a narration and shot list. Keep the recording under 90 seconds.
After uploading to Google Drive, YouTube, OneDrive, or Dropbox, make sure the
link is public or "anyone with the link can view".

## Shot List

1. 0-10s: Show README title and endpoints.
2. 10-25s: Show a curl request to `/analyze-ticket`.
3. 25-45s: Show `app/pipeline.py`, `classify.py`, and `matching.py`.
4. 45-60s: Show `app/safety.py` and one adversarial test response.
5. 60-75s: Show optional `app/llm.py` assist-only layer.
6. 75-90s: Show `pytest -q`, `stress_test.py`, Dockerfile, and final endpoint.

## Narration

Hi, this is QueueStorm Investigator, a backend support-copilot API for digital
finance complaints. It exposes two judge-facing endpoints: `GET /health`, which
returns `{"status":"ok"}`, and `POST /analyze-ticket`, which accepts a complaint
plus recent transaction history and returns the required structured decision.

The architecture is intentionally simple and reliable. A FastAPI service receives
the ticket, Pydantic normalizes the request, and the pipeline extracts facts such
as amount, phone number, transaction tokens, Bangla digits, and prompt-injection
signals. Then a deterministic rule cascade classifies the case type, for example
wrong transfer, failed payment, duplicate payment, merchant settlement delay, or
phishing.

The evidence engine is the core. It filters transaction history by expected type,
scores candidates by amount, counterparty, and status, and refuses to guess when
multiple transactions match. It returns the relevant transaction ID, evidence
verdict, severity, department, confidence, reason codes, and whether human review
is required.

Safety is enforced after every response path. The customer reply never asks for
PIN, OTP, password, or card details; never promises a refund, reversal, recovery,
or account unblock; and never sends the customer to a suspicious third party.
If unsafe wording appears, the scrubber replaces it with a vetted fallback.
Phishing and ambiguous or risky money cases are escalated for human review.

There is an optional Gemini 2.5 Flash layer through OpenRouter, but it is
assist-only. The rules decide every scored field first. The model can only polish
agent text and customer wording, and its output is accepted only if it passes the
same safety checks. If the model times out, fails, or returns unsafe text, the
service falls back to deterministic rules.

For deployment, the Dockerfile builds a small Python 3.12 image, binds to
`0.0.0.0`, exposes the configured port, and includes a health check. In rules-only
mode the full test suite passes, the black-box stress test reports zero
contract or safety violations, and p95 latency is well under the judge target.
