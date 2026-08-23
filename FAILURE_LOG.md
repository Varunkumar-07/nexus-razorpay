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
