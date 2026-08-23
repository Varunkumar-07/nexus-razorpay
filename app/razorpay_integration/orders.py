"""Razorpay Integration (Phase 5).

Creates a real Razorpay test-mode order from an APPROVED gate result, then
checks the Payments API for that order's payment status. Every step is
logged via the Phase 4 Audit Log, threaded under the same transaction_id as
the recommendation and gate check that preceded it.

create_order() refuses to run — in code, not just by convention — unless
given a gate result with approved == True. There is no code path from a
rejected (or malformed) gate result to a live Razorpay API call.
"""

import os
from typing import Tuple

import requests
from dotenv import load_dotenv

from app.audit.audit_log import log_event

load_dotenv()

RAZORPAY_BASE_URL = "https://api.razorpay.com/v1"


class GateNotApprovedError(RuntimeError):
    """Raised when order creation is attempted with a gate result that wasn't approved."""


class RazorpayConfigError(RuntimeError):
    """Raised when Razorpay credentials are missing from the environment."""


def _auth() -> Tuple[str, str]:
    key_id = os.environ.get("RAZORPAY_KEY_ID")
    key_secret = os.environ.get("RAZORPAY_KEY_SECRET")
    if not key_id or not key_secret:
        raise RazorpayConfigError(
            "RAZORPAY_KEY_ID / RAZORPAY_KEY_SECRET are not set in the environment."
        )
    return key_id, key_secret


def create_order(
    gate_result: dict,
    transaction_id: str,
    source: str = "unspecified",
    receipt_prefix: str = "nexus",
) -> dict:
    """Create a Razorpay test-mode order from an approved gate result.

    Args:
        gate_result: the dict returned by app.gate.gate.check_gate(). Must
            have approved == True — this is checked before anything else,
            and no Razorpay call is made if it isn't.
        transaction_id: the shared transaction_id from the recommendation +
            gate check, so this order's audit events thread together with
            them.
        source: "chat" or "agent" — which entry adapter is completing this
            order.
        receipt_prefix: prefix used for the Razorpay receipt id.

    Returns:
        On success:
            {"success": True, "order": {...}, "payment_status": {...}}
        On failure (Razorpay error, network error, missing config):
            {"success": False, "error": "<detail>"}

    Raises:
        GateNotApprovedError: if gate_result["approved"] is not True. This
            is a programming error — the caller should never invoke this
            function with a rejected gate result — so it's raised rather
            than returned as a soft failure.
    """
    if gate_result.get("approved") is not True:
        raise GateNotApprovedError(
            "create_order() refused: gate_result['approved'] is not True. "
            "An order can only be created from an approved Gate result."
        )

    amount_paise = gate_result["amount_paise"]

    try:
        key_id, key_secret = _auth()
        response = requests.post(
            f"{RAZORPAY_BASE_URL}/orders",
            auth=(key_id, key_secret),
            json={
                "amount": amount_paise,
                "currency": "INR",
                "receipt": f"{receipt_prefix}_{transaction_id[:16]}",
                "notes": {"transaction_id": transaction_id, "source": source},
            },
            timeout=15,
        )
        response.raise_for_status()
        order = response.json()
    except requests.HTTPError as exc:
        error_detail = exc.response.text if exc.response is not None else str(exc)
        log_event(
            transaction_id=transaction_id,
            source=source,
            event_type="order_failed",
            details={"stage": "order_create", "amount_paise": amount_paise, "error": error_detail},
        )
        return {"success": False, "error": error_detail}
    except (requests.RequestException, RazorpayConfigError) as exc:
        log_event(
            transaction_id=transaction_id,
            source=source,
            event_type="order_failed",
            details={"stage": "order_create", "amount_paise": amount_paise, "error": str(exc)},
        )
        return {"success": False, "error": str(exc)}

    log_event(
        transaction_id=transaction_id,
        source=source,
        event_type="order_created",
        details={"order": order},
    )

    payment_status = fetch_order_payments(order["id"], transaction_id, source)

    return {"success": True, "order": order, "payment_status": payment_status}


def fetch_order_payments(order_id: str, transaction_id: str, source: str = "unspecified") -> dict:
    """Fetch payment status for a Razorpay order via the Payments API.

    In test mode, an order created purely server-side (no client checkout)
    has no attached payments yet — that's an expected outcome, reported as
    status "no_payment_yet", not treated as a failure.

    Args:
        order_id: Razorpay order id (e.g. "order_xxx").
        transaction_id: shared transaction id for audit logging.
        source: "chat" or "agent".

    Returns:
        {"status": "no_payment_yet", "payments": []}
        or
        {"status": "<latest payment status>", "payments": [...]}
        or, on API failure:
        {"status": "fetch_failed", "error": "<detail>"}
    """
    try:
        key_id, key_secret = _auth()
        response = requests.get(
            f"{RAZORPAY_BASE_URL}/orders/{order_id}/payments",
            auth=(key_id, key_secret),
            timeout=15,
        )
        response.raise_for_status()
        payments = response.json().get("items", [])
        status = payments[-1]["status"] if payments else "no_payment_yet"
        result = {"status": status, "payments": payments}
        log_event(
            transaction_id=transaction_id,
            source=source,
            event_type="payment_status_fetched",
            details={"order_id": order_id, **result},
        )
        return result
    except (requests.RequestException, RazorpayConfigError) as exc:
        error_detail = (
            exc.response.text
            if isinstance(exc, requests.HTTPError) and exc.response is not None
            else str(exc)
        )
        log_event(
            transaction_id=transaction_id,
            source=source,
            event_type="order_failed",
            details={"stage": "payment_fetch", "order_id": order_id, "error": error_detail},
        )
        return {"status": "fetch_failed", "error": error_detail}
