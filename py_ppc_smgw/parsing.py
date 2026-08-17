"""Parsing functions for PPC SMGW HTML and XML responses."""

import xml.etree.ElementTree as ET
from datetime import datetime
from typing import cast

from asn1crypto import cms
from bs4 import BeautifulSoup, Tag
from obis_parser import OBIS

from .types import FirmwareVersion, Meter, MeterEntry, MeterProfile, Reading

_CMS_XML_END_TAGS = (
    b"</ns1:object>",
    b"</khw:container>",
    b"</klc:container>",
    b"</taf01:object>",
    b"</taf07:object>",
)


def extract_xml_from_cms(content: bytes) -> bytes:
    """
    Extract embedded XML from a CMS/PKCS#7 SignedData envelope.

    Tries proper ASN.1 parsing first (works with real SMGW responses).
    Falls back to marker-based extraction (works with fake server / incomplete CMS).
    """
    try:
        content_info = cms.ContentInfo.load(content)
        signed_data = content_info["content"]
        return cast("bytes", signed_data["encap_content_info"]["content"].native)
    except Exception:
        pass

    xml_start = content.find(b"<?xml")
    if xml_start == -1:
        raise ValueError("No XML found in export response")

    for end_tag in _CMS_XML_END_TAGS:
        end_pos = content.rfind(end_tag)
        if end_pos != -1:
            return content[xml_start : end_pos + len(end_tag)]

    return content[xml_start:]


def parse_meters(html: bytes) -> list[Meter]:
    """Parse meter list from meterform HTML response."""
    soup = BeautifulSoup(html, "html.parser")
    select = soup.find("select", id="meterform_select_meter")
    if not isinstance(select, Tag):
        return []

    meters: list[Meter] = []
    for option in select.find_all("option"):
        if not isinstance(option, Tag):
            continue
        value = option.get("value", "")
        if not isinstance(value, str):
            continue
        meters.append(
            Meter(
                mid=value,
                name=option.get_text().strip(),
            )
        )

    return meters


def parse_meter_reading(html: bytes) -> dict[OBIS, Reading]:
    """Parse meter readings from showMeterProfile HTML response."""
    soup = BeautifulSoup(html, "html.parser")

    table_data = soup.find("table", id="metervalue")
    if not isinstance(table_data, Tag):
        return {}

    rows = table_data.find_all("tr")
    timestamp: datetime | None = None
    readings: dict[OBIS, Reading] = {}

    for row in rows:
        if not isinstance(row, Tag):
            continue

        obis_cell = row.find(id="table_metervalues_col_obis")
        if not isinstance(obis_cell, Tag) or obis_cell.string is None:
            continue

        row_timestamp = row.find(id="table_metervalues_col_timestamp")
        if isinstance(row_timestamp, Tag) and row_timestamp.string is not None:
            timestamp = datetime.strptime(row_timestamp.string, "%Y-%m-%d %H:%M:%S")

        if timestamp is None:
            continue

        value_cell = row.find(id="table_metervalues_col_wert")
        if not isinstance(value_cell, Tag) or value_cell.string is None:
            continue

        obis = OBIS.parse(obis_cell.string.strip())
        if obis is None:
            continue

        readings[obis] = Reading(
            value=value_cell.string,
            timestamp=timestamp,
            obis=obis,
        )

    return readings


def parse_firmware_versions(html: bytes) -> list[FirmwareVersion]:
    """Parse firmware versions from swversions HTML response."""
    soup = BeautifulSoup(html, "html.parser")
    rows = soup.find_all("tr")
    versions: list[FirmwareVersion] = []
    for row in rows[1:]:
        cells = row.find_all("td")
        if len(cells) == 3:
            versions.append(
                FirmwareVersion(
                    component=cells[0].get_text().strip(),
                    version=cells[1].get_text().strip(),
                    checksum=cells[2].get_text().strip(),
                )
            )
    return versions


