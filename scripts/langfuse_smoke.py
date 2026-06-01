"""Day 1 Langfuse sanity check (langfuse SDK v4.x).

Sends one trace to Langfuse Cloud and confirms auth works. Run AFTER filling in
LANGFUSE_PUBLIC_KEY / LANGFUSE_SECRET_KEY / LANGFUSE_HOST in .env:

    ./bin/python scripts/langfuse_smoke.py

Then check the Langfuse UI: you should see a trace named "day1-smoke-test".
"""

from __future__ import annotations

import sys

from dotenv import load_dotenv
from langfuse import get_client


def main() -> int:
    load_dotenv()  # pulls LANGFUSE_* keys from .env into the environment

    client = get_client()  # reads LANGFUSE_PUBLIC_KEY / _SECRET_KEY / _HOST

    if not client.auth_check():
        print("FAILED: Langfuse auth_check() returned False. Check your keys/host in .env.")
        return 1

    with client.start_as_current_span(name="day1-smoke-test") as span:
        span.update(
            input={"msg": "hello from day 1"},
            output={"status": "harness + langfuse wired"},
        )

    client.flush()  # force-send before the script exits
    print("OK: trace 'day1-smoke-test' sent. Check the Langfuse UI.")
    return 0


if __name__ == "__main__":
    sys.exit(main())
