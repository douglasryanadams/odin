"""Inspect and unblock the abuse denylist.

IPs are added automatically after repeated bot-detection triggers (see
store.record_bot_trigger); this script only offers visibility and a way to
undo a false-positive block. Run inside the web container so it picks up the
app's Valkey connection settings from the environment:

    docker compose exec web python scripts/denylist.py list
    docker compose exec web python scripts/denylist.py allow 203.0.113.7
"""

import argparse
import asyncio

from valkey.asyncio import Valkey

from odin import store
from odin.config import settings


async def _allow(client: Valkey, value: str) -> None:
    await store.allow_ip(client, value)
    print(f"Allowed {value}")


async def _list(client: Valkey) -> None:
    entries = await store.list_denied(client)
    if not entries:
        print("Denylist is empty.")
        return
    for entry in entries:
        print(entry)


async def _run(args: argparse.Namespace) -> None:
    client = Valkey.from_url(settings.odin_valkey_url)
    try:
        if args.command == "allow":
            await _allow(client, args.value)
        else:
            await _list(client)
    finally:
        await client.aclose()


def main() -> None:
    """Parse CLI args and run the requested denylist command."""
    parser = argparse.ArgumentParser(description=__doc__)
    subparsers = parser.add_subparsers(dest="command", required=True)

    allow = subparsers.add_parser("allow", help="Remove an IP address from the denylist")
    allow.add_argument("value", help="The IP address to unblock")

    subparsers.add_parser("list", help="List every denied IP address")

    args = parser.parse_args()
    asyncio.run(_run(args))


if __name__ == "__main__":
    main()
