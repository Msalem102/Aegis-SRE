# Protocols and interfaces

**Submission repository:** https://github.com/Msalem102/personal-insight

## Integration boundaries

| Connection | Protocol/interface | Purpose |
|---|---|---|
| Mobile ↔ Aegis | HTTPS with JSON REST requests | Read service and incident information; optionally initiate an explicit remediation |
| Aegis → foreground mobile client | Server-Sent Events over HTTPS | One-way progress/event updates |
| Monitoring system → Aegis | HTTP webhook, deployed over HTTPS | Deliver incident alerts |
| Aegis ↔ PostgreSQL | PostgreSQL driver and read-only telemetry connection | Inspect database statistics, schema and query context |
| Aegis ↔ model provider | Provider HTTP API | Generate candidate corrections and incident reports |
| Aegis ↔ Modal | Modal SDK/cloud execution interface | Run isolated verification workloads |
| Aegis ↔ GitHub | Authenticated GitHub API | Create branches, commits and PRs |
| Mobile → GitHub | HTTPS URL opened externally | Human review of the proposed fix |

HTTPS deployment, authentication and authorization are requirements for the proposed remote mobile integration; they are not presented as completed features of the inspected local listener.

## Existing backend routes inspected

| Method and path | Role | Client use |
|---|---|---|
| `GET /api/status` | Active service, repository, branch and monitor state | Overview |
| `GET /api/services` | Configured services | Service selection |
| `GET /api/incidents` | Incident history/results | Incident list and selected detail |
| `GET /api/stream/events` | SSE JSON events | Progress while app is foregrounded |
| `GET /api/logs?since_id=...` | Logs after a known event identifier | Refresh/reconnect support |
| `POST /api/remediate` | Manual database/API workflow | Optional explicit user action |
| `POST /webhooks/alert` | Alert ingestion | Backend monitoring integration |

The inspected manual remediation endpoint waits for the worker result. It is not an existing asynchronous job-ID API. Progress can arrive independently through the event stream. A production mobile integration may later add an asynchronous job interface and explicit incident-stage messages.

## Proposed client contracts

- `ServiceRepository`: load current status and configured services.
- `IncidentRepository`: load incident summaries/results and retrieve cached data.
- `EventStreamClient`: subscribe, disconnect, reconnect and deduplicate event identifiers.
- `PullRequestLauncher`: open a confirmed PR URL externally.
- `LocalCache`: save bounded summaries with source and retrieval timestamps.

HTTP errors, disconnected streams and verification failures become explicit ViewModel states. Stale cached results must never be presented as current live telemetry. SSE is a foreground connection, not a replacement for background push notification services.

## Result interpretation

The backend delivery engine can use `SIMULATED_LOCAL` when a GitHub token is absent. The mobile design must distinguish simulation from `LIVE_GITHUB_PR` or a confirmed existing live PR, and must not open a constructed simulation URL as proof of delivery.

Database results show measured or recorded benchmark context. API results show the actual targeted test count. Neither implies that production was deployed or that every application behavior was tested.

## Sources

- [FastAPI listener](https://github.com/ahmedharib/Aegis-SRE/blob/master/core/webhooks/listener.py)
- [GitHub delivery](https://github.com/ahmedharib/Aegis-SRE/blob/master/core/delivery/github_delivery.py)
