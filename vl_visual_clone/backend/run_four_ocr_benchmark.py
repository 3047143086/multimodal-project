#!/usr/bin/env python3
from __future__ import annotations

import argparse
import difflib
import json
import os
import shutil
import sys
import time
import zipfile
from pathlib import Path
from typing import Any

import fitz

CURRENT_DIR = Path(__file__).resolve().parent
if str(CURRENT_DIR) not in sys.path:
    sys.path.insert(0, str(CURRENT_DIR))

import export_docx_test as edt  # noqa: E402
from pipeline import _call_dotsocr, _call_mineru, _call_vl  # noqa: E402
from translator import Translator  # noqa: E402


# 临时仅保留三路 OCR：paddleocr-vl / mineru / dotsocr
# ENGINES = ("paddleocr-vl", "mineru", "dotsocr", "opendataloader-hybrid-full")
ENGINES = ("paddleocr-vl", "mineru", "dotsocr")


def _parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description="Run 4 OCR engines and export comparable DOCX outputs")
    parser.add_argument("--input-pdf", required=True, help="Path to input PDF")
    parser.add_argument("--output-root", required=True, help="Output root directory")
    parser.add_argument("--vl-api-base", default="http://127.0.0.1:8080", help="PaddleOCR-VL API base")
    parser.add_argument("--mineru-api-base", default="http://127.0.0.1:18000", help="MinerU API base")
    parser.add_argument("--dotsocr-api-base", default="http://127.0.0.1:18001", help="DotsOCR API base")
    parser.add_argument("--dotsocr-model", default="model", help="DotsOCR served model name (must match service served-model-name)")
    parser.add_argument("--dotsocr-prompt", default="prompt_layout_all_en", help="DotsOCR prompt mode")
    parser.add_argument("--odl-hybrid-url", default="http://127.0.0.1:5002", help="OpenDataLoader hybrid backend URL")
    parser.add_argument("--odl-py-path", default="/u01/huzekun/.local/opendataloader_pdf_py", help="OpenDataLoader python package path")
    parser.add_argument("--odl-java-bin", default="/u01/huzekun/.local/java/jdk-21.0.10+7-jre/bin", help="Java bin path for OpenDataLoader")
    parser.add_argument("--odl-hf-endpoint", default="https://hf-mirror.com", help="HF endpoint for OpenDataLoader backend")
    parser.add_argument("--font-name", default="SimSun", help="DOCX font name")
    parser.add_argument("--font-size", type=float, default=10.0, help="DOCX default font size")
    parser.add_argument("--min-font-size", type=float, default=2.0, help="DOCX min font size")
    parser.add_argument("--geometry-source", choices=["auto", "parsing", "layout-hybrid"], default="auto")
    return parser.parse_args()


def _normalize_text(s: str) -> str:
    return " ".join((s or "").replace("\u3002", ".").replace("\n", " ").split()).lower()


def _unique_bbox_count(blocks: list[Any], labels: set[str]) -> int:
    seen = set()
    for b in blocks:
        if str(getattr(b, "label", "")).lower() in labels:
            key = tuple(round(float(v), 1) for v in getattr(b, "bbox", []))
            seen.add(key)
    return len(seen)


def _docx_xml_counts(path: Path) -> dict[str, int]:
    with zipfile.ZipFile(path) as zf:
        xml = zf.read("word/document.xml").decode("utf-8", errors="ignore")
    return {
        "w_tbl_xml_count": xml.count("<w:tbl>"),
        "v_textbox_xml_count": xml.count("<v:textbox"),
        "v_imagedata_xml_count": xml.count("<v:imagedata"),
    }


