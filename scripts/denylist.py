"""Curate the abuse denylist: block or unblock IPs and CIDR ranges.

Run inside the web container so it picks up the app's Valkey connection
settings from the environment:

    docker compose exec web python scripts/denylist.py deny 203.0.113.7
    docker compose exec web python scripts/denylist.py deny 203.0.113.0/24
    docker compose exec web python scripts/denylist.py allow 203.0.113.7
    docker compose exec web python scripts/denylist.py list
"""

import argparse
import asyncio

from valkey.asyncio import Valkey

from odin import store
from odin.config import settings


async def _deny(client: Valkey, value: str) -> None:
    await store.deny_ip(client, value)
    print(f"Denied {value}")


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
        if args.command == "deny":
            await _deny(client, args.value)
        elif args.command == "allow":
            await _allow(client, args.value)
        else:
            await _list(client)
    finally:
        await client.aclose()


def main() -> None:
    """Parse CLI args and run the requested denylist command."""
    parser = argparse.ArgumentParser(description=__doc__)
    subparsers = parser.add_subparsers(dest="command", required=True)

    deny = subparsers.add_parser("deny", help="Add an IP or CIDR range to the denylist")
    deny.add_argument("value", help="An IP address (1.2.3.4) or CIDR range (1.2.3.0/24)")

    allow = subparsers.add_parser("allow", help="Remove an IP or CIDR range from the denylist")
    allow.add_argument("value", help="An IP address (1.2.3.4) or CIDR range (1.2.3.0/24)")

    subparsers.add_parser("list", help="List every denied IP and CIDR range")

    args = parser.parse_args()
    asyncio.run(_run(args))


if __name__ == "__main__":
    main()
