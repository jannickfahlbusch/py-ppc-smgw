"""Tests for parsing functions — no async, no mocking, no HTTP."""

from datetime import datetime

import pytest
from obis_parser import OBIS

from py_ppc_smgw.errors import ResponseParseError
from py_ppc_smgw.parsing import (
    extract_xml_from_cms,
    parse_export_meter_values,
    parse_firmware_versions,
    parse_meter_reading,
    parse_meters,
)
from py_ppc_smgw.types import FirmwareVersion, Meter, Reading

METERFORM_SINGLE = b"""<html><body>
<select name='mid' id='meterform_select_meter' size=1>
<option value='898e85613b6c6888db9bdb5ef7ec4ec3'>01005e318002.1lgz0067285558.sm</option>
</select>
</body></html>"""

METERFORM_MULTI = b"""<html><body>
<select name='mid' id='meterform_select_meter' size=1>
<option value='aaa111'>01005e318002.meter1.sm</option>
<option value='bbb222'>01005e318002.meter2.sm</option>
</select>
</body></html>"""

METERFORM_EMPTY = b"""<html><body>
<select name='mid' id='meterform_select_meter' size=1>
</select>
</body></html>"""

METERFORM_NO_SELECT = b"""<html><body><p>No meters</p></body></html>"""

READING_SINGLE = b"""<html><body>
<table id="metervalue">
<tr><th>Zeitstempel</th><th>Wert</th><th>OBIS</th></tr>
<tr>
<td id='table_metervalues_col_timestamp'>2026-05-14 12:00:01</td>
<td id='table_metervalues_col_wert'>10.5993</td>
<td id='table_metervalues_col_obis'>1-0:2.8.0</td>
</tr>
</table>
</body></html>"""

READING_MULTI_OBIS = b"""<html><body>
<table id="metervalue">
<tr><th>Zeitstempel</th><th>Wert</th><th>OBIS</th></tr>
<tr>
<td id='table_metervalues_col_timestamp'>2026-05-14 12:00:01</td>
<td id='table_metervalues_col_wert'>10.5993</td>
<td id='table_metervalues_col_obis'>1-0:2.8.0</td>
</tr>
<tr>
<td id='table_metervalues_col_wert'>3344.0514</td>
<td id='table_metervalues_col_obis'>1-0:1.8.0</td>
</tr>
</table>
</body></html>"""

READING_NO_TABLE = b"""<html><body><p>No readings</p></body></html>"""

SWVERSIONS_HTML = b"""<html><body>
<table>
<tr><th>Komponente</th><th>Version</th><th>Prufsumme</th></tr>
<tr><td>smgw-bootstream</td><td>33918</td><td>3044022007f60e61</td></tr>
<tr><td>smgw-services</td><td>34868</td><td>304402201df9b452</td></tr>
</table>
</body></html>"""


class TestParseMeters:
    @pytest.mark.parametrize(
        ("html", "expected"),
        [
            (
                METERFORM_SINGLE,
                [
                    Meter(
                        mid="898e85613b6c6888db9bdb5ef7ec4ec3",
                        name="01005e318002.1lgz0067285558.sm",
                    )
                ],
            ),
            (
                METERFORM_MULTI,
                [
                    Meter(mid="aaa111", name="01005e318002.meter1.sm"),
                    Meter(mid="bbb222", name="01005e318002.meter2.sm"),
                ],
            ),
            (METERFORM_EMPTY, []),
            (METERFORM_NO_SELECT, []),
        ],
    )
    def test_parse_meters(self, html: bytes, expected: list[Meter]) -> None:
        assert parse_meters(html) == expected


class TestParseMeterReading:
    def test_single_obis(self) -> None:
        obis = OBIS(1, 0, 2, 8, 0)
        assert parse_meter_reading(READING_SINGLE) == {
            obis: Reading(
                value="10.5993",
                timestamp=datetime(2026, 5, 14, 12, 0, 1),
                obis=obis,
            ),
        }

    def test_multi_obis_inherits_timestamp(self) -> None:
        obis_2_8 = OBIS(1, 0, 2, 8, 0)
        obis_1_8 = OBIS(1, 0, 1, 8, 0)
        readings = parse_meter_reading(READING_MULTI_OBIS)
        assert readings == {
            obis_2_8: Reading(
                value="10.5993",
                timestamp=datetime(2026, 5, 14, 12, 0, 1),
                obis=obis_2_8,
            ),
            obis_1_8: Reading(
                value="3344.0514",
                timestamp=datetime(2026, 5, 14, 12, 0, 1),
                obis=obis_1_8,
            ),
        }

    def test_no_table_returns_empty(self) -> None:
        assert parse_meter_reading(READING_NO_TABLE) == {}


