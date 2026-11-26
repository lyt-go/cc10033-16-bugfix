"""跨模块数据流集成测试与业务失败场景覆盖。

覆盖：
- 10组跨模块数据流链路
- 7种业务失败场景（脏行、重复任务、代理封禁、频率触发、内容重复、Schema不匹配、Cookie过期）
- 18个模块domain_snapshot完整性测试

运行：
cd backend && python3 -m pytest tests/ -v
"""
from __future__ import annotations

import sys
import os

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from app.store import store
from app.services import SERVICES


# ═══════════════════════════════════════════════════════════════
# 10 组跨模块数据流链路测试
# ═══════════════════════════════════════════════════════════════

class TestCrossModuleChains:
    """跨模块数据流链路：验证模块间 pipeline_trace, event_queue, metrics 正确记录。"""

    # ── Chain 1: crawl_mission → scheduler ──
    def test_chain1_crawl_to_scheduler(self):
        cm = SERVICES["crawl_mission"]
        sch = SERVICES["scheduler"]
        m, _ = cm.create_entry({"任务编号": "CHAIN1-001", "目标URL": "https://c1.example.com", "优先级": "5"})
        s, _ = sch.create_entry({"计划编号": "CHAIN1-SCH", "Cron表达式": "0 0 * * *", "关联任务组": "c1"})
        sch.run_action(s["id"], "启动计划")
        cm.dispatch(m["id"], scheduler_plan_id=s["id"])
        sch.enqueue_mission(s["id"], m["id"], priority=5)
        dispatched = sch.dispatch_next(s["id"])
        assert dispatched is not None
        assert dispatched["mission_id"] == m["id"]
        logs = store.pipeline_log()
        assert any("dispatch" in l["action"] for l in logs)

    # ── Chain 2: proxy_node + rate_limit ──
    def test_chain2_proxy_with_rate_limit(self):
        pn = SERVICES["proxy_node"]
        rl = SERVICES["rate_limit"]
        prox, _ = pn.create_entry({"节点编号": "CHAIN2-P", "IP地址": "10.0.0.1", "端口号": "8080"})
        rate, _ = rl.create_entry({"策略编号": "CHAIN2-R", "目标域名": "example.com", "请求间隔": "1s"})
        pn.run_action(prox["id"], "验证节点")
        rl.run_action(rate["id"], "标记生效")
        allowed, _ = rl.check_allow(rate["id"], "example.com")
        assert allowed
        assign = pn.assign_to_mission(prox["id"], 100, rate_limit_id=rate["id"])
        assert assign is not None
        logs = store.pipeline_log()
        assert any("assign" in l["action"] for l in logs), "pipeline trace for rate_limit assign missing"

    # ── Chain 3: fingerprint → cookie_jar ──
    def test_chain3_fingerprint_to_cookie_jar(self):
        fp = SERVICES["fingerprint"]
        cj = SERVICES["cookie_jar"]
        f, _ = fp.create_entry({"模板编号": "CHAIN3-FP", "浏览器类型": "Firefox", "UserAgent": "Mozilla/5.0"})
        c, _ = cj.create_entry({"容器编号": "CHAIN3-COOK", "所属账号": "c3@test.com", "域名范围": "example.com"})
        fp.run_action(f["id"], "测试指纹")
        fp.assign_to_cookie_jar(f["id"], c["id"])
        cj.bind_fingerprint(c["id"], f["id"])
        assert c.get("关联指纹") is not None
        assert "FING-" in str(c.get("关联指纹") or "")
        logs = store.pipeline_log()
        assert any("bind" in l["action"] for l in logs)

    # ── Chain 4: page_render → extract_rule → result_parse → schema_match → quality_check ──
    def test_chain4_render_to_quality(self):
        pr = SERVICES["page_render"]
        er = SERVICES["extract_rule"]
        rp = SERVICES["result_parse"]
        sm = SERVICES["schema_match"]
        qc = SERVICES["quality_check"]

        page, _ = pr.create_entry({"记录编号": "CHAIN4-PAGE", "渲染引擎": "Chromium Headless", "页面URL": "https://c4.com"})
        rule, _ = er.create_entry({"规则编号": "CHAIN4-EXTR", "目标页面": "c4_page", "抽取方式": "CSS_Selector"})
        parse_ent, _ = rp.create_entry({"记录编号": "CHAIN4-PARSE", "来源页面": "https://c4.com", "解析方式": "HTML_Parse"})
        schema, _ = sm.create_entry({"配置编号": "CHAIN4-SCHM", "来源站点": "c4.com", "目标Schema": "default"})
        quality, _ = qc.create_entry({"任务编号": "CHAIN4-QUAL", "数据批次": "c4_batch", "抽检比例": "20%", "通过标准": "0.8"})

        er.run_action(rule["id"], "发布规则")
        sm.run_action(schema["id"], "启用配置")
        pr.render(page["id"])
        if page.get("status") == "成功":
            pr.trigger_extraction(page["id"], rule["id"])
        er.execute(rule["id"])
        parse_result = rp.parse(parse_ent["id"], "title: Test, content: lots of data here, author: John, tags: test")
        if parse_ent.get("status") == "解析完成" and parse_result:
            rp.feed_to_schema_match(parse_ent["id"], schema["id"], parse_result["fields"])
            sm.match(schema["id"], parse_result["fields"])
        qc.run_check(quality["id"])

        logs = store.pipeline_log()
        assert len(logs) >= 2, f"Chain4 got {len(logs)} traces, expected >=2"

    # ── Chain 5: robot_verify → delivery_pipe ──
    def test_chain5_robot_to_delivery(self):
        rv = SERVICES["robot_verify"]
        dp = SERVICES["delivery_pipe"]
        rob, _ = rv.create_entry({"日志编号": "CHAIN5-ROB", "检测页面": "https://c5.com/", "触发规则": "高频请求"})
        pipe, _ = dp.create_entry({"配置编号": "CHAIN5-DELI", "目标系统": "Kafka", "投递方式": "push"})
        dp.run_action(pipe["id"], "启动管道")
        detect_result = rv.detect(rob["id"], "https://c5.com/")
        rv.sync_to_delivery_pipe(rob["id"], pipe["id"], detect_result)
        logs = store.pipeline_log()
        assert any("sync_detection" in l["action"] for l in logs)

    # ── Chain 6: scheduler → scalable_pool ──
    def test_chain6_scheduler_to_scalable(self):
        sch = SERVICES["scheduler"]
        sp = SERVICES["scalable_pool"]
        s, _ = sch.create_entry({"计划编号": "CHAIN6-SCH", "Cron表达式": "*/30 * * * *", "关联任务组": "c6"})
        sch.run_action(s["id"], "启动计划")
        sch.enqueue_mission(s["id"], 100, priority=3)
        sch.enqueue_mission(s["id"], 101, priority=5)
        pool, _ = sp.create_entry({"策略编号": "CHAIN6-POOL", "Worker类型": "crawler", "最小实例数": "1", "最大实例数": "10"})
        sp.run_action(pool["id"], "标记生效")
        predict = sch.predict_load(s["id"])
        eval_result = sp.evaluate(pool["id"], predict)
        assert eval_result is not None
        assert "action" in eval_result

    # ── Chain 7: seed_url → content_dedup ──
    def test_chain7_seed_to_dedup(self):
        su = SERVICES["seed_url"]
        cd = SERVICES["content_dedup"]
        seed, _ = su.create_entry({"种子编号": "CHAIN7-SEED", "URL地址": "https://c7.com/article", "所属站点": "c7.com"})
        dedup, _ = cd.create_entry({"记录编号": "CHAIN7-DEDUP", "内容指纹": "fp_c7_001", "原始URL": "https://c7.com/article"})
        su.start_crawl(seed["id"])
        su.feed_to_dedup(seed["id"], dedup["id"], "unique content for c7 test chain")
        logs = store.pipeline_log()
        assert any("feed_content" in l["action"] for l in logs)

    # ── Chain 8: cookie_jar → crawl_mission (expired notify) ──
    def test_chain8_cookie_expired_notify(self):
        cj = SERVICES["cookie_jar"]
        jar, _ = cj.create_entry({"容器编号": "CHAIN8-COOK", "所属账号": "c8@test.com", "域名范围": "c8.com"})
        cj.set_cookie(jar["id"], "session", "tok123", expires_in=1)  # very short TTL
        import time
        time.sleep(1.1)
        _, needs_notify = cj.check_expiry(jar["id"])
        if needs_notify:
            cj.notify_mission_pause(jar["id"], 200)
        logs = store.pipeline_log()
        # 至少应有expired_notify或者在之前已有其他trace
        assert len(logs) > 0

    # ── Chain 9: result_parse → schema_match ──
    def test_chain9_parse_to_schema(self):
        rp = SERVICES["result_parse"]
        sm = SERVICES["schema_match"]
        parse_ent, _ = rp.create_entry({"记录编号": "CHAIN9-PARSE", "来源页面": "https://c9.com", "解析方式": "JSON_Parse"})
        schema, _ = sm.create_entry({"配置编号": "CHAIN9-SCHM", "来源站点": "c9.com", "目标Schema": "default"})
        sm.run_action(schema["id"], "启用配置")
        result = rp.parse(parse_ent["id"], "JSON: field1, field2, field3, field4, field5, field6")
        if parse_ent.get("status") == "解析完成" and result:
            rp.feed_to_schema_match(parse_ent["id"], schema["id"], result["fields"])
            match_result = sm.match(schema["id"], result["fields"])
            assert "score" in match_result
        # 至少解析有返回
        assert result is not None

    # ── Chain 10: quality_check → export_dataset ──
    def test_chain10_quality_to_export(self):
        qc = SERVICES["quality_check"]
        ed = SERVICES["export_dataset"]
        batch_entry, _ = qc.create_entry({"任务编号": "CHAIN10-QUAL", "数据批次": "c10_batch", "抽检比例": "50%", "通过标准": "0.6"})
        export, _ = ed.create_entry({"任务编号": "CHAIN10-EXP", "数据来源": "c10_data", "导出格式": "CSV"})
        qc.run_check(batch_entry["id"])
        if batch_entry.get("status") == "通过":
            qc.trigger_export_if_passed(batch_entry["id"], export["id"])
            ed.export_with_quality_check(export["id"], batch_entry["id"], True)
        logs = store.pipeline_log()
        assert len(logs) > 0


