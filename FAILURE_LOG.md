# NEXUS — Failure & Breakdown Log

This file tracks every error, failure, or breakdown encountered during the 
build, and exactly how it was resolved. Updated live, phase by phase.

---

## Log Entry Template
(copy this block for every new entry, fill in each field, do not skip any)

### [Entry #] — [Short title of what broke]
- **Date/Time:**
- **Phase:** (0–9, per the NEXUS build plan)
- **Component:** (e.g. Catalog Service, Gate, Razorpay Orders API, Chat Adapter)
- **What broke (symptom):** exact error message / observed behavior
- **What we were trying to do:** the action that triggered it
- **Root cause:** what actually caused it, once diagnosed
- **How we solved it:** step-by-step, what was tried, what worked
- **Tools/resources used:** docs, commands, debugging tools referenced
- **Time lost:** rough estimate
- **Status:** Resolved / Workaround in place / Open

---

## Entries

(new entries go below this line, most recent first)

### 1 — Groq model `llama-3.3-70b-versatile` not found
- **Date/Time:** 2026-08-23
- **Phase:** 2
- **Component:** Agent Reasoning Core (`app/reasoning/agent.py`)
- **What broke (symptom):** `groq.NotFoundError: Error code: 404 - {'error': {'message': 'The model `llama-3.3-70b-versatile` does not exist or you do not have access to it.', 'type': 'invalid_request_error', 'code': 'model_not_found'}}`
- **What we were trying to do:** Running `scripts/test_reasoning.py` (Scenario A) — the reasoning core's first live call to the Groq chat completions API with tool-calling enabled.
- **Root cause:** `llama-3.3-70b-versatile` has been deprecated/removed from Groq's served model lineup since the code was written; it's no longer valid for this API key.
- **How we solved it:** Queried `GET https://api.groq.com/openai/v1/models` with the real API key to list currently available models. Selected `openai/gpt-oss-120b` (a current Groq-hosted model with tool-calling support) and updated `MODEL` in `app/reasoning/agent.py`. Re-ran the test script — both Scenario A and the no-match case passed.
- **Tools/resources used:** `curl` against Groq's `/v1/models` endpoint, `groq` Python SDK error traceback.
- **Time lost:** ~5 minutes.
- **Status:** Resolved

---

## Deliberate Failure Scenarios — Demonstrated

(Phase 8. These are intentionally injected failures used to prove the
system fails gracefully — not build breakdowns, so they don't follow the
Entry template above. This is the reference for "what broke and how did
you get out of it" in the panel interview.)

### Scenario 1 — Amount exceeds the Rs.5,000 auto-approval bound (brief's Scenario C)

- **What triggers it:** A recommended order total (primary + upsell, where
  applicable) exceeds `AUTO_APPROVAL_LIMIT_PAISE` (Rs.5,000), regardless of
  what budget the buyer or calling agent believes they have.
- **How the system responds:** `check_gate()` (Phase 3) rejects the order
  *before* any Razorpay call is made — `create_order()` is never even
  invoked, since it structurally refuses to run without an approved gate
  result. The rejection returns `{"approved": false, "reason": "Amount
  Rs.X exceeds Rs.5,000.00 auto-approval limit."}`, and one `gate_check`
  event (`approved: false`) is written to the Audit Log. No `order_created`
  or `order_failed` event ever appears for a rejected transaction.
- **Proven on both entry points, same Gate, same reason format:**
  - **Agent path** (Phase 7, Case 2): ScoutBot asked for "one tent under
    Rs.9000" — its own stated budget. It independently selected, and
    `/recommend` confirmed, the AlpineGuard Winter Tent (Rs.8,999) — well
    within ScoutBot's own budget, but over the system's fixed Gate bound.
    `POST /order` returned `approved: false` with the exact reason above.
  - **Chat path** (Phase 8, Case A): A human buyer asked for the Glacier
    Extreme Sleeping Bag (Rs.4,999) plus the CloudRest Sleeping Pad
    upsell (Rs.499) — total Rs.5,498 — and confirmed with "yes". The Chat
    Adapter returned "I can't place that order: Amount Rs.5,498.00 exceeds
    Rs.5,000.00 auto-approval limit." No order was created.
  - Both runs call the identical `app.gate.gate.check_gate()` function —
    there is one Gate implementation, not two adapters with parallel
    logic that happen to agree.

### Scenario 2 — Razorpay API failure (invalid credentials)

- **What triggers it:** A real Razorpay API error — simulated by
  temporarily setting `RAZORPAY_KEY_SECRET` to an invalid value **in the
  test process's memory only** (the `.env` file on disk was never
  written to). `create_order()` reads credentials fresh from the
  environment on every call, so the very next order-creation attempt hit
  Razorpay's real `POST /v1/orders` endpoint with bad Basic Auth and got
  back a genuine `401`-class error: `{"error":{"description":
  "Authentication failed","code":"BAD_REQUEST_ERROR"}}`.
- **How the system responds:** The `requests.HTTPError` is caught (not an
  unhandled crash), an `order_failed` event is logged with the real
  Razorpay error detail attached (`stage: "order_create"`), and
  `create_order()` returns a clear structured failure:
  `{"success": false, "error": "<the real Razorpay error body>"}`. The
  same try/except path handles this identically regardless of which
  adapter (chat or agent) triggered the call.
- **Recovery confirmed, no lasting damage:** The real
  `RAZORPAY_KEY_SECRET` was restored immediately after the injected
  failure (`.env` on disk was untouched throughout — `git diff .env`
  shows no change). A follow-up order was then created successfully
  (`order_TT76uxecKlgAYa`, Rs.99.00, status `created`) using the restored
  credentials, proving the test-mode account and credentials were left in
  fully working order — the injected failure left no residual bad state.

Full evidence for both scenarios (audit trails, exact assertions) is in
`scripts/test_failure_injection.py` and `scripts/test_agent_api_scoutbot.py`.