class TestParseFirmwareVersions:
    def test_parse(self) -> None:
        assert parse_firmware_versions(SWVERSIONS_HTML) == [
            FirmwareVersion(
                component="smgw-bootstream",
                version="33918",
                checksum="3044022007f60e61",
            ),
            FirmwareVersion(component="smgw-services", version="34868", checksum="304402201df9b452"),
        ]


_BIN_TRAILER = b"\x30\x82\x04\xa0\xff\xfe</fake>\x00\x81\xde\xad"
_PG_NS = b'xmlns:pg="urn:k461-dke-de:profile_generic-1"'
_DEFAULT_NS = b'xmlns="urn:k461-dke-de:profile_generic-1"'

MULTI_COLUMN_CMS = (
    b"PKCS7-CMS-BINARY-WRAPPER-PREAMBLE\n"
    b'<?xml version="1.0" encoding="UTF-8"?>\n'
    b'<ns1:object class_id="7" id="x.1lgz.sm"'
    b' xmlns:ns1="urn:k461-dke-de:profile_generic-1"'
    b' xmlns:ns2="urn:k461-dke-de:extension-1">\n'
    b'  <ns1:attributes count="3">\n'
    b'    <ns1:capture_objects id="2" count="3">\n'
    b'      <ns1:capture_object id="1">\n'
    b"        <ns2:logical_name>0100010800ff.1lgz.sm</ns2:logical_name>\n"
    b"      </ns1:capture_object>\n"
    b'      <ns1:capture_object id="2">\n'
    b"        <ns2:logical_name>0100020800ff.1lgz.sm</ns2:logical_name>\n"
    b"      </ns1:capture_object>\n"
    b'      <ns1:capture_object id="3">\n'
    b"        <ns2:logical_name>0100200700ff.1lgz.sm</ns2:logical_name>\n"
    b"      </ns1:capture_object>\n"
    b"    </ns1:capture_objects>\n"
    b'    <ns1:buffer id="3">\n'
    b'      <ns1:simple_data count="3">\n'
    b'        <ns1:column count="2" id="1">\n'
    b'          <ns1:entry_gateway_signed id="1">\n'
    b"            <ns2:value><ns2:long64>10000000</ns2:long64></ns2:value>\n"
    b"            <ns2:scaler>-1</ns2:scaler>\n"
    b"            <ns2:unit>30</ns2:unit>\n"
    b"            <ns2:status><ns2:unsigned>0</ns2:unsigned></ns2:status>\n"
    b"            <ns2:capture_time>2026-05-14T22:00:01Z</ns2:capture_time>\n"
    b"            <ns2:smgw_signature>SIG_1_1</ns2:smgw_signature>\n"
    b"          </ns1:entry_gateway_signed>\n"
    b'          <ns1:entry_gateway_signed id="2">\n'
    b"            <ns2:value><ns2:long64>10025000</ns2:long64></ns2:value>\n"
    b"            <ns2:scaler>-1</ns2:scaler>\n"
    b"            <ns2:unit>30</ns2:unit>\n"
    b"            <ns2:status><ns2:unsigned>4</ns2:unsigned></ns2:status>\n"
    b"            <ns2:capture_time>2026-05-15T03:00:01Z</ns2:capture_time>\n"
    b"          </ns1:entry_gateway_signed>\n"
    b"        </ns1:column>\n"
    b'        <ns1:column count="1" id="2">\n'
    b'          <ns1:entry_gateway_signed id="1">\n'
    b"            <ns2:value><ns2:long64>5000000</ns2:long64></ns2:value>\n"
    b"            <ns2:scaler>-1</ns2:scaler>\n"
    b"            <ns2:unit>30</ns2:unit>\n"
    b"            <ns2:status><ns2:unsigned>3</ns2:unsigned></ns2:status>\n"
    b"            <ns2:capture_time>2026-05-14T22:00:01Z</ns2:capture_time>\n"
    b"          </ns1:entry_gateway_signed>\n"
    b"        </ns1:column>\n"
    b'        <ns1:column count="1" id="3">\n'
    b'          <ns1:entry_gateway_signed id="1">\n'
    b"            <ns2:value><ns2:long64>2300</ns2:long64></ns2:value>\n"
    b"            <ns2:scaler>-1</ns2:scaler>\n"
    b"            <ns2:unit>35</ns2:unit>\n"
    b"            <ns2:status><ns2:unsigned>0</ns2:unsigned></ns2:status>\n"
    b"            <ns2:capture_time>2026-05-14T22:00:01Z</ns2:capture_time>\n"
    b"          </ns1:entry_gateway_signed>\n"
    b"        </ns1:column>\n"
    b"      </ns1:simple_data>\n"
    b"    </ns1:buffer>\n"
    b"  </ns1:attributes>\n"
    b"</ns1:object>\n" + _BIN_TRAILER
)


