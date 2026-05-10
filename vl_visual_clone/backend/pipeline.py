import base64
import json
import os
import re
import sys
import textwrap
from dataclasses import dataclass
from pathlib import Path
from typing import Any

import fitz
import requests

from translator import Translator

THIRD_PARTY_DOTS_OCR_DIR = Path(__file__).resolve().parent.parent / "third_party" / "dots.ocr"
if THIRD_PARTY_DOTS_OCR_DIR.exists():
    dots_ocr_path = str(THIRD_PARTY_DOTS_OCR_DIR)
    if dots_ocr_path not in sys.path:
        sys.path.insert(0, dots_ocr_path)

try:
    from dots_ocr.parser import DotsOCRParser
except Exception:  # noqa: BLE001
    DotsOCRParser = None


@dataclass
class Block:
    bbox: list[float]
    label: str
    order: float
    text: str
    image_ref: str | None = None


def _safe_bbox(v: Any) -> list[float] | None:
    if not isinstance(v, list) or len(v) != 4:
        return None
    out = []
    for x in v:
        if x is None:
            return None
        try:
            out.append(float(x))
        except Exception:
            return None
    return out


def _call_vl(api_base: str, input_pdf: Path) -> dict[str, Any]:
    payload = {
        "file": base64.b64encode(input_pdf.read_bytes()).decode("ascii"),
        "fileType": 0,
        "useDocOrientationClassify": False,
        "useDocUnwarping": False,
        "useLayoutDetection": True,
        "formatBlockContent": True,
    }
    resp = requests.post(f"{api_base.rstrip('/')}/layout-parsing", json=payload, timeout=600)
    resp.raise_for_status()
    return resp.json()


def _post_json_with_fallback_endpoints(api_base: str, endpoints: list[str], payload: dict[str, Any], timeout: int = 600) -> dict[str, Any]:
    base = api_base.rstrip("/")
    last_error = None
    for ep in endpoints:
        url = f"{base}{ep}"
        try:
            resp = requests.post(url, json=payload, timeout=timeout)
            if resp.status_code >= 400:
                last_error = RuntimeError(f"{url} returned HTTP {resp.status_code}: {resp.text[:400]}")
                continue
            data = resp.json()
            if isinstance(data, dict):
                return data
            return {"result": data}
        except Exception as e:  # noqa: BLE001
            last_error = e
    if last_error:
        raise RuntimeError(f"Failed to call provider API at {api_base}: {last_error}")
    raise RuntimeError(f"Failed to call provider API at {api_base}")


def _call_mineru(mineru_api_base: str, input_pdf: Path) -> dict[str, Any]:
    if not mineru_api_base.strip():
        raise RuntimeError("MinerU API base is empty. Please set mineruApiBase.")
    url = f"{mineru_api_base.rstrip('/')}/file_parse"
    files = {"files": (input_pdf.name, input_pdf.read_bytes(), "application/pdf")}
    form = {
        "backend": "pipeline",
        "parse_method": "auto",
        "return_content_list": "true",
        "return_middle_json": "true",
        "return_md": "true",
        "response_format_zip": "false",
    }
    resp = requests.post(url, files=files, data=form, timeout=1800)
    resp.raise_for_status()
    data = resp.json()
    if isinstance(data, dict) and str(data.get("status", "")).lower() == "failed":
        raise RuntimeError(f"MinerU parse failed: {data.get('error') or data}")
    if not isinstance(data, dict):
        return {"result": data}
    return data


def _extract_json_from_text(raw_text: str) -> Any:
    s = (raw_text or "").strip()
    if not s:
        return {}
    if s.startswith("```"):
        s = re.sub(r"^```[a-zA-Z0-9_-]*", "", s).strip()
        if s.endswith("```"):
            s = s[:-3].strip()
    try:
        return json.loads(s)
    except Exception:
        pass

    # Heuristic recovery for truncated DotsOCR JSON arrays.
    # It extracts objects like: {"bbox":[...],"category":"...","text":"..."}
    rec = re.compile(
        r'\{"bbox"\s*:\s*\[(?P<bbox>[^\]]+)\]\s*,\s*"category"\s*:\s*"(?P<cat>[^"]+)"(?:\s*,\s*"text"\s*:\s*"(?P<txt>(?:\\.|[^"\\])*)")?\s*\}',
        flags=re.DOTALL,
    )
    recovered = []
    for m in rec.finditer(s):
        nums = [x.strip() for x in m.group("bbox").split(",")]
        if len(nums) != 4:
            continue
        try:
            bbox = [float(v) for v in nums]
        except Exception:
            continue
        txt = m.group("txt") or ""
        txt = txt.encode("utf-8").decode("unicode_escape") if txt else ""
        recovered.append({"bbox": bbox, "category": m.group("cat"), "text": txt})
    if recovered:
        return recovered

    # Try to locate a JSON object/array in mixed text.
    first_obj = s.find("{")
    first_arr = s.find("[")
    candidates = [x for x in [first_obj, first_arr] if x >= 0]
    if not candidates:
        return {"text": raw_text}
    start = min(candidates)
    sub = s[start:]
    for end in range(len(sub), max(0, len(sub) - 4000), -1):
        part = sub[:end]
        try:
            return json.loads(part)
        except Exception:
            continue
    return {"text": raw_text}


