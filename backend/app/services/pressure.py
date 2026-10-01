"""压力监测业务规则：筛选口径、状态流转、统计去重与历史快照都收在这里。

两条不可破坏的历史规则：
1. 历史压力监测记录按记录产生当时的判定口径留存，后续口径升级或状态流转都不改写它；
2. 监测点位归属片区变更只影响点位当前归属与之后的新记录，历史记录保留登记时的归属快照。
"""
from __future__ import annotations

from datetime import date
from typing import Any

from app.store import store

MODULE = "pressure"
REQUIRED_FIELDS = ["监测编号", "监测点位", "监测时段"]
STATUS_ORDER = ["待采集", "采集正常", "压力越限", "已停测"]
ACTION_RULES = {"启动采集": "采集正常", "标记越限": "压力越限", "停止监测": "已停测"}
NEGATIVE_ACTIONS = ["标记越限"]

# 新登记记录采用当前口径；历史记录保留各自登记时的口径，不做升级。
CURRENT_JUDGMENT_RULE = "压力判定口径（2026版）"
DEFAULT_OWNER = "未划分片区"

# 列表字段里用于对外展示的状态列，流转时需要与内部 status 保持一致。
DISPLAY_STATUS_FIELD = "监测状态"
POINT_FIELD = "监测点位"
PERIOD_FIELD = "监测时段"
ALARM_COUNT_FIELD = "越限次数"


