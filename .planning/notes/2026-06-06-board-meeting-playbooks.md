# Board Meeting 2026-06-06 — Canonical Playbooks

Agreed at the board meeting as the six canonical farmer interaction playbooks.
These are the shared abstraction that both the Signal bot and the farmOS Flask app
should be clients of — one implementation, not two parallel ones.

## Playbooks

1. Inoculation session
2. Random observation
3. Create a todo task
4. Mark a task as done
5. Substrate prep (mix and jar/bag oats or sawdust before sterilization — "media prep" in mycology jargon, renamed for clarity)
6. Harvest event

## Intent

- Bot re-enable is gated on an intent router that identifies which playbook a farmer message belongs to before any conversation starts.
- Signal bot and farmOS Flask dashboard should share the same playbook implementation, not maintain separate code paths.
- MCP server is the read/query side of the same layer (assets, logs, strain codes) used by both surfaces and AI tooling.

## Next step

Short discuss session with radicheta + farmOS team to define each playbook's schema and validation before planning a build phase.
