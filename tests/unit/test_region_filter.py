"""任务区域解析与商品所在地匹配的单元测试。"""

from src.scraper import _extract_choose_position
from src.services.region_filter import (
    RegionPath,
    is_same_city,
    matches_any,
    normalize_city,
    parse_region,
)


def _item(choose_position, area="姑苏区"):
    return {
        "data": {
            "item": {
                "main": {
                    "exContent": {"area": area},
                    "clickParam": {"args": {"choosePosition": choose_position}},
                }
            }
        }
    }


class TestExtractChoosePosition:
    def test_reads_first_non_empty_value(self):
        payload = {"data": {"resultList": [_item(None), _item("苏州")]}}
        assert _extract_choose_position(payload) == "苏州"

    def test_unfiltered_response_has_no_position(self):
        payload = {"data": {"resultList": [_item(None), _item("")]}}
        assert _extract_choose_position(payload) == ""

    def test_empty_result_list(self):
        assert _extract_choose_position({"data": {"resultList": []}}) == ""

    def test_missing_fields_are_tolerated(self):
        assert _extract_choose_position({}) == ""
        assert _extract_choose_position({"data": {"resultList": [{}]}}) == ""


class TestParseRegion:
    def test_full_path(self):
        path = parse_region("江苏/苏州/全苏州")
        assert path == RegionPath(province="江苏", city="苏州", district="全苏州")

    def test_missing_parts_padded(self):
        assert parse_region("江苏") == RegionPath(province="江苏", city="", district="")
        assert parse_region("") == RegionPath()
        assert parse_region(None) == RegionPath()

    def test_extra_parts_ignored(self):
        assert parse_region("江苏/苏州/姑苏区/多余") == RegionPath(
            province="江苏", city="苏州", district="姑苏区"
        )

    def test_whitespace_trimmed(self):
        assert parse_region(" 江苏 / 苏州 ").city == "苏州"


class TestExpectedPositions:
    """服务端筛选地的候选集合（粒度到地级市）。"""

    def test_city_level_region(self):
        assert parse_region("江苏/苏州/全苏州").expected_positions == ("苏州",)
        assert parse_region("江苏/苏州").expected_positions == ("苏州",)

    def test_county_level_city_is_also_a_candidate(self):
        # 「江苏/镇江/丹阳」：服务端只回传地级市「镇江」，两个候选都要算命中
        positions = parse_region("江苏/镇江/丹阳").expected_positions
        assert positions == ("镇江", "丹阳")
        assert matches_any(positions, "镇江") is True
        assert matches_any(positions, "丹阳") is True
        assert matches_any(positions, "南京") is False

    def test_whole_province_option_falls_back_to_province(self):
        # 「全江苏」代表整个省，服务端回传地级市，无法精确比对时回落省级
        assert parse_region("江苏/全江苏").expected_positions == ("江苏",)

    def test_municipality_whole_option_is_a_city(self):
        assert parse_region("上海/全上海").expected_positions == ("上海",)
        assert parse_region("重庆/全重庆").expected_positions == ("重庆",)

    def test_province_only_region(self):
        assert parse_region("江苏").expected_positions == ("江苏",)

    def test_empty_region(self):
        assert parse_region("").expected_positions == ()


class TestExpectedCities:
    """商品所在地（publishCity）的候选集合。"""

    def test_city_level_region(self):
        assert parse_region("江苏/苏州/全苏州").expected_cities == ("苏州",)

    def test_county_level_city_is_also_a_candidate(self):
        assert parse_region("江苏/镇江/丹阳").expected_cities == ("镇江", "丹阳")

    def test_province_only_region_skips_city_check(self):
        assert parse_region("江苏/全江苏").expected_cities == ()
        assert parse_region("江苏").expected_cities == ()
        assert parse_region("").expected_cities == ()

    def test_municipality_whole_option_is_a_city(self):
        assert parse_region("上海/全上海").expected_cities == ("上海",)


class TestCityMatch:
    def test_same_city(self):
        assert is_same_city("苏州", "苏州") is True

    def test_city_suffix_ignored(self):
        assert is_same_city("苏州", "苏州市") is True
        assert is_same_city("苏州市", "苏州") is True

    def test_different_city(self):
        assert is_same_city("苏州", "南京") is False

    def test_empty_side_never_matches(self):
        assert is_same_city("", "苏州") is False
        assert is_same_city("苏州", "") is False
        assert is_same_city(None, None) is False

    def test_normalize_city_keeps_short_names(self):
        assert normalize_city("苏州") == "苏州"
        assert normalize_city(" 苏州 ") == "苏州"
        assert normalize_city("") == ""


class TestMatchesAny:
    def test_hits_any_candidate(self):
        assert matches_any(("镇江", "丹阳"), "丹阳市") is True

    def test_empty_candidates_never_match(self):
        assert matches_any((), "苏州") is False

    def test_empty_actual_never_matches(self):
        assert matches_any(("苏州",), "") is False
        assert matches_any(("苏州",), None) is False
