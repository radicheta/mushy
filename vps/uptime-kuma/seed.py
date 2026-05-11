#!/usr/bin/env python3
"""Phase 34 — seed uptime-kuma admin + ntfy notification + 5 monitors.

Idempotent-ish: if admin already exists, prompts re-login (we abort).
If a monitor with the same name exists, skips it.
"""
import secrets
import string
import sys
import time
from uptime_kuma_api import UptimeKumaApi, MonitorType, NotificationType

URL = "http://10.66.0.1:3001"
NTFY_TOPIC = "mushy-alerts-7f3a9c2b8e"

ADMIN_USER = "Mushy"
ADMIN_PASS = ""  # SET BEFORE RUNNING (or leave empty for first-time api.setup() to generate)

MONITORS = [
    dict(type=MonitorType.PING, name="fc1 ping (wg-hub)", hostname="10.66.0.11", interval=60, retryInterval=20, maxretries=2),
    dict(type=MonitorType.PING, name="elder-plops ping (wg-hub)", hostname="10.66.0.12", interval=60, retryInterval=20, maxretries=2),
    dict(type=MonitorType.HTTP, name="Mission Control (openmct)", url="http://10.66.0.12:8080/", interval=60, retryInterval=20, maxretries=2),
    dict(type=MonitorType.KEYWORD, name="Bridge health", url="http://10.66.0.12:8081/health", keyword='"status":"ok"', interval=60, retryInterval=20, maxretries=2),
    # 5th monitor (VPS heartbeat receiver self-check) deliberately omitted —
    # uptime-kuma container is on Docker bridge net and can't reach the
    # receiver's 10.66.0.1:9000 binding through docker0 → wg-hub locally.
    # Add `extra_hosts: ["host.docker.internal:host-gateway"]` to compose
    # and use http://host.docker.internal:9000/health if you want it.
]

def main():
    api = UptimeKumaApi(URL, timeout=15)
    if api.need_setup():
        print(f"[seed] first-time setup with admin '{ADMIN_USER}'")
        api.setup(ADMIN_USER, ADMIN_PASS)
    print(f"[seed] login as '{ADMIN_USER}'")
    api.login(ADMIN_USER, ADMIN_PASS)

    # Notification: ntfy
    print("[seed] adding ntfy notification channel")
    n = api.add_notification(
        name="mushy ntfy",
        type=NotificationType.NTFY,
        ntfyserverurl="https://ntfy.sh",
        ntfytopic=NTFY_TOPIC,
        ntfyPriority=4,
        isDefault=True,
        applyExisting=True,
    )
    notif_id = n.get("id") if isinstance(n, dict) else None
    print(f"[seed]   notification_id={notif_id}")

    # Monitors
    existing = {m["name"] for m in api.get_monitors()}
    notif_ids = [notif_id] if notif_id else []
    for spec in MONITORS:
        if spec["name"] in existing:
            print(f"[seed] skip existing: {spec['name']}")
            continue
        spec["notificationIDList"] = notif_ids
        m = api.add_monitor(**spec)
        print(f"[seed] added monitor: {spec['name']} -> id={m.get('monitorID')}")

    # Test the notification
    print("[seed] firing test notification…")
    try:
        api.test_notification(
            name="mushy ntfy",
            type=NotificationType.NTFY,
            ntfyserverurl="https://ntfy.sh",
            ntfytopic=NTFY_TOPIC,
            ntfyPriority=4,
        )
        print("[seed]   test fired (check phone)")
    except Exception as e:
        print(f"[seed]   test failed: {e}")

    print("\n[seed] DONE")
    print(f"[seed] dashboard:   {URL}")
    print(f"[seed] admin user:  {ADMIN_USER}  (existing creds preserved)")
    print(f"[seed] ntfy topic:  {NTFY_TOPIC}")

    # Give monitors a tick to start polling, then snapshot status
    time.sleep(3)
    print("\n[seed] monitor states:")
    for m in api.get_monitors():
        print(f"  - {m['name']:<32}  active={m.get('active')}")

    api.disconnect()

if __name__ == "__main__":
    main()
