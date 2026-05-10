# VL Visual Clone

基于 PaddleOCR-VL 的页面结构结果，进行视觉复原（visual clone）并导出 PDF 的工程化系统。  
项目目标是：让用户尽可能用“一次点击”的方式得到可用结果，同时保持良好的版面还原度。

本项目采用前后端分离：

- 前端：React + Vite，可视化填写参数、触发任务、预览输出。
- 后端：FastAPI + PyMuPDF，负责调用 VL 接口、解析结构、自动选优、重建 PDF。

## 1. 系统要解决什么问题

OCR 的文本识别和版面还原是两件事。很多系统只做“识别出文本”，但无法保留原文档的视觉结构。本系统重点处理的是以下问题：

- 在翻译或重排后，尽量保持原文档视觉布局。
- 对不同 PDF 自适应选择几何策略（parsing 或 layout-hybrid）。
- 尽可能减少用户手动调参，实现一键运行。

## 2. 系统架构

```text
前端 React (5174)
  -> POST /api/run
后端 FastAPI (8091)
  -> 调用 PaddleOCR-VL API /layout-parsing (例如 8080)
  -> 结构解析 + 每页自动选优 (auto)
  -> 视觉重建 (PyMuPDF)
  -> 输出 JSON 与 PDF
前端
  -> 通过 /api/file 预览生成 PDF
```

## 3. 目录结构与模块职责

```text
tools/vl_visual_clone/
  README.md
  backend/
    app.py
    schemas.py
    pipeline.py
    translator.py
    requirements.txt
  frontend/
    package.json
    src/
      main.jsx
      App.jsx
      styles.css
```

### 3.1 后端模块说明

- `backend/app.py`
  - 对外 API 入口。
  - `GET /api/health`：健康检查。
  - `POST /api/run`：执行完整流水线。
  - `GET /api/file`：文件预览下载（给前端 iframe 用）。

- `backend/schemas.py`
  - 请求/响应模型定义。
  - `RunRequest` 目前核心字段：
    - `inputPdf`
    - `outputDir`
    - `apiBase`
    - `sourceLang`
    - `targetLang`
    - `enableTranslate`
    - `geometrySource`（默认 `auto`）
    - `renderBackground`

- `backend/pipeline.py`
  - 系统核心。负责：
    1. 调用 VL 接口拿结构化结果。
    2. 支持多 OCR 引擎（`paddleocr-vl/mineru/dotsocr`）统一处理。
    3. 从结果抽取页面与块，生成可渲染结构。
    4. 对 VL 结果生成 `parsing` 与 `layout-hybrid` 两套候选块。
    5. `auto` 模式下按页评分选优。
    6. 支持一次请求对比全部引擎（容错执行）。
    7. 按选中方案进行视觉重绘，输出 PDF。
    8. 输出中间 JSON 与统计信息。

- `backend/translator.py`
  - 翻译适配层。
  - 当前是占位实现：启用翻译但无外部 MT 后端时，会保留原文。
  - 设计为可插拔，便于接入真实翻译服务。

### 3.2 前端模块说明

- `frontend/src/App.jsx`
  - 页面主组件。
  - 维护表单状态，调用 `/api/run`。
  - 展示任务返回 JSON 与 PDF 预览。
  - `geometrySource` 支持 `auto/parsing/layout-hybrid`，默认 `auto`。

- `frontend/src/main.jsx`
  - 应用挂载入口。

- `frontend/package.json`
  - 开发脚本：`dev/build/preview`。

## 4. 数据流与运行流程

### 4.1 端到端流程

1. 前端提交运行参数到 `/api/run`。
2. 后端校验输入 PDF 路径。
3. 后端调用 VL 的 `/layout-parsing` 接口，获取每页结构。
4. 后端按页处理：
   - 获取坐标映射比例（VL 坐标系 -> PDF 页面坐标系）。
   - 生成候选块：
     - parsing：直接使用解析块。
     - layout-hybrid：layout 几何框 + parsing 文本分配。
   - 若为 `auto`：按重叠率、越界率、文本覆盖率打分并选择更优方案。
   - 渲染背景图（可选）并写入文本/图片。
5. 汇总并导出：
   - `*_vl_raw.json`
   - `*_translated_blocks.json`
   - `*_visual_clone.pdf`
6. 前端读取输出并预览。

### 4.2 auto 模式决策逻辑（按页）

每页同时评估 parsing 与 layout-hybrid，计算：

- 文本覆盖率：文本字符量越高越好。
- 重叠率：文本块两两 IoU 大于阈值的比例，越低越好。
- 越界率：块映射到页面后被裁切的比例，越低越好。

当前综合评分形式：

$$
score = 0.60 \cdot coverage + 0.22 \cdot (1-overlapRate) + 0.18 \cdot (1-overflowRate)
$$

决策规则：

- 若 `layout-hybrid` 分数明显高于 `parsing`，选 `layout-hybrid`。
- 否则选 `parsing`（平局偏向稳定方案）。

