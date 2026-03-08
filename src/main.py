#!/usr/bin/env python3
"""Entry point for SaaS Pricing Intelligence API prototype."""

from __future__ import annotations

import argparse
import json
from datetime import datetime, timezone
from pathlib import Path
import sys

# Add src to path for imports
sys.path.insert(0, str(Path(__file__).parent))

from pipeline import run_pipeline


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description="Run SaaS Pricing Intelligence API prototype")
    parser.add_argument("--dry-run", action="store_true", help="Run without recording non-zero economics")
    parser.add_argument(
        "--requests",
        default=None,
        help="Optional path to request JSON (defaults to config/sample_requests.json)",
    )
    parser.add_argument(
        "--max-requests",
        type=int,
        default=None,
        help="Optional override for max requests to process",
    )
    return parser.parse_args()


def main() -> int:
    args = parse_args()

    prototype_root = Path(__file__).resolve().parent.parent
    now = datetime.now(timezone.utc).isoformat()

    context = {
        "idea_id": "idea-saas-pricing-intelligence",
        "title": "SaaS Pricing Intelligence API",
        "run_started": now,
        "dry_run": args.dry_run,
        "requests_path": args.requests,
        "max_requests": args.max_requests,
        "prototype_root": str(prototype_root),
    }

    result = run_pipeline(context=context, clients={})

    print(
        "run completed: "
        f"success={result['success']} "
        f"dry_run={args.dry_run} "
        f"analyses_generated={result['analyses_generated']} "
        f"projected_monthly_revenue=${result['projected_monthly_revenue']:.2f} "
        f"revenue=${result['revenue']:.2f}"
    )
    return 0 if result["success"] else 1


if __name__ == "__main__":
    raise SystemExit(main())
