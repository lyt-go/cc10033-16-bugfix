"""交付确认与接收核对接口：数据导出 → 投递管道 的跨模块交付流。

- 数据导出侧：生成产物（按批次）、查看交付确认、按批次确认交付
- 投递管道侧：接收预览、领取清单、签收生成回执
"""
from __future__ import annotations

from typing import Any

from fastapi import APIRouter, HTTPException
from pydantic import BaseModel, Field

from app.services import service_for

router = APIRouter(prefix="/api", tags=["交付确认"])


class GeneratePayload(BaseModel):
    data: list[dict[str, Any]] | None = None
    rows: int | None = Field(default=None, ge=0)


class ConfirmPayload(BaseModel):
    batch_no: int | None = None
    pipe_id: int | None = None


class SignoffPayload(BaseModel):
    processed_file: str | None = None


def _service(module: str, method: str):
    service = service_for(module)
    if service is None or not hasattr(service, method):
        raise HTTPException(status_code=404, detail=f"模块 {module} 不支持交付核对")
    return service


@router.get("/export_dataset/{entry_id}/delivery", response_model=dict)
def delivery_confirmation(entry_id: int) -> dict[str, Any]:
    """交付确认视图：实际行数、可交付批次与已确认清单。"""
    service = _service("export_dataset", "delivery_confirmation")
    view = service.delivery_confirmation(entry_id)
    if view is None:
        raise HTTPException(status_code=404, detail=f"导出任务 {entry_id} 不存在或已归档")
    return {"ok": True, **view}


@router.post("/export_dataset/{entry_id}/generate", response_model=dict)
def generate_export(entry_id: int, payload: GeneratePayload) -> dict[str, Any]:
    """生成/重新生成导出产物：每次生成一个新批次，文件路径不复用。"""
    service = _service("export_dataset", "execute_export")
    data: list[dict[str, Any]] | int | None
    if payload.data is not None:
        data = payload.data
    elif payload.rows is not None:
        data = payload.rows
    else:
        data = None
    entry = service.execute_export(entry_id, data=data)
    if entry is None:
        raise HTTPException(status_code=404, detail=f"导出任务 {entry_id} 不存在或已归档")
    batch = entry.get("_batches", [])[-1] if entry.get("_batches") else None
    return {"ok": entry.get("status") == "已完成",
            "message": f"已生成批次 {batch['batch_no']}" if batch else "生成失败",
            "entry": entry, "batch": batch}


@router.post("/export_dataset/{entry_id}/delivery/confirm", response_model=dict)
def confirm_delivery(entry_id: int, payload: ConfirmPayload) -> dict[str, Any]:
    """确认交付：按批次生成清单；重复确认同一批次沿用原清单。"""
    service = _service("export_dataset", "confirm_delivery")
    result = service.confirm_delivery(entry_id, batch_no=payload.batch_no,
                                      pipe_id=payload.pipe_id)
    if result is None:
        raise HTTPException(status_code=404, detail=f"导出任务 {entry_id} 不存在或已归档")
    return result


@router.get("/delivery_pipe/{entry_id}/inbox", response_model=dict)
def receive_preview(entry_id: int) -> dict[str, Any]:
    """接收预览：接收清单、签收待办与历史回执。"""
    service = _service("delivery_pipe", "receive_preview")
    view = service.receive_preview(entry_id)
    if view is None:
        raise HTTPException(status_code=404, detail=f"投递配置 {entry_id} 不存在或已归档")
    return {"ok": True, **view}


@router.post("/delivery_pipe/{entry_id}/inbox/{manifest_id}/claim", response_model=dict)
def claim_manifest(entry_id: int, manifest_id: str) -> dict[str, Any]:
    """投递方领取接收清单。"""
    service = _service("delivery_pipe", "claim_manifest")
    result = service.claim_manifest(entry_id, manifest_id)
    if result is None:
        raise HTTPException(status_code=404, detail=f"投递配置 {entry_id} 不存在或已归档")
    return result


@router.post("/delivery_pipe/{entry_id}/inbox/{manifest_id}/signoff", response_model=dict)
def sign_off(entry_id: int, manifest_id: str, payload: SignoffPayload) -> dict[str, Any]:
    """接收端签收：回执固定为清单的批次与条数，重复签收沿用原回执。"""
    service = _service("delivery_pipe", "sign_off")
    result = service.sign_off(entry_id, manifest_id,
                              processed_file=payload.processed_file)
    if result is None:
        raise HTTPException(status_code=404, detail=f"投递配置 {entry_id} 不存在或已归档")
    return result
