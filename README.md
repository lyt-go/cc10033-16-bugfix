# 分布式采集调度与反封锁平台

面向分布式采集任务调度、代理池管理、反封锁策略与结果质量校验的数据采集平台。

这是一个前后端分离的管理平台：前端 Vue 3 + Vite + TypeScript，后端 FastAPI（Python）。
两边各自独立启动，前端 dev server 已关掉自动打开页面，启动后按终端打印的地址手工打开。

## 目录结构

```text
.
├── frontend/                 Vue 3 + Vite + TypeScript 前端
│   ├── src/views/WorkbenchView.vue|tsx  全部模块共享工作台
│   ├── src/data/modules.ts              18个业务模块配置
│   ├── src/api/              统一请求封装
│   └── vite.config.ts        dev server 配置（open: false）
├── backend/                  FastAPI（Python） 后端
│   ├── app/routers/resource.py  通用查询/导出/登记/动作接口
│   ├── app/routers/delivery.py  数据导出→投递管道的交付确认/接收核对接口
│   ├── app/services/<key>.py    每个模块独立领域逻辑
│   ├── app/services/base.py     共享服务骨架
│   └── app/store.py          内存数据仓库与示例数据
├── .gitignore
└── docker-compose.yml
```

## 启动

### 后端

```bash
cd backend
python3 -m venv .venv && .venv/bin/pip install -r requirements.txt
./run.sh
```

健康检查：`curl http://127.0.0.1:8000/api/health`

### 前端

```bash
cd frontend
npm ci
npm run dev
```

前端默认监听 `http://127.0.0.1:5173/`，dev server 不会自动打开浏览器，
需要自己访问。`/api` 由 vite 代理到后端 `http://127.0.0.1:8000`。

## 业务模块

| 模块 | 目录 | 业务对象 | 主要字段 |
| --- | --- | --- | --- |
| 采集任务 | `crawl_mission` | 采集任务 | 任务编号、目标URL、优先级 |
| 代理节点 | `proxy_node` | 代理节点 | 节点编号、IP地址、端口号 |
| 频率控制 | `rate_limit` | 限速策略 | 策略编号、目标域名、请求间隔 |
| 设备指纹 | `fingerprint` | 指纹模板 | 模板编号、浏览器类型、UserAgent |
| 验证码处理 | `captcha_solve` | 验证码记录 | 记录编号、验证码类型、图片数据摘要 |
| Cookie管理 | `cookie_jar` | Cookie容器 | 容器编号、所属账号、域名范围 |
| 页面渲染 | `page_render` | 渲染记录 | 记录编号、渲染引擎、页面URL |
| 抽取规则 | `extract_rule` | 抽取规则 | 规则编号、目标页面、抽取方式 |
| 种子URL | `seed_url` | 种子URL | 种子编号、URL地址、所属站点 |
| 内容去重 | `content_dedup` | 去重记录 | 记录编号、内容指纹、原始URL |
| 结果解析 | `result_parse` | 解析记录 | 记录编号、来源页面、解析方式 |
| Schema匹配 | `schema_match` | 匹配配置 | 配置编号、来源站点、目标Schema |
| 调度计划 | `scheduler` | 调度计划 | 计划编号、Cron表达式、关联任务组 |
| 数据导出 | `export_dataset` | 导出任务 | 任务编号、数据来源、导出格式 |
| 质量抽检 | `quality_check` | 抽检任务 | 任务编号、数据批次、抽检比例 |
| 机器人校验 | `robot_verify` | 校验日志 | 日志编号、检测页面、触发规则 |
| 投递管道 | `delivery_pipe` | 投递配置 | 配置编号、目标系统、投递方式 |
| 弹性伸缩 | `scalable_pool` | 伸缩策略 | 策略编号、Worker类型、最小实例数 |

## 约定

- 全部模块共享`frontend/src/views/WorkbenchView.vue|tsx`和一套资源路由。
- 每个模块仍保留独立`backend/app/services/<模块>.py`；纯前端保留
  `frontend/src/domain/<模块>.ts`，用于承载真实业务差异并维持36题位容量。
- 列表接口统一返回 `{ items, total, page, size }`，动作接口统一返回 `{ ok, message }`。
- 状态流转只允许在 `app/services` 里改，路由层不做业务判断。

领域：数据工程
子方向：数据采集、爬虫与RPA