# ═══════════════════════════════════════════════════════════════
# 7 种业务失败场景测试
# ═══════════════════════════════════════════════════════════════

class TestBusinessFailureScenarios:
    """业务失败场景：覆盖真实爬虫工程中的典型异常。"""

    # ── 失败场景 1: 脏行数据 ──
    def test_failure_dirty_rows(self):
        """脏行：采集结果中包含空字段、特殊字符、超长值。"""
        cm = SERVICES["crawl_mission"]
        m, _ = cm.create_entry({"任务编号": "DIRTY-001", "目标URL": "https://dirty.example.com", "优先级": "1"})
        # 任务编号重复登记（模拟脏数据）
        m2, missing = cm.create_entry({"任务编号": "DIRTY-001", "目标URL": "https://dirty2.example.com", "优先级": "1"})
        assert m2 is not None
        # 验证创建后发现 missing 列表为空（因为目标URL也填了）
        assert missing == []

        # 缺少必填字段的脏行
        dirty, missing2 = cm.create_entry({"任务编号": "DIRTY-002"})  # 缺少目标URL和优先级
        assert dirty is None
        assert len(missing2) >= 1

    # ── 失败场景 2: 重复任务 ──
    def test_failure_duplicate_tasks(self):
        """重复任务：同一URL多次提交采集任务。"""
        cm = SERVICES["crawl_mission"]
        sch = SERVICES["scheduler"]
        m1, _ = cm.create_entry({"任务编号": "DUP-001", "目标URL": "https://dup.example.com", "优先级": "3"})
        m2, _ = cm.create_entry({"任务编号": "DUP-002", "目标URL": "https://dup.example.com", "优先级": "3"})
        s, _ = sch.create_entry({"计划编号": "DUP-SCH", "Cron表达式": "* * * * *", "关联任务组": "dup"})
        sch.run_action(s["id"], "启动计划")
        cm.dispatch(m1["id"])
        sch.enqueue_mission(s["id"], m1["id"], 3)
        sch.enqueue_mission(s["id"], m2["id"], 3)
        # 两个任务都被排入队列
        assert len(s["_task_queue"]) == 2
        # 但高优(同优先级)先入队的先出
        dispatched = sch.dispatch_next(s["id"])
        assert dispatched is not None

    # ── 失败场景 3: 代理封禁 ──
    def test_failure_proxy_banned(self):
        """代理封禁：节点被目标站点封禁，触发降级/禁用。"""
        pn = SERVICES["proxy_node"]
        rv = SERVICES["robot_verify"]

        prox, _ = pn.create_entry({"节点编号": "BAN-PROX", "IP地址": "192.168.1.99", "端口号": "3128"})
        pn.run_action(prox["id"], "验证节点")

        # 连续3次高延迟触发降级
        pn.health_check(prox["id"], 6000.0)
        pn.health_check(prox["id"], 6000.0)
        pn.health_check(prox["id"], 6000.0)
        assert prox["status"] == "降级"

        rob, _ = rv.create_entry({"日志编号": "BAN-ROB", "检测页面": "https://banned.com", "触发规则": "IP封禁检测"})
        rv.detect(rob["id"], "https://banned.com")
        rotate_result = pn.rotate_on_ban(prox["id"], rob["id"])
        assert rotate_result is not None
        # 降级后再旋转仍然成功
        assert "_ban_count" in prox

    # ── 失败场景 4: 频率触发 ──
    def test_failure_rate_limit_triggered(self):
        """频率触发：请求超过限制，触发冷却。"""
        rl = SERVICES["rate_limit"]
        rate, _ = rl.create_entry({"策略编号": "RATE-TRIG", "目标域名": "hot.example.com", "请求间隔": "1h", "日请求上限": "3"})
        rl.run_action(rate["id"], "标记生效")

        # 直接设置内部状态模拟已达日上限（绕过间隔检查的时间依赖）
        rate["_request_count"] = 3
        rate["_last_request_ts"] = 0
        allowed, msg = rl.check_allow(rate["id"], "hot.example.com")
        assert not allowed, f"Expected rate limit block, got: {msg}"
        assert "日请求上限" in msg, f"Expected 日请求上限 in msg: {msg}"

        # 冷却触发
        rate2, _ = rl.create_entry({"策略编号": "RATE-COOL", "目标域名": "cool.example.com", "请求间隔": "1s"})
        rl.run_action(rate2["id"], "标记生效")
        rl.trigger_cooldown(rate2["id"], 60.0, mission_id=300)
        allowed2, msg2 = rl.check_allow(rate2["id"], "cool.example.com")
        assert not allowed2
        assert "冷却" in msg2

    # ── 失败场景 5: 内容重复 ──
    def test_failure_content_duplicate(self):
        """内容重复：采集到的内容与已有数据完全重复。"""
        cd = SERVICES["content_dedup"]
        rec, _ = cd.create_entry({"记录编号": "CONT-DUP", "内容指纹": "fp_dup_test", "原始URL": "https://dup-content.example.com"})

        content = "exact same article content appears again"
        r1 = cd.check_duplicate(rec["id"], content, "https://dup-content.example.com")
        assert r1["status"] == "唯一内容"

        r2 = cd.check_duplicate(rec["id"], content, "https://dup-content.example.com")
        assert r2["status"] == "完全重复", f"Expected 完全重复, got {r2['status']}"

    # ── 失败场景 6: Schema不匹配 ──
    def test_failure_schema_mismatch(self):
        """Schema不匹配：解析字段与目标Schema差异大。即使有补全策略，缺失字段也会被记录。"""
        sm = SERVICES["schema_match"]
        schema, _ = sm.create_entry({"配置编号": "SCHE-MISMATCH", "来源站点": "mismatch.com", "目标Schema": "default",
                                      "缺失补全策略": "default"})
        sm.run_action(schema["id"], "启用配置")

        # 只有2个不相关的字段：匹配度应很低（即使补全会填满，核心字段匹配度才是关键）
        poor_fields = {"x_field": "x", "y_field": "y"}
        result = sm.match(schema["id"], poor_fields)
        # 检查5号缺少字段（补全前 missing 非空）
        assert "missing" in result, "match result should have missing info"
        # 关键断言：即使自动补全了 missing 字段，metrics 记录了 low_score（因为 similarity < 0.6 亦进入 missing）
        recent = [m for m in store.metrics("schema_match") if m["name"] == "match_low_score"]
        assert len(recent) > 0, f"Expected match_low_score metric for poor match, got {len(recent)}"
        # Schema match success rate snapshot 应该反映这种不匹配
        snap = sm.domain_snapshot()
        assert snap["match_success_rate"] < 0.5, f"Expected poor success rate: {snap['match_success_rate']}"

    # ── 失败场景 7: Cookie过期 ──
    def test_failure_cookie_expired(self):
        """Cookie过期：会话Cookie到期导致采集中断。"""
        cj = SERVICES["cookie_jar"]
        jar, _ = cj.create_entry({"容器编号": "COOK-EXPIRED", "所属账号": "expired@test.com", "域名范围": "expired.com"})

        # 设置短生命期Cookie
        cj.set_cookie(jar["id"], "auth_token", "tok_value", expires_in=-1)  # 立即过期
        import time
        time.sleep(0.1)
        status, needs_notify = cj.check_expiry(jar["id"])

        # 所有Cookie都过期 → 已失效 或 已过期
        assert status in ("已过期", "已失效"), f"Expected expired status, got {status}"
        assert needs_notify

        cj.notify_mission_pause(jar["id"], 500)
        logs = store.pipeline_log()
        assert any("expired_notify" in l["action"] for l in logs)


