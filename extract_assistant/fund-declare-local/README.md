# 基金公司投资申报系统

这是一个最小可运行的本地 Web 项目骨架，包含：

- 前端：原生 HTML + CSS + JavaScript，由 FastAPI 托管静态文件
- 后端：FastAPI
- 数据：后续使用本地文件系统和 JSON 存储，当前暂不接入数据库

当前阶段不包含上传文件、OCR、LLM、JSON 抽取、Excel 导出等业务逻辑。

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

## 启动 PaddleOCR 服务

PaddleOCR 服务独立于主 FastAPI 后端。需要先按 PaddleX 官方服务化方式安装并启动 OCR 服务：

```bash
paddlex --install serving
paddlex --serve --pipeline OCR --host 0.0.0.0 --port 8010
```

主后端会调用：

```text
http://localhost:8010/ocr
```

## 启动主后端

```bash
uvicorn app.main:app --host 0.0.0.0 --port 8000 --reload
```

如果提示 `uvicorn: command not found`，说明当前 shell 没有激活虚拟环境，可以改用：

```bash
.venv/bin/python -m uvicorn app.main:app --host 0.0.0.0 --port 8000 --reload
```

后端地址：

```text
http://localhost:8000
```

启动后访问：

```text
http://localhost:8000
```

健康检查接口：

```text
http://localhost:8000/api/health
```

## 测试创建 case

```bash
curl -X POST http://localhost:8000/api/cases \
  -H "Content-Type: application/json" \
  -d '{"name":"张三","phone":"13800000000","relation_type":"employee_self"}'
```

然后检查本地目录：

```text
data/cases/case_001/
```

## 测试文件处理

```bash
curl -X POST http://localhost:8000/api/debug/process-file \
  -F "file=@/你的文件路径/对账单.pdf"
```

处理结果会写入：

```text
data/debug_uploads/
data/debug_outputs/
```

本项目首期不需要 `npm install`，不依赖 `node_modules`，也不再启动 `localhost:5173`。