def _call_dotsocr(dotsocr_api_base: str, input_pdf: Path, model: str, prompt: str) -> dict[str, Any]:
    if not dotsocr_api_base.strip():
        raise RuntimeError("DotsOCR API base is empty. Please set dotsocrApiBase.")
    prompt_mode = prompt.strip() or "prompt_layout_all_en"
    if DotsOCRParser is not None:
        m = re.match(r"^https?://([^/:]+)(?::(\d+))?$", dotsocr_api_base.strip().rstrip("/"))
        if m:
            host = m.group(1)
            port = int(m.group(2) or 80)
            output_dir = Path("/tmp/dotsocr_parser_output") / input_pdf.stem
            output_dir.mkdir(parents=True, exist_ok=True)
            parser = DotsOCRParser(
                protocol="http",
                ip=host,
                port=port,
                model_name=model,
                temperature=0.1,
                top_p=0.9,
                max_completion_tokens=32768,
                num_thread=8,
                dpi=200,
                output_dir=str(output_dir),
                use_hf=False,
            )
            results = parser.parse_file(
                str(input_pdf),
                output_dir=str(output_dir),
                prompt_mode=prompt_mode,
                fitz_preprocess=False,
            )
            pages = []
            for item in results:
                page_no = int(item.get("page_no", len(pages)))
                layout_info_path = item.get("layout_info_path")
                md_content_path = item.get("md_content_path")
                layout_info = []
                md_content = ""
                if isinstance(layout_info_path, str) and layout_info_path.strip() and Path(layout_info_path).exists():
                    try:
                        layout_info = json.loads(Path(layout_info_path).read_text(encoding="utf-8"))
                    except Exception:
                        layout_info = []
                if isinstance(md_content_path, str) and md_content_path.strip() and Path(md_content_path).exists():
                    try:
                        md_content = Path(md_content_path).read_text(encoding="utf-8")
                    except Exception:
                        md_content = ""
                pages.append(
                    {
                        "page": page_no + 1,
                        "result": layout_info,
                        "markdown": md_content,
                        "raw": item,
                    }
                )
            if pages:
                return {"pages": pages, "mode": "official_parser"}

    base = dotsocr_api_base.rstrip("/")
    api_url = f"{base}/v1/chat/completions"
    doc = fitz.open(str(input_pdf))
    page_results: list[dict[str, Any]] = []
    for i in range(len(doc)):
        page = doc[i]
        # Use 200 DPI to align with official parser defaults and improve small-text recall.
        pix = page.get_pixmap(dpi=200, alpha=False)
        b64 = base64.b64encode(pix.tobytes("png")).decode("ascii")
        payload = {
            "model": model,
            "messages": [
                {
                    "role": "user",
                    "content": [
                        {"type": "image_url", "image_url": {"url": f"data:image/png;base64,{b64}"}},
                        {"type": "text", "text": f"<|img|><|imgpad|><|endofimg|>{prompt_mode}"},
                    ],
                }
            ],
            "temperature": 0.1,
            "top_p": 0.9,
            "max_completion_tokens": 32768,
        }
        resp = requests.post(api_url, json=payload, timeout=1800)
        resp.raise_for_status()
        data = resp.json()
        content = (
            data.get("choices", [{}])[0]
            .get("message", {})
            .get("content", "")
            if isinstance(data, dict)
            else ""
        )
        parsed = _extract_json_from_text(str(content))
        page_results.append({"page": i + 1, "result": parsed, "raw": data})
    doc.close()
    return {"pages": page_results}


def _extract_pages(vl_json: Any) -> list[dict[str, Any]]:
    if isinstance(vl_json, dict):
        result = vl_json.get("result")
        if isinstance(result, dict):
            lpr = result.get("layoutParsingResults")
            if isinstance(lpr, list):
                return [p for p in lpr if isinstance(p, dict)]
        if isinstance(result, list):
            return [p for p in result if isinstance(p, dict)]
    if isinstance(vl_json, list):
        return [p for p in vl_json if isinstance(p, dict)]
    return []


def _parse_bbox_from_any(v: Any) -> list[float] | None:
    if isinstance(v, list) and len(v) == 4:
        return _safe_bbox(v)
    if isinstance(v, dict):
        for k in ("bbox", "box", "coordinate", "rect"):
            bb = _parse_bbox_from_any(v.get(k))
            if bb:
                return bb
    return None


def _extract_generic_page_blocks(page_obj: Any) -> list[Block]:
    blocks: list[Block] = []
    non_text_labels = {
        "picture",
        "image",
        "image_body",
        "figure",
        "chart",
        "table",
        "table_body",
        "formula",
        "seal",
        "caption",
    }

    def walk(obj: Any, order_seed: float = 0.0) -> None:
        if isinstance(obj, dict):
            bbox = _parse_bbox_from_any(obj)
            text = obj.get("text") or obj.get("content") or obj.get("block_content") or ""
            label = obj.get("label") or obj.get("type") or obj.get("category") or obj.get("block_label") or "text"
            image_ref = obj.get("image_ref") or obj.get("img_ref")
            normalized_label = str(label).strip().lower()
            keep_non_text = normalized_label in non_text_labels
            if bbox and (str(text).strip() or image_ref or keep_non_text):
                blocks.append(
                    Block(
                        bbox=bbox,
                        label=str(label),
                        order=float(obj.get("order") if isinstance(obj.get("order"), (int, float)) else order_seed),
                        text=_clean_text(str(text)),
                        image_ref=str(image_ref) if image_ref else None,
                    )
                )
            for i, v in enumerate(obj.values()):
                walk(v, order_seed + i / 1000.0)
        elif isinstance(obj, list):
            for i, v in enumerate(obj):
                walk(v, order_seed + i / 1000.0)

    walk(page_obj, 0.0)
    blocks.sort(key=lambda b: (b.order, b.bbox[1], b.bbox[0]))

    # Deduplicate near-identical entries from recursive extraction.
    dedup: list[Block] = []
    seen = set()
    for b in blocks:
        key = (round(b.bbox[0], 1), round(b.bbox[1], 1), round(b.bbox[2], 1), round(b.bbox[3], 1), b.label, b.text[:120])
        if key in seen:
            continue
        seen.add(key)
        dedup.append(b)

    if dedup:
        return dedup

    # Fallback for providers that return only text/markdown without explicit bboxes.
    texts: list[str] = []

    def collect_text(obj: Any) -> None:
        if isinstance(obj, dict):
            for k, v in obj.items():
                lk = str(k).lower()
                if lk in {"text", "content", "markdown", "md", "result_text"} and isinstance(v, str):
                    s = _clean_text(v)
                    if s:
                        texts.append(s)
                else:
                    collect_text(v)
        elif isinstance(obj, list):
            for it in obj:
                collect_text(it)

    collect_text(page_obj)
    merged = "\n\n".join(t for t in texts if t.strip())
    if not merged.strip():
        return []

    # Use normalized coordinates as a generic text-flow fallback.
    lines = [ln.strip() for ln in merged.split("\n") if ln.strip()]
    if not lines:
        return []
    out: list[Block] = []
    top = 60.0
    line_h = 24.0
    x0, x1 = 60.0, 740.0
    for i, ln in enumerate(lines[:200]):
        y0 = top + i * line_h
        y1 = y0 + line_h
        out.append(Block(bbox=[x0, y0, x1, y1], label="text", order=float(i), text=ln))
    return out


