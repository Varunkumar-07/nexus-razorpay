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

### 2 — Small-talk classifier returned empty content, "hi" fell through to the LLM recommendation pipeline and crashed it
- **Date/Time:** 2026-08-23
- **Phase:** Web frontend addition (small-talk handling, on top of Phase 6/10)
- **Component:** `app/web_chat/intent_classifier.py`, surfaced via `POST /chat/message` (`app/web_chat/routes.py`)
- **What broke (symptom):** `python3 scripts/test_web_chat.py` Case 3 got `500 Internal Server Error` on `POST /chat/message` for the message `"hi"`. Server traceback: `app.reasoning.agent.ReasoningError: Agent did not converge on a recommendation within 6 tool iterations.` — i.e. "hi" was sent into the full Phase 2 LLM recommend() pipeline instead of being caught as small talk.
- **What we were trying to do:** Verifying Part A (small-talk classification) — sending "hi" through the new web chat endpoint and expecting the canned friendly reply, never touching the catalog/recommendation logic.
- **Root cause:** `classify_intent()` called Groq's `openai/gpt-oss-120b` with `max_tokens=5`. That model spends tokens on internal reasoning before emitting its final answer; with only 5 tokens available, the response was cut off (`finish_reason: "length"`) with `content=""` before any answer token was produced. The classifier's fail-open behavior (`"small_talk" in "" → False`) then silently returned `"product_request"`, so "hi" was routed into `recommend()`, which the LLM reasoning core couldn't resolve into a real product and eventually raised `ReasoningError` — uncaught in `chat_message()`, so FastAPI returned a 500.
- **How we solved it:** Reproduced directly against the Groq API outside the app, sweeping `max_tokens` (5 → empty, 20 → empty, 50 → `"small_talk"`, `finish_reason: "stop"`). Raised `max_tokens` from 5 to 60 in `intent_classifier.py` to leave room for the model's internal reasoning plus the one-word answer. Re-ran `scripts/test_web_chat.py` — Case 3 passed, "hi" now gets the canned greeting, and a real request sent afterward in the same session still completes normally.
- **Tools/resources used:** Direct Groq SDK calls from a Python REPL to isolate `max_tokens` vs. `finish_reason`/`content`, the `test_web_chat.py` server traceback.
- **Time lost:** ~10 minutes.
- **Status:** Resolved

### 3 — Classifier silently skipped after the first order completed (DONE state not treated as "fresh request")
- **Date/Time:** 2026-08-23
- **Phase:** React frontend addition (browse-intent feature, on top of the web chat backend)
- **Component:** `app/web_chat/routes.py` (`chat_message`), interacting with `app/chat_adapter/adapter.py` (`ChatSession`, unmodified)
- **What broke (symptom):** Live in the new React frontend: after completing one order (session state `DONE`), sending "show me the products you own, lemme browse" did **not** trigger the browse-intent button — it went straight into the full LLM `recommend()` pipeline and came back with a generic "you haven't specified any particular preference" reply instead of the catalog-navigation button.
- **What we were trying to do:** Manually verifying the new browse-intent classification live in the browser, in the same chat session right after successfully placing an order (a realistic continued-conversation scenario).
- **Root cause:** `chat_message()`'s classification gate was `if record.chat_session.state == ChatState.AWAITING_REQUEST`. But `ChatSession.handle_message()` itself only special-cases `AWAITING_CONFIRMATION` — every other state, including `DONE` (a just-completed or just-cancelled order), falls through to `_handle_request()` and is treated as a fresh request. The classifier's gate didn't match that: it only fired in the session's very first `AWAITING_REQUEST` state, so any message sent after a session reached `DONE` bypassed classification entirely and went straight into `ChatSession.handle_message()` → `recommend()`.
- **How we solved it:** Changed the gate condition to `if record.chat_session.state != ChatState.AWAITING_CONFIRMATION`, mirroring `ChatSession.handle_message()`'s own routing logic exactly (classify whenever ChatSession itself would call `_handle_request()`). No change to `ChatSession` or any core Phase 1-10 logic — fix is entirely in the web routing layer. Re-tested live: the same message in the same post-order session now correctly returns the browse-intent reply with the navigation button.
- **Tools/resources used:** Live browser walkthrough (Browser pane) reproduced it directly; fix verified by re-running the same conversation.
- **Time lost:** ~10 minutes.
- **Status:** Resolved

