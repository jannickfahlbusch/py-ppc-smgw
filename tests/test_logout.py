import logging

import httpx
import pytest
from pytest_httpx import HTTPXMock

from py_ppc_smgw import PPCSMGWClient


@pytest.mark.asyncio
@pytest.mark.usefixtures("mock_login")
class TestLogout:
    async def test_logout(
        self,
        httpx_mock: HTTPXMock,
        smgw_host: str,
        username: str,
        password: str,
    ) -> None:
        httpx_mock.add_response(
            method="POST",
            url=smgw_host,
            status_code=200,
            html="<html>abgemeldet</html>",
        )

        async with PPCSMGWClient(
            host=smgw_host,
            username=username,
            password=password,
            httpx_client=httpx.AsyncClient(),
            logger=logging.getLogger("test"),
        ) as client:
            await client.logout()
            assert not client.session_active()

    async def test_logout_connection_error(
        self,
        httpx_mock: HTTPXMock,
        smgw_host: str,
        username: str,
        password: str,
    ) -> None:
        httpx_mock.add_exception(
            method="POST",
            url=smgw_host,
            exception=httpx.ConnectError("Connection refused"),
        )

        client = PPCSMGWClient(
            host=smgw_host,
            username=username,
            password=password,
            httpx_client=httpx.AsyncClient(),
            logger=logging.getLogger("test"),
        )

        await client.login()

        with pytest.raises(ConnectionError, match="Error logging out"):
            await client.logout()

        assert not client.session_active()
        assert client._cookies == {}