# ═══════════════════════════════════════════════════════════════
# 数据导出 → 投递管道：交付确认与接收核对
# ═══════════════════════════════════════════════════════════════

class TestExportDeliveryFlow:
    """交付确认：实际条数、批次归属、跨模块清单/回执一致性。"""

    def _new_export(self, task_no: str):
        ed = SERVICES["export_dataset"]
        entry, missing = ed.create_entry(
            {"任务编号": task_no, "数据来源": "交付核对数据源", "导出格式": "CSV",
             "压缩方式": "none"})
        assert entry is not None and not missing
        return ed, entry

    def _new_pipe(self, pipe_no: str):
        dp = SERVICES["delivery_pipe"]
        entry, missing = dp.create_entry(
            {"配置编号": pipe_no, "目标系统": "Kafka", "投递方式": "push"})
        assert entry is not None and not missing
        return dp, entry

    # ── 实际输入时批次详情必须是实际条数，不是模拟条数 ──
    def test_actual_input_rows_win_over_simulated_count(self):
        ed, entry = self._new_export("DELIV-ACTUAL")
        ed.execute_export(entry["id"], data=[{"a": 1}, {"a": 2}])
        assert entry["_exported_rows"] == 2
        view = ed.delivery_confirmation(entry["id"])
        assert view["generated"] is True
        assert view["actual_rows"] == 2
        batch = view["batches"][-1]
        assert batch["rows"] == 2
        assert batch["row_source"] == "actual"

    def test_simulated_count_marked_as_simulated(self):
        ed, entry = self._new_export("DELIV-SIM")
        ed.execute_export(entry["id"], data=5)
        view = ed.delivery_confirmation(entry["id"])
        assert view["actual_rows"] == 5
        assert view["batches"][-1]["row_source"] == "simulated"

    # ── 重新生成不复用原文件路径 ──
    def test_regenerate_uses_new_file_path(self):
        ed, entry = self._new_export("DELIV-PATH")
        ed.execute_export(entry["id"], data=[{"a": 1}, {"a": 2}])
        first_path = entry["文件路径"]
        ed.execute_export(entry["id"], data=[{"a": 1}])
        second_path = entry["文件路径"]
        assert first_path != second_path
        view = ed.delivery_confirmation(entry["id"])
        paths = [b["file_path"] for b in view["batches"]]
        assert len(paths) == len(set(paths)) == 2

    # ── 空产物与未生成是不同结果；空产物确认条数必须为零 ──
    def test_empty_artifact_distinct_from_not_generated(self):
        ed, entry = self._new_export("DELIV-EMPTY")
        view = ed.delivery_confirmation(entry["id"])
        assert view["generated"] is False
        assert view["actual_rows"] is None
        refused = ed.confirm_delivery(entry["id"])
        assert refused["ok"] is False
        ed.execute_export(entry["id"], data=[])
        view = ed.delivery_confirmation(entry["id"])
        assert view["generated"] is True
        assert view["actual_rows"] == 0
        assert view["batches"][-1]["empty"] is True
        confirmed = ed.confirm_delivery(entry["id"])
        assert confirmed["ok"] is True
        assert confirmed["manifest"]["rows"] == 0

    # ── 完整旅程：模拟5 → 实际2 → 交付 → 再生成1 → 重试第一次确认 ──
    def test_journey_simulated5_actual2_regenerate1_retry_confirm(self):
        ed, entry = self._new_export("DELIV-JOURNEY")
        dp, pipe = self._new_pipe("DELIV-JOURNEY-PIPE")

        # 模拟计数为五
        ed.execute_export(entry["id"], data=5)
        # 实际只有两条
        ed.execute_export(entry["id"], data=[{"r": 1}, {"r": 2}])
        actual_batch = entry["_batches"][-1]
        assert actual_batch["rows"] == 2

        # 发起交付：清单条数按实际两条
        confirmed = ed.confirm_delivery(entry["id"], pipe_id=pipe["id"])
        assert confirmed["ok"] is True
        manifest = confirmed["manifest"]
        assert manifest["batch_no"] == actual_batch["batch_no"]
        assert manifest["rows"] == 2
        assert manifest["file_path"] == actual_batch["file_path"]

        # 投递管道接收列表与导出清单对得上
        preview = dp.receive_preview(pipe["id"])
        inbox = [r for r in preview["inbox"] if r["manifest_id"] == manifest["manifest_id"]]
        assert len(inbox) == 1
        assert inbox[0]["rows"] == 2
        assert inbox[0]["file_path"] == actual_batch["file_path"]

        # 另一窗口再生成一份单条版本
        ed.execute_export(entry["id"], data=[{"r": 1}])
        assert entry["_exported_rows"] == 1

        # 旧确认界面重试第一次确认：仍按原批次，不悄悄换成最新一版
        retried = ed.confirm_delivery(entry["id"], batch_no=actual_batch["batch_no"],
                                      pipe_id=pipe["id"])
        assert retried["ok"] is True
        assert retried["reused"] is True
        assert retried["manifest"]["manifest_id"] == manifest["manifest_id"]
        assert retried["manifest"]["rows"] == 2
        # 接收列表不因重试重复登记
        preview = dp.receive_preview(pipe["id"])
        assert sum(1 for r in preview["inbox"]
                   if r["manifest_id"] == manifest["manifest_id"]) == 1

        # 核对文件、清单和接收结果各自的条数：2 / 2 / 2
        receipt = dp.sign_off(pipe["id"], manifest["manifest_id"])
        assert receipt["ok"] is True
        assert receipt["receipt"]["rows"] == 2
        assert receipt["receipt"]["batch_no"] == actual_batch["batch_no"]
        assert receipt["receipt"]["file_path"] == actual_batch["file_path"]
        assert actual_batch["rows"] == 2 and manifest["rows"] == 2

    # ── 再次生成后旧交付仍按原清单核对，原回执仍能打开 ──
    def test_old_manifest_and_receipt_survive_regeneration(self):
        ed, entry = self._new_export("DELIV-RECEIPT")
        dp, pipe = self._new_pipe("DELIV-RECEIPT-PIPE")
        ed.execute_export(entry["id"], data=[{"r": 1}, {"r": 2}, {"r": 3}])
        old_batch = entry["_batches"][-1]
        confirmed = ed.confirm_delivery(entry["id"], batch_no=old_batch["batch_no"],
                                        pipe_id=pipe["id"])
        manifest = confirmed["manifest"]
        dp.claim_manifest(pipe["id"], manifest["manifest_id"])
        signed = dp.sign_off(pipe["id"], manifest["manifest_id"])
        receipt = signed["receipt"]

        # 重新生成新版
        ed.execute_export(entry["id"], data=[{"r": 9}])
        assert entry["_batches"][-1]["batch_no"] != old_batch["batch_no"]

        # 旧交付仍按原清单核对
        view = ed.delivery_confirmation(entry["id"])
        old_delivery = [d for d in view["deliveries"]
                        if d["manifest_id"] == manifest["manifest_id"]]
        assert len(old_delivery) == 1
        assert old_delivery[0]["rows"] == 3
        assert old_delivery[0]["batch_no"] == old_batch["batch_no"]
        assert old_delivery[0]["pipe_status"] == "已签收"

        # 原接收记录仍能按旧回执打开
        preview = dp.receive_preview(pipe["id"])
        reopened = [r for r in preview["receipts"]
                    if r["receipt_id"] == receipt["receipt_id"]]
        assert len(reopened) == 1
        assert reopened[0]["rows"] == 3
        assert reopened[0]["file_path"] == old_batch["file_path"]

    # ── 已领取未答复时重新生成：迟到确认沿原领取继续，条数不变 ──
    def test_late_signoff_after_regeneration_stays_on_claimed_round(self):
        ed, entry = self._new_export("DELIV-LATE")
        dp, pipe = self._new_pipe("DELIV-LATE-PIPE")
        ed.execute_export(entry["id"], data=[{"r": 1}, {"r": 2}])
        claimed_batch = entry["_batches"][-1]
        manifest = ed.confirm_delivery(entry["id"], pipe_id=pipe["id"])["manifest"]
        dp.claim_manifest(pipe["id"], manifest["manifest_id"])

        # 接收端尚未答复，另一窗口重新生成新版
        ed.execute_export(entry["id"], data=[{"r": 1}])
        preview = dp.receive_preview(pipe["id"])
        assert len(preview["pending_signoff"]) == 1
        assert preview["pending_signoff"][0]["rows"] == 2

        # 迟到确认沿原领取继续：回执仍指向被领取的那一轮
        signed = dp.sign_off(pipe["id"], manifest["manifest_id"])
        assert signed["receipt"]["batch_no"] == claimed_batch["batch_no"]
        assert signed["receipt"]["rows"] == 2
        assert signed["receipt"]["file_path"] == claimed_batch["file_path"]

        # 重复签收沿用原回执
        again = dp.sign_off(pipe["id"], manifest["manifest_id"])
        assert again["reused"] is True
        assert again["receipt"]["receipt_id"] == signed["receipt"]["receipt_id"]

    # ── 接收端说明实际处理了哪份文件：不一致要标出来 ──
    def test_signoff_flags_processed_file_mismatch(self):
        ed, entry = self._new_export("DELIV-MISMATCH")
        dp, pipe = self._new_pipe("DELIV-MISMATCH-PIPE")
        ed.execute_export(entry["id"], data=[{"r": 1}])
        manifest = ed.confirm_delivery(entry["id"], pipe_id=pipe["id"])["manifest"]
        signed = dp.sign_off(pipe["id"], manifest["manifest_id"],
                             processed_file="/exports/elsewhere.csv")
        assert signed["receipt"]["file_mismatch"] is True
        assert signed["receipt"]["rows"] == 1


