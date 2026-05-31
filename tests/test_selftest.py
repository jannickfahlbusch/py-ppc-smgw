"""Tests for selftest and reboot."""

import logging

import httpx
import pytest
from pytest_httpx import HTTPXMock

from py_ppc_smgw import PPCSMGWClient

SELFTEST_HTML = """<html><body>
<p>Selbsttest wird ausgeführt...</p>
</body></html>"""


@pytest.mark.asyncio
@pytest.mark.parametrize("method_name", ["selftest", "reboot"])
@pytest.mark.usefixtures("mock_login")
async def test_selftest_and_reboot(
    httpx_mock: HTTPXMock,
    smgw_host: str,
    username: str,
    password: str,
    method_name: str,
) -> None:
    httpx_mock.add_response(
        method="POST",
        url=smgw_host,
        status_code=200,
        html=SELFTEST_HTML,
    )

    async with PPCSMGWClient(
        host=smgw_host,
        username=username,
        password=password,
        httpx_client=httpx.AsyncClient(),
        logger=logging.getLogger("test"),
    ) as client:
        await getattr(client, method_name)()

        assert not client.session_active(), (
            "_session_active should be False to indicate that a new session should be created."
        )

    requests = httpx_mock.get_requests()
    assert len(requests) == 2
    assert b"action=selftest" in requests[1].content
