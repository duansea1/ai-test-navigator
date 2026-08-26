# AI Test Navigator

需求驱动的代码实现识别、影响分析、测试设计与报告 MVP。

## 当前能力

- 支持直接输入需求文字、上传文档、图片和多个附件
- React 交互工作台（命令面板 Ctrl+K / 可折叠侧栏 / 实时 Agent 活动流，核心入口 `/#/requirements`）
- 8-Agent 语义分析流水线（需求结构化 → 项目侦察 → 代码定位 → 调用链 → 实现审查 → 测试设计 → 质量裁决 → 三视角报告），输出强校验后入库
- 本地 MySQL `ai-navigator` 数据库持久化（11 表，任务/需求/证据/用例/裁决全链路），配置见 `.env.example` 和 `plansea/DATABASE.md`

## 一键启动

双击项目根目录的 `start.bat` 即可启动页面。脚本会：

1. 自动进入项目目录。
2. 检查 Python 和核心依赖。
3. 如果 8090 已运行，则直接打开现有页面，不重复启动。
4. 如果 8090 未运行，则启动 FastAPI 并打开浏览器。

停止服务可以双击 `stop.bat`。

## 页面体验

启动服务：

```powershell
cd C:\Akua\ai-test-navigator
$env:PYTHONPATH = "$PWD\backend"
uvicorn app.main:app --host 127.0.0.1 --port 8090
```

打开：

```text
http://127.0.0.1:8090/
```

页面可以直接输入需求文字，也可以上传文档、图片和多个附件，再选择源码项目、触发分析并打开 JSON/Markdown/HTML 报告。当前图片和二进制附件会保留为附件元数据；真正视觉识别需要接入 OCR 或支持图片输入的模型。

## 运行

在 Windows PowerShell 中：

```powershell
cd C:\Akua\ai-test-navigator
python -m pip install -r requirements.txt
$env:PYTHONPATH = "$PWD\backend"
python -m app.cli `
  --requirement requirements\passport-ocr-demo.md `
  --projects baofu-customer-core baofu-international-core baofu-admin-control-core baofu-admin-control-client-vue member-exchange-client `
  --workspace C:\Akua `
  --branch integration `
  --output reports
```

也可以直接运行：

```powershell
python backend\app\cli.py --requirement requirements\passport-ocr-demo.md --projects baofu-customer-core baofu-international-core baofu-admin-control-core baofu-admin-control-client-vue member-exchange-client --workspace C:\Akua --output reports
```

报告会生成在 `reports` 目录：

- `.json`：供后续前端和数据库使用
- `.md`：适合代码审查和归档
- `.html`：浏览器直接打开

## DSH 语义分析

Agent Runtime 基于 DeepSeek Harness（DSH）源码集成（Windows 经 node 载体运行），支持子代理、工作流、Skills 与多模型热切换；密钥不写入配置文件（`~/.dsh/.credentials.yaml` 或环境变量）。DSH 不可用时自动降级离线规则分析，任务不失败。详见 `plansea/PLAN.md` §0.3。

## 设计边界

默认只读扫描源码、读取 Git commit 和生成报告，不修改业务项目、不执行推送、不切换分支。测试执行引擎（白名单 + dry-run）排期 M4；图片/二进制附件当前仅登记元数据，OCR 视觉解析未接入。