def _extract_generic_pages(provider_json: Any) -> list[dict[str, Any]]:
    pages: list[dict[str, Any]] = []
    if isinstance(provider_json, dict):
        for k in ("pages", "result", "data"):
            v = provider_json.get(k)
            if isinstance(v, list):
                for p in v:
                    blocks = _extract_generic_page_blocks(p)
                    if blocks:
                        pages.append({"blocks": blocks, "raw": p})
                if pages:
                    return pages
            if isinstance(v, dict):
                sub = v.get("pages")
                if isinstance(sub, list):
                    for p in sub:
                        blocks = _extract_generic_page_blocks(p)
                        if blocks:
                            pages.append({"blocks": blocks, "raw": p})
                    if pages:
                        return pages
        blocks = _extract_generic_page_blocks(provider_json)
        if blocks:
            return [{"blocks": blocks, "raw": provider_json}]
    if isinstance(provider_json, list):
        for p in provider_json:
            blocks = _extract_generic_page_blocks(p)
            if blocks:
                pages.append({"blocks": blocks, "raw": p})
    return pages


def _mineru_collect_line_text(line_obj: dict[str, Any]) -> str:
    spans = line_obj.get("spans")
    parts: list[str] = []
    if isinstance(spans, list):
        for span in spans:
            if not isinstance(span, dict):
                continue
            if bool(span.get("cross_page")):
                continue
            content = _clean_text(str(span.get("content") or span.get("text") or ""))
            if content:
                parts.append(content)
    if parts:
        return "".join(parts)
    return _clean_text(str(line_obj.get("content") or line_obj.get("text") or ""))


def _merge_mineru_paragraph_lines(lines: list[str]) -> str:
    # MinerU 原始行分割偏密；这里重排成“适中换行”：
    # 1) 相邻两行优先合并，2) 同一行最大长度受限，避免无换行或换行过密。
    cleaned = [re.sub(r"\s+", " ", (s or "").strip()) for s in lines if (s or "").strip()]
    if not cleaned:
        return ""

    chunks: list[str] = []
    cur = ""
    cur_line_count = 0
    for ln in cleaned:
        if not cur:
            cur = ln
            cur_line_count = 1
            continue

        # 每段内大致保留“2个原始行”的信息量，并给长度上限。
        if cur_line_count < 2 and (len(cur) + len(ln)) <= 110:
            cur += ln
            cur_line_count += 1
        else:
            chunks.append(cur)
            cur = ln
            cur_line_count = 1

    if cur:
        chunks.append(cur)

    merged = "\n".join(chunks).strip()
    # 中文语境下尽量去除汉字之间多余空格，避免“字词被空格打散”。
    merged = re.sub(r"([\u4e00-\u9fff])\s+([\u4e00-\u9fff])", r"\1\2", merged)
    return merged


def _extract_mineru_page_blocks(page_obj: dict[str, Any]) -> list[Block]:
    candidates = page_obj.get("para_blocks")
    if not isinstance(candidates, list) or not candidates:
        candidates = page_obj.get("preproc_blocks")
    if not isinstance(candidates, list) or not candidates:
        # Fallback to generic recursive extraction when structured lists are missing.
        return _extract_generic_page_blocks(page_obj)

    blocks: list[Block] = []
    for idx, item in enumerate(candidates):
        if not isinstance(item, dict):
            continue
        if bool(item.get("cross_page")):
            continue

        bbox = _parse_bbox_from_any(item.get("bbox") or item.get("bbox_fs") or item.get("bounding box"))
        if not bbox:
            continue

        label = str(item.get("type") or item.get("label") or "text").strip().lower()
        lines = item.get("lines")
        order = float(item.get("index") if isinstance(item.get("index"), (int, float)) else idx)

        # 段级聚合：将同段的行文本合并，避免每行变成短段导致可读性下降。
        merged_lines: list[str] = []
        if isinstance(lines, list):
            for line in lines:
                if not isinstance(line, dict):
                    continue
                if bool(line.get("cross_page")):
                    continue
                t = _mineru_collect_line_text(line)
                if t:
                    merged_lines.append(t)

        text = _merge_mineru_paragraph_lines(merged_lines)
        if not text:
            text = _clean_text(str(item.get("text") or item.get("content") or ""))
            text = _merge_mineru_paragraph_lines(text.split("\n"))

        if not text and label not in {"table", "table_body", "image", "image_body", "picture", "figure", "chart"}:
            continue

        blocks.append(
            Block(
                bbox=bbox,
                label=label,
                order=order,
                text=text,
            )
        )

    blocks.sort(key=lambda b: (b.order, b.bbox[1], b.bbox[0]))
    return blocks


def _extract_mineru_pages(provider_json: dict[str, Any]) -> list[dict[str, Any]]:
    pages: list[dict[str, Any]] = []
    if not isinstance(provider_json, dict):
        return pages
    results = provider_json.get("results")
    if not isinstance(results, dict):
        return pages

    for _, item in results.items():
        if not isinstance(item, dict):
            continue
        middle_json_raw = item.get("middle_json")
        parsed_middle = None
        if isinstance(middle_json_raw, str) and middle_json_raw.strip():
            try:
                parsed_middle = json.loads(middle_json_raw)
            except Exception:
                parsed_middle = _extract_json_from_text(middle_json_raw)
        elif isinstance(middle_json_raw, dict):
            parsed_middle = middle_json_raw

        if isinstance(parsed_middle, dict):
            pdf_info = parsed_middle.get("pdf_info")
            if isinstance(pdf_info, list):
                for p in pdf_info:
                    if not isinstance(p, dict):
                        continue
                    blocks = _extract_mineru_page_blocks(p)
                    if blocks:
                        pages.append({"blocks": blocks, "raw": p})

        if not pages:
            md = str(item.get("md_content", "")).strip()
            if md:
                pages.append({"blocks": _extract_generic_page_blocks({"text": md}), "raw": item})

    return pages


def _clean_text(text: str) -> str:
    s = text or ""
    s = s.replace("\r\n", "\n").replace("\r", "\n")
    s = re.sub(r"<br\\s*/?>", "\n", s, flags=re.IGNORECASE)
    s = re.sub(r"</tr>", "\n", s, flags=re.IGNORECASE)
    s = re.sub(r"</td>\\s*<td[^>]*>", "\t", s, flags=re.IGNORECASE)
    s = re.sub(r"<img[^>]*>", "", s)
    s = re.sub(r"<[^>]+>", "", s)
    s = re.sub(r"\n{3,}", "\n\n", s)
    return s.strip()


