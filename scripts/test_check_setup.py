"""Setup-check regression test.

Confirms scripts/check_setup.py reports a clean, specific FAILURE — never
a crash — when one required piece is deliberately broken, and confirms
the unmodified environment passes cleanly first.

Handles the real .env file with care: reads its exact current content
before touching anything, and restores it byte-for-byte in a finally
block regardless of what happens in between, so this test can never
leave the project mis-configured, even if it's interrupted.

Run with: python3 scripts/test_check_setup.py
"""

import re
import subprocess
import sys
from pathlib import Path

PROJECT_ROOT = Path(__file__).resolve().parent.parent
CHECK_SETUP = PROJECT_ROOT / "scripts" / "check_setup.py"
ENV_PATH = PROJECT_ROOT / ".env"


def run_check_setup() -> subprocess.CompletedProcess:
    return subprocess.run(
        [sys.executable, str(CHECK_SETUP)],
        cwd=str(PROJECT_ROOT),
        capture_output=True,
        text=True,
        timeout=60,
    )


def case_1_baseline_passes() -> None:
    print("########## CASE 1 — baseline (unmodified .env): should pass cleanly ##########")
    result = run_check_setup()
    print(result.stdout)

    assert result.returncode == 0, f"Expected exit code 0 on a correctly configured environment, got {result.returncode}"
    assert "checks passed" in result.stdout
    assert "Traceback" not in result.stdout and "Traceback" not in result.stderr

    print("Confirmed: baseline environment passes cleanly, exit code 0.\n")


def case_2_broken_groq_key_reports_failure_cleanly() -> None:
    print("\n########## CASE 2 — GROQ_API_KEY deliberately blanked: should report failure cleanly ##########")

    assert ENV_PATH.exists(), "This test requires a real .env file to temporarily modify and restore."
    original_content = ENV_PATH.read_text()
    assert "GROQ_API_KEY=" in original_content, ".env must have a GROQ_API_KEY line for this test to modify."

    broken_content = re.sub(r"^GROQ_API_KEY=.*$", "GROQ_API_KEY=", original_content, flags=re.MULTILINE)
    assert broken_content != original_content, "Failed to actually modify the GROQ_API_KEY line — aborting."

    try:
        ENV_PATH.write_text(broken_content)
        result = run_check_setup()
    finally:
        ENV_PATH.write_text(original_content)
        restored = ENV_PATH.read_text()
        assert restored == original_content, "CRITICAL: .env was not restored to its original content!"
        print("(.env restored to its original content)")

    print(result.stdout)

    assert result.returncode == 1, f"Expected exit code 1 with a broken key, got {result.returncode}"
    assert "Traceback" not in result.stdout and "Traceback" not in result.stderr, (
        "check_setup.py must never crash with a raw traceback, even on a broken environment"
    )
    assert "GROQ_API_KEY" in result.stdout, "The failure should specifically name the broken key"
    assert "Fix:" in result.stdout, "A failure must come with a specific fix instruction"

    # Precision check: only GROQ_API_KEY was broken — Razorpay's own live
    # call, which depends only on its own two keys, must still pass. A
    # broken Groq key must never hide an unrelated, working Razorpay key.
    assert "[✓] Razorpay API auth" in result.stdout, (
        "Razorpay's check should be unaffected by an unrelated broken Groq key"
    )
    assert "[✗] Groq API auth" in result.stdout, "Groq's check should specifically report failure"

    print(
        "Confirmed: check_setup.py reports the broken key clearly (with a fix instruction), "
        "does not crash, and correctly leaves the unrelated Razorpay check passing."
    )


def main() -> None:
    case_1_baseline_passes()
    case_2_broken_groq_key_reports_failure_cleanly()
    print("\n\nAll check_setup.py regression cases behaved as expected.")


if __name__ == "__main__":
    main()