说明：权重是工程经验值，可按你的业务目标继续微调。

## 5. 安装与运行

### 5.1 环境要求

- Linux（当前运行环境）
- Python 3.10+
- Node.js 18+
- 已可访问的 PaddleOCR-VL API（例如 `http://127.0.0.1:8080`）

### 5.2 安装依赖

```bash
cd /u01/huzekun/PaddleOCR/PaddleOCR-main/tools/vl_visual_clone
python3 -m pip install --user -r backend/requirements.txt
cd frontend
npm install
```

### 5.3 启动后端

```bash
cd /u01/huzekun/PaddleOCR/PaddleOCR-main/tools/vl_visual_clone/backend
python3 -m uvicorn app:app --host 0.0.0.0 --port 8091
```

### 5.4 启动前端

```bash
cd /u01/huzekun/PaddleOCR/PaddleOCR-main/tools/vl_visual_clone/frontend
npm run dev -- --host 0.0.0.0 --port 5174
```

浏览器访问：`http://127.0.0.1:5174`

### 5.5 启动 MinerU 本地服务（可选，但用于三引擎对比）

```bash
python3 -m pip install --user -U "mineru[core]>=3.0.0"
python3 -m pip install --user -U "jinja2>=3.1.4"

MINERU_MODEL_SOURCE=modelscope \
MINERU_API_OUTPUT_ROOT=/u01/huzekun/data/FUNSD/test/mineru_api_output \
/u01/huzekun/.local/bin/mineru-api --host 0.0.0.0 --port 18000 --enable-vlm-preload false
```

健康检查：`http://127.0.0.1:18000/health`

### 5.6 启动 DotsOCR 本地服务（可选，但用于三引擎对比）

1. 下载 dots.ocr 与模型（推荐 ModelScope）

```bash
cd tools/vl_visual_clone/third_party
git -c http.version=HTTP/1.1 clone --depth 1 https://github.com/rednote-hilab/dots.ocr.git
cd dots.ocr
python3 -m pip install --user -r requirements.txt
python3 tools/download_model.py --type modelscope --name rednote-hilab/dots.mocr
```

2. 启动 vLLM OpenAI 服务（本地权重）

```bash
docker run --rm --gpus all \
  --security-opt seccomp=unconfined --ipc=host \
  --ulimit memlock=-1 --ulimit stack=67108864 \
  -e PYTHONPATH=/workspace/weights:$PYTHONPATH \
  -e OPENBLAS_NUM_THREADS=1 -e OMP_NUM_THREADS=1 -e MKL_NUM_THREADS=1 -e NUMEXPR_NUM_THREADS=1 \
  -v /u01/huzekun/PaddleOCR/PaddleOCR-main/tools/vl_visual_clone/third_party/dots.ocr/weights/DotsMOCR:/workspace/weights/DotsMOCR \
  -p 18001:8000 \
  vllm/vllm-openai:v0.11.2 /workspace/weights/DotsMOCR \
  --tensor-parallel-size 1 \
  --gpu-memory-utilization 0.8 \
  --chat-template-content-format string \
  --served-model-name model
```

健康检查：`http://127.0.0.1:18001/v1/models`

## 6. API 文档（核心）

### 6.1 `POST /api/run`

请求示例：

```json
{
  "inputPdf": "/u01/huzekun/data/FUNSD/pdf_test/funsd_test_0000.pdf",
  "outputDir": "/u01/huzekun/data/FUNSD/test",
  "apiBase": "http://127.0.0.1:8080",
  "sourceLang": "zh",
  "targetLang": "en",
  "enableTranslate": true,
  "geometrySource": "auto",
  "renderBackground": true
}
```

字段说明：

- `inputPdf`：待处理 PDF 路径（必填）。
- `outputDir`：输出目录。
- `apiBase`：VL 服务地址。
- `sourceLang/targetLang`：语言标记。
- `enableTranslate`：是否启用翻译流程。
- `geometrySource`：`auto/parsing/layout-hybrid`。
- `renderBackground`：是否保留原背景。
- `ocrEngine`：`paddleocr-vl/mineru/dotsocr`。
- `compareAllEngines`：是否一次跑三种引擎并对比。
- `mineruApiBase`：MinerU API 地址。
- `dotsocrApiBase`：DotsOCR API 地址。
- `dotsocrModel`：DotsOCR 模型名称。
- `dotsocrPrompt`：DotsOCR 可选提示词。

返回示例（节选）：

```json
{
  "ok": true,
  "message": "Pipeline completed",
  "jsonPath": "..._vl_raw.json",
  "translatedJsonPath": "..._translated_blocks.json",
  "outputPdfPath": "..._visual_clone.pdf",
  "stats": {
    "pages": 1,
    "geometrySource": "auto",
    "autoDecisions": [
      {
        "page": 1,
        "selected": "parsing",
        "score": {
          "parsing": 1.0,
          "layout-hybrid": 0.99
        }
      }
    ]
  }
}
```