def _restore_form_layout(text: str, strength: float = 1.0) -> str:
    s = (text or "").strip()
    if not s:
        return s
    if strength <= 0:
        return s
    # Recover common blank fields in Chinese form-like documents.
    s = s.replace("名称为专利号为", "名称为________\n专利号为________")
    s = s.replace("名称为申请号或专利号为", "名称为________\n申请号或专利号为____________")
    s = s.replace("专利号为 的专利权评价报告", "专利号为____________的专利权评价报告")
    s = s.replace("申请号或专利号为 的中止程序请求", "申请号或专利号为____________的中止程序请求")
    s = s.replace("申请号或专利号为）", "申请号或专利号为____________）")
    if strength >= 1.5:
        s = s.replace("代为办理名称为", "代为办理名称为________\n")
    return s


def _extract_img_src(html: str) -> str | None:
    m = re.search(r'<img[^>]+src="([^"]+)"', html or "", flags=re.IGNORECASE)
    return m.group(1) if m else None


def _bbox_from_img_ref(image_ref: str | None) -> list[float] | None:
    if not image_ref:
        return None
    m = re.search(r"_(\d+)_(\d+)_(\d+)_(\d+)\.[A-Za-z0-9]+$", image_ref)
    if not m:
        return None
    x1, y1, x2, y2 = [float(m.group(i)) for i in range(1, 5)]
    if x2 <= x1 or y2 <= y1:
        return None
    return [x1, y1, x2, y2]


def _choose_cjk_fontfile() -> str | None:
    candidates = [
        "/usr/share/fonts/opentype/noto/NotoSansCJK-Regular.ttc",
        "/usr/share/fonts/opentype/noto/NotoSerifCJK-Regular.ttc",
        "/usr/share/fonts/truetype/noto/NotoSansCJK-Regular.ttc",
        "/usr/share/fonts/truetype/wqy/wqy-zenhei.ttc",
        "/usr/share/fonts/truetype/wqy/wqy-microhei.ttc",
    ]
    for p in candidates:
        if Path(p).exists():
            return p
    return None


def _is_text_label(label: str) -> bool:
    return label in {"text", "paragraph_title", "doc_title", "footer", "header", "aside_text"}


def _iou(a: list[float], b: list[float]) -> float:
    ax1, ay1, ax2, ay2 = [float(v) for v in a]
    bx1, by1, bx2, by2 = [float(v) for v in b]
    ix1, iy1 = max(min(ax1, ax2), min(bx1, bx2)), max(min(ay1, ay2), min(by1, by2))
    ix2, iy2 = min(max(ax1, ax2), max(bx1, bx2)), min(max(ay1, ay2), max(by1, by2))
    inter = max(0.0, ix2 - ix1) * max(0.0, iy2 - iy1)
    if inter <= 0:
        return 0.0
    area_a = abs((ax2 - ax1) * (ay2 - ay1))
    area_b = abs((bx2 - bx1) * (by2 - by1))
    union = area_a + area_b - inter
    return inter / union if union > 0 else 0.0


def _center_y(b: list[float]) -> float:
    return (float(b[1]) + float(b[3])) / 2.0


def _split_chunks(parsing_blocks: list[dict[str, Any]]) -> list[dict[str, Any]]:
    chunks = []
    cid = 0
    for b in parsing_blocks:
        raw = str(b.get("block_content", ""))
        txt = _clean_text(raw)
        if not txt:
            continue
        bbox = _safe_bbox(b.get("block_bbox"))
        if not bbox:
            continue
        order = float(b.get("block_order", 1e9)) if isinstance(b.get("block_order"), (int, float)) else 1e9
        label = str(b.get("block_label", "text"))
        if label == "table":
            lines = [ln.strip() for ln in txt.split("\n") if ln.strip()]
            h = max(1.0, bbox[3] - bbox[1])
            for i, line in enumerate(lines):
                y1 = bbox[1] + h * (i / max(1, len(lines)))
                y2 = bbox[1] + h * ((i + 1) / max(1, len(lines)))
                chunks.append({"id": cid, "text": line, "bbox": [bbox[0], y1, bbox[2], y2], "order": order + i / 1000.0})
                cid += 1
        else:
            chunks.append({"id": cid, "text": txt, "bbox": bbox, "order": order})
            cid += 1
    return chunks


def _build_hybrid_blocks(page_item: dict[str, Any], keep_unmatched_chunks: bool = True) -> list[Block]:
    pruned = page_item.get("prunedResult", {})
    parsing = [b for b in pruned.get("parsing_res_list", []) if isinstance(b, dict) and _safe_bbox(b.get("block_bbox"))]
    parsing.sort(
        key=lambda x: (
            x.get("block_order") if isinstance(x.get("block_order"), (int, float)) else 1e9,
            x.get("block_id") if isinstance(x.get("block_id"), (int, float)) else 1e9,
        )
    )

    layout_boxes = [b for b in pruned.get("layout_det_res", {}).get("boxes", []) if isinstance(b, dict) and _safe_bbox(b.get("coordinate"))]
    layout_boxes.sort(key=lambda x: x.get("order") if isinstance(x.get("order"), (int, float)) else 1e9)

    chunks = _split_chunks(parsing)
    chunks_sorted = sorted(chunks, key=lambda c: c["order"])
    rank = {c["id"]: i for i, c in enumerate(chunks_sorted)}

    used = set()
    assigned = {}

    if layout_boxes and chunks_sorted:
        ys = [float(lb["coordinate"][1]) for lb in layout_boxes] + [float(lb["coordinate"][3]) for lb in layout_boxes]
        page_h = max(1.0, max(ys) - min(ys))
        text_layout = [lb for lb in layout_boxes if _is_text_label(str(lb.get("label", "text")))]
        for li, lb in enumerate(text_layout):
            lbox = _safe_bbox(lb.get("coordinate"))
            if not lbox:
                continue
            lrank = li / max(1, len(text_layout) - 1)
            best_id = None
            best_score = -1.0
            for c in chunks_sorted:
                if c["id"] in used:
                    continue
                iou = _iou(lbox, c["bbox"])
                ydist = min(1.0, abs(_center_y(lbox) - _center_y(c["bbox"])) / page_h)
                crank = rank[c["id"]] / max(1, len(chunks_sorted) - 1)
                odist = min(1.0, abs(lrank - crank))
                score = 0.62 * iou + 0.25 * (1 - ydist) + 0.13 * (1 - odist)
                if ydist > 0.55 and iou < 0.01:
                    score -= 0.35
                if score > best_score:
                    best_score = score
                    best_id = c["id"]
            if best_id is not None and best_score >= 0.10:
                used.add(best_id)
                assigned[id(lb)] = next(c["text"] for c in chunks_sorted if c["id"] == best_id)

    blocks: list[Block] = []
    for lb in layout_boxes:
        label = str(lb.get("label", "text"))
        bbox = _safe_bbox(lb.get("coordinate"))
        if not bbox:
            continue
        text = assigned.get(id(lb), "") if _is_text_label(label) else ""
        order = lb.get("order") if isinstance(lb.get("order"), (int, float)) else 1e9
        blocks.append(Block(bbox=bbox, label=label, order=float(order), text=text))

    for pb in parsing:
        raw = str(pb.get("block_content", ""))
        img_ref = _extract_img_src(raw)
        if img_ref:
            blocks.append(
                Block(
                    bbox=_bbox_from_img_ref(img_ref) or _safe_bbox(pb.get("block_bbox")) or [0.0, 0.0, 0.0, 0.0],
                    label=str(pb.get("block_label", "seal")),
                    order=float(pb.get("block_order") if isinstance(pb.get("block_order"), (int, float)) else 1e9),
                    text="",
                    image_ref=img_ref,
                )
            )

    if keep_unmatched_chunks and chunks_sorted:
        used_ids = set(used)
        for c in chunks_sorted:
            if c["id"] in used_ids:
                continue
            # Append unmatched chunk as low-priority text block to avoid recall loss.
            blocks.append(
                Block(
                    bbox=c["bbox"],
                    label="text",
                    order=float(c["order"]) + 10000.0,
                    text=c["text"],
                )
            )

    blocks.sort(key=lambda b: (b.order, b.bbox[1], b.bbox[0]))
    return blocks


