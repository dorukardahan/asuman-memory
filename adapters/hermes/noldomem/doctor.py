#!/usr/bin/env python3
"""Privacy-safe NoldoMem Hermes adapter diagnostics."""

from __future__ import annotations

import argparse
import ipaddress
import sys

from pathlib import Path
from typing import Optional, Sequence
from urllib.parse import urlsplit


def _load_provider():
    root = Path(__file__).resolve().parent
    sys.path.insert(0, str(root.parent))
    import noldomem  # type: ignore

    return noldomem.NoldoMemProvider()


def _endpoint_metadata(base_url: str) -> tuple[str, str]:
    try:
        parsed = urlsplit(base_url)
        scheme = parsed.scheme.lower()
        if scheme not in {"http", "https"}:
            return "other", "invalid"
        hostname = parsed.hostname
        if not hostname:
            return scheme, "invalid"
        if hostname.lower() == "localhost":
            return scheme, "loopback"
        try:
            address = ipaddress.ip_address(hostname)
        except ValueError:
            return scheme, "remote"
        if address.is_loopback:
            return scheme, "loopback"
        if address.is_private:
            return scheme, "private"
        return scheme, "remote"
    except ValueError:
        return "other", "invalid"


def _bool_text(value: bool) -> str:
    return str(value).lower()


def _safe_error_type(value: object) -> str:
    name = str(value or "")
    classifications = {
        "JSONDecodeError": "InvalidResponse",
        "ValueError": "InvalidResponse",
        "_ReadinessPayloadTooLarge": "ResponseTooLarge",
        "_ReadinessDeadlineExceeded": "DeadlineExceeded",
        "_ReadinessDeadlineUnavailable": "DeadlineUnavailable",
    }
    if name in classifications:
        return classifications[name]
    allowed = {
        "HTTPError",
        "InvalidResponse",
        "DeadlineExceeded",
        "DeadlineUnavailable",
        "OSError",
        "ReadinessError",
        "ResponseTooLarge",
        "TimeoutError",
        "URLError",
    }
    return name if name in allowed else "ReadinessError"


def main(argv: Optional[Sequence[str]] = None) -> int:
    parser = argparse.ArgumentParser(description="Check NoldoMem adapter configuration and optional readiness.")
    parser.add_argument("--live", action="store_true", help="Perform one bounded live readiness probe.")
    parser.add_argument("--timeout", type=float, default=2.0, help="Live probe timeout, capped at 2 seconds.")
    args = parser.parse_args(argv)

    provider = _load_provider()
    configured = provider.is_available()
    cfg = provider.load_config()
    endpoint_scheme, endpoint_scope = _endpoint_metadata(cfg.base_url)
    print(f"provider_configured={_bool_text(configured)}")
    print(f"api_key_present={_bool_text(bool(cfg.api_key))}")
    print(f"endpoint_scheme={endpoint_scheme}")
    print(f"endpoint_scope={endpoint_scope}")

    if not args.live:
        print("readiness_probe=skipped")
        return 0 if configured else 1

    print("readiness_probe=completed")
    if not configured:
        print("readiness_ready=false")
        print("readiness_status=unconfigured")
        return 1

    health = provider.probe_readiness(timeout_seconds=args.timeout)
    ready = health.get("ready") is True
    print(f"readiness_ready={_bool_text(ready)}")
    print(f"readiness_status={health.get('status', 'unavailable')}")
    if isinstance(health.get("storage_ok"), bool):
        print(f"readiness_storage_ok={_bool_text(health['storage_ok'])}")
    if isinstance(health.get("embedding_ok"), bool):
        print(f"readiness_embedding_ok={_bool_text(health['embedding_ok'])}")
    uptime_seconds = health.get("uptime_seconds")
    if isinstance(uptime_seconds, (int, float)) and not isinstance(uptime_seconds, bool):
        print(f"readiness_uptime_seconds={max(0.0, float(uptime_seconds)):.1f}")
    if health.get("error_type"):
        print(f"readiness_error_type={_safe_error_type(health['error_type'])}")
    return 0 if ready else 2


if __name__ == "__main__":
    raise SystemExit(main())
