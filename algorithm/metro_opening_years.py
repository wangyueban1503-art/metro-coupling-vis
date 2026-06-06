"""Metro line opening years for all cities.

Each city has a dict mapping normalized line names -> opening year.
The line names must match how they appear in the raw CSV rname column
(after the regex extraction in preprocess_raw.py).

Usage:
    from metro_opening_years import get_opening_year, HANGZHOU_OPENING_YEARS
    year = get_opening_year(line_name, city_code)
"""

from __future__ import annotations

# ── City code constants ────────────────────────────────────────────────────────
BEIJING_CODE = "110000"
SHANGHAI_CODE = "310000"
GUANGZHOU_CODE = "440100"
CHENGDU_CODE = "510100"
HANGZHOU_CODE = "330100"
SHENZHEN_CODE = "440300"

# ──杭州 (Hangzhou) ────────────────────────────────────────────────────────────
# Line names match "地铁N号线" pattern from rname column
HANGZHOU_OPENING_YEARS: dict[str, int] = {
    "杭州地铁1号线": 2012,
    "杭州地铁2号线": 2014,
    "杭州地铁4号线": 2015,
    "杭州地铁5号线": 2019,
    "杭州地铁6号线": 2021,
    "杭州地铁7号线": 2021,
    "杭州地铁8号线": 2021,
    "杭州地铁9号线": 2022,
    "杭州地铁10号线": 2022,
    "杭州地铁16号线": 2020,     # 16号线 (临安线) - 临安段
    "杭州地铁19号线": 2023,
    "杭州地铁3号线": 2022,
    # Variants (phase extensions stored as separate rows)
    "杭州地铁1号线二期": 2016,   # 机场延伸段
    "杭州地铁4号线三期南延段": 2022,
    "杭州地铁4号线三期西延段": 2022,
    "杭州地铁5号线二期": 2019,
    "杭州地铁3号线二期": 2022,
    "杭州地铁9号线二期": 2022,
    "杭州地铁10号线二期": 2022,
    "杭州地铁12号线北段": 2024,
    "杭州地铁12号线南段": 2024,
    "杭州地铁15号线": 2024,
    "杭州地铁18号线": 2024,
    "杭州地铁19号线接驳线": 2023,
    # Intercity rails
    "杭州杭海城际铁路西延": 2021,
    "杭州杭德城际铁路": 2022,
}

# ── 上海 (Shanghai) ───────────────────────────────────────────────────────────
SHANGHAI_OPENING_YEARS: dict[str, int] = {
    "上海地铁1号线": 1993,
    "上海地铁2号线": 1999,
    "上海地铁3号线": 2000,
    "上海地铁4号线": 2005,
    "上海地铁5号线": 2003,
    "上海地铁6号线": 2007,
    "上海地铁7号线": 2009,
    "上海地铁8号线": 2007,
    "上海地铁9号线": 2007,
    "上海地铁10号线": 2010,
    "上海地铁11号线": 2009,
    "上海地铁12号线": 2013,
    "上海地铁13号线": 2012,
    "上海地铁14号线": 2021,
    "上海地铁15号线": 2021,
    "上海地铁16号线": 2014,
    "上海地铁17号线": 2017,
    "上海地铁18号线": 2020,
}

# ── 北京 (Beijing) ──────────────────────────────────────────────────────────────
BEIJING_OPENING_YEARS: dict[str, int] = {
    "北京地铁1号线": 1969,
    "北京地铁2号线": 1984,
    "北京地铁4号线": 2009,
    "北京地铁5号线": 2007,
    "北京地铁6号线": 2012,
    "北京地铁7号线": 2014,
    "北京地铁8号线": 2008,
    "北京地铁9号线": 2011,
    "北京地铁10号线": 2008,
    "北京地铁11号线": 2021,
    "北京地铁13号线": 2002,
    "北京地铁14号线": 2013,
    "北京地铁15号线": 2011,
    "北京地铁16号线": 2016,
    "北京地铁17号线": 2021,
    "北京地铁19号线": 2022,
    "北京地铁昌平线": 2010,
    "北京地铁房山线": 2010,
    "北京地铁燕房线": 2017,
    "北京地铁机场线": 2008,
    "北京地铁大兴线": 2010,
    "北京地铁亦庄线": 2010,
}