def _build_parsing_blocks(page_item: dict[str, Any]) -> list[Block]:
    pruned = page_item.get("prunedResult", {})
    raw_blocks = [b for b in pruned.get("parsing_res_list", []) if isinstance(b, dict) and _safe_bbox(b.get("block_bbox"))]
    blocks: list[Block] = []
    for b in raw_blocks:
        raw = str(b.get("block_content", ""))
        bb = _safe_bbox(b.get("block_bbox"))
        if not bb:
            continue
        order = b.get("block_order") if isinstance(b.get("block_order"), (int, float)) else 1e9
        blocks.append(
            Block(
                bbox=bb,
                label=str(b.get("block_label", "text")),
                order=float(order),
                text=_clean_text(raw),
                image_ref=_extract_img_src(raw),
            )
        )
    blocks.sort(key=lambda x: (x.order, x.bbox[1], x.bbox[0]))
    return blocks


def _page_quality_metrics(blocks: list[Block], rect: fitz.Rect, sx: float, sy: float) -> dict[str, float]:
    text_boxes: list[list[float]] = []
    text_chars = 0
    overflow_sum = 0.0
    overflow_count = 0

    for b in blocks:
        txt = (b.text or "").strip()
        if not txt:
            continue
        text_chars += len(txt)
        ox0, oy0, ox1, oy1 = b.bbox[0] * sx, b.bbox[1] * sy, b.bbox[2] * sx, b.bbox[3] * sy
        raw_area = max(0.0, (ox1 - ox0) * (oy1 - oy0))
        cx0 = max(0.0, ox0)
        cy0 = max(0.0, oy0)
        cx1 = min(rect.width, ox1)
        cy1 = min(rect.height, oy1)
        clip_area = max(0.0, (cx1 - cx0) * (cy1 - cy0))

        if raw_area > 1e-6:
            overflow = max(0.0, 1.0 - clip_area / raw_area)
            overflow_sum += overflow
            if overflow > 0.01:
                overflow_count += 1

        if clip_area > 1.0:
            text_boxes.append([cx0, cy0, cx1, cy1])

    overlap_pairs = 0
    pair_count = 0
    for i in range(len(text_boxes)):
        for j in range(i + 1, len(text_boxes)):
            pair_count += 1
            if _iou(text_boxes[i], text_boxes[j]) > 0.35:
                overlap_pairs += 1

    overlap_rate = overlap_pairs / pair_count if pair_count > 0 else 0.0
    overflow_rate = overflow_sum / max(1, len(text_boxes))
    overflow_block_rate = overflow_count / max(1, len(text_boxes))

    return {
        "textChars": float(text_chars),
        "textBlocks": float(len(text_boxes)),
        "overlapRate": overlap_rate,
        "overflowRate": overflow_rate,
        "overflowBlockRate": overflow_block_rate,
    }


def _choose_blocks_auto(page_item: dict[str, Any], rect: fitz.Rect, sx: float, sy: float) -> tuple[list[Block], str, dict[str, Any]]:
    parsing_blocks = _build_parsing_blocks(page_item)
    hybrid_blocks = _build_hybrid_blocks(page_item, keep_unmatched_chunks=True)

    parsing_metrics = _page_quality_metrics(parsing_blocks, rect, sx, sy)
    hybrid_metrics = _page_quality_metrics(hybrid_blocks, rect, sx, sy)

    max_chars = max(parsing_metrics["textChars"], hybrid_metrics["textChars"], 1.0)

    def score(m: dict[str, float]) -> float:
        coverage = m["textChars"] / max_chars
        return 0.60 * coverage + 0.22 * (1.0 - m["overlapRate"]) + 0.18 * (1.0 - m["overflowRate"])

    score_parsing = score(parsing_metrics)
    score_hybrid = score(hybrid_metrics)

    # Prefer parsing on near-ties for stability.
    if score_hybrid > score_parsing + 0.01:
        return hybrid_blocks, "layout-hybrid", {
            "selected": "layout-hybrid",
            "score": {"parsing": score_parsing, "layout-hybrid": score_hybrid},
            "metrics": {"parsing": parsing_metrics, "layout-hybrid": hybrid_metrics},
        }
    return parsing_blocks, "parsing", {
        "selected": "parsing",
        "score": {"parsing": score_parsing, "layout-hybrid": score_hybrid},
        "metrics": {"parsing": parsing_metrics, "layout-hybrid": hybrid_metrics},
    }


