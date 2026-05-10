# export_docx_test.py 使用说明

本文档对应脚本：

- /u01/huzekun/PaddleOCR/PaddleOCR-main/tools/vl_visual_clone/backend/export_docx_test.py

当前工程默认只启用三路 OCR：

- paddleocr-vl
- mineru
- dotsocr

## 1. 启动 OCR 服务（建议 3 个终端）

### 终端 1：启动 PaddleOCR-VL 服务（8080）

方式 A（推荐，Docker Compose）

1) 下载官方 compose.yaml 与 .env 到同一目录（参考项目文档）。
2) 在该目录执行：

    docker compose up

3) 健康检查（示例）：

    curl -s http://127.0.0.1:8080/health

说明：本项目只要求该服务能响应 /layout-parsing。

参考：

- /u01/huzekun/PaddleOCR/PaddleOCR-main/docs/version3.x/pipeline_usage/PaddleOCR-VL.md
- /u01/huzekun/PaddleOCR/PaddleOCR-main/tools/vl_visual_clone/README.md

### 终端 2：启动 MinerU 服务（18000）

    MINERU_MODEL_SOURCE=modelscope \
    MINERU_API_OUTPUT_ROOT=/u01/huzekun/data/FUNSD/test/mineru_api_output \
    /u01/huzekun/.local/bin/mineru-api --host 0.0.0.0 --port 18000 --enable-vlm-preload false

健康检查：

    curl -s http://127.0.0.1:18000/health

参考：

- /u01/huzekun/PaddleOCR/PaddleOCR-main/tools/vl_visual_clone/README.md

### 终端 3：启动 DotsOCR 服务（18001）

    docker run --rm --gpus all \
      --security-opt seccomp=unconfined --ipc=host \
      --ulimit memlock=-1 --ulimit stack=67108864 \
      -e PYTHONPATH=/workspace/weights:$PYTHONPATH \
      -e OPENBLAS_NUM_THREADS=1 -e OMP_NUM_THREADS=1 -e MKL_NUM_THREADS=1 -e NUMEXPR_NUM_THREADS=1 \
      -v /u01/huzekun/PaddleOCR/PaddleOCR-main/tools/vl_visual_clone/third_party/dots.ocr/weights/DotsMOCR:/workspace/weights/DotsMOCR \
      -p 18001:8000 \
      --name dotsocr-vllm \
      vllm/vllm-openai:v0.11.2 /workspace/weights/DotsMOCR \
      --tensor-parallel-size 1 \
      --gpu-memory-utilization 0.8 \
      --chat-template-content-format string \
      --served-model-name model \
      --trust-remote-code

健康检查：

    curl -s http://127.0.0.1:18001/v1/models

参考：

- /u01/huzekun/PaddleOCR/PaddleOCR-main/tools/vl_visual_clone/README.md

## 2. export_docx_test.py 如何使用

此脚本读取已有的 raw JSON（文件名格式：样本名_引擎_raw.json），导出对应 DOCX。

### 常用命令

    cd /u01/huzekun/PaddleOCR/PaddleOCR-main/tools/vl_visual_clone/backend

    python3 export_docx_test.py \
      --input-dir /u01/huzekun/data/FUNSD/benchmark_053_20260415_rerun/raw \
      --output-dir /u01/huzekun/data/FUNSD/benchmark_053_docx \
      --pdf-search-dir /u01/huzekun/data/FUNSD/test \
      --geometry-source parsing \
      --font-size 11 \
      --min-font-size 3.0

### 关键参数说明

- --input-dir：raw JSON 所在目录。
- --output-dir：DOCX 输出目录。
- --pdf-search-dir：原始 PDF 搜索目录（可传多次）。
- --geometry-source：auto、parsing、layout-hybrid。
- --font-size：默认字号。
- --min-font-size：最小字号。
- --with-page-background：是否保留页面背景图。

### 输出内容

- 每个引擎会输出一个 DOCX：
  - 样本名_paddleocr-vl_visual_clone.docx
  - 样本名_mineru_visual_clone.docx
  - 样本名_dotsocr_visual_clone.docx
- 还会输出 manifest.json，记录成功项与错误项。

## 3. 完善输出：识别时间 + DOCX 转换时间

说明：

- export_docx_test.py 只负责“raw JSON -> DOCX”，本身不调用 OCR 服务，所以不直接产生 OCR 识别耗时。
- 如果你要同时得到三路 OCR 识别时间和 DOCX 转换时间，请使用 run_four_ocr_benchmark.py。

### 一条命令同时拿到两类耗时

    cd /u01/huzekun/PaddleOCR/PaddleOCR-main/tools/vl_visual_clone/backend

    python3 run_four_ocr_benchmark.py \
      --input-pdf /u01/huzekun/data/FUNSD/test/sample_扫描版.pdf \
      --output-root /u01/huzekun/data/FUNSD/benchmark_053_times \
      --vl-api-base http://127.0.0.1:8080 \
      --mineru-api-base http://127.0.0.1:18000 \
      --dotsocr-api-base http://127.0.0.1:18001 \
      --dotsocr-model model \
      --geometry-source parsing \
      --font-size 11 \
      --min-font-size 3.0

### 时间结果在哪里看

- JSON 汇总：
  - output-root/benchmark_results.json
- Markdown 汇总：
  - output-root/样本名_三路OCR_DXOC对比总结.md

其中每个引擎都有以下字段：

- ocr_seconds：OCR 识别耗时（秒）
- docx_seconds：DOCX 导出耗时（秒）

## 4. 常见问题

### 4.1 提示 Unable to locate source PDF

原因：找不到样本同名 PDF。

处理：

- 检查 raw 文件的样本名前缀是否与 PDF 文件名一致。
- 增加或修正 --pdf-search-dir。

### 4.2 某引擎报连接失败

处理：

- 检查端口是否正确：8080、18000、18001。
- 用健康检查命令确认服务是否在线。

### 4.3 DotsOCR 容器退出

常见原因：显存不足。

处理建议：

- 降低 --gpu-memory-utilization（例如 0.7 或 0.6）。
- 关闭其他占用 GPU 的进程。
