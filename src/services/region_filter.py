"""任务区域（省/市/区）解析，以及商品所在地与任务区域的匹配判断。

闲鱼「区域」筛选的选项层级为 省/市/区，其中「全X」表示整个 X 区域。
商品自身可用的位置字段来自详情接口 sellerDO.publishCity（精确到城市）。

注意粒度差异：服务端回传的筛选地（choosePosition）只到地级市，而任务区域可能选到
县级市/区（如「江苏/镇江/丹阳」会回传「镇江」）。因此校验一律使用候选集合而不是单值，
避免把「丹阳」这类下级区域误判为筛选未生效。
"""

from dataclasses import dataclass
from typing import Optional, Sequence, Tuple

_FULL_PREFIX = "全"
_MUNICIPALITIES = {"北京", "上海", "天津", "重庆"}
_CITY_SUFFIX = "市"

# 省级任务（如「江苏/全江苏」）无法定位到城市，不做城市级校验
_NO_CITY_CANDIDATES: Tuple[str, ...] = ()


@dataclass(frozen=True)
class RegionPath:
    province: str = ""
    city: str = ""
    district: str = ""

    def _specific(self, value: str) -> str:
        """把「全X」这类整体选项归一化。

        「全苏州」表示整个苏州，本身不构成更细的约束，返回空；
        「全上海」这类直辖市本身就是城市，直接返回「上海」。
        """
        text = value.strip()
        if not text:
            return ""
        if not text.startswith(_FULL_PREFIX) or len(text) == 1:
            return text
        whole = text[1:]
        return whole if whole in _MUNICIPALITIES else ""

    @property
    def specific_city(self) -> str:
        return self._specific(self.city)

    @property
    def specific_district(self) -> str:
        return self._specific(self.district)

    @property
    def expected_positions(self) -> Tuple[str, ...]:
        """服务端筛选地（choosePosition，粒度到地级市）的候选集合。"""
        candidates = [
            value
            for value in (self.specific_city, self.specific_district)
            if value
        ]
        if not candidates and self.province.strip():
            # 省级任务只能校验到省
            candidates.append(self.province.strip())
        return tuple(candidates)

    @property
    def expected_cities(self) -> Tuple[str, ...]:
        """商品所在地（publishCity，粒度到城市）的候选集合；为空表示不校验。"""
        if not self.specific_city and not self.specific_district:
            return _NO_CITY_CANDIDATES
        return tuple(
            value
            for value in (self.specific_city, self.specific_district)
            if value
        )


def parse_region(value: Optional[str]) -> RegionPath:
    """把 '江苏/苏州/全苏州' 这类区域字符串解析为省/市/区三段。"""
    parts = [part.strip() for part in str(value or "").split("/")]
    parts = (parts + ["", "", ""])[:3]
    return RegionPath(province=parts[0], city=parts[1], district=parts[2])


def normalize_city(name: Optional[str]) -> str:
    text = str(name or "").strip()
    if len(text) > len(_CITY_SUFFIX) and text.endswith(_CITY_SUFFIX):
        return text[: -len(_CITY_SUFFIX)]
    return text


def is_same_city(expected: Optional[str], actual: Optional[str]) -> bool:
    """比较任务要求的城市与商品所在地城市，任一侧为空时返回 False。"""
    left = normalize_city(expected)
    right = normalize_city(actual)
    return bool(left) and bool(right) and left == right


def matches_any(candidates: Sequence[str], actual: Optional[str]) -> bool:
    """实际地点命中候选集合中的任意一个即视为匹配。"""
    return any(is_same_city(candidate, actual) for candidate in candidates)