def _resolve_image_bytes(image_ref: str | None, images_map: dict[str, Any]) -> bytes | None:
    if not image_ref:
        return None
    v = images_map.get(image_ref)
    if isinstance(v, bytes):
        return v
    if isinstance(v, str):
        s = v.strip()
        if not s:
            return None
        if s.startswith("data:"):
            _, _, payload = s.partition(",")
            if not payload:
                return None
            try:
                return base64.b64decode(payload)
            except Exception:
                return None
        if s.startswith("http://") or s.startswith("https://"):
            try:
                r = requests.get(s, timeout=30)
                if r.status_code == 200:
                    return r.content
            except Exception:
                return None
        # 超长字符串更可能是 base64，避免被 Path() 当成本地文件名触发 OSError。
        if len(s) < 512 and "\n" not in s and "\r" not in s:
            try:
                p = Path(s)
                if p.exists() and p.is_file():
                    try:
                        return p.read_bytes()
                    except Exception:
                        return None
            except OSError:
                return None
        try:
            return base64.b64decode(s)
        except Exception:
            return None
    return None


def _get_input_image_bytes(page_item: dict[str, Any]) -> bytes | None:
    src = page_item.get("inputImage")
    if not isinstance(src, str) or not src.strip():
        return None
    s = src.strip()
    if s.startswith("http://") or s.startswith("https://"):
        try:
            r = requests.get(s, timeout=30)
            if r.status_code == 200:
                return r.content
        except Exception:
            return None
        return None
    try:
        return base64.b64decode(s)
    except Exception:
        return None


def _get_input_image_size(page_item: dict[str, Any]) -> tuple[float, float] | None:
    raw = _get_input_image_bytes(page_item)
    if not raw:
        return None
    try:
        pix = fitz.Pixmap(raw)
        if pix.width > 0 and pix.height > 0:
            return float(pix.width), float(pix.height)
    except Exception:
        return None
    return None


def _fit_insert_text(
    page: fitz.Page,
    rect: fitz.Rect,
    text: str,
    pad: float,
    fontfile: str | None,
    min_font_size: float,
    line_height: float,
) -> bool:
    w = max(1.0, rect.width)
    h = max(1.0, rect.height)
    # Avoid over-shrinking tiny boxes after coordinate scaling.
    eff_pad = min(float(pad), w * 0.08, h * 0.18, 1.2)
    r = fitz.Rect(rect.x0 + eff_pad, rect.y0 + eff_pad, rect.x1 - eff_pad, rect.y1 - eff_pad)
    if r.width <= 0.5 or r.height <= 0.5:
        r = fitz.Rect(rect.x0, rect.y0, rect.x1, rect.y1)

    font_steps = [11, 10, 9, 8, 7, 6, 5, 4, 3, 2.5, 2]
    font_steps = [fs for fs in font_steps if fs >= min_font_size]
    if not font_steps:
        font_steps = [min_font_size]

    for fs in font_steps:
        kwargs = {
            "fontsize": fs,
            "color": (0, 0, 0),
            "lineheight": max(0.85, float(line_height)),
        }
        if fontfile:
            kwargs["fontname"] = "NotoSansCJK"
            kwargs["fontfile"] = fontfile
        else:
            kwargs["fontname"] = "china-s"
        remains = page.insert_textbox(r, text, **kwargs)
        if remains >= 0:
            return True
        page.draw_rect(r, color=(1, 1, 1), fill=(1, 1, 1), overlay=True)
    kwargs = {"fontsize": max(2.0, float(min_font_size)), "color": (0, 0, 0), "lineheight": max(0.85, float(line_height))}
    if fontfile:
        kwargs["fontname"] = "NotoSansCJK"
        kwargs["fontfile"] = fontfile
    else:
        kwargs["fontname"] = "china-s"
    remains = page.insert_textbox(r, text, **kwargs)
    return remains >= 0


def _draw_text_overflow_safe(
    page: fitz.Page,
    rect: fitz.Rect,
    text: str,
    fontfile: str | None,
    min_font_size: float,
) -> None:
    """Last-resort text drawing for generic providers when textbox fitting fails."""
    fs = max(2.0, float(min_font_size))
    est_char_w = max(1.0, fs * 0.55)
    max_chars = max(8, int(max(1.0, rect.width) / est_char_w))

    lines: list[str] = []
    for raw in (text or "").split("\n"):
        chunk = raw.strip()
        if not chunk:
            lines.append("")
            continue
        wrapped = textwrap.wrap(chunk, width=max_chars, break_long_words=True, break_on_hyphens=False)
        lines.extend(wrapped or [chunk])

    draw_text = "\n".join(lines[:300]).strip()
    if not draw_text:
        return

    p = fitz.Point(
        min(max(0.5, rect.x0 + 0.5), max(0.5, page.rect.width - 0.5)),
        min(max(2.0, rect.y0 + fs), max(2.0, page.rect.height - 0.5)),
    )
    kwargs = {"fontsize": fs, "color": (0, 0, 0)}
    if fontfile:
        kwargs["fontname"] = "NotoSansCJK"
        kwargs["fontfile"] = fontfile
    else:
        kwargs["fontname"] = "china-s"
    page.insert_text(p, draw_text, **kwargs)


def _infer_coord_size_from_blocks(blocks: list[Block], rect: fitz.Rect) -> tuple[float, float]:
    if not blocks:
        return rect.width, rect.height
    max_x = max(max(float(b.bbox[0]), float(b.bbox[2])) for b in blocks)
    max_y = max(max(float(b.bbox[1]), float(b.bbox[3])) for b in blocks)
    if max_x <= 0 or max_y <= 0:
        return rect.width, rect.height
    return max_x, max_y