### 4 — React frontend totally unresponsive: Send button and Enter key both silently did nothing
- **Date/Time:** 2026-08-23
- **Phase:** React frontend (`frontend/`), `ChatView.jsx`'s session-init effect
- **Component:** `frontend/src/components/ChatView.jsx` (`useEffect` init logic + `handleSend()`)
- **What broke (symptom):** In the live, already-running frontend (localhost:5173) against the live backend (127.0.0.1:8000), typing a message and clicking "Send" did nothing — no user bubble appeared, the input text stayed in the box, no network request fired at all, and no error was visible anywhere in the UI. Pressing Enter had the same effect. Reported by the user as "unresponsive."
- **What we were trying to do:** Nothing — this was a bug report investigation. Instructed to check CORS mismatch, fetch target URLs, and both the button's onClick and the input's onKeyDown wiring, then reproduce live and fix.
- **Root cause — ruled out first:**
  - **Not CORS.** Simulated the exact browser preflight (`curl -i -X OPTIONS .../chat/start -H "Origin: http://localhost:5173" ...`) against the live backend — correct `access-control-allow-origin: http://localhost:5173` came back. Confirmed independently by running a raw `fetch()` to `POST /chat/message` directly from the live page's own console — it succeeded and returned real JSON. CORS was fully correctly configured and working; the symptom just resembled a classic CORS failure (silent, no visible error) closely enough to be the natural first suspect.
  - **Not the onClick/onKeyDown wiring itself.** `read_page` and a direct DOM query confirmed the Send button was present, not disabled, and correctly labeled; the input still held the typed text (proving `setInput("")` inside `handleSend()` never ran) and zero network requests were ever issued for `/chat/message` — meaning `handleSend()` was returning immediately at its very first guard clause, before reaching either the state updates or the `fetch` call.
  - **Actual root cause:** `handleSend()`'s guard is `if (!text || !sessionId || sending) return;` — and `sessionId` (React state) was permanently stuck at its initial value of `null`. Traced to the session-init `useEffect`: an earlier fix (Entry 3's neighboring change, made to stop React StrictMode's dev-only double-invoke from firing two `POST /chat/start` calls) added an `initStarted` ref guard that makes the *second* StrictMode invocation of the effect a complete no-op — including never registering a new cleanup function. But StrictMode still calls the *cleanup* of the *first* (real) invocation as part of its synthetic unmount/remount cycle. That cleanup set the effect's local `cancelled` flag to `true` while the first invocation's async `init()` (the one actually doing real work — `chatStart()`, `chatHistoryRaw()`, etc.) was still in flight. When that async work finally resolved and reached `if (!cancelled) setSessionIdState(sid);`, `cancelled` was already `true`, so the call was silently skipped — permanently. Every subsequent click of Send or press of Enter hit the `!sessionId` guard and returned immediately, with no fetch ever attempted. (The `POST /chat/start` network call itself always succeeded — that's what masked the bug in the *previous* turn's regression check, which only confirmed a single `/chat/start` call was made and the page rendered, but never re-clicked Send afterward to confirm `sessionId` state was actually usable.)
  - **Confirmed by direct trace**, not guesswork: read the exact `useEffect` source, identified the `initStarted` ref + `cancelled` closure interaction, then verified via DOM/console inspection (input still had typed text, zero network requests, button not disabled) that this exact mechanism matched the observed symptom before touching any code.
- **How we solved it:** Removed the `cancelled` flag and its cleanup function entirely from the effect — the `initStarted` ref already guarantees the effect's body (and therefore `init()`) runs exactly once across StrictMode's double-invoke, so the extra flag was not just redundant but actively wrong once combined with the ref guard. `init()` now unconditionally calls `setSessionIdState(sid)` when it finishes. No change to `ChatSession`, `gate.py`, the backend, or any Phase 1-10 logic — the entire fix is inside `ChatView.jsx`.
- **Tools/resources used:** `lsof`/`ps` to find the user's own already-running backend + frontend processes and reuse them for reproduction instead of starting duplicates; `curl` to simulate the CORS preflight directly; the Browser pane (`read_console_messages`, `read_network_requests`, `read_page`, `javascript_exec`) to inspect live DOM/state and dispatch a real `KeyboardEvent{key:"Enter"}` to distinguish a genuine handler bug from an automation-tool key-naming quirk (confirmed it's the latter — the tool's synthetic "Return" keypress doesn't always produce `e.key === "Enter"`, harmless for real keyboards).
- **Time lost:** ~25 minutes.
- **Status:** Resolved — re-verified live: typed a request, pressed a real `Enter` keydown (via `dispatchEvent`) to confirm the order, and a real Razorpay test-mode order was created and displayed with its Order ID. Also re-confirmed the Send button path separately in the same session.

