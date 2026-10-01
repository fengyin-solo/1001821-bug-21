"""压力监测业务规则：状态流转、字段校验、筛选口径与历史快照都收在这里。

口径约定（不可回溯重算）：
- 每条记录在登记时固化「判定口径 / 判定阈值 / 归属班组」三个快照字段；
- 后续即使点位归属变更、平台判定口径升级，历史记录仍按当时的快照保留；
- 点位归属只影响变更之后新登记的记录，不回写历史记录。
"""
from __future__ import annotations

from datetime import date
from typing import Any

from app.store import store

MODULE = "pressure"
REQUIRED_FIELDS = ["监测编号", "监测点位", "监测时段"]
STATUS_ORDER = ["待采集", "采集正常", "压力越限", "已停测"]
ACTION_RULES = {"启动采集": "采集正常", "标记越限": "压力越限", "停止监测": "已停测"}
# 压力越限属于负向动作，用于看板异常统计
NEGATIVE_ACTIONS = ["标记越限"]
ACTIVE_STATUSES = ["待采集", "采集正常", "压力越限"]

# 当前生效的判定口径：只用于新登记记录的快照，不会改写历史记录
CURRENT_CRITERION = "2026版压力判定口径"
CURRENT_THRESHOLD = "0.28 MPa"

# 各监测点位「当前」归属班组；归属变更只改这里，历史记录的归属字段保持原样
POINT_OWNERS: dict[str, str] = {
    "滨河路1号压力监测点": "滨河片区一班",
    "滨河路2号压力监测点": "滨河片区二班",
    "工业大道调压站": "工业片区运维班",
    "城南水厂出厂压力点": "水厂运维班",
}


def _snapshot_fields(point: str, values: dict[str, Any]) -> dict[str, str]:
    """新登记记录的历史快照：归属取点位当前归属，判定口径取当前生效版本。"""
    owner = str(values.get("归属班组") or "").strip() or POINT_OWNERS.get(point, "未分配班组")
    return {
        "归属班组": owner,
        "判定口径": str(values.get("判定口径") or CURRENT_CRITERION).strip(),
        "判定阈值": str(values.get("判定阈值") or CURRENT_THRESHOLD).strip(),
    }


class PressureService:
    def _filter_rows(
        self,
        *,
        keyword: str | None = None,
        point: str | None = None,
        period: str | None = None,
        period_start: str | None = None,
        period_end: str | None = None,
        status: str | None = None,
    ) -> list[dict[str, Any]]:
        """统一筛选口径：列表、导出、点位明细、统计都走这里，保证各处条数一致。"""
        rows = store.rows(MODULE)
        if keyword:
            rows = [row for row in rows if keyword in str(row.get("监测编号", ""))]
        if point:
            rows = [row for row in rows if point in str(row.get("监测点位", ""))]
        if period:
            # 兼容直接传一个时段片段（年月、日期或时段文字），做包含匹配
            rows = [row for row in rows if period in str(row.get("监测时段", ""))]
        if period_start:
            rows = [row for row in rows if str(row.get("监测时段", "")) >= period_start]
        if period_end:
            rows = [row for row in rows if str(row.get("监测时段", "")) <= period_end]
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
        rows = self._filter_rows(
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

    def stats(self) -> dict[str, int]:
        """看板统计：同一监测点位的多批记录只算一次（按点位去重）。"""
        rows = store.rows(MODULE)
        active_points = {
            str(row.get("监测点位", ""))
            for row in rows
            if row.get("status") in ACTIVE_STATUSES and row.get("监测点位")
        }
        overlimit_points = {
            str(row.get("监测点位", ""))
            for row in rows
            if row.get("status") == "压力越限" and row.get("监测点位")
        }
        today = date.today().isoformat()
        today_overlimit = 0
        for row in rows:
            if str(row.get("监测时段", "")) == today:
                try:
                    today_overlimit += int(row.get("越限次数", 0) or 0)
                except (TypeError, ValueError):
                    continue
        return {
            "active_points": len(active_points),
            "overlimit_points": len(overlimit_points),
            "today_overlimit": today_overlimit,
        }

    def get_entry(self, entry_id: int) -> dict[str, Any] | None:
        return store.find(MODULE, entry_id)

    def create_entry(self, values: dict[str, Any]) -> tuple[dict[str, Any] | None, list[str]]:
        missing = [field for field in REQUIRED_FIELDS if not str(values.get(field) or "").strip()]
        if missing:
            return None, missing
        rows = store.rows(MODULE)
        point = str(values.get("监测点位", "")).strip()
        entry = {"id": max((int(row.get("id", 0)) for row in rows), default=0) + 1}
        entry.update({field: values.get(field) for field in REQUIRED_FIELDS})
        # 登记时固化历史快照：归属随点位当前归属，判定口径随当前生效版本
        entry.update(_snapshot_fields(point, values))
        entry["status"] = STATUS_ORDER[0]
        entry["监测状态"] = STATUS_ORDER[0]
        entry["pending"] = True
        entry["abnormal"] = False
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
        if "监测状态" in entry:
            entry["监测状态"] = target
        entry["pending"] = target != STATUS_ORDER[-1]
        entry["abnormal"] = action in NEGATIVE_ACTIONS
        # 标记越限只按记录自身固化的判定口径落结论，不回写口径/阈值/归属快照
        if action == "标记越限":
            criterion = entry.get("判定口径") or "登记时口径"
            entry["判定结论"] = f"按{criterion}判定为压力越限"
        return entry, f"压力记录已{action}"

    def transfer_ownership(self, point: str, new_owner: str) -> tuple[dict[str, Any] | None, str]:
        """变更监测点位归属：只影响之后新登记的记录，历史记录仍归原处。"""
        point = point.strip()
        new_owner = new_owner.strip()
        if not point:
            return None, "请指定要变更归属的监测点位"
        if not new_owner:
            return None, "请指定新的归属班组"
        historical = [
            row for row in store.rows(MODULE)
            if str(row.get("监测点位", "")) == point
        ]
        old_owner = POINT_OWNERS.get(point)
        # 历史记录一条都不改：归属班组保持登记时的快照值
        untouched = sum(1 for row in historical if row.get("归属班组"))
        POINT_OWNERS[point] = new_owner
        return {
            "监测点位": point,
            "原归属班组": old_owner or "未登记",
            "新归属班组": new_owner,
            "历史记录保持原归属条数": untouched,
            "历史归属明细": [
                {"监测编号": row.get("监测编号"), "归属班组": row.get("归属班组")}
                for row in historical
            ],
        }, f"监测点位「{point}」归属已变更为{new_owner}，{untouched} 条历史记录仍归原处"