def parse_export_meter_values(content: bytes) -> list[MeterEntry]:
    """Parse meter values from exportMeterValues CMS response."""
    xml_content = extract_xml_from_cms(content)

    ns = {
        "ns1": "urn:k461-dke-de:profile_generic-1",
        "ns2": "urn:k461-dke-de:extension-1",
    }

    root = ET.fromstring(xml_content)
    entries: list[MeterEntry] = []

    capture_obj = root.find(".//ns1:capture_object/ns2:logical_name", ns)
    obis_logical = capture_obj.text if capture_obj is not None and capture_obj.text else ""
    obis = OBIS.parse(obis_logical)
    if obis is None:
        return []

    for entry in root.findall(".//ns1:entry_gateway_signed", ns):
        value_el = entry.find("ns2:value/ns2:long64", ns)
        scaler_el = entry.find("ns2:scaler", ns)
        unit_el = entry.find("ns2:unit", ns)
        status_el = entry.find("ns2:status/ns2:unsigned", ns)
        time_el = entry.find("ns2:capture_time", ns)
        sig_el = entry.find("ns2:smgw_signature", ns)

        if value_el is None or time_el is None:
            continue

        entries.append(
            MeterEntry(
                value=float(value_el.text or "0"),
                scaler=int(scaler_el.text or "0") if scaler_el is not None else 0,
                unit=int(unit_el.text or "0") if unit_el is not None else 0,
                status=int(status_el.text or "0") if status_el is not None else 0,
                capture_time=datetime.fromisoformat(time_el.text) if time_el.text else datetime.now(),
                obis=obis,
                signature=sig_el.text or "" if sig_el is not None else "",
            )
        )

    return entries


def parse_meter_profile(content: bytes) -> MeterProfile:
    """
    Parse meter setup metadata from an exportMeterProfile CMS response.

    Extracts the meter's own identifier (serial), read-out cadence (samplerate), active
    flag and the list of captured OBIS codes from the signed LMN container. Reads are
    scoped to the meter's e_meter_device_object. Individual missing fields degrade to
    None / empty list rather than raising, since the gateway controls the XML layout.
    (Malformed or non-XML content still raises, as with the other export parsers.)
    """
    xml_content = extract_xml_from_cms(content)

    ns = {
        "klc": "urn:k461-dke-de:kaf_lmn_container-1",
        "adevs": "urn:k461-dke-de:abstract_device_setup-1",
        "ems": "urn:k461-dke-de:e_meter_sensor_setup-1",
    }

    root = ET.fromstring(xml_content)

    # Scope reads to the meter's device object. A real container also holds a sibling
    # klc:kaf_object (index/routing), and could in principle hold more than one meter
    # object; searching from root with .// would risk picking up the wrong element or
    # concatenating OBIS across meters. We read the first e_meter_device_object — the
    # gateway returns the profile for the single mid we requested.
    device = root.find(".//klc:e_meter_device_object", ns)
    if device is None:
        return MeterProfile(mid="", device_identifier=None, samplerate_s=None, active=None, captured_obis=[])

    ident_el = device.find(".//adevs:device_identifier", ns)
    device_identifier = ident_el.text.strip() if ident_el is not None and ident_el.text else None

    samplerate_el = device.find(".//adevs:samplerate", ns)
    samplerate_s = (
        int(samplerate_el.text.strip())
        if samplerate_el is not None and samplerate_el.text and samplerate_el.text.strip().isdigit()
        else None
    )

    active_el = device.find(".//adevs:active", ns)
    active = active_el.text.strip() == "1" if active_el is not None and active_el.text else None

    captured_obis: list[OBIS] = []
    for value_el in device.findall(".//ems:values/ems:value", ns):
        if value_el.text and (obis := OBIS.parse(value_el.text.strip())):
            captured_obis.append(obis)

    return MeterProfile(
        mid="",
        device_identifier=device_identifier,
        samplerate_s=samplerate_s,
        active=active,
        captured_obis=captured_obis,
    )