def _load_selected_blocks(raw_path: Path, engine: str, input_pdf: Path, geometry_source: str) -> tuple[list[Any], str, list[str]]:
    payload = json.loads(raw_path.read_text(encoding="utf-8"))
    pages, provider_kind = edt._load_engine_pages(payload, engine, raw_json_path=raw_path)
    src_doc = fitz.open(str(input_pdf))
    blocks: list[Any] = []
    selected_geometry: list[str] = []
    try:
        for page_index, page_item in enumerate(pages[: len(src_doc)]):
            rect = src_doc[page_index].rect
            page_blocks, page_geometry, _, _, _ = edt._page_blocks(
                page_item=page_item,
                provider_kind=provider_kind,
                geometry_source=geometry_source,
                rect=rect,
            )
            blocks.extend(page_blocks)
            selected_geometry.append(page_geometry)
    finally:
        src_doc.close()
    return blocks, provider_kind, selected_geometry


def _run_opendataloader(input_pdf: Path, output_dir: Path, args: argparse.Namespace) -> dict[str, Any]:
    sys.path.insert(0, args.odl_py_path)
    os.environ["PATH"] = f"{args.odl_java_bin}:{os.environ.get('PATH', '')}"
    os.environ["HF_ENDPOINT"] = args.odl_hf_endpoint
    import opendataloader_pdf  # type: ignore

    output_dir.mkdir(parents=True, exist_ok=True)
    opendataloader_pdf.convert(
        input_path=[str(input_pdf)],
        output_dir=str(output_dir),
        format="markdown,json,html",
        hybrid="docling-fast",
        hybrid_mode="full",
        hybrid_url=args.odl_hybrid_url,
    )
    src_json = output_dir / f"{input_pdf.stem}.json"
    return json.loads(src_json.read_text(encoding="utf-8"))


def _write_summary_markdown(output_path: Path, input_pdf: Path, results: dict[str, Any]) -> None:
    ref_engine = "paddleocr-vl" if "paddleocr-vl" in results else ENGINES[0]
    lines = [
        f"# {input_pdf.stem} 三路 OCR + DOCX 对比总结",
        "",
        f"测试文件：`{input_pdf}`",
        "",
        "## 说明",
        "",
        "- 该“识别率”是工程代理指标，不是带标注真值的严格 OCR accuracy。",
        f"- 计算口径：以 `{ref_engine}` 的规范化文本为参考，文本相似度权重 80%，表格覆盖 15%，图片覆盖 5%。",
        "",
        "## 结果",
        "",
        f"| 方法 | OCR耗时(s) | DOCX耗时(s) | 代理识别率(%) | 文本相似度到 {ref_engine}(%) | 文本字符数 | 表格数 | 图片数 | DOCX文本框 |",
        "|---|---:|---:|---:|---:|---:|---:|---:|---:|",
    ]
    for engine in ENGINES:
        meta = results[engine]
        lines.append(
            f"| {engine} | {meta['ocr_seconds']:.3f} | {meta['docx_seconds']:.3f} | {meta['ocr_proxy_rate']:.2f} | "
            f"{meta['text_similarity_to_ref']:.2f} | {meta['text_chars']} | {meta['table_count']} | "
            f"{meta['image_count']} | {meta['v_textbox_xml_count']} |"
        )
    output_path.write_text("\n".join(lines) + "\n", encoding="utf-8")


