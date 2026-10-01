"""压力监测接口：筛选、状态流转、统计去重、导出与点位归属变更。"""
from __future__ import annotations

from typing import Any

from fastapi import APIRouter, HTTPException, Query

from app.schemas import ActionResult, EntryPayload, PageResult
from app.services.pressure import PressureService
from app.store import store

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
    """列表、统计、导出共用同一份查询参数，保证「另存」范围就是列表当前范围。"""
    return {
        "keyword": keyword or None,
        "point": point or None,
        "period": period or None,
        "period_start": period_start or None,
        "period_end": period_end or None,
        "status": status or None,
    }


# 静态路径（/export、/stats、/point）必须声明在 /{entry_id} 之前，否则会被当成记录编号。
@router.get("", response_model=PageResult[dict])
def list_entries(
    keyword: str | None = Query(default=None, description="按监测编号检索"),
    point: str | None = Query(default=None, description="按监测点位模糊检索"),
    period: str | None = Query(default=None, description="按监测时段检索"),
    period_start: str | None = Query(default=None, description="监测时段起，YYYY-MM-DD"),
    period_end: str | None = Query(default=None, description="监测时段止，YYYY-MM-DD"),
    status: str | None = Query(default=None, description="待采集、采集正常、压力越限、已停测"),
    page: int = Query(default=1, ge=1),
    size: int = Query(default=20, ge=1),
) -> PageResult[dict]:
    """按监测编号、监测点位、监测时段与状态过滤压力监测列表；没有数据时返回空页。"""
    if size > 200:
        raise HTTPException(status_code=400, detail="每页最多 200 条，请缩小分页范围")
    items, total = service.list_entries(
        **_list_kwargs(keyword, point, period, period_start, period_end, status),
        page=page,
        size=size,
    )
    return PageResult(items=items, total=total, page=page, size=size)


@router.get("/stats")
def get_stats(
    keyword: str | None = None,
    point: str | None = None,
    period: str | None = None,
    period_start: str | None = None,
    period_end: str | None = None,
    status: str | None = None,
) -> dict[str, int]:
    """当前筛选口径下的统计；监测点位去重，同一批点位只算一次。"""
    return service.stats(
        **_list_kwargs(keyword, point, period, period_start, period_end, status),
    )


@router.get("/export")
def export_entries(
    keyword: str | None = None,
    point: str | None = None,
    period: str | None = None,
    period_start: str | None = None,
    period_end: str | None = None,
    status: str | None = None,
) -> dict[str, Any]:
    """另存当前清单：沿用列表当前筛选条件导出全量匹配记录，与列表同一批。"""
    items, total = service.list_entries(
        **_list_kwargs(keyword, point, period, period_start, period_end, status),
        page=1,
        size=10000,
    )
    return {
        "module": "pressure",
        "scope": _list_kwargs(keyword, point, period, period_start, period_end, status),
        "total": total,
        "items": items,
    }


@router.get("/points")
def list_points() -> dict[str, Any]:
    """去重后的监测点位清单及其当前归属；同一批点位只出现一次。"""
    points: list[str] = []
    for row in store.rows("pressure"):
        point = str(row.get("监测点位") or "").strip()
        if point and point not in points:
            points.append(point)
    items = [{"监测点位": point, "归属片区": service.current_owner(point)} for point in points]
    return {"total": len(items), "items": items}


@router.get("/point")
def point_history(point: str = Query(description="监测点位，精确点位名")) -> dict[str, Any]:
    """同一监测点位的全部历史记录；归属变更后老记录仍留在原归属处。"""
    items = service.point_history(point)
    return {"point": point, "owner": service.current_owner(point), "total": len(items), "items": items}


@router.post("/point/reassign", response_model=ActionResult)
def reassign_point(payload: EntryPayload) -> ActionResult:
    """变更监测点位当前归属，只影响点位当前归属与之后的新记录。"""
    point = str(payload.values.get("监测点位") or "").strip()
    owner = str(payload.values.get("归属片区") or "").strip()
    ok, message = service.reassign_point(point, owner)
    return ActionResult(ok=ok, message=message)


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
