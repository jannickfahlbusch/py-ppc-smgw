# py-ppc-smgw

Async Python client for **PPC Smart Meter Gateways** (BSI TR-03109 / German Smart Meter Gateway, PPC vendor implementation).

Talks to the consumer-facing HAN-API of a PPC SMGW: Digest authentication, meter readings, firmware versions, historic export, reboot.

> **Status: alpha.** Used as the upstream client for the [`ha-ppc-smgw`](https://github.com/jannickfahlbusch/ha-ppc-smgw) Home Assistant integration. API surface is stable for the implemented methods, but not yet 1.0.

## Installation

```bash
pip install py-ppc-smgw
```

Or with uv:

```bash
uv add py-ppc-smgw
```

Requires Python 3.13+.

## Quick start

```python
import asyncio
import logging

import httpx

from py_ppc_smgw import PPCSMGWClient


async def main() -> None:
    logger = logging.getLogger("py-ppc-smgw")

    async with httpx.AsyncClient(verify=False) as http:
        async with PPCSMGWClient(
            host="https://192.0.2.1",
            username="user",
            password="secret",
            httpx_client=http,
            logger=logger,
        ) as client:
            # Firmware versions
            for fw in await client.get_firmware_versions():
                print(f"{fw.component}: {fw.version}")

            # Meter readings (current values)
            meters = await client.get_meters()
            readings = await client.get_meter_reading(meters[0])
            for obis, reading in readings.items():
                print(f"{obis}: {reading.value} @ {reading.timestamp}")


asyncio.run(main())
```

The client is an async context manager — `__aenter__` calls `login()` and `__aexit__` calls `logout()`. The PPC SMGW only allows a single concurrent session per user, so always logging out is important.

## Implemented API surface

| Method | Purpose |
|---|---|
| `login() / logout()` | Session lifecycle (also handled by `async with`) |
| `get_meters()` | List installed meters |
| `get_meter_reading(meter)` | Current OBIS readings for a meter |
| `export_meter_values(meter, from, to)` | Historic interval values |
| `get_firmware_versions()` | `swversions` action |
| `selftest() / reboot()` | Reboot the gateway via self-test |

Stubbed (raise `NotImplementedError`):

- `get_tariff_profiles()` — `tariffform` endpoint, planned
- `export_log_data(from, to)` — log export, planned

## Notes on gateway behaviour

- **Digest authentication** with a fresh nonce per session. Stale nonces cached across HA-style 15-minute polls cause silent 200-but-empty responses on PPC firmware — the client always creates a fresh `httpx.DigestAuth` on every `login()`.
- **Timestamps are local time, not UTC.** The gateway returns naive datetimes in its own local zone. The library does not attach timezone info — consumers must localize at the boundary if needed.
- **Single session per user.** Always log out (use `async with` and you get this for free).
- **Polling rate**: 15-minute intervals are safe. Faster polling has been observed to crash the gateway (CGI process exhaustion, requires manual restart by the metering operator).

## Development

```bash
git clone https://github.com/jannickfahlbusch/py-ppc-smgw
cd py-ppc-smgw
uv sync
uv run pytest
uv run ruff check py_ppc_smgw/ tests/
uv run mypy py_ppc_smgw/
```

## License

Apache License 2.0 — see [LICENSE](LICENSE).
