"""Shared fixtures for py-ppc-smgw tests."""

import pytest
from pytest_httpx import HTTPXMock


@pytest.fixture
def smgw_host() -> str:
    return "https://fake-smgw/cgi-bin/hanservice.cgi"


@pytest.fixture
def username() -> str:
    return "1234567890"


@pytest.fixture
def password() -> str:
    return "a-super-secret-password#?0!@"


LOGIN_HTML = """<html><body>
<input type="hidden" name="tkn" value="abc123">
<h1 id='headline_willkommen'>Willkommen</h1>
</body></html>"""


@pytest.fixture
def mock_login(httpx_mock: HTTPXMock, smgw_host: str) -> None:
    httpx_mock.add_response(
        method="GET",
        url=smgw_host,
        status_code=200,
        html=LOGIN_HTML,
        headers={"Set-Cookie": "session=123456789;secure;HttpOnly"},
    )


@pytest.fixture
def mock_logout(httpx_mock: HTTPXMock, smgw_host: str) -> None:
    httpx_mock.add_response(
        method="POST",
        url=smgw_host,
        match_content=b"action=logout",
        status_code=200,
        html="<html><body>abgemeldet</body></html>",
    )
