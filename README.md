# 多源数据采集与RPA自动化平台

面向网页抓取、API接入、增量采集、RPA流程编排、数据校验与采集监控的数据工程平台。

这是一个前后端分离的管理平台：前端 Vue 3 + Vite + TypeScript，后端 FastAPI（Python）。
两边各自独立启动，前端 dev server 已关掉自动打开页面，启动后按终端打印的地址手工打开。

## 目录结构

```text
.
├── frontend/                 Vue 3 + Vite + TypeScript 前端
│   ├── src/views/            每个业务模块一个页面
│   ├── src/api/              统一请求封装
│   ├── src/stores/           会话与筛选状态
│   └── vite.config.ts        dev server 配置（open: false）
├── backend/                  FastAPI（Python） 后端
│   ├── app/routers/          每个业务模块一组接口
│   ├── app/services/         业务规则与状态流转
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
npm install
npm run dev
```

前端默认监听 `http://127.0.0.1:5173/`，dev server 不会自动打开浏览器，
需要自己访问。`/api` 由 vite 代理到后端 `http://127.0.0.1:8000`。

## 业务模块

| 模块 | 目录 | 业务对象 | 主要字段 |
| --- | --- | --- | --- |
| 数据源配置 | `datasource` | 数据源 | 源端编号、连接类型、接入地址 |
| 网页采集规则 | `crawler` | 采集规则 | 规则编号、目标网址、页面选择器 |
| API接入管理 | `apiclient` | API客户端 | 客户端编号、接口名称、请求方法 |
| 增量采集 | `incremental` | 增量游标 | 游标编号、来源标识、增量字段 |
| RPA任务编排 | `robot_task` | RPA任务 | 任务编号、任务名称、页面定位器 |
| 数据接入通道 | `ingestion` | 接入通道 | 通道编号、通道名称、输入格式 |
| 格式解析器 | `parser` | 解析配置 | 解析编号、输入格式、输出格式 |
| 采集结果校验 | `validator` | 校验规则 | 规则编号、校验字段、校验类型 |
| 采集去重 | `dedup` | 去重策略 | 策略编号、输入来源、去重键 |
| 采集调度 | `schedule` | 调度计划 | 计划编号、关联任务、调度周期 |
| 采集监控 | `monitor` | 监控面板 | 面板编号、采集源总数、今日采集量 |
| 采集日志 | `log_viewer` | 日志条目 | 日志编号、关联任务、日志级别 |
| 凭证管理 | `auth` | 认证凭证 | 凭证编号、凭证类型、关联数据源 |
| 采集转换管道 | `transform` | 转换节点 | 节点编号、输入来源、输出目标 |
| 数据流转编排 | `flow` | 流转管道 | 管道编号、管道名称、起始节点 |
| 数据血缘追踪 | `lineage` | 血缘关系 | 关系编号、上游节点、下游节点 |
| 采集报告 | `report` | 采集报告 | 报告编号、采集源、统计周期 |
| 页面样本 | `page_sample` | 页面样本 | 样本编号、来源站点、采集状态码、正文片段 |
| 软错误页面隔离 | `soft_error` | 隔离记录 | 隔离编号、来源站点、错误模板、响应ID |
| 公告办事台 | `announcement` | 公告 | 公告编号、停办日期、正文指纹、来源响应 |
| 站点追问 | `inquiry` | 追问 | 追问编号、隔离编号、响应ID |

## 约定

- 每个模块的前端页面在 `frontend/src/views/<模块>/index.vue`，后端接口在
  `backend/app/routers/<模块>.py`，业务规则在 `backend/app/services/<模块>.py`。
- 列表接口统一返回 `{ items, total, page, size }`，动作接口统一返回 `{ ok, message }`。
- 状态流转只允许在 `app/services` 里改，路由层不做业务判断。

## 软错误页面处理链路

网页采集规则负责选择器配置，但选择器命中不等于拿到有效公告：站点可能在状态码 200 的
报错占位页里也渲染同一套标题和正文容器。处理链路如下：

1. **页面样本**（`page_sample`）：留存解析成功返回的原始页面，采集状态码、正文片段、
   命中标记都原样保存。正文完整性校验会给出 `MISSING_SELECTOR_MISS` /
   `MISSING_EMPTY_BODY` / `MISSING_HTTP_STATUS` 原因码；正文缺失的样本不会生成公告。
   证据接口 `GET /api/page_sample/{id}/evidence` 逐项指向样本原始字段，可回查。
2. **检测**：需要站点页面标记与页面实际内容两类证据。正文容器/页尾命中标记且正文没有
   真实内容（日期、停办措辞）判为软错误页面；正文有真实内容却命中标记判为「证据冲突」；
   标题上的「未开放」是站点占位页与正式公告共用的文案，不单独触发软错误，短正文公告
   只要正文完整、没有结构性错误标记就按有效公告处理。
3. **隔离**（`soft_error`）：按「站点 + 错误模板」合并，同一模板下的多个响应只留一条
   隔离记录，证据里逐条保留响应ID。`POST /api/soft_error/scan` 可重复扫描，保留编号与
   人工处理状态，不触碰公告正文。
4. **去重**（`dedup`）：有效内容按「站点 + 标题 + 正文指纹」去重写入 `dedup_valid`；
   拦截样本按错误模板合并写入 `dedup_blocked`。已发布的公告正文只登记命中，不重写。
5. **公告办事台**（`announcement`）：`POST /api/announcement/publish` 只接受去重结果，
   正文为空或来源样本被隔离时拒绝发布；发布时记录正文指纹。`GET
   /api/announcement/{id}/verify` 按留存原文重新计算指纹，已确认的公告可以独立核对。
   `GET /api/announcement/day?date=YYYY-MM-DD` 回答“这一天采用哪份公告、追问针对哪个响应”。
6. **站点追问**（`inquiry`）：`POST /api/inquiry/raise` 必须携带隔离编号和响应ID，
   响应不属于该隔离记录时直接拒绝并列出可选响应。

自检：`cd backend && .venv/bin/python -I -m unittest discover -s tests -t . -v`。
