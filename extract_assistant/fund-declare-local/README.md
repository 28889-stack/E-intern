# 基金公司投资申报系统

这是一个最小可运行的本地 Web 项目骨架，包含：

- 前端：原生 HTML + CSS + JavaScript，由 FastAPI 托管静态文件
- 后端：FastAPI
- 数据：文件处理调试产物使用本地文件系统和 JSON 存储

当前阶段只验证文件分流、PDF 文本提取、PDF 表格提取和 PaddleOCR 服务调用链路，不包含账户创建、账户材料归档、LLM 抽取、最终整合、checklist、Excel 导出等业务逻辑。

## 启动后端

如果你在仓库根目录 `extract_assistant` 下：

```bash
cd fund-declare-local/apps/api
```

如果你已经在 `fund-declare-local` 目录下：

```bash
cd apps/api
```

首次启动前安装依赖：

```bash
python -m venv .venv
source .venv/bin/activate
pip install -r requirements.txt
```

## OCR 配置

OCR 现在在主 FastAPI 进程内直接调用 PaddleOCR Python API，不再需要单独启动 PaddleOCR 服务。

默认模型兼顾速度和准确率：

```text
OCR_TEXT_DETECTION_MODEL_NAME=PP-OCRv5_mobile_det
OCR_TEXT_RECOGNITION_MODEL_NAME=PP-OCRv5_mobile_rec
OCR_DEVICE=cpu
```

如果后续更看重准确率，可以只改 `.env` 中的模型名，例如切换到 `PP-OCRv5_server_det`。

## 启动主后端

```bash
uvicorn app.main:app --host 127.0.0.1 --port 8000 --reload
```

如果提示 `uvicorn: command not found`，说明当前 shell 没有激活虚拟环境，可以改用：

```bash
.venv/bin/python -m uvicorn app.main:app --host 127.0.0.1 --port 8000 --reload
```

后端地址：

```text
http://127.0.0.1:8000
```

启动后访问：

```text
http://127.0.0.1:8000
```

## 配置 DeepSeek LLM

在 `apps/api` 目录下复制环境变量文件：

```bash
cp .env.example .env
```

编辑 `apps/api/.env`：

```text
LLM_PROVIDER=openai_compatible
LLM_API_KEY=你的 DeepSeek API Key
LLM_BASE_URL=https://api.deepseek.com
LLM_MODEL=deepseek-v4-flash
LLM_TIMEOUT_SECONDS=120
LLM_MAX_TOKENS=8192
OCR_TEXT_DETECTION_MODEL_NAME=PP-OCRv5_mobile_det
OCR_TEXT_RECOGNITION_MODEL_NAME=PP-OCRv5_mobile_rec
OCR_DEVICE=cpu
```

`.env` 只用于本地配置，不会提交到 git。
修改 `.env` 后请重启 FastAPI 后端，让新配置生效。

测试 LLM 连接：

```bash
curl http://127.0.0.1:8000/api/llm/health
```

重跑 Chinaclear 抽取：

```bash
curl -X POST http://127.0.0.1:8000/api/cases/case_001/files/file_001/extract
```

## 测试文件处理

```bash
curl -X POST http://127.0.0.1:8000/api/debug/process-file \
  -F "file=@/你的文件路径/对账单.pdf"
```

处理结果会写入：

```text
data/debug_uploads/
data/debug_outputs/
```

本项目首期不需要 `npm install`，不依赖 `node_modules`，也不再启动 `localhost:5173`。