def _choose_generic_coord_size(blocks: list[Block], rect: fitz.Rect) -> tuple[float, float]:
    """Choose a stable coordinate space for generic providers.

    Some providers may return only a subset of page blocks. Using max bbox as
    full-page size in that case over-stretches boxes and pushes text out of
    place. Prefer 1:1 page coordinates unless bboxes clearly look larger than
    the page and need down-scaling.

    DotsOCR renders pages at 2x resolution (Matrix(2,2)) before sending to the
    VLM, so its bbox coordinates are in 2x pixel space. We detect this by
    checking whether the bbox extent is close to 2x the PDF page size and snap
    to the exact 2x dimensions to avoid the 1.60~1.80 grey-zone drift.
    """
    if not blocks:
        return rect.width, rect.height

    max_x, max_y = _infer_coord_size_from_blocks(blocks, rect)
    if max_x <= 0 or max_y <= 0:
        return rect.width, rect.height

    # Normalized coordinates in [0, 1].
    if max_x <= 2.0 and max_y <= 2.0:
        return 1.0, 1.0

    rx = max_x / max(rect.width, 1.0)
    ry = max_y / max(rect.height, 1.0)

    # If close to page size, keep 1:1 mapping to avoid introducing drift.
    if 0.70 <= rx <= 1.60 and 0.70 <= ry <= 1.60:
        return rect.width, rect.height

    # Detect 2x-rendered coordinate space (e.g. DotsOCR uses Matrix(2,2)).
    # If both axes are within ±25% of 2x page size, snap to exact 2x to avoid
    # grey-zone drift when max_bbox doesn't reach the full rendered canvas.
    if 1.50 <= rx <= 2.50 and 1.50 <= ry <= 2.50:
        return rect.width * 2.0, rect.height * 2.0

    # If bbox extent is much larger than page, down-scale to fit.
    if rx >= 1.80 or ry >= 1.80:
        return max_x, max_y

    # If extent is clearly smaller than page, it's likely partial extraction.
    # Avoid stretching partial blocks to full page.
    if rx <= 0.65 or ry <= 0.65:
        return rect.width, rect.height

    return max_x, max_y


def _load_provider_payload(
    *,
    ocr_engine: str,
    vl_api_base: str,
    mineru_api_base: str,
    dotsocr_api_base: str,
    dotsocr_model: str,
    dotsocr_prompt: str,
    input_pdf: Path,
) -> tuple[dict[str, Any], list[dict[str, Any]], str]:
    if ocr_engine == "paddleocr-vl":
        payload = _call_vl(vl_api_base, input_pdf)
        pages = _extract_pages(payload)
        if not pages:
            raise RuntimeError("No pages in PaddleOCR-VL result")
        return payload, pages, "vl"

    if ocr_engine == "mineru":
        payload = _call_mineru(mineru_api_base, input_pdf)
        pages = _extract_mineru_pages(payload)
        if not pages:
            pages = _extract_generic_pages(payload)
        if not pages:
            raise RuntimeError("No pages in MinerU result")
        return payload, pages, "generic"

    if ocr_engine == "dotsocr":
        payload = _call_dotsocr(dotsocr_api_base, input_pdf, model=dotsocr_model, prompt=dotsocr_prompt)
        pages = _extract_generic_pages(payload)
        if not pages:
            raise RuntimeError("No pages in DotsOCR result")
        return payload, pages, "generic"

    raise RuntimeError(f"Unsupported OCR engine: {ocr_engine}")


