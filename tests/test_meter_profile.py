"""Tests for meter-profile parsing and the get_meter_profile client method.

All fixtures here are synthetic — fake meter IDs, no real device serials, no
certificates or signatures. The CMS envelope is faked with an arbitrary byte
prefix/suffix around the XML so the marker-fallback path in extract_xml_from_cms
is exercised without needing a real PKCS#7 signature.
"""

import logging

import httpx
import pytest
from pytest_httpx import HTTPXMock

from py_ppc_smgw import PPCSMGWClient
from py_ppc_smgw.parsing import cosem_hex_to_obis, parse_meter_profile
from py_ppc_smgw.types import Meter, MeterProfile

# --- Synthetic fixtures -----------------------------------------------------

# A minimal, synthetic LMN container mirroring the real exportMeterProfile
# structure. IDs are fabricated; only the field shapes are realistic.
_METER_PROFILE_XML = b"""<?xml version="1.0" encoding="UTF-8"?>
<klc:container id="00000000e000.synthmeter00000001.sm"
 xmlns:adevs="urn:k461-dke-de:abstract_device_setup-1"
 xmlns:adls="urn:k461-dke-de:abstract_device_lmn_setup-1"
 xmlns:cox="urn:k461-dke-de:extension-1"
 xmlns:ems="urn:k461-dke-de:e_meter_sensor_setup-1"
 xmlns:klc="urn:k461-dke-de:kaf_lmn_container-1"
 xmlns:kli="urn:k461-dke-de:kaf_lmn_index-1">
  <klc:e_meter_device_object class_id="32809" class_version="0" id="00000000e001.synthmeter00000001.sm">
    <ems:attributes count="19">
      <cox:logical_name id="1">00000000e001.synthmeter00000001.sm</cox:logical_name>
      <adevs:device_identifier id="2">synthmeter00000001</adevs:device_identifier>
      <adevs:device_type id="3">0</adevs:device_type>
      <adevs:active id="4">1</adevs:active>
      <adevs:samplerate id="5">900</adevs:samplerate>
      <adls:com_type id="7">TLS</adls:com_type>
      <ems:values count="5" id="16">
        <ems:value id="1">0100010800ff</ems:value>
        <ems:value id="2">0100020800ff</ems:value>
        <ems:value id="3">0100200700ff</ems:value>
        <ems:value id="4">0100340700ff</ems:value>
        <ems:value id="5">0100480700ff</ems:value>
      </ems:values>
    </ems:attributes>
  </klc:e_meter_device_object>
</klc:container>"""


def _fake_cms(xml: bytes) -> bytes:
    """Wrap XML in fake CMS envelope bytes to exercise the marker-fallback path.

    Real responses are PKCS#7 SignedData; here we only need bytes before <?xml
    and after the closing tag, with no valid ASN.1, so the parser falls through
    to marker extraction.
    """
    return b"\x30\x82\xff\xff" + xml + b"\x00\x01\x02signature-not-real"


METER_PROFILE_CMS = _fake_cms(_METER_PROFILE_XML)

_EXPECTED_OBIS = ["1-0:1.8.0", "1-0:2.8.0", "1-0:32.7.0", "1-0:52.7.0", "1-0:72.7.0"]


# --- cosem_hex_to_obis ------------------------------------------------------


class TestCosemHexToObis:
    @pytest.mark.parametrize(
        ("hex_code", "expected"),
        [
            ("0100010800ff", "1-0:1.8.0"),
            ("0100020800ff", "1-0:2.8.0"),
            ("0100200700ff", "1-0:32.7.0"),
            ("short", "short"),
            ("", ""),
        ],
    )
    def test_conversion(self, hex_code: str, expected: str) -> None:
        assert cosem_hex_to_obis(hex_code) == expected


# --- parse_meter_profile ----------------------------------------------------


class TestParseMeterProfile:
    def test_full_profile(self) -> None:
        profile = parse_meter_profile(METER_PROFILE_CMS)
        assert profile.samplerate_s == 900
        assert profile.active is True
        assert profile.captured_obis == _EXPECTED_OBIS
        # mid is set by the client, not the parser
        assert profile.mid == ""

    def test_inactive_meter(self) -> None:
        xml = _METER_PROFILE_XML.replace(
            b'<adevs:active id="4">1</adevs:active>',
            b'<adevs:active id="4">0</adevs:active>',
        )
        assert parse_meter_profile(_fake_cms(xml)).active is False

    def test_missing_samplerate_is_none(self) -> None:
        xml = _METER_PROFILE_XML.replace(b'<adevs:samplerate id="5">900</adevs:samplerate>', b"")
        assert parse_meter_profile(_fake_cms(xml)).samplerate_s is None

    def test_non_numeric_samplerate_is_none(self) -> None:
        xml = _METER_PROFILE_XML.replace(
            b'<adevs:samplerate id="5">900</adevs:samplerate>',
            b'<adevs:samplerate id="5">n/a</adevs:samplerate>',
        )
        assert parse_meter_profile(_fake_cms(xml)).samplerate_s is None

    def test_missing_active_is_none(self) -> None:
        xml = _METER_PROFILE_XML.replace(b'<adevs:active id="4">1</adevs:active>', b"")
        assert parse_meter_profile(_fake_cms(xml)).active is None

    def test_no_values_is_empty_list(self) -> None:
        xml = (
            _METER_PROFILE_XML.replace(b"0100010800ff", b"")
            .replace(b"0100020800ff", b"")
            .replace(b"0100200700ff", b"")
            .replace(b"0100340700ff", b"")
            .replace(b"0100480700ff", b"")
        )
        # empty <ems:value/> elements have no text -> skipped
        assert parse_meter_profile(_fake_cms(xml)).captured_obis == []


# --- get_meter_profile (integration) ----------------------------------------


@pytest.mark.asyncio
@pytest.mark.usefixtures("mock_login", "mock_logout")
class TestGetMeterProfileIntegration:
    async def test_sends_correct_action_and_returns_profile(
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
            content=METER_PROFILE_CMS,
        )

        async with PPCSMGWClient(
            host=smgw_host,
            username=username,
            password=password,
            httpx_client=httpx.AsyncClient(),
            logger=logging.getLogger("test"),
        ) as client:
            profile = await client.get_meter_profile(Meter(mid="fake_mid_0001", name="synth.sm"))

        assert isinstance(profile, MeterProfile)
        assert profile.mid == "fake_mid_0001"
        assert profile.samplerate_s == 900
        assert profile.active is True
        assert profile.captured_obis == _EXPECTED_OBIS

        post_requests = [
            r for r in httpx_mock.get_requests() if r.method == "POST" and b"action=exportMeterProfile" in r.content
        ]
        assert len(post_requests) == 1
        assert b"mid=fake_mid_0001" in post_requests[0].content
