"""Parsing functions for PPC SMGW HTML and XML responses."""

import xml.etree.ElementTree as ET
from datetime import datetime
from xml.parsers import expat

from bs4 import BeautifulSoup, Tag
from obis_parser import OBIS

from .errors import ResponseParseError
from .types import FirmwareVersion, Meter, MeterEntry, MeterProfile, Reading

_DKE_PROFILE_GENERIC_NS = {
    "p": "urn:k461-dke-de:profile_generic-1",
    "e": "urn:k461-dke-de:extension-1",
}
_EXPECTED_PROFILE_ROOT = f"{{{_DKE_PROFILE_GENERIC_NS['p']}}}object"


class _RootClosedError(Exception):
    """
    Internal signal: the embedded document root element was closed.

    Raised from the expat end-element handler to stop parsing immediately at the
    document boundary, excluding any subsequent CMS signature trailer bytes.
    """


def extract_xml_from_cms(content: bytes) -> bytes:
    """
    Extract embedded XML from a CMS/PKCS#7 SignedData envelope or raw XML stream.

    Uses a streaming expat depth counter to slice out the XML document at the root
    element boundary, stripping trailing PKCS#7 signature bytes without ASN.1 parsing.
    """
    start = content.find(b"<?xml")
    if start < 0:
        raise ResponseParseError("No XML declaration ('<?xml') found in export response.")

    payload = content[start:]
    parser = expat.ParserCreate()
    depth = 0
    max_depth = 0
    root_close_start = -1

    def _on_start(_name: str, _attrs: dict[str, str]) -> None:
        nonlocal depth, max_depth
        depth += 1
        max_depth = max(max_depth, depth)

    def _on_end(_name: str) -> None:
        nonlocal depth, root_close_start
        depth -= 1
        if depth == 0:
            root_close_start = parser.CurrentByteIndex
            raise _RootClosedError

    parser.StartElementHandler = _on_start
    parser.EndElementHandler = _on_end

    try:
        parser.Parse(payload, True)  # noqa: FBT003
    except _RootClosedError:
        pass
    except expat.ExpatError as err:
        raise ResponseParseError(f"Embedded XML is not well-formed: {err}") from err

    if root_close_start < 0:
        raise ResponseParseError("Embedded XML ended before its root was closed.")

    if max_depth < 2:
        raise ResponseParseError("Embedded XML root has no child elements.")

    if not payload.startswith(b"</", root_close_start):
        raise ResponseParseError("Root closing tag not found where expected.")

    close_end = payload.find(b">", root_close_start)
    if close_end < 0:
        raise ResponseParseError("Unterminated root closing tag in CMS response.")

    return payload[: close_end + 1]


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


def _build_column_obis_map(root: ET.Element) -> dict[str, OBIS]:
    """
    Map each column ID to its OBIS code via the capture_objects block.

    The logical_name element typically holds a COSEM identifier such as
    '0100010800ff.1lgz0072999211.sm', where the prefix maps to OBIS 1-0:1.8.0.
    """
    capture_objects = root.find("p:attributes/p:capture_objects", _DKE_PROFILE_GENERIC_NS)
    if capture_objects is None:
        raise ResponseParseError("capture_objects element not found in CMS XML.")

    mapping: dict[str, OBIS] = {}
    for obj in capture_objects.findall("p:capture_object", _DKE_PROFILE_GENERIC_NS):
        obj_id = obj.attrib.get("id")
        logical_name = obj.findtext("e:logical_name", default="", namespaces=_DKE_PROFILE_GENERIC_NS).strip()
        if not obj_id or not logical_name:
            continue

        raw_obis = logical_name.split(".")[0].strip()
        obis = OBIS.parse(raw_obis) or OBIS.parse(logical_name)
        if obis is not None:
            mapping[obj_id] = obis

    return mapping


def _parse_signed_entry(entry: ET.Element, obis: OBIS) -> MeterEntry | None:
    """
    Parse a single entry_gateway_signed element into a MeterEntry.

    Returns None if mandatory value or capture_time fields are missing.
    """
    value_text = entry.findtext("e:value/e:long64", default="", namespaces=_DKE_PROFILE_GENERIC_NS).strip()
    time_text = entry.findtext("e:capture_time", default="", namespaces=_DKE_PROFILE_GENERIC_NS).strip()
    if not value_text or not time_text:
        return None

    scaler_text = entry.findtext("e:scaler", default="0", namespaces=_DKE_PROFILE_GENERIC_NS).strip()
    unit_text = entry.findtext("e:unit", default="0", namespaces=_DKE_PROFILE_GENERIC_NS).strip()
    status_text = entry.findtext("e:status/e:unsigned", default="0", namespaces=_DKE_PROFILE_GENERIC_NS).strip()
    sig_text = entry.findtext("e:smgw_signature", default="", namespaces=_DKE_PROFILE_GENERIC_NS).strip()

    try:
        value = float(value_text)
        scaler = int(scaler_text) if scaler_text else 0
        unit = int(unit_text) if unit_text else 0
        status = int(status_text) if status_text else 0
        capture_time = datetime.fromisoformat(time_text)
    except (ValueError, TypeError) as err:
        raise ResponseParseError(f"Unparseable CMS meter entry: {err}") from err

    return MeterEntry(
        value=value,
        unit=unit,
        scaler=scaler,
        status=status,
        capture_time=capture_time,
        obis=obis,
        signature=sig_text,
    )


def parse_export_meter_values(content: bytes) -> list[MeterEntry]:
    """
    Parse meter values from exportMeterValues CMS response.

    Extracts the embedded DKE profile_generic-1 XML document, resolves
    column OBIS codes from capture_objects, and parses all signed meter entries.
    Entries are sorted chronologically by capture_time and OBIS code.
    """
    xml_content = extract_xml_from_cms(content)
    try:
        root = ET.fromstring(xml_content)
    except ET.ParseError as err:
        raise ResponseParseError(f"Invalid embedded XML in export response: {err}") from err

    if root.tag != _EXPECTED_PROFILE_ROOT:
        raise ResponseParseError(f"Unsupported embedded XML root: {root.tag}")

    column_obis = _build_column_obis_map(root)
    simple_data = root.find("p:attributes/p:buffer/p:simple_data", _DKE_PROFILE_GENERIC_NS)
    if simple_data is None:
        raise ResponseParseError("simple_data element not found in CMS XML.")

    entries: list[MeterEntry] = []
    for column in simple_data.findall("p:column", _DKE_PROFILE_GENERIC_NS):
        col_id = column.attrib.get("id", "")
        obis = column_obis.get(col_id)
        if obis is None:
            continue

        for entry_el in column.findall("p:entry_gateway_signed", _DKE_PROFILE_GENERIC_NS):
            entry = _parse_signed_entry(entry_el, obis)
            if entry is not None:
                entries.append(entry)

    entries.sort(key=lambda e: (e.capture_time, str(e.obis)))
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

    try:
        root = ET.fromstring(xml_content)
    except ET.ParseError as err:
        raise ResponseParseError(f"Invalid embedded XML in meter profile response: {err}") from err

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
