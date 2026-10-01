"""压力监测接口：维护压力记录，覆盖启动采集、标记越限、停止监测、归属变更等动作。"""
from __future__ import annotations

from typing import Any

from fastapi import APIRouter, HTTPException, Query

from app.schemas import ActionResult, EntryPayload, PageResult
from app.services.pressure import PressureService

router = APIRouter(prefix="/api/pressure", tags=["压力监测"])

service = PressureService()

LIST_FIELDS = ["监测编号", "监测点位", "监测时段", "平均压力", "峰值压力", "越限次数", "采集人员", "监测状态"]
STATUSES = ["待采集", "采集正常", "压力越限", "已停测"]


def _list_kwargs(
    keyword: str | None,
    point: str | None,
    period: str | None,
    period_start: str | None,
    period_end: str | None,
    status: str | None,
) -> dict[str, Any]:
    return {
        "keyword": keyword or None,
        "point": point or None,
        "period": period or None,
        "period_start": period_start or None,
        "period_end": period_end or None,
        "status": status or None,
    }


# 固定路径放在 /{entry_id} 之前，避免「export / stats / transfer」被当作记录 id 匹配
@router.get("/export")
def export_entries(
    keyword: str | None = None,
    point: str | None = Query(default=None, description="按监测点位过滤，与列表同一口径"),
    period: str | None = Query(default=None, description="按监测时段片段过滤"),
    period_start: str | None = Query(default=None, description="监测时段起（含），YYYY-MM-DD"),
    period_end: str | None = Query(default=None, description="监测时段止（含），YYYY-MM-DD"),
    status: str | None = None,
) -> dict[str, Any]:
    """导出当前过滤条件下的全量数据；不带条件时才导出全部。"""
    items, total = service.list_entries(
        **_list_kwargs(keyword, point, period, period_start, period_end, status),
        page=1,
        size=10000,
    )
    return {
        "module": "pressure",
        "total": total,
        "filters": {
            "keyword": keyword or None,
            "point": point or None,
            "period": period or None,
            "period_start": period_start or None,
            "period_end": period_end or None,
            "status": status or None,
        },
        "items": items,
    }


@router.get("/stats")
def pressure_stats() -> dict[str, int]:
    """压力看板统计：点位按去重计数，今日越限次数按时段当天汇总。"""
    return service.stats()


@router.post("/transfer")
def transfer_ownership(payload: EntryPayload) -> ActionResult:
    """变更监测点位归属；历史记录保留原归属，只有之后新登记记录跟随新归属。"""
    point = str(payload.values.get("point") or payload.values.get("监测点位") or "")
    new_owner = str(payload.values.get("owner") or payload.values.get("归属班组") or "")
    result, message = service.transfer_ownership(point, new_owner)
    if result is None:
        return ActionResult(ok=False, message=message)
    return ActionResult(ok=True, message=message, entry=result)


@router.get("", response_model=PageResult[dict])
def list_entries(
    keyword: str | None = Query(default=None, description="按监测编号检索"),
    point: str | None = Query(default=None, description="按监测点位过滤"),
    period: str | None = Query(default=None, description="按监测时段片段过滤"),
    period_start: str | None = Query(default=None, description="监测时段起（含），YYYY-MM-DD"),
    period_end: str | None = Query(default=None, description="监测时段止（含），YYYY-MM-DD"),
    status: str | None = Query(default=None, description="待采集、采集正常、压力越限、已停测"),
    page: int = 1,
    size: int = 20,
) -> PageResult[dict]:
    """按监测编号、监测点位、监测时段与状态过滤压力监测列表；没有数据时返回空页，不报错。"""
    if size > 200:
        raise HTTPException(status_code=400, detail="每页最多 200 条，请缩小分页范围")
    if page < 1:
        page = 1
    items, total = service.list_entries(
        **_list_kwargs(keyword, point, period, period_start, period_end, status),
        page=page,
        size=size,
    )
    return PageResult(items=items, total=total, page=page, size=size)


@router.get("/{entry_id}", response_model=dict)
def get_entry(entry_id: int) -> dict:
    """读取单条压力记录明细；不存在时给出可读的错误说明。"""
    entry = service.get_entry(entry_id)
    if entry is None:
        raise HTTPException(status_code=404, detail=f"压力记录 {entry_id} 不存在或已归档")
    return entry


@router.post("", response_model=ActionResult)
def create_entry(payload: EntryPayload) -> ActionResult:
    """登记一条压力记录，缺字段时说明原因而不是静默丢弃。"""
    entry, missing = service.create_entry(payload.values)
    if missing:
        return ActionResult(ok=False, message=f"缺少必填字段：{'、'.join(missing)}")
    return ActionResult(ok=True, message="压力记录已登记", entry=entry)


@router.post("/{entry_id}/actions", response_model=ActionResult)
def run_action(entry_id: int, payload: EntryPayload) -> ActionResult:
    """对单条压力记录执行启动采集、标记越限、停止监测；不允许的动作会被拦下并说明原因。"""
    action = str(payload.values.get("action") or "").strip()
    entry, message = service.run_action(entry_id, action)
    if entry is None:
        return ActionResult(ok=False, message=message)
    return ActionResult(ok=True, message=message, entry=entry)
