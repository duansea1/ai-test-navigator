# AI Test Navigator

需求驱动的代码实现识别、影响分析、测试设计与报告 MVP。

## 当前能力

- 支持直接输入需求文字、上传文档、图片和多个附件
- 读取 Markdown 需求文档并提取标题/列表需求项
- 扫描 Java、Vue、JavaScript 源码并生成代码证据
- 按项目生成影响范围
- 生成正常、异常、边界、幂等、权限测试用例
- 输出 JSON、Markdown、HTML 报告
- 可选接入 DeepSeek Harness Python SDK；没有 API Key 或 Windows 运行时不可用时自动使用离线规则分析
- 预留本地 MySQL `ai-navigator` 数据库接入，配置见 `.env.example` 和 `plansea/DATABASE.md`

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

DSH 仅作为可选增强层。配置 `DEEPSEEK_API_KEY` 后，在支持的 Linux/macOS/WSL2 环境运行；Windows 原生环境优先使用离线规则分析。密钥不写入配置文件。

## 设计边界

MVP 默认只读扫描源码、读取 Git commit 和生成报告，不修改业务项目、不执行推送、不切换分支。测试执行器和 React 页面将在后续阶段接入。