def _run_single_engine(
    input_pdf: Path,
    output_dir: Path,
    source_lang: str,
    target_lang: str,
    enable_translate: bool,
    geometry_source: str,
    render_background: bool,
    *,
    ocr_engine: str,
    vl_api_base: str,
    mineru_api_base: str,
    dotsocr_api_base: str,
    dotsocr_model: str,
    dotsocr_prompt: str,
) -> dict[str, Any]:
    payload, pages, provider_kind = _load_provider_payload(
        ocr_engine=ocr_engine,
        vl_api_base=vl_api_base,
        mineru_api_base=mineru_api_base,
        dotsocr_api_base=dotsocr_api_base,
        dotsocr_model=dotsocr_model,
        dotsocr_prompt=dotsocr_prompt,
        input_pdf=input_pdf,
    )

    raw_json_path = output_dir / f"{input_pdf.stem}_{ocr_engine}_raw.json"
    raw_json_path.write_text(json.dumps(payload, ensure_ascii=False, indent=2), encoding="utf-8")

    translator = Translator(enabled=enable_translate, source_lang=source_lang, target_lang=target_lang)
    cjk_font = _choose_cjk_fontfile()

    src_doc = fitz.open(str(input_pdf))
    out_doc = fitz.open()
    translated_dump = []
    auto_decisions: list[dict[str, Any]] = []

    total_blocks = 0
    translated_blocks = 0
    adaptive_profile = {
        "textBoxPadding": 2.0,
        "minFontSize": 2.5,
        "lineHeight": 1.0,
        "underlineRestoreStrength": 1.0,
        "receiptMode": False,
    }

    page_count = min(len(pages), len(src_doc))
    for page_idx in range(page_count):
        page_item = pages[page_idx]
        src_page = src_doc[page_idx]
        rect = src_page.rect
        out_page = out_doc.new_page(width=rect.width, height=rect.height)

        if provider_kind == "vl":
            coord_size = _get_input_image_size(page_item)
            if coord_size:
                coord_w, coord_h = coord_size
            else:
                coord_w, coord_h = rect.width, rect.height
            images_map = page_item.get("markdown", {}).get("images", {})
            if not isinstance(images_map, dict):
                images_map = {}
        else:
            generic_blocks = page_item.get("blocks", [])
            coord_w, coord_h = _choose_generic_coord_size(generic_blocks, rect)
            images_map = {}

        sx = rect.width / max(coord_w, 1.0)
        sy = rect.height / max(coord_h, 1.0)

        short_edge = min(rect.width, rect.height)
        page_area = rect.width * rect.height
        is_dense_small_page = short_edge < 520 or page_area < 180000
        text_box_padding = 1.0 if is_dense_small_page else 2.0
        min_font_size = 2.0 if is_dense_small_page else 2.5
        line_height = 0.9 if is_dense_small_page else 1.0
        underline_restore_strength = 1.0
        receipt_mode = is_dense_small_page

        adaptive_profile = {
            "textBoxPadding": text_box_padding,
            "minFontSize": min_font_size,
            "lineHeight": line_height,
            "underlineRestoreStrength": underline_restore_strength,
            "receiptMode": receipt_mode,
        }

        if render_background:
            pix = src_page.get_pixmap(alpha=False)
            out_page.insert_image(rect, stream=pix.tobytes("png"))

        selected_mode = geometry_source
        if provider_kind == "vl":
            if geometry_source == "layout-hybrid":
                blocks = _build_hybrid_blocks(page_item, keep_unmatched_chunks=True)
            elif geometry_source == "auto":
                blocks, selected_mode, decision = _choose_blocks_auto(page_item, rect=rect, sx=sx, sy=sy)
                auto_decisions.append({"page": page_idx + 1, **decision})
            else:
                blocks = _build_parsing_blocks(page_item)
        else:
            blocks = page_item.get("blocks", [])
            if geometry_source == "layout-hybrid":
                selected_mode = "parsing"
            elif geometry_source == "auto":
                selected_mode = "parsing"
                auto_decisions.append(
                    {
                        "page": page_idx + 1,
                        "selected": "parsing",
                        "reason": f"{ocr_engine} provider has no hybrid geometry; fallback to parsing",
                    }
                )

        page_dump = []
        for b in blocks:
            total_blocks += 1
            bb = fitz.Rect(
                b.bbox[0] * sx,
                b.bbox[1] * sy,
                b.bbox[2] * sx,
                b.bbox[3] * sy,
            )
            bb = fitz.Rect(
                max(0.0, bb.x0),
                max(0.0, bb.y0),
                min(rect.width, bb.x1),
                min(rect.height, bb.y1),
            )
            tiny_box = bb.width < 1.0 or bb.height < 1.0

            if b.image_ref:
                img_bytes = _resolve_image_bytes(b.image_ref, images_map)
                if img_bytes:
                    out_page.insert_image(bb, stream=img_bytes)

            txt = (b.text or "").strip()
            if not txt:
                page_dump.append({"label": b.label, "bbox": b.bbox, "text": "", "translated": ""})
                continue

            txt = _restore_form_layout(txt, strength=underline_restore_strength)

            ttxt = translator.translate_text(txt)
            if ttxt != txt:
                translated_blocks += 1

            if tiny_box:
                # Some providers emit very dense line-flow coordinates; after
                # scaling, many bboxes become sub-point and cannot host textbox.
                # Fallback to point insertion so text is still visible/selectable.
                pos = fitz.Point(
                    min(max(0.5, bb.x0), max(0.5, rect.width - 0.5)),
                    min(max(2.0, bb.y1), max(2.0, rect.height - 0.5)),
                )
                tiny_kwargs = {"fontsize": max(2.0, float(min_font_size)), "color": (0, 0, 0)}
                if cjk_font:
                    tiny_kwargs["fontname"] = "NotoSansCJK"
                    tiny_kwargs["fontfile"] = cjk_font
                else:
                    tiny_kwargs["fontname"] = "china-s"
                out_page.insert_text(pos, ttxt, **tiny_kwargs)
                page_dump.append({"label": b.label, "bbox": b.bbox, "text": txt, "translated": ttxt})
                continue

            should_clear_bg = ((not render_background) or enable_translate) and not receipt_mode
            # Generic providers often contain partially overlapping text boxes;
            # clearing each bbox can erase nearby already-rendered text.
            if provider_kind == "generic":
                should_clear_bg = False
            if should_clear_bg:
                out_page.draw_rect(bb, color=(1, 1, 1), fill=(1, 1, 1), overlay=True)
            fitted = _fit_insert_text(
                out_page,
                bb,
                ttxt,
                pad=text_box_padding,
                fontfile=cjk_font,
                min_font_size=min_font_size,
                line_height=line_height,
            )
            if (not fitted) and provider_kind == "generic":
                _draw_text_overflow_safe(
                    out_page,
                    bb,
                    ttxt,
                    fontfile=cjk_font,
                    min_font_size=min_font_size,
                )
            page_dump.append({"label": b.label, "bbox": b.bbox, "text": txt, "translated": ttxt})

        translated_dump.append({"page": page_idx + 1, "geometrySelected": selected_mode, "blocks": page_dump})

    output_pdf = output_dir / f"{input_pdf.stem}_{ocr_engine}_visual_clone.pdf"
    out_doc.save(str(output_pdf))
    out_doc.close()
    src_doc.close()

    translated_json_path = output_dir / f"{input_pdf.stem}_{ocr_engine}_translated_blocks.json"
    translated_json_path.write_text(json.dumps(translated_dump, ensure_ascii=False, indent=2), encoding="utf-8")

    return {
        "engine": ocr_engine,
        "jsonPath": str(raw_json_path),
        "translatedJsonPath": str(translated_json_path),
        "outputPdfPath": str(output_pdf),
        "stats": {
            "pages": page_count,
            "totalBlocks": total_blocks,
            "translatedBlocks": translated_blocks,
            "geometrySource": geometry_source,
            "renderBackground": render_background,
            "fontFile": cjk_font,
            "adaptiveDefaults": adaptive_profile,
            "autoDecisions": auto_decisions,
            "providerKind": provider_kind,
        },
    }


def run_pipeline(
    input_pdf: Path,
    output_dir: Path,
    api_base: str,
    source_lang: str,
    target_lang: str,
    enable_translate: bool,
    geometry_source: str,
    render_background: bool,
    ocr_engine: str = "paddleocr-vl",
    compare_all_engines: bool = False,
    mineru_api_base: str = "",
    dotsocr_api_base: str = "",
    dotsocr_model: str = "dots.ocr-1.5",
    dotsocr_prompt: str = "",
) -> dict[str, Any]:
    output_dir.mkdir(parents=True, exist_ok=True)

    engines = ["paddleocr-vl", "mineru", "dotsocr"] if compare_all_engines else [ocr_engine]
    runs: list[dict[str, Any]] = []
    errors: list[dict[str, Any]] = []

    for engine in engines:
        try:
            run = _run_single_engine(
                input_pdf=input_pdf,
                output_dir=output_dir,
                source_lang=source_lang,
                target_lang=target_lang,
                enable_translate=enable_translate,
                geometry_source=geometry_source,
                render_background=render_background,
                ocr_engine=engine,
                vl_api_base=api_base,
                mineru_api_base=mineru_api_base,
                dotsocr_api_base=dotsocr_api_base,
                dotsocr_model=dotsocr_model,
                dotsocr_prompt=dotsocr_prompt,
            )
            runs.append(run)
        except Exception as e:  # noqa: BLE001
            errors.append({"engine": engine, "error": str(e)})

    if not runs:
        raise RuntimeError(f"All OCR engines failed: {errors}")

    primary = runs[0]
    primary_stats = dict(primary.get("stats", {}))
    if errors:
        primary_stats["engineErrors"] = errors

    return {
        "jsonPath": primary["jsonPath"],
        "translatedJsonPath": primary["translatedJsonPath"],
        "outputPdfPath": primary["outputPdfPath"],
        "stats": primary_stats,
        "runs": runs,
    }
