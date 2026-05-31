"""Tests for parsing functions — no async, no mocking, no HTTP."""

from datetime import datetime

import pytest

from py_ppc_smgw.parsing import (
    logical_name_to_obis,
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
        assert parse_meter_reading(READING_SINGLE) == {
            "1-0:2.8.0": Reading(
                value="10.5993",
                timestamp=datetime(2026, 5, 14, 12, 0, 1),
                obis="1-0:2.8.0",
            ),
        }

    def test_multi_obis_inherits_timestamp(self) -> None:
        readings = parse_meter_reading(READING_MULTI_OBIS)
        assert readings == {
            "1-0:2.8.0": Reading(
                value="10.5993",
                timestamp=datetime(2026, 5, 14, 12, 0, 1),
                obis="1-0:2.8.0",
            ),
            "1-0:1.8.0": Reading(
                value="3344.0514",
                timestamp=datetime(2026, 5, 14, 12, 0, 1),
                obis="1-0:1.8.0",
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


class TestLogicalNameToObis:
    @pytest.mark.parametrize(
        ("logical_name", "expected"),
        [
            ("0100010800ff.1lgz0067285558.sm", "1-0:1.8.0"),
            ("0100020800ff.1lgz0067285558.sm", "1-0:2.8.0"),
            ("0100100700ff.meter.sm", "1-0:16.7.0"),
            ("short", "short"),
        ],
    )
    def test_conversion(self, logical_name: str, expected: str) -> None:
        assert logical_name_to_obis(logical_name) == expected
