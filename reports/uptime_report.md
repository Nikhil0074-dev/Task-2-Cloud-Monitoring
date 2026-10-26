# Uptime Report

_Generated: 2026-10-24T13:51:04.983Z_

## Availability & latency

| Endpoint | Checks | Uptime | Avg ms | p95 ms | Max ms | Last status | Last check (UTC) |
|---|---:|---:|---:|---:|---:|:---:|---|
| GitHub Website | 6 | 83.33% | 3051.18 | 6751.19 | 6751.19 | DOWN (ERR) | 2026-10-24T13:50:52.951Z |
| GitHub API | 6 | 83.33% | 2166.47 | 4107.63 | 4107.63 | DOWN (ERR) | 2026-10-24T13:50:52.978Z |
| Example Site | 6 | 83.33% | 2236.39 | 4342.09 | 4342.09 | DOWN (ERR) | 2026-10-24T13:50:53.007Z |
| Web Frontend | 40 | 90.00% | 6.02 | 8.59 | 9.09 | UP (200) | 2026-10-24T07:20:48.232Z |
| Payments API | 40 | 80.00% | 5.00 | 7.66 | 7.68 | UP (200) | 2026-10-24T07:20:48.233Z |
| Auth Service | 40 | 100.00% | 98.96 | 1003.68 | 1006.72 | UP (200) | 2026-10-24T07:20:48.234Z |

## Incidents

| Endpoint | Started (UTC) | Duration | Failed checks | Status | Cause |
|---|---|---:|---:|:---:|---|
| Example Site | 2026-10-24T13:50:53.007Z | 0s | 1 | ONGOING | ConnectionError: HTTPSConnectionPool(host='example.com', port=443): Max retries exceeded with url: / (Caused by NewConnectionError("HTTPSConnection(host='example.com', port=443): Failed to establish a new connectio... |
| GitHub API | 2026-10-24T13:50:52.978Z | 0s | 1 | ONGOING | ConnectionError: HTTPSConnectionPool(host='api.github.com', port=443): Max retries exceeded with url: / (Caused by NameResolutionError("HTTPSConnection(host='api.github.com', port=443): Failed to resolve 'api.githu... |
| GitHub Website | 2026-10-24T13:50:52.951Z | 0s | 1 | ONGOING | ConnectionError: HTTPSConnectionPool(host='github.com', port=443): Max retries exceeded with url: / (Caused by NewConnectionError("HTTPSConnection(host='github.com', port=443): Failed to establish a new connection:... |
| Web Frontend | 2026-10-24T07:20:43.082Z | 2s | 4 | resolved | ConnectionError: ('Connection aborted.', RemoteDisconnected('Remote end closed connection without response')) |
| Payments API | 2026-10-24T07:20:31.332Z | 4s | 8 | resolved | Unexpected status 503 (expected [200]) |

## Status codes

| Endpoint | Distribution |
|---|---|
| GitHub Website | 200: 5, ERR: 1 |
| GitHub API | 200: 5, ERR: 1 |
| Example Site | 200: 5, ERR: 1 |
| Web Frontend | 200: 36, ERR: 4 |
| Payments API | 200: 32, 503: 8 |
| Auth Service | 200: 40 |