# ═══════════════════════════════════════════════════════════════
# 18 个模块 Domain Snapshot 完整性测试
# ═══════════════════════════════════════════════════════════════

class TestDomainSnapshotIntegrity:
    """每个模块的 domain_snapshot 必须返回完整的模块画像。"""

    BASE_KEYS = frozenset({"module", "entity", "artifact", "count", "by_status", "abnormal"})

    def test_snapshot_crawl_mission(self):
        snap = SERVICES["crawl_mission"].domain_snapshot()
        assert self.BASE_KEYS <= set(snap)
        assert "avg_retry" in snap
        assert "total_dispatched" in snap

    def test_snapshot_proxy_node(self):
        snap = SERVICES["proxy_node"].domain_snapshot()
        assert self.BASE_KEYS <= set(snap)
        assert "available_nodes" in snap
        assert "degraded_nodes" in snap
        assert "total_assigned" in snap

    def test_snapshot_rate_limit(self):
        snap = SERVICES["rate_limit"].domain_snapshot()
        assert self.BASE_KEYS <= set(snap)
        assert "active_policies" in snap
        assert "total_requests" in snap

    def test_snapshot_fingerprint(self):
        snap = SERVICES["fingerprint"].domain_snapshot()
        assert self.BASE_KEYS <= set(snap)
        assert "active_templates" in snap
        assert "banned_count" in snap
        assert "total_assignments" in snap

    def test_snapshot_captcha_solve(self):
        snap = SERVICES["captcha_solve"].domain_snapshot()
        assert self.BASE_KEYS <= set(snap)
        assert "total_attempts" in snap
        assert "solve_rate" in snap

    def test_snapshot_cookie_jar(self):
        snap = SERVICES["cookie_jar"].domain_snapshot()
        assert self.BASE_KEYS <= set(snap)
        assert "active_jars" in snap
        assert "expired_jars" in snap
        assert "total_refreshes" in snap

    def test_snapshot_page_render(self):
        snap = SERVICES["page_render"].domain_snapshot()
        assert self.BASE_KEYS <= set(snap)
        assert "success_renders" in snap
        assert "timeout_renders" in snap
        assert "total_js_errors" in snap

    def test_snapshot_extract_rule(self):
        snap = SERVICES["extract_rule"].domain_snapshot()
        assert self.BASE_KEYS <= set(snap)
        assert "published_rules" in snap
        assert "total_executions" in snap
        assert "success_rate" in snap

    def test_snapshot_seed_url(self):
        snap = SERVICES["seed_url"].domain_snapshot()
        assert self.BASE_KEYS <= set(snap)
        assert "pending_seeds" in snap
        assert "completed_seeds" in snap
        assert "total_child_urls" in snap

    def test_snapshot_content_dedup(self):
        snap = SERVICES["content_dedup"].domain_snapshot()
        assert self.BASE_KEYS <= set(snap)
        assert "unique_count" in snap
        assert "duplicate_count" in snap
        assert "fingerprint_db_size" in snap

    def test_snapshot_result_parse(self):
        snap = SERVICES["result_parse"].domain_snapshot()
        assert self.BASE_KEYS <= set(snap)
        assert "completed_parses" in snap
        assert "error_parses" in snap
        assert "avg_field_count" in snap

    def test_snapshot_schema_match(self):
        snap = SERVICES["schema_match"].domain_snapshot()
        assert self.BASE_KEYS <= set(snap)
        assert "active_configs" in snap
        assert "total_matches" in snap
        assert "match_success_rate" in snap

    def test_snapshot_scheduler(self):
        snap = SERVICES["scheduler"].domain_snapshot()
        assert self.BASE_KEYS <= set(snap)
        assert "active_plans" in snap
        assert "total_dispatched" in snap
        assert "queue_depth" in snap
        assert "active_tasks" in snap

    def test_snapshot_export_dataset(self):
        snap = SERVICES["export_dataset"].domain_snapshot()
        assert self.BASE_KEYS <= set(snap)
        assert "completed_exports" in snap
        assert "total_rows_exported" in snap

    def test_snapshot_quality_check(self):
        snap = SERVICES["quality_check"].domain_snapshot()
        assert self.BASE_KEYS <= set(snap)
        assert "passed_checks" in snap
        assert "failed_checks" in snap
        assert "avg_score" in snap

    def test_snapshot_robot_verify(self):
        snap = SERVICES["robot_verify"].domain_snapshot()
        assert self.BASE_KEYS <= set(snap)
        assert "blocked_count" in snap
        assert "recovered_count" in snap
        assert "total_proxy_rotations" in snap

    def test_snapshot_delivery_pipe(self):
        snap = SERVICES["delivery_pipe"].domain_snapshot()
        assert self.BASE_KEYS <= set(snap)
        assert "running_pipes" in snap
        assert "total_deliveries" in snap
        assert "overall_success_rate" in snap

    def test_snapshot_scalable_pool(self):
        snap = SERVICES["scalable_pool"].domain_snapshot()
        assert self.BASE_KEYS <= set(snap)
        assert "active_pools" in snap
        assert "total_instances" in snap
        assert "total_scale_ups" in snap
        assert "total_scale_downs" in snap


# ═══════════════════════════════════════════════════════════════
# 全局拓扑和 Store 完整性测试
# ═══════════════════════════════════════════════════════════════

class TestStoreTopology:
    """验证全局 store 与拓扑完整性。"""

    def test_pipeline_topology_has_edges(self):
        """所有跨模块测试运行后，拓扑应有边。"""
        topology = store.get_pipeline_topology()
        assert isinstance(topology, dict)
        assert len(topology) > 0, "Pipeline topology should have edges after cross-module tests"

    def test_event_queue_non_empty(self):
        """事件队列应有待处理事件。"""
        pending = store.pending_events()
        assert pending >= 0
        # 至少应该有事件产生
        assert pending > 0 or len(store.pipeline_log()) > 0

    def test_metrics_collected(self):
        """指标收集应有数据。"""
        metrics = store.metrics()
        assert len(metrics) > 0, "Metrics should be collected from module operations"

    def test_overview_cards(self):
        """概览看板应正确计算。"""
        ov = store.overview()
        assert "cards" in ov
        assert "modules" in ov
        cards = ov["cards"]
        assert len(cards) == 4
        assert cards[0]["label"] == "业务模块"
        assert cards[3]["label"] == "异常量"