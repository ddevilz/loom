from __future__ import annotations

import argparse


def main() -> int:
    parser = argparse.ArgumentParser(prog="loom")
    parser.add_argument(
        "--dev",
        action="store_true",
        help="Run the Loom app in development mode (placeholder entrypoint).",
    )
    args = parser.parse_args()

    if args.dev:
        # Placeholder until LOOM-002 introduces real runtime dependencies and entrypoints.
        print("loom (dev): package import OK")
        return 0

    parser.print_help()
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
