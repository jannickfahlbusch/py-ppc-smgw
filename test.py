import asyncio
import logging
import os
from datetime import datetime, timedelta

import httpx

from py_ppc_smgw import PPCSMGWClient
from py_ppc_smgw.actions import Action

logging.basicConfig(level=logging.DEBUG)
logging.getLogger("httpcore").setLevel(logging.WARN)
logging.getLogger("httpx").setLevel(logging.WARN)
logger = logging.getLogger("py_ppc_smgw")


def print_line(message: str, length: int = 80):
    logger.info("-" * length)
    logger.info(message)


async def main():
    httpx_client = httpx.AsyncClient(verify=False)

    ppc_smgw_client = PPCSMGWClient(
        host=os.environ.get("SMGW_HOST", "https://localhost:8443/cgi-bin/hanservice.cgi"),
        username=os.environ.get("SMGW_USERNAME", "1234567890"),
        password=os.environ.get("SMGW_PASSWORD", "test"),
        httpx_client=httpx_client,
        logger=logger,
    )

    logger.info("Constructed everything, trying to use")

    async with ppc_smgw_client:
        logger.info("Connected!")

        print_line("Firmware Versions:")

        versions = await ppc_smgw_client.get_firmware_versions()

        for version in versions:
            logger.info(f"{version.component}: {version.version} ({version.checksum})")

        print_line("Meters:")

        meters = await ppc_smgw_client.get_meters()
        logger.info(meters)

        for meter in meters:
            print_line("Current Readings:")
            readings = await ppc_smgw_client.get_meter_reading(meter)
            logger.info(f"{meter}: {readings}")

            print_line("Meter Profile (raw CMS dump, 60s timeout, NO tkn):")
            raw_profile = await ppc_smgw_client._request(
                Action.ExportMeterProfile,
                {"mid": meter.mid},
                timeout=60,
            )
            with open("/tmp/meter_profile_sample.bin", "wb") as f:
                f.write(raw_profile.content)
            logger.info(
                f"Saved {len(raw_profile.content)} bytes to /tmp/meter_profile_sample.bin "
                f"(status={raw_profile.status_code})"
            )

            print_line("Export Meter Values (raw CMS dump):")
            raw_resp = await ppc_smgw_client._request(
                Action.ExportMeterValues,
                {"mid": meter.mid, "from": str(datetime.now() - timedelta(hours=2)), "to": str(datetime.now())},
            )
            with open("/tmp/cms_sample.bin", "wb") as f:
                f.write(raw_resp.content)
            logger.info(f"Saved {len(raw_resp.content)} bytes to /tmp/cms_sample.bin")

            print_line("Export Meter Values (parsed):")
            entries = await ppc_smgw_client.export_meter_values(
                meter, from_time=datetime.now() - timedelta(hours=2), to_time=datetime.now()
            )
            for entry in entries:
                logger.info(f"{entry.capture_time}: {entry.value}, {entry.unit} {entry.scaler} {entry.obis}")


asyncio.run(main())