class PressureService:
    def __init__(self) -> None:
        # 点位当前归属表：按种子数据里每个点位最新一条记录的归属初始化，
        # 之后归属变更只更新这里，不回写任何历史记录。
        self._point_owners: dict[str, str] = {}
        for row in sorted(store.rows(MODULE), key=lambda item: int(item.get("id", 0))):
            point = str(row.get(POINT_FIELD) or "").strip()
            owner = str(row.get("归属片区") or "").strip()
            if point and owner:
                self._point_owners[point] = owner

    # ------------------------------------------------------------------ 筛选
    def _apply_filters(
        self,
        rows: list[dict[str, Any]],
        *,
        keyword: str | None = None,
        point: str | None = None,
        period: str | None = None,
        period_start: str | None = None,
        period_end: str | None = None,
        status: str | None = None,
    ) -> list[dict[str, Any]]:
        """列表、详情同口径记录、导出、统计共用这一份筛选，保证各处条数一致。"""
        if keyword:
            keyword = keyword.strip()
            rows = [row for row in rows if keyword in str(row.get("监测编号", ""))]
        if point:
            point = point.strip()
            rows = [row for row in rows if point in str(row.get(POINT_FIELD, ""))]
        if period:
            period = period.strip()
            rows = [row for row in rows if period in str(row.get(PERIOD_FIELD, ""))]
        if period_start:
            period_start = period_start.strip()
            rows = [row for row in rows if str(row.get(PERIOD_FIELD, "")) >= period_start]
        if period_end:
            period_end = period_end.strip()
            rows = [row for row in rows if str(row.get(PERIOD_FIELD, "")) <= period_end]
        if status:
            rows = [row for row in rows if row.get("status") == status]
        return rows

    def list_entries(
        self,
        *,
        keyword: str | None = None,
        point: str | None = None,
        period: str | None = None,
        period_start: str | None = None,
        period_end: str | None = None,
        status: str | None = None,
        page: int = 1,
        size: int = 20,
    ) -> tuple[list[dict[str, Any]], int]:
        rows = self._apply_filters(
            store.rows(MODULE),
            keyword=keyword,
            point=point,
            period=period,
            period_start=period_start,
            period_end=period_end,
            status=status,
        )
        total = len(rows)
        start = max(page - 1, 0) * size
        return rows[start:start + size], total

    def point_history(self, point: str) -> list[dict[str, Any]]:
        """该点位全部历史记录，归属变更后仍能看到留在原片区的老记录。"""
        point = point.strip()
        return [row for row in store.rows(MODULE) if point in str(row.get(POINT_FIELD, ""))]

    # ------------------------------------------------------------------ 统计
    def stats(
        self,
        *,
        keyword: str | None = None,
        point: str | None = None,
        period: str | None = None,
        period_start: str | None = None,
        period_end: str | None = None,
        status: str | None = None,
    ) -> dict[str, int]:
        """统计口径：监测点位去重计数，同一批点位只算一次。"""
        rows = self._apply_filters(
            store.rows(MODULE),
            keyword=keyword,
            point=point,
            period=period,
            period_start=period_start,
            period_end=period_end,
            status=status,
        )
        active_points = {
            str(row.get(POINT_FIELD, ""))
            for row in rows
            if row.get("status") != "已停测"
        }
        # 越限点位按每个点位最新一条记录的状态判定，去重后计数。
        latest_by_point: dict[str, dict[str, Any]] = {}
        for row in sorted(rows, key=lambda item: int(item.get("id", 0))):
            latest_by_point[str(row.get(POINT_FIELD, ""))] = row
        abnormal_points = {
            point_name
            for point_name, row in latest_by_point.items()
            if row.get("status") == "压力越限"
        }
        today = date.today().isoformat()
        today_alarms = sum(
            self._to_int(row.get(ALARM_COUNT_FIELD))
            for row in rows
            if str(row.get(PERIOD_FIELD, "")) == today
        )
        return {
            "active_points": len(active_points),
            "abnormal_points": len(abnormal_points),
            "today_alarms": today_alarms,
            "total": len(rows),
        }

    @staticmethod
    def _to_int(value: Any) -> int:
        try:
            return int(value)
        except (TypeError, ValueError):
            return 0

    # ------------------------------------------------------------------ 单条
    def get_entry(self, entry_id: int) -> dict[str, Any] | None:
        return store.find(MODULE, entry_id)

    def create_entry(self, values: dict[str, Any]) -> tuple[dict[str, Any] | None, list[str]]:
        missing = [field for field in REQUIRED_FIELDS if not str(values.get(field) or "").strip()]
        if missing:
            return None, missing
        rows = store.rows(MODULE)
        point = str(values.get(POINT_FIELD) or "").strip()
        entry = {"id": max((int(row.get("id", 0)) for row in rows), default=0) + 1}
        entry.update({field: values.get(field) for field in REQUIRED_FIELDS})
        for field in ["平均压力", "峰值压力", "越限次数", "采集人员"]:
            if str(values.get(field) or "").strip():
                entry[field] = values.get(field)
        entry["status"] = STATUS_ORDER[0]
        entry[DISPLAY_STATUS_FIELD] = STATUS_ORDER[0]
        entry["pending"] = True
        entry["abnormal"] = False
        # 登记时固化判定口径与归属快照，之后改点位归属不影响这条记录。
        entry["判定口径"] = CURRENT_JUDGMENT_RULE
        entry["归属片区"] = self._point_owners.get(point, DEFAULT_OWNER)
        rows.append(entry)
        return entry, []

    def run_action(self, entry_id: int, action: str) -> tuple[dict[str, Any] | None, str]:
        entry = store.find(MODULE, entry_id)
        if entry is None:
            return None, f"压力记录 {entry_id} 不存在或已归档"
        if action not in ACTION_RULES:
            return None, f"动作「{action}」不属于压力监测可执行范围"
        target = ACTION_RULES[action]
        if target not in STATUS_ORDER:
            return None, f"目标状态「{target}」不在允许的状态序列里"
        entry["status"] = target
        entry[DISPLAY_STATUS_FIELD] = target
        entry["pending"] = target != STATUS_ORDER[-1]
        entry["abnormal"] = action in NEGATIVE_ACTIONS
        # 只改状态，判定口径与归属片区等历史快照一律不动。
        return entry, f"压力记录已{action}"

    # ------------------------------------------------------------------ 归属
    def current_owner(self, point: str) -> str:
        return self._point_owners.get(point.strip(), DEFAULT_OWNER)

    def reassign_point(self, point: str, owner: str) -> tuple[bool, str]:
        """变更点位当前归属；历史记录留在原片区，只有之后新登记的记录跟随新归属。"""
        point = point.strip()
        owner = owner.strip()
        if not point:
            return False, "监测点位不能为空"
        if not owner:
            return False, "新归属片区不能为空"
        self._point_owners[point] = owner
        return True, f"监测点位「{point}」当前归属已变更为{owner}，历史记录仍保留原归属"
