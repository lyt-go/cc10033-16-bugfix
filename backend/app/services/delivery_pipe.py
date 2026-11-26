"""投递管道领域服务：采集数据下游投递管道配置、传输监控与重试机制。

跨模块数据流：
- delivery_pipe ← robot_verify: 反封锁检测信息同步到投递管道
- delivery_pipe ← export_dataset: 确认交付的清单进入接收列表，签收后生成回执
"""
from __future__ import annotations

import random
import time
from typing import Any

from app.services.base import BaseModuleService
from app.store import store


class DeliveryPipeService(BaseModuleService):
    MODULE = "delivery_pipe"
    ENTITY = "投递配置"
    OPERATION_TERM = "采集"
    LIST_FIELDS = ["配置编号", "目标系统", "投递方式", "接口地址", "数据筛选", "投递频率", "重试次数", "最后投递"]
    REQUIRED_FIELDS = ["配置编号", "目标系统", "投递方式"]
    STATUS_ORDER = ["草稿", "待验证", "运行中", "已停用"]
    ACTION_RULES = {"提交验证": "待验证", "启动管道": "运行中", "停用管道": "已停用"}
    NEGATIVE_ACTIONS = ["停用管道"]

    TARGET_SYSTEMS = ["Kafka", "RabbitMQ", "HTTP_API", "FTP", "S3", "HDFS", "Elasticsearch",
                      "Database", "Redis_Stream", "Webhook"]
    DELIVERY_METHODS = ["push", "pull", "batch", "stream", "event_driven"]

    def create_entry(self, values: dict[str, Any]) -> tuple:
        entry, missing = super().create_entry(values)
        if entry is None:
            return None, missing
        entry["_delivery_history"] = []
        entry["_total_deliveries"] = 0
        entry["_successful_deliveries"] = 0
        entry["_failed_deliveries"] = 0
        entry["_retry_attempts"] = 0
        entry["_inbox"] = []
        entry["_receipts"] = []
        entry["_receipt_seq"] = 0
        store.record_metric("delivery_pipe", "pipe_created", 1,
                            {"target": values.get("目标系统", ""),
                             "method": values.get("投递方式", "")})
        return entry, []

    @staticmethod
    def _ensure_inbox(entry: dict[str, Any]) -> None:
        """老数据（含种子行）没有接收列表/回执台账，读取前补齐。"""
        entry.setdefault("_inbox", [])
        entry.setdefault("_receipts", [])
        entry.setdefault("_receipt_seq", 0)

    def deliver(self, entry_id: int, data: list[dict[str, Any]], auto_retry: bool = True) -> dict[str, Any]:
        """执行投递操作，支持自动重试。"""
        entry = store.find(self.MODULE, entry_id)
        if entry is None:
            return {"status": "error", "reason": "配置不存在"}
        if entry.get("status") != "运行中":
            return {"status": "error", "reason": "管道未运行"}
        entry["_total_deliveries"] += 1
        max_retries = int(entry.get("重试次数", "3"))
        for attempt in range(1, max_retries + 2):
            success = random.random() > 0.2
            if success:
                entry["_successful_deliveries"] += 1
                entry["最后投递"] = time.strftime("%Y-%m-%d %H:%M:%S")
                record = {"ts": time.time(), "batch_size": len(data) if data else 0,
                          "success": True, "attempt": attempt}
                entry["_delivery_history"].append(record)
                store.record_metric("delivery_pipe", "delivery_success", len(data) if data else 0,
                                    {"target": entry.get("目标系统", ""),
                                     "attempt": str(attempt)})
                return {"status": "success", "delivered": len(data) if data else 0,
                        "attempts": attempt}
            if not auto_retry or attempt > max_retries:
                break
            entry["_retry_attempts"] += 1
            time.sleep(random.uniform(0.5, 2.0))
        entry["_failed_deliveries"] += 1
        store.record_metric("delivery_pipe", "delivery_failed", 1,
                            {"target": entry.get("目标系统", ""),
                             "attempts": str(max_retries + 1)})
        return {"status": "failed", "reason": "超过重试次数", "attempts": max_retries + 1}

    def receive_detection_sync(self, entry_id: int, robot_verify_id: int,
                               detection_data: dict[str, Any]) -> dict[str, Any] | None:
        """接收来自机器人校验的检测信息。跨模块：delivery_pipe ← robot_verify"""
        entry = store.find(self.MODULE, entry_id)
        if entry is None:
            return None
        store.pipeline_trace(
            "robot_verify", "delivery_pipe", robot_verify_id, entry_id,
            "receive_detection", {"blocked": detection_data.get("blocked", False)}
        )
        # 投递检测事件
        return self.deliver(entry_id, [detection_data], auto_retry=False)

    # ── 接收列表与签收回执（export_dataset → delivery_pipe） ──

    def receive_preview(self, entry_id: int) -> dict[str, Any] | None:
        """接收预览：接收清单、签收待办与历史回执。

        清单条数来自导出方确认交付时的实际行数；已领取未签收的部分
        单独列为签收待办，核对者能看清还在等接收端答复哪些清单。
        """
        entry = store.find(self.MODULE, entry_id)
        if entry is None:
            return None
        self._ensure_inbox(entry)
        inbox = entry["_inbox"]
        return {
            "entry_id": entry_id,
            "配置编号": entry.get("配置编号"),
            "inbox": [dict(record) for record in inbox],
            "pending_claim": [dict(r) for r in inbox if r.get("status") == "待领取"],
            "pending_signoff": [dict(r) for r in inbox if r.get("status") == "已领取"],
            "receipts": [dict(r) for r in entry["_receipts"]],
        }

    def claim_manifest(self, entry_id: int, manifest_id: str) -> dict[str, Any] | None:
        """投递方领取接收清单。重复领取同一份清单保持原领取记录。"""
        entry = store.find(self.MODULE, entry_id)
        if entry is None:
            return None
        self._ensure_inbox(entry)
        record = self._find_inbox(entry, manifest_id)
        if record is None:
            return {"ok": False, "reason": f"清单 {manifest_id} 不在接收列表", "record": None}
        if record["status"] == "待领取":
            record["status"] = "已领取"
            record["claimed_at"] = time.strftime("%Y-%m-%d %H:%M:%S")
            store.record_metric("delivery_pipe", "manifest_claimed", record.get("rows", 0),
                                {"manifest_id": manifest_id})
        return {"ok": True, "reason": "已领取", "record": dict(record)}

    def sign_off(self, entry_id: int, manifest_id: str,
                 processed_file: str | None = None) -> dict[str, Any] | None:
        """接收端签收，生成回执。

        回执的批次、条数、文件路径固定为清单内容（同一轮），重复签收返回原回执；
        接收端可说明实际处理了哪份文件，与清单不一致时标记 file_mismatch。
        """
        entry = store.find(self.MODULE, entry_id)
        if entry is None:
            return None
        self._ensure_inbox(entry)
        record = self._find_inbox(entry, manifest_id)
        if record is None:
            return {"ok": False, "reason": f"清单 {manifest_id} 不在接收列表", "receipt": None}
        if record["status"] == "已签收":
            receipt = next(
                (r for r in entry["_receipts"] if r.get("manifest_id") == manifest_id),
                None,
            )
            return {"ok": True, "reason": "该清单已签收，沿用原回执",
                    "receipt": dict(receipt) if receipt else None, "reused": True}
        entry["_receipt_seq"] += 1
        receipt = {
            "receipt_id": f"RCPT-{entry.get('配置编号', 'PIPE')}-{entry['_receipt_seq']:02d}",
            "manifest_id": record["manifest_id"],
            "export_id": record.get("export_id"),
            "batch_no": record["batch_no"],
            "rows": record["rows"],
            "file_path": record["file_path"],
            "signed_at": time.strftime("%Y-%m-%d %H:%M:%S"),
            "processed_file": processed_file or record["file_path"],
            "file_mismatch": bool(processed_file) and processed_file != record["file_path"],
        }
        record["status"] = "已签收"
        record["receipt_id"] = receipt["receipt_id"]
        entry["_receipts"].append(receipt)
        store.record_metric("delivery_pipe", "manifest_signed", record.get("rows", 0),
                            {"manifest_id": manifest_id,
                             "file_mismatch": str(receipt["file_mismatch"])})
        return {"ok": True, "reason": "已签收", "receipt": dict(receipt), "reused": False}

    @staticmethod
    def _find_inbox(entry: dict[str, Any], manifest_id: str) -> dict[str, Any] | None:
        return next(
            (r for r in entry.get("_inbox", []) if r.get("manifest_id") == manifest_id),
            None,
        )

    def topic_overview(self, entry_id: int) -> dict[str, Any]:
        """管道状态总览。"""
        entry = store.find(self.MODULE, entry_id)
        if entry is None:
            return {"error": "不存在"}
        return {
            "total": entry["_total_deliveries"],
            "success": entry["_successful_deliveries"],
            "failed": entry["_failed_deliveries"],
            "retries": entry["_retry_attempts"],
            "success_rate": (
                entry["_successful_deliveries"] / max(entry["_total_deliveries"], 1)
            ),
        }

    def domain_snapshot(self) -> dict[str, Any]:
        base = super().domain_snapshot()
        pipes = store.rows(self.MODULE)
        base["running_pipes"] = sum(1 for p in pipes if p.get("status") == "运行中")
        base["total_deliveries"] = sum(p.get("_total_deliveries", 0) for p in pipes)
        base["overall_success_rate"] = (
            sum(p.get("_successful_deliveries", 0) for p in pipes) /
            max(sum(p.get("_total_deliveries", 0) for p in pipes), 1)
        )
        base["inbox_pending"] = sum(
            sum(1 for r in p.get("_inbox", []) if r.get("status") != "已签收")
            for p in pipes
        )
        base["signed_receipts"] = sum(len(p.get("_receipts", [])) for p in pipes)
        return base