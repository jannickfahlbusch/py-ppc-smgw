"""Tests for firmware version retrieval."""

import logging

import httpx
import pytest
from pytest_httpx import HTTPXMock

from py_ppc_smgw import PPCSMGWClient
from py_ppc_smgw.types import FirmwareVersion

SWVERSIONS_HTML = """<html><head><title>Smart Meter Gateway</title></head><body>
<table width=100% cellpadding=0 cellspacing=0 border=1>
<tr><th>Komponente</th><th>Version</th><th>Prüfsumme</th></tr>
<tr><td>smgw-bootstream</td><td>33918</td><td>3044022007f60e61</td></tr>
<tr><td>smgw-services</td><td>34868</td><td>304402201df9b452</td></tr>
</table>
<div id="div_fwversion">33918-34868</div>
</body></html>"""


@pytest.mark.asyncio
@pytest.mark.usefixtures("mock_login")
async def test_get_firmware_versions(
    httpx_mock: HTTPXMock,
    smgw_host: str,
    username: str,
    password: str,
) -> None:
    # Order matters: client does POST swversions first, then POST logout
    httpx_mock.add_response(
        method="POST",
        url=smgw_host,
        status_code=200,
        html=SWVERSIONS_HTML,
    )
    httpx_mock.add_response(
        method="POST",
        url=smgw_host,
        status_code=200,
        html="<html><body>abgemeldet</body></html>",
    )

    async with PPCSMGWClient(
        host=smgw_host,
        username=username,
        password=password,
        httpx_client=httpx.AsyncClient(),
        logger=logging.getLogger("test"),
    ) as client:
        versions = await client.get_firmware_versions()

    assert versions == [
        FirmwareVersion(
            component="smgw-bootstream",
            version="33918",
            checksum="3044022007f60e61",
        ),
        FirmwareVersion(
            component="smgw-services",
            version="34868",
            checksum="304402201df9b452",
        ),
    ]