class TestExtractXmlFromCms:
    def test_alternative_prefix_and_trailer_stripped(self) -> None:
        doc = b'<?xml version="1.0"?>\n<pg:object ' + _PG_NS + b"><a><b/></a></pg:object>"
        xml = extract_xml_from_cms(doc + _BIN_TRAILER)
        assert xml == doc

    def test_default_namespace(self) -> None:
        doc = b'<?xml version="1.0"?>\n<object ' + _DEFAULT_NS + b"><a><b/></a></object>"
        assert extract_xml_from_cms(doc + _BIN_TRAILER) == doc

    def test_whitespace_in_close_tag(self) -> None:
        doc = b'<?xml version="1.0"?>\n<pg:object ' + _PG_NS + b"><a><b/></a></pg:object   >"
        assert extract_xml_from_cms(doc + _BIN_TRAILER) == doc

    def test_missing_xml_marker_raises(self) -> None:
        with pytest.raises(ResponseParseError):
            extract_xml_from_cms(b"plain non-xml bytes")

    @pytest.mark.parametrize(
        "root",
        [b"<pg:object " + _PG_NS + b"/>", b"<pg:object " + _PG_NS + b"></pg:object>"],
    )
    def test_childless_root_rejected(self, root: bytes) -> None:
        doc = b'<?xml version="1.0"?>\n' + root
        with pytest.raises(ResponseParseError, match="no child elements"):
            extract_xml_from_cms(doc + _BIN_TRAILER)

    def test_malformed_xml_raises(self) -> None:
        broken = b'<?xml version="1.0"?>\n<pg:object ' + _PG_NS + b"><a></b></pg:object>"
        with pytest.raises(ResponseParseError, match="not well-formed"):
            extract_xml_from_cms(broken)


class TestParseExportMeterValues:
    def test_multi_column_mapping_and_ordering(self) -> None:
        entries = parse_export_meter_values(MULTI_COLUMN_CMS)
        assert len(entries) == 4

        obis_1_8 = OBIS(1, 0, 1, 8, 0, 255)
        obis_2_8 = OBIS(1, 0, 2, 8, 0, 255)
        obis_32_7 = OBIS(1, 0, 32, 7, 0, 255)

        by_key = {(e.obis, e.capture_time): e for e in entries}

        e1 = by_key[(obis_1_8, datetime.fromisoformat("2026-05-14T22:00:01+00:00"))]
        assert e1.value == 10000000.0
        assert e1.value_kwh == 1000.0
        assert e1.status == 0
        assert e1.signature == "SIG_1_1"

        e2 = by_key[(obis_2_8, datetime.fromisoformat("2026-05-14T22:00:01+00:00"))]
        assert e2.value == 5000000.0
        assert e2.value_kwh == 500.0
        assert e2.status == 3

        e3 = by_key[(obis_1_8, datetime.fromisoformat("2026-05-15T03:00:01+00:00"))]
        assert e3.status == 4

        e4 = by_key[(obis_32_7, datetime.fromisoformat("2026-05-14T22:00:01+00:00"))]
        assert e4.value == 2300.0
        assert e4.unit == 35
        # unit 35 (Volt) is not scaled to kWh by value_kwh
        assert e4.value_kwh == 230.0

        # Chronological ordering check
        timestamps = [e.capture_time for e in entries]
        assert timestamps == sorted(timestamps)

    def test_unsupported_root_raises(self) -> None:
        foreign = (
            b'<?xml version="1.0"?>\n<khw:container xmlns:khw="urn:example"><khw:x><khw:y/></khw:x></khw:container>'
        )
        with pytest.raises(ResponseParseError, match="Unsupported embedded XML root"):
            parse_export_meter_values(foreign)

    def test_missing_simple_data_raises(self) -> None:
        xml = (
            b'<?xml version="1.0"?>\n<ns1:object xmlns:ns1="urn:k461-dke-de:profile_generic-1"'
            b' xmlns:ns2="urn:k461-dke-de:extension-1">\n'
            b"  <ns1:attributes>\n"
            b"    <ns1:capture_objects id='1'>\n"
            b"      <ns1:capture_object id='1'>\n"
            b"        <ns2:logical_name>0100010800ff.sm</ns2:logical_name>\n"
            b"      </ns1:capture_object>\n"
            b"    </ns1:capture_objects>\n"
            b"  </ns1:attributes>\n"
            b"</ns1:object>"
        )
        with pytest.raises(ResponseParseError, match="simple_data element not found"):
            parse_export_meter_values(xml)
