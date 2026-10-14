"""CLI adapter; the service can also be called directly by any Python app."""
import argparse
import json
from pathlib import Path
import sys

from . import create_service, Settings, TradingError
from .config import read_env


def main():
    parser = argparse.ArgumentParser(description="Toss fractional market buy")
    parser.add_argument("--env", type=Path, default=Path(".env"))
    sub = parser.add_subparsers(dest="command", required=True)
    sub.add_parser("setup")
    sub.add_parser("history")
    sub.add_parser("batch-history")
    batch = sub.add_parser("batch-preview")
    batch.add_argument("symbol")
    batch.add_argument("value")
    batch.add_argument("--side", choices=["BUY", "SELL"], default="BUY")
    batch.add_argument("--basis", choices=["AMOUNT", "QUANTITY"], default="AMOUNT")
    batch.add_argument("--account")
    start = sub.add_parser("batch-start")
    start.add_argument("batch_id")
    start.add_argument("--confirm", help="Optional legacy confirmation text")
    start.add_argument("--acknowledge", action="store_true")
    for command in ("batch-status", "batch-stop"):
        sub.add_parser(command).add_argument("batch_id")
    preview = sub.add_parser("preview")
    preview.add_argument("symbol")
    preview.add_argument("amount", help="USD amount, e.g. 5.00")
    preview.add_argument("--account")
    submit = sub.add_parser("submit")
    submit.add_argument("preview_id")
    submit.add_argument("--confirm", required=True, help="Exact confirmationText from preview")
    submit.add_argument("--acknowledge", action="store_true")
    orders = sub.add_parser("orders")
    holdings = sub.add_parser("holdings")
    holdings.add_argument("--account")
    orders.add_argument("--account")
    orders.add_argument("--status", choices=["OPEN", "CLOSED"], default="OPEN")
    args = parser.parse_args()
    try:
        service = create_service(Settings.from_env(read_env(args.env)))
        if args.command == "setup":
            result = service.setup()
        elif args.command == "history":
            result = service.store.history()
        elif args.command == "batch-history":
            result = service.batch_history()
        elif args.command == "batch-preview":
            result = service.preview_batch(args.symbol, args.value, args.account, side=args.side, basis=args.basis)
        elif args.command == "batch-start":
            result = service.start_batch(args.batch_id, args.confirm, acknowledged=args.acknowledge, background=False)
        elif args.command == "batch-status":
            result = service.batch_status(args.batch_id)
        elif args.command == "batch-stop":
            result = service.stop_batch(args.batch_id)
        elif args.command == "preview":
            result = service.preview(args.symbol, args.amount, args.account)
        elif args.command == "orders":
            result = service.orders(args.account, args.status)
        elif args.command == "holdings":
            result = service.holdings(args.account)
        else:
            result = service.submit(args.preview_id, args.confirm, acknowledged=args.acknowledge)
        print(json.dumps(result, ensure_ascii=False, indent=2))
        return 0
    except (TradingError, ValueError, PermissionError) as exc:
        print(str(exc), file=sys.stderr)
        return 1


if __name__ == "__main__":
    raise SystemExit(main())
