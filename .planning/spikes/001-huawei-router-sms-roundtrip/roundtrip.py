#!/usr/bin/env python3
"""
Phase 25 pre-gate spike: prove the Huawei 4G router exposes SMS send/receive
to a script running on fc1.

Usage:
  pip install --user huawei-lte-api
  python3 roundtrip.py auth                    # login only — sanity check
  python3 roundtrip.py info                    # device + signal + sms-count
  python3 roundtrip.py inbox [N]               # last N inbox entries (default 5)
  python3 roundtrip.py send <to> <text>        # send SMS
  python3 roundtrip.py wait-for-from <num> [timeout]
                                               # poll inbox for SMS from <num>

Defaults are read from env vars or hardcoded for fc1:
  ROUTER_URL  default http://192.168.8.1/
  ROUTER_USER default admin
  ROUTER_PASS default (must be set)
"""
import os
import sys
import time
from datetime import datetime

from huawei_lte_api.Client import Client
from huawei_lte_api.Connection import Connection
from huawei_lte_api.enums.sms import BoxTypeEnum

ROUTER_URL = os.environ.get("ROUTER_URL", "http://192.168.8.1/")
ROUTER_USER = os.environ.get("ROUTER_USER", "admin")
ROUTER_PASS = os.environ.get("ROUTER_PASS")


def open_client():
    if not ROUTER_PASS:
        sys.exit("ROUTER_PASS not set")
    auth_url = ROUTER_URL.replace("://", f"://{ROUTER_USER}:{ROUTER_PASS}@", 1)
    return Connection(auth_url)


def cmd_auth():
    with open_client() as conn:
        c = Client(conn)
        info = c.device.information()
        print("AUTH OK")
        print(f"  device: {info.get('DeviceName')}  serial: {info.get('SerialNumber')}")


def cmd_info():
    with open_client() as conn:
        c = Client(conn)
        print("=== device.information")
        for k, v in c.device.information().items():
            print(f"  {k}: {v}")
        print("=== device.signal")
        for k, v in c.device.signal().items():
            print(f"  {k}: {v}")
        print("=== sms.sms_count")
        for k, v in c.sms.sms_count().items():
            print(f"  {k}: {v}")


def _list_inbox(client, n=5):
    resp = client.sms.get_sms_list(
        page=1, box_type=BoxTypeEnum.LOCAL_INBOX,
        read_count=n, sort_type=0, ascending=0, unread_preferred=0,
    )
    msgs = resp.get("Messages", {}).get("Message", []) or []
    if isinstance(msgs, dict):
        msgs = [msgs]
    return msgs


def cmd_inbox():
    n = int(sys.argv[2]) if len(sys.argv) > 2 else 5
    with open_client() as conn:
        msgs = _list_inbox(Client(conn), n)
        print(f"INBOX ({len(msgs)} msgs):")
        for m in msgs:
            print(f"  [{m.get('Date')}] from={m.get('Phone')}  smstat={m.get('Smstat')}")
            body = (m.get("Content") or "").replace("\n", " ")
            print(f"    {body[:140]}")


def cmd_send():
    if len(sys.argv) < 4:
        sys.exit("usage: send <to> <text>")
    to = sys.argv[2]
    text = sys.argv[3]
    with open_client() as conn:
        c = Client(conn)
        rc = c.sms.send_sms([to], text)
        print(f"SEND rc={rc} (OK if 'OK' or 200000)")


def cmd_wait_for_from():
    if len(sys.argv) < 3:
        sys.exit("usage: wait-for-from <num> [timeout_seconds=120]")
    num = sys.argv[2]
    timeout = int(sys.argv[3]) if len(sys.argv) > 3 else 120
    suffix = num.lstrip("+")[-8:]
    deadline = time.time() + timeout
    seen = set()
    with open_client() as conn:
        c = Client(conn)
        baseline = {m.get("Index") for m in _list_inbox(c, 20)}
        print(f"baseline inbox={len(baseline)} ids; polling for new SMS from ...{suffix}")
        while time.time() < deadline:
            msgs = _list_inbox(c, 20)
            for m in msgs:
                idx = m.get("Index")
                if idx in baseline or idx in seen:
                    continue
                seen.add(idx)
                phone = m.get("Phone", "")
                if suffix in phone.replace("+", ""):
                    print(f"HIT [{m.get('Date')}] from={phone}")
                    print(f"  {m.get('Content')}")
                    return
                else:
                    print(f"  (other) {m.get('Date')} {phone}")
            time.sleep(5)
        sys.exit(f"TIMEOUT after {timeout}s — no SMS from ...{suffix}")


CMDS = {
    "auth": cmd_auth,
    "info": cmd_info,
    "inbox": cmd_inbox,
    "send": cmd_send,
    "wait-for-from": cmd_wait_for_from,
}

if __name__ == "__main__":
    if len(sys.argv) < 2 or sys.argv[1] not in CMDS:
        print(__doc__)
        sys.exit(1)
    CMDS[sys.argv[1]]()
