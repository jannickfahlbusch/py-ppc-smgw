import logging

import httpx
import pytest
from pytest_httpx import HTTPXMock

from py_ppc_smgw import PPCSMGWClient
from py_ppc_smgw.errors import LoginFailedError


@pytest.mark.asyncio
class TestLogin:
    @pytest.mark.usefixtures("mock_login")
    async def test_login(self, smgw_host: str, username: str, password: str) -> None:
        client = PPCSMGWClient(
            host=smgw_host,
            username=username,
            password=password,
            httpx_client=httpx.AsyncClient(),
            logger=logging.getLogger("test"),
        )

        await client.login()

        assert client.session_active()
        assert client._cookies == {"Cookie": "123456789"}

    @pytest.mark.usefixtures("mock_login")
    async def test_login_session_cookie_still_present(
        self,
        smgw_host: str,
        username: str,
        password: str,
    ) -> None:
        client = PPCSMGWClient(
            host=smgw_host,
            username=username,
            password=password,
            httpx_client=httpx.AsyncClient(),
            logger=logging.getLogger("test"),
        )

        # Simulate a stale cookie left from a previous session
        client.httpx_client.cookies.set("session", "old_stale_value")

        await client.login()

        # Cookie was cleared and replaced with new one
        assert client.session_active()
        assert client._cookies == {"Cookie": "123456789"}

    async def test_login_raises_connection_error_no_cookie(
        self,
        httpx_mock: HTTPXMock,
        smgw_host: str,
        username: str,
        password: str,
    ) -> None:
        httpx_mock.add_response(
            method="GET",
            url=smgw_host,
            status_code=200,
            html="<html><body>No cookie here</body></html>",
        )

        client = PPCSMGWClient(
            host=smgw_host,
            username=username,
            password=password,
            httpx_client=httpx.AsyncClient(),
            logger=logging.getLogger("test"),
        )

        with pytest.raises(LoginFailedError, match="no session cookie"):
            await client.login()
            assert not client.session_active()

    async def test_login_connection_error(
        self,
        httpx_mock: HTTPXMock,
        smgw_host: str,
        username: str,
        password: str,
    ) -> None:
        httpx_mock.add_exception(
            method="GET",
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

        with pytest.raises(ConnectionError, match="Connection refused"):
            await client.login()
            assert not client.session_active()