# ── 广州 (Guangzhou) ──────────────────────────────────────────────────────────
GUANGZHOU_OPENING_YEARS: dict[str, int] = {
    "广州地铁1号线": 1997,
    "广州地铁2号线": 2002,
    "广州地铁3号线": 2005,
    "广州地铁4号线": 2005,
    "广州地铁5号线": 2009,
    "广州地铁6号线": 2013,
    "广州地铁7号线": 2016,
    "广州地铁8号线": 2010,
    "广州地铁9号线": 2017,
    "广州地铁13号线": 2017,
    "广州地铁14号线": 2018,
    "广州地铁18号线": 2021,
    "广州地铁21号线": 2018,
    "广州地铁广佛线": 2010,
    "广州地铁APM线": 2010,
}

# ── 成都 (Chengdu) ───────────────────────────────────────────────────────────
CHENGDU_OPENING_YEARS: dict[str, int] = {
    "成都地铁1号线": 2010,
    "成都地铁2号线": 2012,
    "成都地铁3号线": 2016,
    "成都地铁4号线": 2016,
    "成都地铁5号线": 2019,
    "成都地铁6号线": 2020,
    "成都地铁7号线": 2017,
    "成都地铁8号线": 2020,
    "成都地铁9号线": 2020,
    "成都地铁10号线": 2017,
    "成都地铁17号线": 2020,
    "成都地铁18号线": 2020,
    "成都地铁19号线": 2023,
    "成都地铁蓉2号线": 2018,
}

# ── 深圳 (Shenzhen) ───────────────────────────────────────────────────────────
SHENZHEN_OPENING_YEARS: dict[str, int] = {
    "深圳地铁1号线": 2004,
    "深圳地铁2号线": 2010,
    "深圳地铁3号线": 2011,
    "深圳地铁4号线": 2004,
    "深圳地铁5号线": 2011,
    "深圳地铁6号线": 2020,
    "深圳地铁7号线": 2016,
    "深圳地铁8号线": 2020,
    "深圳地铁9号线": 2016,
    "深圳地铁10号线": 2020,
    "深圳地铁11号线": 2016,
    "深圳地铁12号线": 2022,
    "深圳地铁14号线": 2022,
    "深圳地铁16号线": 2022,
    "深圳地铁20号线": 2022,
}

# ── Lookup table ──────────────────────────────────────────────────────────────
CITY_OPENING_YEARS: dict[str, dict[str, int]] = {
    HANGZHOU_CODE: HANGZHOU_OPENING_YEARS,
    SHANGHAI_CODE: SHANGHAI_OPENING_YEARS,
    BEIJING_CODE: BEIJING_OPENING_YEARS,
    GUANGZHOU_CODE: GUANGZHOU_OPENING_YEARS,
    CHENGDU_CODE: CHENGDU_OPENING_YEARS,
    SHENZHEN_CODE: SHENZHEN_OPENING_YEARS,
}


def get_opening_year(line_name: str, city_code: str) -> int:
    """Return opening year for a metro line, or 0 if unknown.
    Handles both "杭州地铁1号线" and "杭州市地铁1号线" formats.
    Also handles phase extensions by matching prefix.
    """
    city_map = CITY_OPENING_YEARS.get(city_code, {})
    # Try direct match first
    if line_name in city_map:
        return city_map[line_name]
    # Strip "市" suffix for city name variant (e.g. "杭州市" -> "杭州")
    stripped = line_name.replace("市", "", 1) if line_name.startswith("市") else line_name
    if stripped in city_map:
        return city_map[stripped]
    # Try prefix match for phase extensions (e.g. "杭州地铁12号线" matches "杭州地铁12号线北段")
    for key, year in city_map.items():
        if stripped.startswith(key) or key.startswith(stripped):
            return year
    return 0


def get_station_opening_year(station_name: str, line_name: str, city_code: str) -> int:
    """Return opening year for a station.
    Stations generally open with their line, so we use line year as default.
    """
    return get_opening_year(line_name, city_code)