"""Setup validation — run once before demos/recordings, or when setting up
cold, to know with certainty the system is ready.

Checks, in order:
  1. .env exists and RAZORPAY_KEY_ID / RAZORPAY_KEY_SECRET / GROQ_API_KEY
     are present and are not still the placeholder values from .env.example
  2. Python dependencies from requirements.txt are installed
  3. frontend/node_modules exists (npm install has been run)
  4. A live, minimal Razorpay test-mode API call succeeds (auth works)
  5. A live, minimal Groq API call succeeds (auth works)
  6. The SQLite catalog is seeded (query returns 15 products)

Every check reports pass/fail with a plain-English detail and, for
failures, a specific fix instruction — never a raw stack trace. Exceptions
inside any single check are caught and reported as that check's failure,
so a broken system state can't crash the checker itself. The Razorpay and
Groq checks each depend only on their own key(s), not on each other or on
the combined "are all three keys set" summary check — a broken Groq key
must never hide a perfectly working Razorpay key, or vice versa.

Run with: python3 scripts/check_setup.py
Exit code 0 if everything passes, 1 if anything fails.
"""

import importlib.metadata
import sys
from pathlib import Path

PROJECT_ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(PROJECT_ROOT))

import requests
from dotenv import dotenv_values, load_dotenv

CHECK = "✓"
CROSS = "✗"

REQUIRED_KEYS = ["RAZORPAY_KEY_ID", "RAZORPAY_KEY_SECRET", "GROQ_API_KEY"]


class CheckResult:
    def __init__(self, name: str, passed: bool, detail: str, fix: str = None):
        self.name = name
        self.passed = passed
        self.detail = detail
        self.fix = fix


def _safe_check(name: str, fn):
    """Run one check function, catching any exception so a broken
    environment reports as a clear failure instead of crashing the whole
    script."""
    try:
        return fn()
    except Exception as exc:  # noqa: BLE001 - deliberately broad, this is a diagnostic tool
        return CheckResult(name, False, f"Check crashed unexpectedly: {exc}", "Re-run with more context or check FAILURE_LOG.md.")


def _load_env_values() -> tuple:
    """Read .env and .env.example directly off disk (not via os.environ),
    so each check can independently decide whether a specific key is
    present and non-placeholder."""
    env_path = PROJECT_ROOT / ".env"
    example_path = PROJECT_ROOT / ".env.example"
    values = dotenv_values(str(env_path)) if env_path.exists() else {}
    placeholders = dotenv_values(str(example_path)) if example_path.exists() else {}
    return values, placeholders


def _key_ready(values: dict, placeholders: dict, key: str) -> bool:
    val = values.get(key)
    if not val:
        return False
    if placeholders.get(key) and val == placeholders.get(key):
        return False
    return True


def check_env_keys() -> CheckResult:
    env_path = PROJECT_ROOT / ".env"
    if not env_path.exists():
        return CheckResult(
            ".env file and API keys",
            False,
            ".env does not exist.",
            "Run: cp .env.example .env   then fill in your real Razorpay + Groq keys.",
        )

    values, placeholders = _load_env_values()
    missing = [k for k in REQUIRED_KEYS if not values.get(k)]
    still_placeholder = [
        k for k in REQUIRED_KEYS
        if values.get(k) and placeholders.get(k) and values.get(k) == placeholders.get(k)
    ]

    if missing or still_placeholder:
        problems = []
        if missing:
            problems.append(f"missing: {', '.join(missing)}")
        if still_placeholder:
            problems.append(f"still placeholder value(s): {', '.join(still_placeholder)}")
        return CheckResult(
            ".env file and API keys",
            False,
            "; ".join(problems) + ".",
            "Edit .env and fill in real values — Razorpay: dashboard.razorpay.com "
            "(Settings -> API Keys, Test Mode). Groq: console.groq.com/keys",
        )

    return CheckResult(
        ".env file and API keys",
        True,
        "RAZORPAY_KEY_ID, RAZORPAY_KEY_SECRET, and GROQ_API_KEY are all set to non-placeholder values.",
    )


def check_python_deps() -> CheckResult:
    req_path = PROJECT_ROOT / "requirements.txt"
    if not req_path.exists():
        return CheckResult(
            "Python dependencies",
            False,
            "requirements.txt not found at the project root.",
            "This shouldn't happen in a checked-out copy of the repo — check you're in the right directory.",
        )

    missing = []
    for line in req_path.read_text().splitlines():
        line = line.strip()
        if not line or line.startswith("#"):
            continue
        pkg = line.split("==")[0].strip()
        try:
            importlib.metadata.version(pkg)
        except importlib.metadata.PackageNotFoundError:
            missing.append(pkg)

    if missing:
        return CheckResult(
            "Python dependencies",
            False,
            f"Not installed: {', '.join(missing)}.",
            "Run: python3 -m pip install -r requirements.txt",
        )
    return CheckResult("Python dependencies", True, "All packages in requirements.txt are installed.")


def check_frontend_deps() -> CheckResult:
    node_modules = PROJECT_ROOT / "frontend" / "node_modules"
    if not node_modules.is_dir():
        return CheckResult(
            "Frontend dependencies",
            False,
            "frontend/node_modules does not exist.",
            "Run: cd frontend && npm install",
        )
    return CheckResult("Frontend dependencies", True, "frontend/node_modules exists.")


