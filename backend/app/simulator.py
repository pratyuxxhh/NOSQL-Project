"""Live transaction stream for demos (F10).

Sends transactions to the ingestion API at a steady rate. Most are ordinary
purchases by existing customers; every so often a NEW account appears that
logs in from a device used by a planted fraud ring. The graph links it to the
ring immediately, so the dashboard shows a LINKED_TO_FRAUD alert and risk
propagation, even though the transaction itself looks harmless to the rules.

    python -m app.simulator --rate 20 --fraud-every 15
"""

import argparse
import json
import random
import time
import uuid
from datetime import datetime, timezone
from pathlib import Path

import httpx

from app.config import get_settings

CITIES = ["Bengaluru", "Mumbai", "Delhi", "Chennai", "Hyderabad", "Pune", "Kolkata"]


def ordinary_event(rng: random.Random, accounts: int, merchants: int) -> dict:
    return {
        "transaction_id": f"SIM-{uuid.uuid4().hex[:12]}",
        "timestamp": datetime.now(timezone.utc).isoformat(),
        "amount": round(min(rng.lognormvariate(7.0, 1.1), 400_000), 2),
        "channel": rng.choice(["CARD", "UPI", "WALLET"]),
        "location": f"{rng.choice(CITIES)}, IN",
        "account": {"id": f"A{rng.randint(1, accounts):06d}"},
        "merchant": {"id": f"M{rng.randint(1, merchants):05d}"},
    }


def ring_event(rng: random.Random, devices: list[str], merchants: int, n: int) -> dict:
    """A brand-new customer whose phone is a known fraud ring's device."""
    suffix = f"{n:04d}"
    return {
        "transaction_id": f"SIM-{uuid.uuid4().hex[:12]}",
        "timestamp": datetime.now(timezone.utc).isoformat(),
        "amount": round(rng.uniform(800, 4000), 2),  # small: no rule fires
        "channel": "UPI",
        "location": "Bengaluru, IN",
        "account": {"id": f"SIMACC{suffix}", "type": "WALLET"},
        "user": {
            "id": f"SIMUSR{suffix}",
            "name": f"New Customer {suffix}",
            "email": f"new{suffix}@example.com",
            "phone": f"+9170{rng.randint(10**7, 10**8 - 1)}",
            "address": {"line": f"{rng.randint(1, 300)} Residency Road", "city": "Bengaluru", "pincode": "560025"},
        },
        "device": {"device_id": rng.choice(devices), "os": "Android 14"},
        "merchant": {"id": f"M{rng.randint(1, merchants):05d}"},
    }


def main() -> None:
    settings = get_settings()
    parser = argparse.ArgumentParser(prog="python -m app.simulator", description=__doc__,
                                     formatter_class=argparse.RawDescriptionHelpFormatter)
    parser.add_argument("--api", default="http://localhost:8000")
    parser.add_argument("--rate", type=float, default=10, help="transactions per second")
    parser.add_argument("--fraud-every", type=float, default=20, help="seconds between ring events")
    parser.add_argument("--duration", type=float, default=0, help="seconds to run (0 = forever)")
    parser.add_argument("--api-key", help="defaults to data/simulator_api_key.txt (written by seed)")
    parser.add_argument("--seed", type=int, default=None)
    args = parser.parse_args()

    data = Path(settings.data_dir)
    key = args.api_key or (data / "simulator_api_key.txt").read_text().strip()
    truth = json.loads((data / "ground_truth.json").read_text())
    accounts, merchants = truth["stats"]["accounts"], truth["params"]["merchants"]
    devices = [d for r in truth["rings"] if r["type"] == "shared_device" for d in r["shared"]["devices"]]
    rng = random.Random(args.seed)

    sent, ring_events, start, last_ring = 0, 0, time.monotonic(), time.monotonic()
    with httpx.Client(base_url=args.api, headers={"X-API-Key": key}, timeout=10) as client:
        print(f"Streaming {args.rate} tx/s to {args.api}, a ring event every {args.fraud_every}s (Ctrl+C to stop)")
        try:
            while not args.duration or time.monotonic() - start < args.duration:
                tick = time.monotonic()
                batch = [ordinary_event(rng, accounts, merchants) for _ in range(max(1, int(args.rate)))]
                if devices and tick - last_ring >= args.fraud_every:
                    ring_events += 1
                    batch.append(ring_event(rng, devices, merchants, ring_events))
                    last_ring = tick
                    print(f"  ring event: new account SIMACC{ring_events:04d} on a ring device")
                response = client.post("/api/v1/ingest/batch", json={"events": batch})
                response.raise_for_status()
                sent += len(batch)
                if sent % (int(args.rate) * 10 or 10) < len(batch):
                    print(f"  sent {sent} (queue depth {response.json()['queue_depth']})")
                time.sleep(max(0.0, 1.0 - (time.monotonic() - tick)))
        except KeyboardInterrupt:
            pass
    print(f"Done: {sent} transactions, {ring_events} ring events")


if __name__ == "__main__":
    main()
