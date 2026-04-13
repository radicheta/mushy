---
task: 13-04 Task 1
date: "2026-04-13"
---

# Deploy Log: farmos-agent + bridge rebuild

## Containers Rebuilt

- `mushy-bridge-1` — rebuilt with staleness guard fix (CR-02, commit 7e33477)
- `mushy-farmos-agent-1` — rebuilt with humidity units fix + upload_photo auth fix (FMOS-03, CR-01, commits da27f67)

## Lifecycle Check

farmos-agent logs after startup:

```
[farmos_agent] configured — FC-1 UUID: 3d6cc537-d775-4a6e-9452-af3e3d6b611d
[farmos_agent] activated — daily report scheduled at 06:00
```

Both containers reached running state. Scheduler active for 06:00 daily run.

## Manual execute_report Outcome

Triggered manual `execute_report` for 2026-04-12 (yesterday):

```
[farmos_agent] running report for 2026-04-12
[farmos_agent] observation for 2026-04-12 already exists — skipping
```

**Duplicate detected (idempotency guard D-09 working correctly).** A stale observation with wrong humidity values (9671%) exists for 2026-04-12. Pending admin action:

- Delete "FC-1 Daily Report 2026-04-12" at http://10.68.155.50:8082/asset/28 → Logs
- Re-trigger: `docker compose exec farmos-agent bash -c "source /opt/ros/jazzy/setup.bash && python3 -c 'from farmos_agent.farmos_agent_node import FarmOSAgent; import rclpy; rclpy.init(); n=FarmOSAgent(); n.on_configure(None); n.execute_report(); n.destroy_node(); rclpy.shutdown()'"`
- OR wait for tomorrow's 06:00 automated run (2026-04-13 report)

## Status

Both containers running with Plan 03 code fixes deployed. Ready for FarmOS admin actions in Task 2.