def main() -> None:
    args = _parse_args()
    input_pdf = Path(args.input_pdf).expanduser().resolve()
    output_root = Path(args.output_root).expanduser().resolve()
    raw_dir = output_root / "raw"
    docx_dir = output_root / "docx"
    odl_tmp_dir = raw_dir / "opendataloader_hybrid_full_out"
    raw_dir.mkdir(parents=True, exist_ok=True)
    docx_dir.mkdir(parents=True, exist_ok=True)

    results: dict[str, Any] = {}
    translator = Translator(enabled=False, source_lang="zh", target_lang="en")

    ocr_jobs = {
        "paddleocr-vl": lambda: _call_vl(args.vl_api_base, input_pdf),
        "mineru": lambda: _call_mineru(args.mineru_api_base, input_pdf),
        "dotsocr": lambda: _call_dotsocr(args.dotsocr_api_base, input_pdf, args.dotsocr_model, args.dotsocr_prompt),
        # "opendataloader-hybrid-full": lambda: _run_opendataloader(input_pdf, odl_tmp_dir, args),
    }

    for engine in ENGINES:
        t0 = time.perf_counter()
        payload = ocr_jobs[engine]()
        ocr_seconds = time.perf_counter() - t0
        raw_path = raw_dir / f"{input_pdf.stem}_{engine}_raw.json"
        raw_path.write_text(json.dumps(payload, ensure_ascii=False, indent=2), encoding="utf-8")
        if engine == "opendataloader-hybrid-full":
            image_src = odl_tmp_dir / f"{input_pdf.stem}_images"
            image_dst = raw_dir / f"{input_pdf.stem}_images"
            if image_dst.exists():
                shutil.rmtree(image_dst)
            if image_src.exists():
                shutil.copytree(image_src, image_dst)
        results[engine] = {
            "ocr_seconds": round(ocr_seconds, 3),
            "raw_json_path": str(raw_path),
        }
        print(f"[OCR] {engine}: {ocr_seconds:.3f}s")

    texts: dict[str, str] = {}
    for engine in ENGINES:
        raw_path = Path(results[engine]["raw_json_path"])
        blocks, provider_kind, selected_geometry = _load_selected_blocks(raw_path, engine, input_pdf, args.geometry_source)
        text = "\n".join((b.text or "").strip() for b in blocks if (b.text or "").strip())
        texts[engine] = _normalize_text(text)
        results[engine].update(
            {
                "provider_kind": provider_kind,
                "selected_geometry": selected_geometry,
                "block_count": len(blocks),
                "text_chars": len(texts[engine]),
                "table_count": _unique_bbox_count(blocks, {"table", "table_body"}),
                "image_count": _unique_bbox_count(blocks, {"image", "image_body", "picture", "figure", "chart"}),
            }
        )

    ref_engine = "paddleocr-vl" if "paddleocr-vl" in results else ENGINES[0]
    ref_text = texts[ref_engine]
    ref_tables = max(results[ref_engine]["table_count"], 1)
    ref_images = max(results[ref_engine]["image_count"], 1)
    for engine in ENGINES:
        ratio = difflib.SequenceMatcher(None, texts[engine], ref_text).ratio() if ref_text else 0.0
        table_score = min(results[engine]["table_count"] / ref_tables, 1.0)
        image_score = min(results[engine]["image_count"] / ref_images, 1.0)
        proxy = 0.8 * ratio + 0.15 * table_score + 0.05 * image_score
        results[engine]["text_similarity_to_ref"] = round(ratio * 100.0, 2)
        results[engine]["ocr_proxy_rate"] = round(proxy * 100.0, 2)

    for engine in ENGINES:
        raw_path = Path(results[engine]["raw_json_path"])
        payload = json.loads(raw_path.read_text(encoding="utf-8"))
        output_docx = docx_dir / f"{input_pdf.stem}_{engine}_visual_clone.docx"
        t0 = time.perf_counter()
        summary = edt._export_single_docx(
            payload=payload,
            engine=engine,
            raw_json_path=raw_path,
            input_pdf=input_pdf,
            output_docx=output_docx,
            geometry_source=args.geometry_source,
            with_page_background=False,
            font_name=args.font_name,
            font_size=args.font_size,
            min_font_size=args.min_font_size,
            text_box_extra_width_pt=2.0,
            text_box_extra_height_pt=1.0,
            translator=translator,
        )
        docx_seconds = time.perf_counter() - t0
        results[engine]["docx_seconds"] = round(docx_seconds, 3)
        results[engine]["docx_path"] = str(output_docx)
        results[engine]["docx_summary"] = summary
        results[engine].update(_docx_xml_counts(output_docx))
        print(f"[DOCX] {engine}: {docx_seconds:.3f}s")

    summary_json = output_root / "benchmark_results.json"
    summary_md = output_root / f"{input_pdf.stem}_三路OCR_DXOC对比总结.md"
    summary_json.write_text(json.dumps(results, ensure_ascii=False, indent=2), encoding="utf-8")
    _write_summary_markdown(summary_md, input_pdf, results)
    print(f"Saved: {summary_json}")
    print(f"Saved: {summary_md}")


if __name__ == "__main__":
    main()