### 5 — Explicit quantity in a buyer request was silently dropped, substituting an unrelated upsell instead
- **Date/Time:** 2026-08-23
- **Phase:** Agent Reasoning Core (Phase 2), surfaced through the Chat Adapter (Phase 6) and Gate (Phase 3)
- **Component:** `app/reasoning/tools.py` (`propose_recommendation` schema), `app/reasoning/agent.py` (`SYSTEM_PROMPT`, `_build_result()`), `app/chat_adapter/adapter.py` (`ChatSession._handle_request()` amount calculation)
- **What broke (symptom):** Reported by the user from manual testing: sending "Tell me about the AlpineGuard Winter Tent x 2" (a single product, explicit quantity of 2, no upsell requested) produced a recommendation of **1x AlpineGuard Winter Tent (Rs.8,999) + 1x Arctic Pro Sleeping Bag as an unrequested upsell (Rs.2,799)**, total Rs.11,798 — instead of 2x AlpineGuard Winter Tent, total Rs.17,998. The explicit "x 2" was ignored entirely and a completely unrelated product (a sleeping bag, not a tent accessory) was substituted in as if it were the correct answer.
- **What we were trying to do:** Investigating a reported correctness bug, per explicit instructions: (1) check whether the classifier/`recommend()` parses quantity at all, (2) reproduce directly against `recommend()` to confirm, before touching any code.
- **Root cause — confirmed by direct reproduction before any fix:** Ran `recommend('Tell me about the AlpineGuard Winter Tent x 2')` directly. The `propose_recommendation` tool schema (`app/reasoning/tools.py`) had **no `quantity` field at all** — only `no_match`, `primary_product_id`, `upsell_product_id`, `reasoning`. The model's own `reasoning` text in the repro *did* correctly understand the request ("comfortably fulfills the request for two tents"), but had no structured field to express that quantity in, so `_build_result()` had nothing to read and the calling code (`ChatSession._handle_request()`) always computed `amount_paise = primary.price_paise + upsell.price_paise` — i.e. quantity was architecturally impossible to represent, not merely mis-parsed. Faced with a shape that has no room for "2 of the same item," the model fell back to its default single-item-plus-upsell behavior, which is what produced the unrelated Arctic Pro Sleeping Bag substitution — a direct side effect of the missing field, not a separate bug.
- **How we solved it:**
  1. Added a `quantity` field (integer, default 1) to the `propose_recommendation` tool schema, documented as applying only to the primary product, never the upsell.
  2. Updated `SYSTEM_PROMPT` to explicitly instruct: parse explicit quantity language ("x2", "2x", "two of", "a couple of") into `quantity`; the upsell is always exactly one unit and must never substitute for or be confused with the primary's quantity.
  3. Added `_parse_quantity()` in `agent.py` to defensively coerce the model's `quantity` argument to a positive int (falls back to 1 on anything missing/invalid — never 0, negative, or non-numeric), and added `quantity` to `_build_result()`'s returned dict and its `recommendation` audit log entry.
  4. Fixed `ChatSession._handle_request()` (`app/chat_adapter/adapter.py`) — the actual amount the Gate evaluates — to compute `amount_paise = primary.price_paise * quantity + (upsell.price_paise if present)`, and updated the confirmation reply text to say "2x AlpineGuard Winter Tent (Rs.8999.00 each, Rs.17998.00 total)" when quantity > 1, unchanged wording when quantity == 1.
  - Per the bug report's explicit guidance, an upsell may still be legitimately offered alongside an explicit-quantity primary (it's additive, not a substitution) — the fix's correctness bar is that the primary's product and quantity are always right and the true total is `unit price × quantity (+ optional single-unit upsell)`, never a silently wrong product/quantity.
- **Verification:** Reproduced the exact failing case again post-fix — quantity correctly returned as 2, primary correctly AlpineGuard Winter Tent (id=8). New `scripts/test_quantity_handling.py` covers three cases end-to-end through the real `ChatSession` + `check_gate()` (not just `recommend()` in isolation): (1) AlpineGuard x2 → Rs.17,998+ total, Gate correctly rejects (>Rs.5,000); (2) CloudRest Sleeping Pad x2 → Rs.998, Gate correctly approves, real order created; (3) Scenario A with no quantity mentioned → quantity=1, Arctic Pro + CloudRest upsell, completely unaffected — no regression. Full existing test suite (all 9 prior scripts) re-run clean. Also verified live in the browser with the exact reported message.
- **Tools/resources used:** Direct Python reproduction against `recommend()` (before and after the fix) to confirm root cause and fix without guesswork; `scripts/test_quantity_handling.py` for regression coverage; live browser walkthrough with the exact reported request.
- **Time lost:** ~20 minutes.
- **Status:** Resolved