### 6.2 `GET /api/health`

用于服务存活检查。

### 6.3 `GET /api/file?path=...`

用于读取结果文件（前端 PDF 预览依赖此接口）。

## 7. 输出文件说明

以输入 `xxx.pdf` 为例，输出目录包含：

- `xxx_vl_raw.json`
  - VL 原始返回，便于追踪上游模型输出。

- `xxx_translated_blocks.json`
  - 每页最终用于渲染的块结果。
  - 包含 `geometrySelected` 字段（在 auto 模式下可看到该页实际选中的模式）。

- `xxx_visual_clone.pdf`
  - 最终视觉重建结果。

补充说明（多引擎一致性）：

- 无论选择 `paddleocr-vl/mineru/dotsocr`，系统都会走“解析 -> 块标准化 -> 页面渲染 -> PDF导出”的完整链路。
- 每个引擎都会产出自己对应的复原 PDF，命名形如：
  - `xxx_paddleocr-vl_visual_clone.pdf`
  - `xxx_mineru_visual_clone.pdf`
  - `xxx_dotsocr_visual_clone.pdf`
- 若某引擎仅返回文本（缺少 bbox），系统会启用文本流降级渲染，仍然输出 PDF（可读但版面精度低于带 bbox 的结果）。

## 8. 常见问题与排障

### 8.1 后端报 `Input PDF not found`

- 检查 `inputPdf` 路径是否真实存在。
- 注意路径需要后端机器可访问。

### 8.2 前端无法预览 PDF

- 确认后端 `8091` 已启动。
- 检查返回的 `outputPdfPath` 是否存在。
- 检查浏览器是否被跨域策略或代理设置影响。

### 8.3 auto 选错模式怎么办

- 可先手动切 `parsing` 或 `layout-hybrid` 复核。
- 用 `stats.autoDecisions` 查看两种模式分数。
- 若业务偏好“召回优先”或“版面优先”，可调整评分权重。

### 8.5 对比模式里 MinerU 或 DotsOCR 失败

- 如果某引擎未配置或接口不可达，请求不会整体失败。
- 可先使用成功引擎（如 VL）的结果继续工作。
- 失败信息会写入返回结果 `stats.engineErrors`。
- DotsOCR 官方网页当前更偏交互演示，若无可编程 API，请使用你自己的网关/代理接口再接入本系统。

### 8.4 启用翻译但文本没变

- 当前 `translator.py` 默认是占位实现，未接外部 MT 引擎时会回传原文。
- 需要接入真实翻译服务才能产生实质翻译。

## 9. 二次开发指南

### 9.1 接入真实翻译引擎

- 修改 `backend/translator.py` 的 `translate_text`。
- 保持输入输出是纯文本字符串。
- 建议加入缓存与重试，避免对同文段重复翻译。

### 9.2 调整 auto 评分策略

- 修改 `backend/pipeline.py` 中的评分权重。
- 你可以扩展更多指标：
  - 行内字符密度异常
  - 页边距聚集异常
  - 同列文本断裂率

### 9.3 增加新输出格式

- 当前目标是 PDF 可视重建。
- 可在后端增加 docx/html 导出分支，复用已标准化的块结构。

## 10. 当前能力边界

- 对复杂手写、极低清晰度扫描件，VL 上游输出仍可能不稳定。
- 表单横线、章戳等视觉元素恢复依赖上游与规则策略，非百分百还原。
- 多语种混排和超密集小字页面仍建议保留人工复核。

## 11. 快速命令清单

```bash
# 启动后端
cd /u01/huzekun/PaddleOCR/PaddleOCR-main/tools/vl_visual_clone/backend
python3 -m uvicorn app:app --host 0.0.0.0 --port 8091

# 启动前端
cd /u01/huzekun/PaddleOCR/PaddleOCR-main/tools/vl_visual_clone/frontend
npm run dev -- --host 0.0.0.0 --port 5174

# 直接调用后端（无前端）
curl -X POST http://127.0.0.1:8091/api/run \
  -H 'Content-Type: application/json' \
  -d '{
    "inputPdf": "/u01/huzekun/data/FUNSD/pdf_test/funsd_test_0000.pdf",
    "outputDir": "/u01/huzekun/data/FUNSD/test",
    "apiBase": "http://127.0.0.1:8080",
    "sourceLang": "zh",
    "targetLang": "en",
    "enableTranslate": true,
    "geometrySource": "auto",
    "renderBackground": true
  }'
```

## 12. 维护建议

- 保留一组固定基准 PDF（表单、票据、多栏、图文混排）做回归。
- 每次算法调整后，比较：
  - 覆盖率
  - 重叠率
  - 越界率
  - 人工主观可读性
- 建议把 `stats.autoDecisions` 持久化，作为后续自动调参的数据基础。
