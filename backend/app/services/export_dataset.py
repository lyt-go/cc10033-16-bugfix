"""数据导出领域服务：采集数据批量导出、格式转换与交付路径。

跨模块数据流：
- export_dataset ← quality_check: 质量抽检通过后触发导出
- export_dataset → delivery_pipe: 确认交付后清单进入投递管道接收列表
"""
from __future__ import annotations

import random
import time
from typing import Any

from app.services.base import BaseModuleService
from app.store import store


class ExportDatasetService(BaseModuleService):
    MODULE = "export_dataset"
    ENTITY = "导出任务"
    OPERATION_TERM = "采集"
    LIST_FIELDS = ["任务编号", "数据来源", "导出格式", "字段筛选", "行数范围", "压缩方式", "文件路径", "导出时间"]
    REQUIRED_FIELDS = ["任务编号", "数据来源", "导出格式"]
    STATUS_ORDER = ["待执行", "导出中", "已完成", "已失败"]
    ACTION_RULES = {"发起导出": "导出中", "标记完成": "已完成", "标记失败": "已失败"}

    SUPPORTED_FORMATS = ["CSV", "JSON", "Parquet", "Excel", "XML", "Avro"]
    COMPRESSION = ["none", "gzip", "snappy", "lz4", "zstd"]

    def create_entry(self, values: dict[str, Any]) -> tuple:
        entry, missing = super().create_entry(values)
        if entry is None:
            return None, missing
        entry["_export_progress"] = 0.0
        entry["_exported_rows"] = 0
        entry["_export_errors"] = []
        entry["_start_ts"] = 0
        entry["_batches"] = []
        entry["_deliveries"] = []
        entry["_batch_seq"] = 0
        entry["_delivery_seq"] = 0
        store.record_metric("export_dataset", "export_task_created", 1,
                            {"format": values.get("导出格式", ""),
                             "source": values.get("数据来源", "")})
        return entry, []

    @staticmethod
    def _ensure_ledgers(entry: dict[str, Any]) -> None:
        """老数据（含种子行）没有批次/交付台账，读取前补齐。"""
        entry.setdefault("_export_errors", [])
        entry.setdefault("_batches", [])
        entry.setdefault("_deliveries", [])
        entry.setdefault("_batch_seq", 0)
        entry.setdefault("_delivery_seq", 0)

    def execute_export(self, entry_id: int, data: list[dict[str, Any]] | int | None = None) -> dict[str, Any] | None:
        """执行数据导出，每次执行生成一个新批次。

        行数口径：
        - data 为实际数据行（list）→ 按实际条数 len(data)，空列表即空产物（0 行）
        - data 为 int → 显式指定的模拟条数
        - data 为 None → 随机模拟条数
        """
        entry = store.find(self.MODULE, entry_id)
        if entry is None:
            return None
        self._ensure_ledgers(entry)
        entry["status"] = "导出中"
        entry["_start_ts"] = time.time()
        fmt = entry.get("导出格式", "CSV")
        if fmt not in self.SUPPORTED_FORMATS:
            entry["status"] = "已失败"
            entry["_export_errors"].append(f"不支持的格式：{fmt}")
            entry["abnormal"] = True
            return entry
        # 模拟导出
        self._simulate_export()
        if isinstance(data, list):
            row_count = len(data)
            row_source = "actual"
        elif isinstance(data, bool):
            row_count = random.randint(100, 100000)
            row_source = "simulated"
        elif isinstance(data, int):
            row_count = data
            row_source = "simulated"
        else:
            row_count = random.randint(100, 100000)
            row_source = "simulated"
        entry["_batch_seq"] += 1
        batch_no = entry["_batch_seq"]
        entry["_exported_rows"] = row_count
        entry["行数范围"] = f"1-{row_count}" if row_count else "0行"
        # 文件路径按批次唯一：重新生成不会复用旧路径，旧清单仍指向原文件
        file_path = f"/exports/{entry.get('任务编号', 'TASK')}-b{batch_no:04d}.{fmt.lower()}"
        compression = entry.get("压缩方式", "none")
        if compression != "none":
            file_path += f".{compression}"
        entry["文件路径"] = file_path
        entry["导出时间"] = time.strftime("%Y-%m-%d %H:%M:%S")
        entry["status"] = "已完成"
        entry["pending"] = False
        entry["_export_progress"] = 100.0
        entry["_batches"].append({
            "batch_no": batch_no,
            "rows": row_count,
            "row_source": row_source,
            "file_path": file_path,
            "generated_at": entry["导出时间"],
            "empty": row_count == 0,
        })
        store.record_metric("export_dataset", "export_completed", row_count,
                            {"format": fmt, "compression": compression,
                             "row_source": row_source, "batch_no": str(batch_no)})
        return entry

    def export_with_quality_check(self, entry_id: int, quality_check_id: int,
                                  passed: bool) -> dict[str, Any] | None:
        """质量抽检通过后触发导出。跨模块：quality_check → export_dataset"""
        entry = store.find(self.MODULE, entry_id)
        if entry is None:
            return None
        if not passed:
            entry["status"] = "已失败"
            entry["abnormal"] = True
            return entry
        store.pipeline_trace(
            "quality_check", "export_dataset", quality_check_id, entry_id,
            "quality_passed", {"action": "trigger_export"}
        )
        return self.execute_export(entry_id)

    # ── 交付确认 ──────────────────────────────

    def delivery_confirmation(self, entry_id: int) -> dict[str, Any] | None:
        """交付确认视图：实际行数、可交付批次与已确认清单。

        generated=False 表示内容未生成；generated=True 且 actual_rows=0 是空产物，
        两者是不同结果。每个批次标注是否已确认交付及对应清单号。
        """
        entry = store.find(self.MODULE, entry_id)
        if entry is None:
            return None
        self._ensure_ledgers(entry)
        batches = entry["_batches"]
        deliveries = entry["_deliveries"]
        manifest_by_batch = {d["batch_no"]: d for d in deliveries}
        current = batches[-1] if batches else None
        return {
            "entry_id": entry_id,
            "任务编号": entry.get("任务编号"),
            "status": entry.get("status"),
            "generated": bool(batches),
            "actual_rows": current["rows"] if current else None,
            "current_batch_no": current["batch_no"] if current else None,
            "batches": [
                {
                    **batch,
                    "delivered": batch["batch_no"] in manifest_by_batch,
                    "manifest_id": (manifest_by_batch.get(batch["batch_no"]) or {}).get("manifest_id"),
                }
                for batch in batches
            ],
            "deliveries": [self._delivery_view(dict(m)) for m in deliveries],
        }

    @staticmethod
    def _delivery_view(manifest: dict[str, Any]) -> dict[str, Any]:
        """补投管道侧的实时状态：能否沿原领取继续确认，或仍在等接收端答复。"""
        pipe_id = manifest.get("pipe_id")
        if pipe_id is None:
            manifest["pipe_status"] = manifest.get("pipe_status") or "未投递"
            manifest["receipt_id"] = None
            return manifest
        pipe = store.find("delivery_pipe", int(pipe_id))
        record = None
        if pipe is not None:
            record = next(
                (r for r in pipe.get("_inbox", [])
                 if r.get("manifest_id") == manifest.get("manifest_id")),
                None,
            )
        if record is None:
            manifest["pipe_status"] = "管道无记录"
            manifest["receipt_id"] = None
        else:
            manifest["pipe_status"] = record.get("status", "待领取")
            manifest["receipt_id"] = record.get("receipt_id")
        return manifest

    def confirm_delivery(self, entry_id: int, batch_no: int | None = None,
                         pipe_id: int | None = None) -> dict[str, Any] | None:
        """确认交付：按批次生成交付清单，条数固定为该批次实际行数。

        - 内容未生成不能确认；空产物确认时条数为 0
        - 同一批次重复确认返回原清单（幂等），不会悄悄换成最新一版
        - 指定 pipe_id 时清单同步进入投递管道接收列表
        """
        entry = store.find(self.MODULE, entry_id)
        if entry is None:
            return None
        self._ensure_ledgers(entry)
        batches = entry["_batches"]
        if not batches:
            return {"ok": False, "reason": "内容未生成，无法确认交付",
                    "manifest": None, "reused": False}
        if batch_no is None:
            batch = batches[-1]
        else:
            batch = next((b for b in batches if b["batch_no"] == batch_no), None)
            if batch is None:
                return {"ok": False, "reason": f"批次 {batch_no} 不存在",
                        "manifest": None, "reused": False}
        for manifest in entry["_deliveries"]:
            if manifest["batch_no"] == batch["batch_no"]:
                return {"ok": True, "reason": "该批次已确认交付，沿用原清单",
                        "manifest": self._delivery_view(dict(manifest)), "reused": True}
        entry["_delivery_seq"] += 1
        manifest = {
            "manifest_id": f"{entry.get('任务编号', 'TASK')}-D{entry['_delivery_seq']:02d}",
            "export_id": entry_id,
            "任务编号": entry.get("任务编号"),
            "batch_no": batch["batch_no"],
            "rows": batch["rows"],
            "file_path": batch["file_path"],
            "confirmed_at": time.strftime("%Y-%m-%d %H:%M:%S"),
            "pipe_id": pipe_id,
            "pipe_status": "待领取" if pipe_id is not None else "未投递",
        }
        entry["_deliveries"].append(manifest)
        if pipe_id is not None:
            inbox = self._register_to_pipe(entry, manifest, int(pipe_id))
            if inbox is None:
                manifest["pipe_status"] = "管道不存在"
        store.record_metric("export_dataset", "delivery_confirmed", batch["rows"],
                            {"batch_no": str(batch["batch_no"]),
                             "manifest_id": manifest["manifest_id"]})
        return {"ok": True, "reason": "已确认交付",
                "manifest": self._delivery_view(dict(manifest)), "reused": False}

    @staticmethod
    def _register_to_pipe(entry: dict[str, Any], manifest: dict[str, Any],
                          pipe_id: int) -> dict[str, Any] | None:
        """交付清单登记进投递管道接收列表。跨模块：export_dataset → delivery_pipe"""
        pipe = store.find("delivery_pipe", pipe_id)
        if pipe is None:
            return None
        pipe.setdefault("_inbox", [])
        inbox_record = {
            "manifest_id": manifest["manifest_id"],
            "export_id": manifest["export_id"],
            "任务编号": manifest["任务编号"],
            "batch_no": manifest["batch_no"],
            "rows": manifest["rows"],
            "file_path": manifest["file_path"],
            "received_at": manifest["confirmed_at"],
            "status": "待领取",
            "claimed_at": None,
            "receipt_id": None,
        }
        pipe["_inbox"].append(inbox_record)
        store.pipeline_trace(
            "export_dataset", "delivery_pipe", entry.get("id", 0), pipe_id,
            "deliver_manifest", {"manifest_id": manifest["manifest_id"],
                                 "batch_no": manifest["batch_no"],
                                 "rows": manifest["rows"]}
        )
        return inbox_record

    def format_to_bytes(self, entry_id: int) -> dict[str, Any] | None:
        """模拟格式转换，返回文件大小。"""
        entry = store.find(self.MODULE, entry_id)
        if entry is None:
            return None
        sizes = {"CSV": 1.2, "JSON": 1.5, "Parquet": 0.6, "Excel": 2.0, "XML": 2.5, "Avro": 0.4}
        row_factor = entry.get("_exported_rows", 1000) / 1000
        size_mb = sizes.get(entry.get("导出格式", "CSV"), 1.0) * row_factor
        return {"format": entry.get("导出格式"), "rows": entry.get("_exported_rows"),
                "size_mb": round(size_mb, 2), "compression": entry.get("压缩方式", "none")}

    def _simulate_export(self) -> None:
        time.sleep(random.uniform(0.05, 0.2))

    def domain_snapshot(self) -> dict[str, Any]:
        base = super().domain_snapshot()
        tasks = store.rows(self.MODULE)
        base["completed_exports"] = sum(1 for t in tasks if t.get("status") == "已完成")
        base["total_rows_exported"] = sum(
            sum(b.get("rows", 0) for b in t.get("_batches", []))
            if t.get("_batches") else t.get("_exported_rows", 0)
            for t in tasks
        )
        base["confirmed_deliveries"] = sum(len(t.get("_deliveries", [])) for t in tasks)
        return base
