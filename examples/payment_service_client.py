"""Example "payment service" using FraudMesh as a reusable fraud-decision service (F13).

The payment service knows nothing about graphs. Before approving a payment it
POSTs the transaction to /api/v1/score and acts on ALLOW / REVIEW / BLOCK.
Only the Python standard library is used, to show how little a client needs.

    python examples/payment_service_client.py --api-key fm_... [--account A000123]
"""

import argparse
import json
import urllib.error
import urllib.request
import uuid
from datetime import datetime, timezone
from pathlib import Path


def score(api: str, api_key: str, transaction: dict) -> dict:
    request = urllib.request.Request(
        f"{api}/api/v1/score",
        data=json.dumps(transaction).encode(),
        headers={"Content-Type": "application/json", "X-API-Key": api_key},
        method="POST",
    )
    with urllib.request.urlopen(request, timeout=10) as response:
        return json.loads(response.read())


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    parser.add_argument("--api", default="http://localhost:8000")
    parser.add_argument("--api-key", help="defaults to data/simulator_api_key.txt")
    parser.add_argument("--account", default="A000001")
    parser.add_argument("--merchant", default="M00011")
    parser.add_argument("--amount", type=float, default=2500.0)
    args = parser.parse_args()
    key = args.api_key or (Path(__file__).resolve().parents[1] / "data" / "simulator_api_key.txt").read_text().strip()

    transaction = {
        "transaction_id": f"PAY-{uuid.uuid4().hex[:12]}",
        "timestamp": datetime.now(timezone.utc).isoformat(),
        "amount": args.amount,
        "channel": "CARD",
        "location": "Bengaluru, IN",
        "account": {"id": args.account},
        "merchant": {"id": args.merchant},
    }
    try:
        result = score(args.api, key, transaction)
    except urllib.error.HTTPError as exc:
        print(f"FraudMesh rejected the request: {exc.code} {exc.read().decode()}")
        return

    print(f"Decision: {result['decision']}  (final score {result['final_score']}, "
          f"rule score {result['rule_score']}, account risk {result['account_risk']})")
    for reason in result["rule_reasons"]:
        print(f"  rule: {reason}")
    for path in result["risk_explanation"]:
        print(f"  graph: {path}")
    print({"ALLOW": "-> approve payment", "REVIEW": "-> hold for manual review",
           "BLOCK": "-> decline payment"}[result["decision"]])


if __name__ == "__main__":
    main()
