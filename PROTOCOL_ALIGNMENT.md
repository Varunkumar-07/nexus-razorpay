# Protocol Alignment

How NEXUS's mechanisms relate to the real agentic-payments protocol layer the buildathon brief is written against — and, just as importantly, where that relationship ends.

## The real context

This isn't a hypothetical trend. Specific, current work:

- **NPCI's Unified Agent Protocol (UAP)** — under development as an authorization layer for AI agents transacting over UPI. Its design goals are explicit: spending limits, user consent, and audit trails, layered *above* existing payment rails rather than replacing them.
- **Razorpay x NPCI live pilot (Feb 2026)** — a real agentic-payments pilot run with Claude, in partnership with Zomato, Swiggy, and Zepto. It used one-time consent plus per-merchant spending limits, so an agent could transact without repeated PIN/OTP entry per purchase.
- **Parallel global protocols, same shape** — Google's Agent Payments Protocol (AP2), OpenAI's Agentic Commerce Protocol (ACP), and Visa's Trusted Agent Protocol (TAP) are all converging on the same primitives: bounded spend, explicit consent, and machine-readable authorization for agent-initiated purchases.

The pattern across all four is consistent: don't let an agent move money without a bound on how much, proof that a human or policy consented, and a record of why.

## Where NEXUS's mechanisms map to that pattern

| NEXUS mechanism | Maps to |
|---|---|
| **The Gate** — amount ≤ Rs.5,000, explicit confirmation required, non-empty reasoning required before any order can be created (`app/gate/gate.py`) | The spending-limit + consent pattern UAP, AP2, ACP, and TAP each formalize as a precondition for agent-initiated payment. NEXUS's Rs.5,000 bound is a hardcoded analogue of a per-agent/per-merchant spending limit; its confirmation check is a minimal analogue of the consent step the Razorpay×NPCI pilot implemented as one-time consent. On the Agent API path specifically, the amount the Gate checks is derived server-side from the prior `/recommend` call (`app/agent_api/recommendation_store.py`), never from the caller-supplied `amount_paise` on `/order` — so neither entry point can talk its way into a different charge than what was actually recommended. |
| **The Audit Log** — one row per pipeline event, threaded by `transaction_id`, covering every recommendation, gate check, order, and rejection (`app/audit/audit_log.py`) | The audit trail requirement that is explicitly part of UAP's stated design goals — a durable, queryable record of what an agent did and why, independent of the payment rail itself. |
| **The Agent API Adapter** — a documented, structured HTTP endpoint (`/recommend`, OpenAPI docs at `/docs`) that a separate AI agent (ScoutBot) calls over real HTTP, with no human in that loop (`app/agent_api/`) | The "agent-readable catalog" and "agent authorization" primitives these protocols are standardizing: a merchant surface an agent can query and act against directly, distinct from the human-facing UI, gated by the same authorization layer. |

## What this is not

NEXUS is **not** a UAP, AP2, ACP, or TAP implementation. It does not speak any of their wire formats, does not integrate with NPCI, Razorpay's pilot infrastructure, Google, OpenAI, or Visa's systems, and makes no claim of protocol compliance or certification with any of them.

What it demonstrates is the same underlying trust primitives these protocols are built around — bounded, gated, audited agent action — implemented from scratch, in miniature, against Razorpay's test-mode API. The Rs.5,000 bound is not a regulatory limit; the confirmation check is not cryptographic consent; the Audit Log is not a compliance-grade ledger. They are a small, honest demonstration of the same shape of problem this real protocol layer exists to solve, built to be legible in a five-minute pitch — not a submission for adoption into any of the systems named above.