def check_razorpay_auth() -> CheckResult:
    values, placeholders = _load_env_values()
    if not (_key_ready(values, placeholders, "RAZORPAY_KEY_ID") and _key_ready(values, placeholders, "RAZORPAY_KEY_SECRET")):
        return CheckResult(
            "Razorpay API auth (live call)",
            False,
            "Skipped — RAZORPAY_KEY_ID / RAZORPAY_KEY_SECRET are missing or still placeholder values.",
            "Fix the .env keys check above, then re-run this script.",
        )

    key_id = values.get("RAZORPAY_KEY_ID")
    key_secret = values.get("RAZORPAY_KEY_SECRET")

    try:
        resp = requests.get(
            "https://api.razorpay.com/v1/payments",
            params={"count": 1},
            auth=(key_id, key_secret),
            timeout=10,
        )
    except requests.RequestException as exc:
        return CheckResult(
            "Razorpay API auth (live call)",
            False,
            f"Network error reaching Razorpay: {exc}",
            "Check your internet connection, then re-run this script.",
        )

    if resp.status_code == 200:
        return CheckResult("Razorpay API auth (live call)", True, "Live test-mode API call succeeded (HTTP 200).")
    if resp.status_code in (401, 403):
        return CheckResult(
            "Razorpay API auth (live call)",
            False,
            f"Razorpay rejected the credentials (HTTP {resp.status_code}).",
            "Double-check RAZORPAY_KEY_ID / RAZORPAY_KEY_SECRET in .env are a valid, current Test Mode "
            "key pair from dashboard.razorpay.com (Settings -> API Keys) — regenerate if unsure.",
        )
    return CheckResult(
        "Razorpay API auth (live call)",
        False,
        f"Unexpected response: HTTP {resp.status_code} - {resp.text[:200]}",
        "Check status.razorpay.com or try again in a moment.",
    )


def check_groq_auth() -> CheckResult:
    values, placeholders = _load_env_values()
    if not _key_ready(values, placeholders, "GROQ_API_KEY"):
        return CheckResult(
            "Groq API auth (live call)",
            False,
            "Skipped — GROQ_API_KEY is missing or still a placeholder value.",
            "Fix the .env keys check above, then re-run this script.",
        )

    api_key = values.get("GROQ_API_KEY")

    try:
        resp = requests.post(
            "https://api.groq.com/openai/v1/chat/completions",
            headers={"Authorization": f"Bearer {api_key}", "Content-Type": "application/json"},
            json={"model": "openai/gpt-oss-120b", "messages": [{"role": "user", "content": "hi"}], "max_tokens": 5},
            timeout=10,
        )
    except requests.RequestException as exc:
        return CheckResult(
            "Groq API auth (live call)",
            False,
            f"Network error reaching Groq: {exc}",
            "Check your internet connection, then re-run this script.",
        )

    if resp.status_code == 200:
        return CheckResult("Groq API auth (live call)", True, "Live API call succeeded (HTTP 200).")
    if resp.status_code == 401:
        return CheckResult(
            "Groq API auth (live call)",
            False,
            "Groq rejected the API key (HTTP 401).",
            "Double-check GROQ_API_KEY in .env is a valid, current key from console.groq.com/keys.",
        )
    if resp.status_code == 429:
        return CheckResult(
            "Groq API auth (live call)",
            True,
            "Auth is valid — Groq returned HTTP 429 (rate limited), which confirms the key itself "
            "works; the account just can't take a full request right now.",
        )
    return CheckResult(
        "Groq API auth (live call)",
        False,
        f"Unexpected response: HTTP {resp.status_code} - {resp.text[:200]}",
        "Check groqstatus.com or try again in a moment.",
    )


def check_catalog_seeded() -> CheckResult:
    from app.catalog.seed_data import seed
    from app.catalog.service import filter_by_max_price

    seed()  # idempotent — only inserts if the table is empty
    products = filter_by_max_price(10**12)  # effectively "all products"

    if len(products) == 15:
        return CheckResult("Catalog seeded", True, "15 products found (seeded now if the table was empty).")
    return CheckResult(
        "Catalog seeded",
        False,
        f"Expected 15 products, found {len(products)}.",
        "Delete data/nexus.db and re-run this script to reseed from a clean slate.",
    )


def main() -> int:
    load_dotenv(dotenv_path=str(PROJECT_ROOT / ".env"))

    print("NEXUS setup check")
    print("=" * 50)

    results = [
        _safe_check(".env file and API keys", check_env_keys),
        _safe_check("Python dependencies", check_python_deps),
        _safe_check("Frontend dependencies", check_frontend_deps),
        _safe_check("Razorpay API auth (live call)", check_razorpay_auth),
        _safe_check("Groq API auth (live call)", check_groq_auth),
        _safe_check("Catalog seeded", check_catalog_seeded),
    ]

    for r in results:
        mark = CHECK if r.passed else CROSS
        print(f"\n[{mark}] {r.name}")
        print(f"    {r.detail}")
        if not r.passed and r.fix:
            print(f"    Fix: {r.fix}")

    passed_count = sum(1 for r in results if r.passed)
    print("\n" + "=" * 50)
    print(f"{passed_count}/{len(results)} checks passed.")

    if passed_count == len(results):
        print("\nEverything is ready — you can start the servers now.")
        return 0

    print("\nFix the items marked above, then re-run: python3 scripts/check_setup.py")
    return 1


if __name__ == "__main__":
    sys.exit(main())
