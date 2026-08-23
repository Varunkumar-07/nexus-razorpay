"""Message-intent classifier for the Web Chat UI.

Purely additive: this runs only in the web HTTP layer (app/web_chat/routes.py),
and only when a session is in AWAITING_REQUEST state, before the message is
ever handed to the existing ChatSession / recommend() pipeline. It never
touches ChatSession, gate.py, or the reasoning core — a message classified
as a product request is passed through to ChatSession.handle_message()
completely unchanged.

Three categories:
  - "product_request" — a specific gear/budget ask, handled by the existing
    recommend() pipeline exactly as before.
  - "small_talk" — a greeting or unclear input, gets a short canned reply.
  - "browse_intent" — the buyer wants to see the catalog in general (no
    specific product/budget in mind), e.g. "show me the products you own,
    lemme browse". Gets a canned reply plus a suggested_action the frontend
    renders as a real "Browse Catalog" navigation button (see routes.py).
"""

import os

from dotenv import load_dotenv
from groq import Groq

load_dotenv()

_CLASSIFIER_MODEL = "openai/gpt-oss-120b"

_SYSTEM_PROMPT = """Classify the buyer's message into exactly one category:

- "product_request" — the buyer describes specific gear they want, a
  budget, or a specific category to shop for right now (e.g. "I need a
  tent under Rs.5000", "show me sleeping bags under 3000", "something warm
  for winter").
- "browse_intent" — the buyer wants to see the catalog / what's available
  in general, with no specific product or budget in mind (e.g. "show me
  the products you own, lemme browse", "what do you sell", "show me
  everything", "let me see your catalog", "what products do you have").
- "small_talk" — a greeting, thanks, or unclear input that is neither of
  the above (e.g. "hi", "hello", "how are you", "thanks", "what can you
  do", "asdf").

Respond with exactly one word: product_request, browse_intent, or
small_talk. Nothing else."""

SMALL_TALK_REPLY = (
    "Hi! I'm the NEXUS shopping assistant for Northlight Outdoors. Tell me "
    "what kind of gear you're looking for and your budget, and I'll find "
    "the right fit."
)

BROWSE_INTENT_REPLY = (
    "Sure — here's our full catalog. Click below to browse everything we "
    "have, or tell me what you're looking for and a budget and I'll "
    "recommend something directly."
)

BROWSE_CATALOG_ACTION = "browse_catalog"


def classify_intent(message: str) -> str:
    """Classify a fresh buyer message as 'product_request', 'browse_intent',
    or 'small_talk'.

    Fails open to 'product_request' on any error (missing API key, network
    issue, unexpected response) so a classifier problem never blocks a real
    shopping request — worst case, the existing recommend() pipeline's own
    no-match handling takes over, exactly as it did before this classifier
    existed.
    """
    api_key = os.environ.get("GROQ_API_KEY")
    if not api_key:
        return "product_request"

    try:
        client = Groq(api_key=api_key)
        response = client.chat.completions.create(
            model=_CLASSIFIER_MODEL,
            messages=[
                {"role": "system", "content": _SYSTEM_PROMPT},
                {"role": "user", "content": message},
            ],
            temperature=0,
            # gpt-oss-120b spends tokens on internal reasoning before the
            # final answer; a tight budget (e.g. 5) gets cut off with empty
            # content before any answer is emitted (see FAILURE_LOG.md
            # Entry 2). 60 leaves enough room.
            max_tokens=60,
        )
        label = (response.choices[0].message.content or "").strip().lower()
        if "browse_intent" in label:
            return "browse_intent"
        if "small_talk" in label:
            return "small_talk"
        return "product_request"
    except Exception:
        return "product_request"
