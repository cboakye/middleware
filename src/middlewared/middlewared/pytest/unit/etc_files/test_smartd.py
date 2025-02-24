import subprocess
import textwrap
from unittest.mock import call, Mock, patch

import pytest

from middlewared.etc_files.smartd import (
    ensure_smart_enabled, annotate_disk_for_smart, get_smartd_schedule, get_smartd_schedule_piece, get_smartd_config
)


@pytest.mark.asyncio
async def test__ensure_smart_enabled__smart_error():
    with patch("middlewared.etc_files.smartd.smartctl") as run:
        run.return_value = Mock(stdout="S.M.A.R.T. Error")

        assert await ensure_smart_enabled(["/dev/ada0"]) is False

        run.assert_called_once()


@pytest.mark.asyncio
async def test__ensure_smart_enabled__smart_enabled():
    with patch("middlewared.etc_files.smartd.smartctl") as run:
        run.return_value = Mock(stdout="SMART   Enabled")

        assert await ensure_smart_enabled(["/dev/ada0"])

        run.assert_called_once()


@pytest.mark.asyncio
async def test__ensure_smart_enabled__smart_was_disabled():
    with patch("middlewared.etc_files.smartd.smartctl") as run:
        run.return_value = Mock(stdout="SMART   Disabled", returncode=0)

        assert await ensure_smart_enabled(["/dev/ada0"])

        assert run.call_args_list == [
            call(["/dev/ada0", "-i"], check=False, stderr=subprocess.STDOUT,
                 encoding="utf8", errors="ignore"),
            call(["/dev/ada0", "-s", "on"], check=False, stderr=subprocess.STDOUT),
        ]


@pytest.mark.asyncio
async def test__ensure_smart_enabled__enabling_smart_failed():
    with patch("middlewared.etc_files.smartd.smartctl") as run:
        run.return_value = Mock(stdout="SMART   Disabled", returncode=1)

        assert await ensure_smart_enabled(["/dev/ada0"]) is False


@pytest.mark.asyncio
async def test__ensure_smart_enabled__handled_args_properly():
    with patch("middlewared.etc_files.smartd.smartctl") as run:
        run.return_value = Mock(stdout="SMART   Enabled")

        assert await ensure_smart_enabled(["/dev/ada0", "-d", "sat"])

        run.assert_called_once_with(
            ["/dev/ada0", "-d", "sat", "-i"], check=False, stderr=subprocess.STDOUT,
            encoding="utf8", errors="ignore",
        )


def test__get_smartd_schedule__need_mapping():
    assert get_smartd_schedule({
        "smarttest_month": "jan,feb,mar,apr,may,jun,jul,aug,sep,oct,nov,dec",
        "smarttest_daymonth": "1,hedgehog day,3",
        "smarttest_dayweek": "tue,SUN",
        "smarttest_hour": "*/1",
    }) == "../(01|03)/(2|7)/.."


def test__get_smartd_schedule_piece__every_day_of_week():
    assert get_smartd_schedule_piece("1,2,3,4,5,6,7", 1, 7) == "."


def test__get_smartd_schedule_piece__every_day_of_week_wildcard():
    assert get_smartd_schedule_piece("*", 1, 7) == "."


def test__get_smartd_schedule_piece__specific_day_of_week():
    assert get_smartd_schedule_piece("1,2,3", 1, 7) == "(1|2|3)"


def test__get_smartd_schedule_piece__every_month():
    assert get_smartd_schedule_piece("1,2,3,4,5,6,7,8,9,10,11,12", 1, 12) == ".."


def test__get_smartd_schedule_piece__each_month_wildcard():
    assert get_smartd_schedule_piece("*", 1, 12) == ".."


def test__get_smartd_schedule_piece__each_month():
    assert get_smartd_schedule_piece("*/1", 1, 12) == ".."


def test__get_smartd_schedule_piece__every_fifth_month():
    assert get_smartd_schedule_piece("*/5", 1, 12) == "(05|10)"


def test__get_smartd_schedule_piece__every_specific_month():
    assert get_smartd_schedule_piece("1,5,11", 1, 12) == "(01|05|11)"


def test__get_smartd_schedule_piece__at_midnight():
    assert get_smartd_schedule_piece("0", 1, 23) == "(00)"


def test__get_smartd_schedule_piece__range_with_divisor():
    assert get_smartd_schedule_piece("3-30/10", 1, 31) == "(10|20|30)"


def test__get_smartd_schedule_piece__range_without_divisor():
    assert get_smartd_schedule_piece("10-15", 1, 31) == "(10|11|12|13|14|15)"


def test__get_smartd_schedule_piece__malformed_range_without_divisor():
    assert get_smartd_schedule_piece("10-1", 1, 31) == "(10)"


def test__get_smartd_config():
    assert get_smartd_config({
        "smartctl_args": ["/dev/ada0", "-d", "sat"],
        "smart_powermode": "never",
        "smart_difference": 0,
        "smart_informational": 1,
        "smart_critical": 2,
        "smarttest_type": "S",
        "smarttest_month": "*/1",
        "smarttest_daymonth": "*/1",
        "smarttest_dayweek": "*/1",
        "smarttest_hour": "*/1",
        "disk_critical": None,
        "disk_difference": None,
        "disk_informational": None,
    }) == textwrap.dedent("""\
        /dev/ada0 -d sat -n never -W 0,1,2 -m root -M exec /usr/local/libexec/smart_alert.py\\
        -s S/../.././..\\
        """)


def test__get_smartd_config_without_schedule():
    assert get_smartd_config({
        "smartctl_args": ["/dev/ada0", "-d", "sat"],
        "smart_powermode": "never",
        "smart_difference": 0,
        "smart_informational": 1,
        "smart_critical": 2,
        "disk_critical": None,
        "disk_difference": None,
        "disk_informational": None,
    }) == textwrap.dedent("""\
        /dev/ada0 -d sat -n never -W 0,1,2 -m root -M exec /usr/local/libexec/smart_alert.py""")


def test__get_smartd_config_with_temp():
    assert get_smartd_config({
        "smartctl_args": ["/dev/ada0", "-d", "sat"],
        "smart_powermode": "never",
        "smart_difference": 0,
        "smart_informational": 1,
        "smart_critical": 2,
        "disk_critical": 50,
        "disk_difference": 10,
        "disk_informational": 40,
    }) == textwrap.dedent("""\
        /dev/ada0 -d sat -n never -W 10,40,50 -m root -M exec /usr/local/libexec/smart_alert.py""")