### 6 — No way to accept the primary item without also accepting the bundled upsell
- **Date/Time:** 2026-08-23
- **Phase:** Chat Adapter (Phase 6), `ChatSession`'s confirmation state
- **Component:** `app/chat_adapter/adapter.py` (`ChatSession._handle_confirmation()`, previously a strict yes/no binary)
- **What broke (symptom):** Reported from manual testing: "Tell me about the ExpeditionMax 65L Backpack" recommended the backpack (Rs.5,499) plus a CloudRest Sleeping Pad upsell (Rs.499), total Rs.5,998, and asked for yes/no confirmation. A buyer trying to decline just the upsell (e.g. replying "i just want the [item]") got treated as unrecognized input and re-asked the same yes/no question — with no way to proceed with just the primary item short of cancelling the entire order and starting over. This was a real product gap: `_AFFIRMATIVE`/`_NEGATIVE` were the only two recognized outcomes at confirmation, and the entire pending amount (primary + upsell together) was the only amount ever gated.
- **What we were trying to do:** Fixing a reported UX/product gap under explicit design constraints: never loosen `AWAITING_CONFIRMATION`'s strictness (no accidental full-order approval), recognize only a small, explicit set of unambiguous primary-only phrases (never guess), always re-run `check_gate()` against the smaller correct amount before creating a primary-only order, and leave the no-upsell flow completely untouched.
- **Root cause:** Architectural, not a wording bug — `ChatSession._pending` only ever stored one combined `amount_paise` (primary + upsell together), and `_handle_confirmation()` only recognized two outcomes. There was no code path that could compute, gate, or order a smaller "primary only" amount at all — declining the upsell had nowhere to go except full cancellation.
- **How we solved it:**
  1. `_pending` now stores `primary`, `upsell`, `quantity`, the full bundle `amount_paise` (unchanged key/semantics, so existing tests reading it still work), and a new `primary_only_amount_paise` (`primary.price_paise * quantity`, upsell excluded).
  2. Added `_matches_primary_only()` — a small, explicit, name-aware matcher: a fixed generic phrase set ("primary only", "no upsell", "skip the upsell", etc.), plus two dynamic patterns: "just/only" + the primary product's name, and "without/no/not/skip" + the upsell product's name. Anything that doesn't clearly match is left to the existing clarifying re-ask — never guessed at, never defaulted to approval.
  3. `_handle_confirmation()` now checks, in order: negative (unchanged — full cancel, no Gate check) → primary-only match (only possible when an upsell exists) → affirmative (unchanged — full bundle) → clarifying re-ask (now lists all three options when an upsell is present, still just yes/no when it isn't).
  4. Both the full-bundle and primary-only paths route through the same `_confirm()` helper, which calls `check_gate()` fresh with whichever amount applies (`amount_paise` or `primary_only_amount_paise`) — primary-only is never a shortcut around the Gate. Confirmed by a genuine edge case found during testing: the ExpeditionMax 65L Backpack alone (Rs.5,499) already exceeds the Rs.5,000 bound, so "primary only" on that item correctly still gets rejected by the Gate — proving the re-check is real, not a rubber stamp.
  5. The turn-1 prompt now says "Confirm both items for Rs.X? Reply 'yes' for both, 'primary only' for just the [item] at Rs.Y, or 'no' to cancel." *only* when an upsell was offered; with no upsell, the original two-way "Confirm order for Rs.X?" wording is completely unchanged (constraint 5).
  6. The audit log needed no new plumbing — `check_gate()` and `create_order()` already log the exact `amount_paise` passed to them, so the trail naturally shows which amount was gated and ordered for either path; the primary-only path's `reasoning` also gets an appended note identifying it as primary-only.
- **Side effects caught and fixed as part of this change (not separate bugs, but real regressions that had to be fixed before this could ship):**
  - `frontend/src/components/ChatView.jsx`'s `detectStatus()` matched confirmation prompts via `/Confirm order for Rs\./` — this no longer matches the new "Confirm both items for Rs." wording used whenever an upsell is present, silently dropping the "awaiting confirmation" status card. Added a second regex for the new wording.
  - Several existing tests asserted the literal substring `"Confirm order"` on Scenario-A-style requests (which always include the CloudRest Sleeping Pad upsell, so they now correctly say "Confirm both items"): `scripts/test_chat_adapter.py` Case 1, and `scripts/test_web_chat.py` Cases 1, 3, 5, 6. Updated all of them to assert the new (correct) wording — this is expected test maintenance for a deliberate behavior change, not a hidden regression.
- **Verification:** New `scripts/test_upsell_decline.py`, 7 cases: accept-both (unchanged), primary-only accepted (Gate approves the smaller amount, real order for that amount only), primary-only via a natural "I just want the X" phrase (Camp Cook Set), primary-only still correctly rejected when the primary alone exceeds the bound (ExpeditionMax), full decline (unchanged, still zero Gate checks), ambiguous input (clarifying re-ask, zero Gate checks, session recovers), and the no-upsell/quantity regression check. Full existing suite (all 11 prior scripts, including Entry 5's quantity handling) re-run clean after updating the wording-dependent assertions. Verified live in the browser with both the ExpeditionMax case (primary-only correctly rejected) and the Camp Cook Set case (primary-only correctly approved with a real order).
- **Tools/resources used:** Direct Python reproduction of both named scenarios before writing any test, to discover the ExpeditionMax edge case ahead of time rather than being surprised by it; `scripts/test_upsell_decline.py`; live browser walkthrough.
- **Time lost:** ~40 minutes (a genuinely larger fix, as flagged — state machine change plus cascading wording updates across the frontend and four existing test files).
- **Status:** Resolved

### 7 — "Catalog matching bug" (Bug 1) was misattributed: real cause was Groq daily-quota exhaustion behind a misleading error message
- **Date/Time:** 2026-08-23
- **Phase:** Web Chat layer (`app/web_chat/routes.py`), investigating a report against Phase 2's `recommend()`
- **Component:** `app/web_chat/routes.py` (`chat_message`'s `ReasoningError` handling — now `_reasoning_error_reply()`). **Not** `app/catalog/service.py`, **not** `app/reasoning/agent.py`'s tool-calling — both were confirmed correct.
- **What broke (symptom):** Reported as a suspected catalog-matching defect, broader than Entry 5's quantity bug: "Tell me about the Compact 20L Backpack" (no quantity suffix at all) got "Sorry, I had trouble finding a match for that." The instruction to compare against "Arctic Pro Sleeping Bag" (which worked) implied something about specific product names broke matching in general.
- **What we were trying to do:** Reproduce directly against `recommend()`, isolate what differs between a working product name and a failing one, per explicit instructions — and *not* touch the Entry 6 primary-only confirmation fix while doing it.
- **Root cause — found by capturing the full tool-call trace, not by guessing:** First ruled out the catalog layer entirely with zero LLM cost — `search_by_keyword('Compact 20L Backpack')`, `search_by_keyword('Compact')`, and `search_by_category('backpacks')` all correctly found product id 12 every time. Then ran one diagnostic `recommend()` call with a pre-generated `transaction_id` (so the audit trail would be readable even if the call raised), and inspected the trail: the model's *first* tool call was `search_by_keyword('Compact 20L Backpack')`, which correctly returned exactly the right product. The failure happened on the model's *second* API call (to finalize via `propose_recommendation`) — `429 rate_limit_exceeded`, `tokens per day (TPD): Limit 200000, Used 199997`. The Groq daily quota was, at that exact moment, essentially fully consumed by this session's own extensive testing (Entries 5 and 6, plus the live-verification wait earlier). **The catalog match had already succeeded** before the failure occurred.
  - The actual defect: `chat_message()`'s `except ReasoningError` handler used one fixed message — "Sorry, I had trouble finding a match for that — could you rephrase your request?" — for *every* cause of `ReasoningError` (missing API key, Groq API/network failure, or genuine tool-loop non-convergence). That wording asserts "no match," which is only true for one of those causes and was false in this exact case. A transient, external rate-limit failure was indistinguishable, from the buyer's perspective, from "this product doesn't exist" — which is exactly why a real infra hiccup got reported as a suspected catalog bug.
- **How we solved it:** Extracted the reply-selection logic into `_reasoning_error_reply(exc)` in `routes.py`. It now inspects the exception text: a rate-limit failure (`"rate_limit"` / `"429"` in the message) gets "NEXUS is temporarily at capacity... this isn't about the product, please try again in a moment"; any other `ReasoningError` gets a generic "temporary issue... please try again" — neither wording claims a product doesn't exist or that no match was found. Purely a message-selection change in the web layer; `ChatSession`, `gate.py`, the Entry 6 confirmation-flow logic, and the actual `recommend()`/catalog-matching code were not touched.
- **Verification:** New `scripts/test_bug1_catalog_matching.py`. Case 1 (zero LLM cost) proves the catalog layer matches both "Compact 20L Backpack" and "DayHiker 25L Backpack" correctly by full name, partial name, and category. Case 2 (zero LLM cost) unit-tests `_reasoning_error_reply()` directly against a synthetic rate-limit exception and a synthetic generic exception, asserting neither reply ever contains "no match" / "trouble finding a match" / "doesn't exist." Cases 3-4 reproduce both originally-reported requests ("Compact 20L Backpack" with no suffix, and "DayHiker 25L Backpack x2" — Entry 5-style quantity, on a *different* product than AlpineGuard to broaden coverage) end-to-end through the real `recommend()`; they gracefully skip (not fail) if Groq quota is still exhausted when run, logging the same 429 this investigation hit, which is expected and consistent with this entry's finding — not a new failure. Re-run once quota clears to get the full green pass.
- **Tools/resources used:** Direct catalog-service calls (no LLM) to rule out the data/query layer first; one diagnostic `recommend()` call with an explicit `transaction_id` to capture the full audit trail of tool calls regardless of outcome — this was the single most useful technique, since it showed the *correct* catalog match happening right before the failure, rather than leaving the failure's timing ambiguous.
- **Time lost:** ~15 minutes (fast once the audit-trail trace was captured — the transaction_id technique made the root cause unambiguous on the very first diagnostic call).
- **Status:** Resolved (message-misattribution fixed and verified at zero cost; end-to-end re-confirmation of both exact reported requests is pending Groq quota recovery — same external blocker as Entry 6's live verification).

### 8 — Groq model occasionally hallucinates a malformed tool-call name (`<|channel|>commentary` leak)
- **Date/Time:** 2026-08-24
- **Phase:** Build of the Metrics module (`app/metrics/`); hit while re-running the full backend regression suite for verification, unrelated to the metrics work itself
- **Component:** External — Groq's `openai/gpt-oss-120b` model, surfaced through `app/reasoning/agent.py`'s tool-calling loop. No NEXUS code is at fault.
- **What broke (symptom):** `scripts/test_quantity_handling.py` Case 1 ("AlpineGuard Winter Tent x 2") failed with an uncaught `ReasoningError`: `groq.BadRequestError: Error code: 400 - Tool call validation failed: attempted to call tool 'search_by_category<|channel|>commentary' which was not in request.tools`. The model emitted a tool name with an internal special token (`<|channel|>commentary` — part of this model's "harmony" response format) leaked into it, which Groq's API correctly rejects as not matching any real registered tool.
- **What we were trying to do:** Running the full 12-script regression suite to confirm the metrics module's changes (the two new `order_declined`/`confirmation_unclear` event types in `adapter.py`) didn't regress anything else.
- **Root cause:** Not a NEXUS bug. This is the second time this exact failure mode has been observed today (the first was during a Groq-quota recovery check, on a *different* request — "ExpeditionMax 65L Backpack" — confirming it's a genuine, low-frequency, model-side quirk rather than a one-off tied to a specific prompt). `openai/gpt-oss-120b` occasionally emits its internal channel-routing tokens as part of the function name in a tool call; Groq's server-side validation then rejects the whole request with a 400, which `recommend()` correctly wraps as a `ReasoningError` — but nothing in the pipeline retries on this specific, almost-certainly-transient failure class.
- **How we solved it:** Nothing in NEXUS's code needed to change to resolve *this* instance — re-ran `scripts/test_quantity_handling.py` alone immediately after, with no code changes, and it passed cleanly (see below). Did not add automatic retry logic for this failure class right now, since it's out of scope for the metrics task this was found during and the existing behavior (surface a clear error rather than silently retry into more quota spend) is a defensible default; flagging it as a good candidate for a future small hardening (e.g. one retry specifically on `tool_use_failed` / malformed function names) rather than doing it as an unplanned addition here.
- **Verification:** Re-ran `scripts/test_quantity_handling.py` standalone — all 3 cases passed. The other 11 regression scripts in the same suite run (`test_catalog` through `test_bug1_catalog_matching`) all passed on the first attempt, confirming this was an isolated, transient hit on one specific call, not a systemic issue introduced by the metrics module's changes.
- **Tools/resources used:** Direct comparison against the earlier `<|channel|>commentary` occurrence (Groq quota-recovery check, prior session turn) to recognize the pattern; a clean standalone re-run to confirm transience.
- **Time lost:** ~5 minutes (mostly just re-running the one script).
- **Status:** Resolved by retry (no code change needed for this instance); noted as a candidate for future retry-hardening in `app/reasoning/agent.py`.

---

### 9 — Entry 8's Groq flakiness recurred twice during the quantity-ask / continue-shopping regression run
- **Date/Time:** 2026-08-25
- **Phase:** Chat Adapter enhancement (AWAITING_QUANTITY + AWAITING_CONTINUE_SHOPPING states, `app/chat_adapter/adapter.py`)
- **Component:** External — Groq's `openai/gpt-oss-120b` model, surfaced through `app/reasoning/agent.py`'s tool-calling loop. No NEXUS code is at fault.
- **What broke (symptom):** Two separate hits while re-running the full regression suite after adding the new quantity-ask and continue-shopping states: (1) `scripts/test_upsell_decline.py` Case 2c ("Tell me about the ExpeditionMax 65L Backpack") failed with the same `<|channel|>commentary` malformed-tool-name `groq.BadRequestError` as Entry 8, on the exact same request text Entry 8 first saw it on; (2) `scripts/test_metrics.py` Step E, same request, failed with `app.reasoning.agent.ReasoningError: Agent did not converge on a recommendation within 6 tool iterations` — a different symptom, same underlying model flakiness on this specific request/product combination.
- **What we were trying to do:** Running the full regression suite (`test_chat_adapter`, `test_quantity_handling`, `test_upsell_decline`, `test_metrics`, `test_failure_injection`, `test_web_chat`, plus the new `test_quantity_ask_and_continue_shopping.py`) to confirm the two new ChatSession states (Part A: ask for quantity when unspecified; Part B: continue-shopping loop after any terminal order outcome) didn't regress any existing behavior.
- **Root cause:** Not a NEXUS bug — confirmed identical to Entry 8's root cause (the model occasionally leaks internal channel-routing tokens into a tool-call name, or simply fails to converge, independent of any NEXUS code). Both failures landed on the same "ExpeditionMax 65L Backpack" request across two different test files, in the same run, reinforcing Entry 8's note that this is a low-frequency but real, request-independent model quirk rather than a one-off.
- **How we solved it:** No code change. Re-ran `scripts/test_upsell_decline.py` and `scripts/test_metrics.py` standalone immediately after with zero changes — both passed cleanly on retry (see below). Still not adding automatic retry logic in `app/reasoning/agent.py` for this specific failure class, for the same reasons Entry 8 gave.
- **Verification:** Full regression suite passed end-to-end after the two retries: `test_catalog`, `test_gate`, `test_audit`, `test_reasoning`, `test_chat_adapter`, `test_quantity_handling`, `test_upsell_decline`, `test_bug1_catalog_matching`, `test_failure_injection`, `test_metrics`, `test_web_chat`, `test_razorpay_integration`, `test_agent_api_scoutbot`, and the new `test_quantity_ask_and_continue_shopping.py` — all exit 0. Also verified live in the browser: a real 3-product shopping session (Arctic Pro Sleeping Bag, TrailChef Portable Stove, CloudRest Sleeping Pad) via `/chat`, then confirmed on `/stats` that Total Orders increased by exactly 3 (39 -> 42), each with its own transaction_id and audit trail.
- **Tools/resources used:** Direct comparison against Entry 8's exact wording and request text; standalone re-runs to confirm transience, same method as Entry 8.
- **Time lost:** ~10 minutes across both retries.
- **Status:** Resolved by retry (no code change needed); reinforces Entry 8's existing candidate note for future retry-hardening around `tool_use_failed` / non-convergence in `app/reasoning/agent.py`.

---

### 10 — "Nothing" at AWAITING_CONTINUE_SHOPPING silently reset the conversation instead of ending it
- **Date/Time:** 2026-08-25
- **Phase:** Chat Adapter enhancement (AWAITING_CONTINUE_SHOPPING, `app/chat_adapter/adapter.py`), found during live browser testing of Part B
- **Component:** Chat Adapter (`app/chat_adapter/adapter.py`, `ChatSession._handle_continue_shopping`)
- **What broke (symptom):** After an order attempt, at the "Would you like to look at anything else?" prompt, replying "Nothing" did not end the session the way an explicit "no" does. Instead the conversation behaved as if it had been reset back to a fresh/finished state, surfacing the opening greeting-style behavior on the next turn instead of a clean goodbye.
- **What we were trying to do:** Live-testing the AWAITING_CONTINUE_SHOPPING flow in the browser after multiple product orders, replying with a natural decline ("Nothing") instead of the literal word "no".
- **Root cause:** `_handle_continue_shopping()` only recognized the general `_NEGATIVE` set (`"no", "n", "nope", "nah", "cancel", "don't", "dont", "stop", "never mind", "nevermind"`) as a decline. `"nothing"` was not in that set, so it fell through to the "anything else is an implicit new product request" branch, which set `self.state = ChatState.AWAITING_REQUEST` and called `self._handle_request("Nothing")` directly. That called `recommend("Nothing", ...)`, which correctly no-matched, and `_handle_request`'s no-match branch then set `self.state = ChatState.DONE` — leaving the session in the same terminal state as a genuinely fresh/finished one, indistinguishable to `app/web_chat/routes.py`'s intent-classifier gate (which treats `AWAITING_REQUEST`/`DONE` identically). The next buyer message was then classified fresh, which is what surfaced as "resetting to the opening greeting" rather than a clean end.
- **How we solved it:** Added a new, dedicated `_CONTINUE_SHOPPING_NEGATIVE_PHRASES` set in `app/chat_adapter/adapter.py` — a superset of `_NEGATIVE` plus `"nothing"`, `"nothing else"`, `"nothing more"`, `"not really"`, `"that's all"` / `"thats all"`, `"that's it"` / `"thats it"`, `"that'll be all"`, `"thats all for now"`, `"i'm done"` / `"im done"` / `"i am done"`, `"i'm good"` / `"im good"`, `"no thanks"`, `"no thank you"`, `"bye"`, `"goodbye"`, `"good bye"`, `"done"`, `"all done"` — scoped to this one state only (left the general `_NEGATIVE` set used by `_handle_confirmation` untouched, since some of these phrases would be ambiguous in a yes/primary-only/no order-confirmation context but are unambiguous answers to "anything else?"). `_handle_continue_shopping` now checks against this wider set before falling through to the implicit-new-request branch.
- **Verification:** Added Cases 7-9 to `scripts/test_quantity_ask_and_continue_shopping.py`. Case 7 and Case 9 were built to exercise `_handle_continue_shopping()`'s own decision logic directly (a session placed straight into `AWAITING_CONTINUE_SHOPPING`, no LLM call needed) and both **passed**: Case 7 confirmed "nothing", "nope", "that's all", "bye", "nothing else", "i'm done", "no thanks", "goodbye" all end the session cleanly (same reply/state as an explicit "no", zero new audit events); Case 9 confirmed a genuinely ambiguous reply ("maybe") still re-asks instead of guessing or resetting. Case 8 (the reverse check — a real new request must still start a fresh cycle, not get misclassified as a decline) has two sub-cases requiring real Groq calls: sub-case 8a ("yes, show me tents") **passed**, correctly recommending a tent via a fresh, independent transaction. Sub-case 8b (a bare product mention, "AlpineGuard Winter Tent", no "yes" prefix) and the live-browser re-check of the exact reported "Nothing" input are **still pending** — blocked by the project's Groq `openai/gpt-oss-120b` daily token quota (200,000 TPD), which was oscillating in a saturated 199,075-199,685 band for 45+ minutes across six wait-and-retry cycles without opening enough headroom, evidently from other concurrent activity on the same account, not from this work. Given the code path 8b would exercise is a strict subset of what 8a already proved (same `_handle_request`/`recommend()` call, just skipping the now-verified `_strip_leading_affirmative` no-op case), and the fix itself never touches that branch's code at all, this is considered low-risk but explicitly unconfirmed. **To finish:** once the Groq quota has headroom, run `python3 scripts/test_quantity_ask_and_continue_shopping.py` (or just `case_8_continue_shopping_real_new_request_still_works` for the fast path) and repeat the live browser "Nothing" reproduction, then update this entry.
- **Tools/resources used:** Live browser reproduction of the exact reported input; re-read of `app/web_chat/routes.py`'s classifier gate to trace the two-turn mechanism; repeated Groq quota-usage messages to confirm the block was external/saturated rather than a code issue.
- **Time lost:** ~20 minutes diagnosis + fix + new tests, plus 45+ minutes of blocked wait-and-retry cycles on the Groq daily quota for the remaining live-LLM verification (sub-case 8b, live browser re-check) — paused per user decision, to resume once quota is available.
- **Status:** Workaround in place — code fix is in and verified against the exact buggy code path (Cases 7 and 9) plus one real-LLM reverse-check (8a); sub-case 8b and the live browser re-check remain open pending Groq quota availability.

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
