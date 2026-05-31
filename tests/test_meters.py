"""Integration tests for meter client methods — verify wiring between HTTP and parsing."""

import logging

import httpx
import pytest
from pytest_httpx import HTTPXMock

from py_ppc_smgw import PPCSMGWClient
from py_ppc_smgw.types import Meter

METERFORM_HTML = """<html><body>
<select name='mid' id='meterform_select_meter' size=1>
<option value='abc123'>01005e318002.1lgz0067285558.sm</option>
</select>
</body></html>"""

METER_READING_HTML = """<html><body>
<table id="metervalue">
<tr><th>Header</th></tr>
<tr>
<td id='table_metervalues_col_timestamp'>2026-05-14 12:00:01</td>
<td id='table_metervalues_col_wert'>10.5993</td>
<td id='table_metervalues_col_obis'>1-0:2.8.0</td>
</tr>
</table>
</body></html>"""


@pytest.mark.asyncio
@pytest.mark.usefixtures("mock_login", "mock_logout")
class TestGetMetersIntegration:
    async def test_sends_correct_action(
        self,
        httpx_mock: HTTPXMock,
        smgw_host: str,
        username: str,
        password: str,
    ) -> None:
        httpx_mock.add_response(method="POST", url=smgw_host, status_code=200, html=METERFORM_HTML)

        async with PPCSMGWClient(
            host=smgw_host,
            username=username,
            password=password,
            httpx_client=httpx.AsyncClient(),
            logger=logging.getLogger("test"),
        ) as client:
            meters = await client.get_meters()

        assert len(meters) == 1
        post_requests = [
            r for r in httpx_mock.get_requests() if r.method == "POST" and b"action=meterform" in r.content
        ]
        assert len(post_requests) == 1


@pytest.mark.asyncio
@pytest.mark.usefixtures("mock_login", "mock_logout")
class TestGetMeterReadingIntegration:
    async def test_sends_correct_action_and_mid(
        self,
        httpx_mock: HTTPXMock,
        smgw_host: str,
        username: str,
        password: str,
    ) -> None:
        httpx_mock.add_response(method="POST", url=smgw_host, status_code=200, html=METER_READING_HTML)

        async with PPCSMGWClient(
            host=smgw_host,
            username=username,
            password=password,
            httpx_client=httpx.AsyncClient(),
            logger=logging.getLogger("test"),
        ) as client:
            readings = await client.get_meter_reading(Meter(mid="my_meter_id", name="test.sm"))

        assert "1-0:2.8.0" in readings
        post_requests = [
            r for r in httpx_mock.get_requests() if r.method == "POST" and b"action=showMeterProfile" in r.content
        ]
        assert len(post_requests) == 1
        assert b"mid=my_meter_id" in post_requests[0].content
