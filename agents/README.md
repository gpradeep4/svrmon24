# Monitoring agents (reference)

L5 defines the **ingest contract** for OS daemons. Production-signed installers
for Linux / Windows / macOS / Unix are **out of scope** for L5 — use the
fixture client for lab and tests.

## Auth

1. Tenant admin: `POST /api/monitor/agents/enrollments` → one-time code  
2. Agent: `POST /api/monitor/agents/register` → `agent_id` + bearer `mat_…`  
3. Ingest / heartbeat / desired-state: `Authorization: Bearer mat_…`  
   (or `X-Monitor-Agent-Token`)

Gates: platform `MONITOR_LIVE_PROBES_ENABLED` + `MONITOR_LIVE_AGENT_ENABLED`
and tenant `monitor_live_opt_in` + `monitor_live_agent_opt_in` (fail-closed).

## Endpoints

| Method | Path | Notes |
| --- | --- | --- |
| `POST` | `/api/monitor/ingest/metrics` | LIVE `metric_samples`, `data_source=AGENT` |
| `POST` | `/api/monitor/ingest/logs` | LIVE `log_events`, `data_source=AGENT` |
| `POST` | `/api/monitor/ingest/file-events` | LIVE `file_version_events`, `AGENT_FILE_WATCH` |
| `GET` | `/api/monitor/agents/{id}/desired-state` | `watch_ids` / `stream_ids` / `target_ids` |
| `POST` | `/api/monitor/agents/{id}/heartbeat` | liveness |

Optional batch field `seq` (≥ 1) enables dedup via `monitor_ingest_cursors`.
Replaying the same or lower `seq` for a channel is a no-op (`deduped: true`).

## Multi-OS contract

| `os_family` | File watcher hint (`os_watcher`) | Core metrics |
| --- | --- | --- |
| `linux` | `inotify` | `cpu.usage_pct`, `mem.used_pct`, `disk.used_pct` |
| `windows` | `readdirectorychanges` | same |
| `macos` | `fsevents` | same |
| `unix` | `kqueue_or_poll` | same |

Payload `os_family` must match the registered agent. Extra OS-specific fields
go in `attrs` (metrics/logs) or event fields (files).

## Fixture client

```bash
# After register, with token + agent_id:
python agents/fixture_client.py \
  --base-url http://127.0.0.1:8200 \
  --agent-id agt-… \
  --token mat_… \
  --os-family linux \
  --stream-id ls-…
```

See `GET /api/monitor/meta` → `agent_ingest_contract` for the machine-readable
contract.
