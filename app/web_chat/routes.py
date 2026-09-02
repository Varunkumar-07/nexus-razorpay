"""HTTP routes for the Web Chat UI.

A thin wrapper over the existing, fully-tested Phase 6 ChatSession — no
changes to its state machine, confirmation flow, or any gate/order/audit
logic. Every call here does exactly what scripts/chat_cli.py already
does (session.handle_message(text)), just over HTTP with server-side
session persistence instead of a local Python loop. Every event this path
produces is still tagged source="chat" in the Audit Log, because it's the
same ChatSession code (app/chat_adapter/adapter.py) doing the work.
"""

from typing import List, Optional

from fastapi import APIRouter, HTTPException
from pydantic import BaseModel, Field

from app.chat_adapter.adapter import ChatState
from app.reasoning.agent import ReasoningError
from app.web_chat.intent_classifier import (
    BROWSE_CATALOG_ACTION,
    BROWSE_INTENT_REPLY,
    SMALL_TALK_REPLY,
    classify_intent,
)
from app.web_chat.sessions import create_session, get_session

router = APIRouter(prefix="/chat", tags=["web-chat"])


class StartResponse(BaseModel):
    session_id: str = Field(..., description="New session id. Store it (e.g. in a cookie) for later calls.")


class MessageRequest(BaseModel):
    session_id: str = Field(..., description="Session id returned by POST /chat/start.")
    message: str = Field(..., description="The buyer's message for this turn.")


class MessageResponse(BaseModel):
    session_id: str
    reply: str = Field(..., description="The agent's reply for this turn.")
    state: str = Field(
        ...,
        description=(
            "Current ChatSession state: AWAITING_REQUEST, AWAITING_QUANTITY, "
            "AWAITING_CONFIRMATION, AWAITING_CONTINUE_SHOPPING, or DONE."
        ),
    )
    transaction_id: Optional[str] = Field(
        None, description="The transaction_id for the most recent recommendation in this session, if any."
    )
    suggested_action: Optional[str] = Field(
        None,
        description=(
            "Set to 'browse_catalog' when the message was classified as browse "
            "intent — the frontend should render a real navigation button/link "
            "to the Catalog view, not just display it as text."
        ),
    )


class HistoryEntry(BaseModel):
    role: str = Field(..., description="'user' or 'agent'.")
    text: str
    action: Optional[str] = Field(
        None, description="Mirrors suggested_action, so a browse-intent turn still renders its button after a page refresh."
    )


def _reasoning_error_reply(exc: Exception) -> str:
    """Choose the buyer-facing reply for a ReasoningError.

    ReasoningError covers several distinct causes (missing API key, a Groq
    API/network failure, or the model genuinely not converging within its
    tool-call budget) — none of which mean "no product in the catalog
    matches this request." The catalog search itself may well have already
    found the exact right product before the failure occurred. This must
    never claim "no match" for what is actually an infra/capacity problem —
    see FAILURE_LOG.md Entry 7, where that exact wording caused a real
    rate-limit failure to be misdiagnosed as a catalog-matching bug.
    """
    error_text = str(exc).lower()
    if "rate_limit" in error_text or "429" in error_text:
        return (
            "Sorry, NEXUS is temporarily at capacity and couldn't process that "
            "just now — this isn't about the product, please try again in a moment."
        )
    return "Sorry, I ran into a temporary issue processing that request — please try again in a moment."


@router.post(
    "/start",
    response_model=StartResponse,
    summary="Start a new chat session",
    description="Creates a new server-side ChatSession (Phase 6, unmodified) and returns its session_id.",
)
def chat_start() -> dict:
    session_id = create_session()
    return {"session_id": session_id}


@router.post(
    "/message",
    response_model=MessageResponse,
    summary="Send one chat turn",
    description=(
        "Runs the message through the existing ChatSession.handle_message() — "
        "the same two-turn recommend/confirm/order flow used by "
        "scripts/chat_cli.py. Returns the agent's reply, the session's current "
        "state, and the active transaction_id (for audit trail lookup). "
        "When the session is awaiting a fresh request (not a yes/no "
        "confirmation), the message is first classified as small talk, browse "
        "intent, or a product request; small talk gets a friendly canned "
        "reply, browse intent gets a reply plus suggested_action="
        "'browse_catalog' for the frontend to render a real navigation "
        "button — neither reaches the catalog/recommendation pipeline."
    ),
)
def chat_message(payload: MessageRequest) -> dict:
    record = get_session(payload.session_id)
    if record is None:
        raise HTTPException(status_code=404, detail="Unknown session_id. Call POST /chat/start first.")

    record.history.append({"role": "user", "text": payload.message})

    # Classify whenever ChatSession.handle_message() would itself treat this
    # as a fresh request — i.e. AWAITING_REQUEST or DONE (a prior order just
    # finished/was cancelled, both routed to _handle_request()). Every other
    # state expects a specific, narrow reply (a quantity, a yes/no/primary-
    # only, a yes/no/new-request) that ChatSession itself must parse — never
    # detour those through the small-talk/browse-intent classifier.
    if record.chat_session.state in (ChatState.AWAITING_REQUEST, ChatState.DONE):
        intent = classify_intent(payload.message)

        if intent == "small_talk":
            record.history.append({"role": "agent", "text": SMALL_TALK_REPLY})
            return {
                "session_id": payload.session_id,
                "reply": SMALL_TALK_REPLY,
                "state": record.chat_session.state.name,
                "transaction_id": record.chat_session.last_transaction_id,
                "suggested_action": None,
            }

        if intent == "browse_intent":
            record.history.append(
                {"role": "agent", "text": BROWSE_INTENT_REPLY, "action": BROWSE_CATALOG_ACTION}
            )
            return {
                "session_id": payload.session_id,
                "reply": BROWSE_INTENT_REPLY,
                "state": record.chat_session.state.name,
                "transaction_id": record.chat_session.last_transaction_id,
                "suggested_action": BROWSE_CATALOG_ACTION,
            }

    try:
        reply = record.chat_session.handle_message(payload.message)
    except ReasoningError as exc:
        # ChatSession's own state is untouched here (the exception is raised
        # before ChatSession records anything), so the buyer can just retry.
        reply = _reasoning_error_reply(exc)

    record.history.append({"role": "agent", "text": reply})

    return {
        "session_id": payload.session_id,
        "reply": reply,
        "state": record.chat_session.state.name,
        "transaction_id": record.chat_session.last_transaction_id,
    }


@router.get(
    "/history/{session_id}",
    response_model=List[HistoryEntry],
    summary="Get full message history for a session",
    description="Returns every user/agent message for this session, in chronological order.",
)
def chat_history(session_id: str) -> list:
    record = get_session(session_id)
    if record is None:
        raise HTTPException(status_code=404, detail="Unknown session_id.")
    return record.history
