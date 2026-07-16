"""PPC SMGW API."""

from logging import Logger
from typing import Self

import httpx

from .actions import Action
from .errors import LoginFailedError, SessionCookieStillPresentError
from .parsing import (
    parse_export_meter_values,
    parse_firmware_versions,
    parse_meter_profile,
    parse_meter_reading,
    parse_meters,
)
from .types import FirmwareVersion, Meter, MeterEntry, MeterProfile, OBISCode, Reading


class PPCSMGWClient:
    def __init__(
        self,
        host: str,
        username: str,
        password: str,
        httpx_client: httpx.AsyncClient,
        logger: Logger,
    ) -> None:
        self.host = host
        self.username = username
        self.password = password

        self.httpx_client = httpx_client
        self.logger = logger

        self._cookies: dict[str, str] = {}

        # Internal marker to store if we are already logged in
        self._session_active = False

    async def __aenter__(self) -> Self:
        await self.login()
        return self

    async def __aexit__(self, *exc: object) -> None:
        if self._session_active:
            await self.logout()

    def session_active(self) -> bool:
        return self._session_active

    async def _request(
        self,
        action: Action,
        additional_parameters: dict[str, str] | None = None,
        timeout: float = 10,
    ) -> httpx.Response:
        return await self.httpx_client.post(
            self.host,
            data={"action": action.value, **(additional_parameters or {})},
            cookies=self._cookies,
            timeout=timeout,
            auth=self._auth,
        )

    async def login(self) -> httpx.Response:
        self.logger.info("Attempting to login to PPC SMGW")

        # Fresh DigestAuth per poll cycle — the gateway's CGI architecture has no
        # persistent nonce state, so reusing a stale nonce from 15 minutes ago fails.
        # Within a single get_data() session the nonce is reused (login→posts→logout).
        self._auth = httpx.DigestAuth(username=self.username, password=self.password)

        # Clear session state upfront so no stale credentials survive any failure path
        self._cookies = {}

        # TODO: Find a way to remove the cookie here!
        # See https://github.com/encode/httpx/pull/3065
        if self.httpx_client.cookies.get(name="session") is not None:
            self.logger.debug("Session cookie still present, trying to delete it")

            self.httpx_client.cookies.delete(name="session")
            self.logger.debug("Deleted session cookie")

            if "session" in self.httpx_client.cookies:
                self.logger.error("Session cookie still present after deletion")
                raise SessionCookieStillPresentError

        try:
            response = await self.httpx_client.get(
                self.host,
                timeout=10,
                auth=self._auth,
            )
        except Exception as e:
            msg = f"Error connecting to {self.host}: {e}"
            self.logger.error(msg)
            raise ConnectionError(msg) from e

        if "session" not in response.cookies:
            msg = f"Login to {self.host} failed: no session cookie in response (HTTP {response.status_code})"
            self.logger.error(msg)
            raise LoginFailedError(msg)
        self._cookies = {"Cookie": response.cookies["session"]}
        self._session_active = True
        self.logger.info("Got cookie response, assuming we are logged in")

        return response

    async def logout(self) -> None:
        # The PPC SMGW only allows a single session to be active at a time
        # Since we don't know the lifetime of the session, we should log out so that we are able to log back in later
        self.logger.info("trying to log out")

        self._session_active = False
        self._cookies = {}

        try:
            response = await self._request(Action.Logout)
            self.logger.debug(f"Got response: {response}\nContent: {response.content!r}")

        except Exception as e:
            raise ConnectionError(f"Error logging out: {e}") from e

    async def get_meters(self) -> list[Meter]:
        response = await self._request(action=Action.MeterForm)
        return parse_meters(response.content)

    async def get_meter_reading(self, meter: Meter) -> dict[OBISCode, Reading]:
        response = await self._request(Action.ShowMeterProfile, {"mid": meter.mid})
        readings = parse_meter_reading(response.content)
        self.logger.info(f"Found {len(readings)} readings")
        return readings

    async def get_meter_profile(self, meter: Meter) -> MeterProfile:
        """
        Fetch meter setup metadata: read-out cadence, active flag, captured OBIS codes.

        Sourced from the CMS-signed exportMeterProfile response. Intended to be called once
        at configuration / component-setup time, not on every poll cycle.

        This action is slow: the gateway fetches the profile from the meter over the LMN link
        on demand and can take well over 10s to respond, so a longer timeout is used.
        """
        self.logger.info("getting meter profile")
        response = await self._request(Action.ExportMeterProfile, {"mid": meter.mid}, timeout=60)
        profile = parse_meter_profile(response.content)
        profile.mid = meter.mid
        self.logger.debug(f"Got meter profile: {profile}")
        return profile

    async def export_meter_values(self, meter: Meter, from_time: str, to_time: str) -> list[MeterEntry]:
        response = await self._request(
            Action.ExportMeterValues,
            {"mid": meter.mid, "from": from_time, "to": to_time},
        )
        entries = parse_export_meter_values(response.content)
        self.logger.info(f"Parsed {len(entries)} meter entries from export")
        return entries

    async def get_firmware_versions(self) -> list[FirmwareVersion]:
        self.logger.info("getting firmware versions")
        response = await self._request(Action.SoftwareVersions)
        versions = parse_firmware_versions(response.content)
        self.logger.debug(f"Got versions: {versions}")
        return versions

    async def selftest(self) -> None:
        """Call the self-test of the SMWG. This reboots the SMGW."""
        self.logger.info("Running self-test")

        await self._request(Action.Selftest)

        self._session_active = False

    async def reboot(self) -> None:
        """Reboot the SMGW through a Self-Test."""
        await self.selftest()
