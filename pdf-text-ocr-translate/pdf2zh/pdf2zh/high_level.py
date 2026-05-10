"""Functions that can be used for the most common use-cases for pdf2zh.six"""
import cv2
import asyncio
import io
import os
import re
import sys
import tempfile
import json
import logging
from asyncio import CancelledError
from pathlib import Path
from string import Template
from typing import Any, BinaryIO, List, Optional, Dict
from datetime import datetime
import numpy as np
import requests
import tqdm
from pdfminer.pdfdocument import PDFDocument
from pdfminer.pdfexceptions import PDFValueError
from pdfminer.pdfinterp import PDFResourceManager
from pdfminer.pdfpage import PDFPage
from pdfminer.pdfparser import PDFParser
from pdfminer.pdftypes import PDFObjRef, stream_value
from pymupdf import Document, Font

from pdf2zh.converter import TranslateConverter
from pdf2zh.doclayout import OnnxModel, YoloResult
from pdf2zh.pdfinterp import PDFPageInterpreterEx

from pdf2zh.config import ConfigManager
from babeldoc.assets.assets import get_font_and_metadata
from utils import request_api

import yaml
with open('/app/pdf2zh/config.yaml', 'r', encoding='utf-8') as f:
    config = yaml.load(f.read(), Loader=yaml.FullLoader)

NOTO_NAME = "noto"

logger = logging.getLogger(__name__)

noto_list = [
    "am",  # Amharic
    "ar",  # Arabic
    "bn",  # Bengali
    "bg",  # Bulgarian
    "chr",  # Cherokee
    "el",  # Greek
    "gu",  # Gujarati
    "iw",  # Hebrew
    "hi",  # Hindi
    "kn",  # Kannada
    "ml",  # Malayalam
    "mr",  # Marathi
    "ru",  # Russian
    "sr",  # Serbian
    "ta",  # Tamil
    "te",  # Telugu
    "th",  # Thai
    "ur",  # Urdu
    "uk",  # Ukrainian
]


def check_files(files: List[str]) -> List[str]:
    files = [
        f for f in files if not f.startswith("http://")
    ]  # exclude online files, http
    files = [
        f for f in files if not f.startswith("https://")
    ]  # exclude online files, https
    missing_files = [file for file in files if not os.path.exists(file)]
    return missing_files


def translate_patch(
    inf: BinaryIO,
    task_id: str = "",
    pages: Optional[list[int]] = None,
    vfont: str = "",
    vchar: str = "",
    thread: int = 0,
    doc_zh: Document = None,
    lang_in: str = "",
    lang_out: str = "",
    service: str = "",
    noto_name: str = "",
    noto: Font = None,
    callback: object = None,
    cancellation_event: asyncio.Event = None,
    model: OnnxModel = None,
    envs: Dict = None,
    prompt: Template = None,
    ignore_cache: bool = False,
    **kwarg: Any,
) -> None:
    # print("task_id: ", task_id)
    rsrcmgr = PDFResourceManager()
    layout = {}
    device = TranslateConverter(
        rsrcmgr,
        vfont,
        vchar,
        thread,
        layout,
        lang_in,
        lang_out,
        service,
        noto_name,
        noto,
        envs,
        prompt,
        ignore_cache,
    )

    assert device is not None
    obj_patch = {}
    interpreter = PDFPageInterpreterEx(rsrcmgr, device, obj_patch)
    if pages:
        total_pages = len(pages)
    else:
        total_pages = doc_zh.page_count

    parser = PDFParser(inf)
    doc = PDFDocument(parser)
    '''
    pre_process_all_pages_info = []
    post_process_all_pages_info = []
    def extract_document_info(doc, pdfpage, pageno, page_layout):
        """
        提取 PDF 文档的详细信息，包含布局信息
        :param doc: pymupdf.Document 对象
        :param layout: 布局信息字典
        :return: 包含文档详细信息的字典
        """
        #info = {}
        # 提取元信息
        #info["metadata"] = doc.metadata
        #info["pages"] = []

        #for page_num, page in enumerate(doc.pages(), start=1):
        page = doc[pageno]  # 获取当前页面对象
        page_info = {
            "page_number": pageno,
            #"text": page.get_text(),
            "images": [],
            "links": [],
            #"annotations": [],
            "fonts": [],
            "layout": [],  # 添加布局信息
            "resources": {},  # 添加资源信息
            "contents": []  # 添加内容流信息
        }
        
        # 获取页面资源
        page_xref = page.get_contents()[0]  # 获取页面的内容流的 xref
        resources_xref = doc.xref_get_key(page_xref, "Resources")  # 获取资源的 xref
        if resources_xref[0] == "xref":
            resources_xref = int(resources_xref[1].split()[0])
            resources = doc.xref_object(resources_xref)  # 获取资源对象
        else:
            resources = {}
        page_info["resources"] = {key: str(value) for key, value in pdfpage.resources.items()}

        # 获取页面内容流
        #page_info["contents"] = str(pdfpage.contents)
        # 获取页面内容流并转换为字符串表示
        def get_content_string(content):
            if isinstance(content, PDFObjRef):
                stream = stream_value(content)
                if stream:
                    if 'Filter' in stream and stream['Filter'] == '/FlateDecode':
                        import zlib
                        content_data = zlib.decompress(stream.get_data())
                        decoded_content = content_data.decode('utf-8')
                        #print(f"Decoded content: {decoded_content[:100]}...")  # 调试输出前100个字符
                        return decoded_content
                    else:
                        content_data = stream.get_data()
                        decoded_content = content_data.decode('utf-8')
                        #print(f"Decoded content: {decoded_content[:100]}...")  # 调试输出前100个字符
                        return decoded_content
                else:
                    print(f"Stream is None for content: {content}")  # 调试输出
            else:
                print(f"Content type: {type(content)}")  # 调试输出内容类型
            return str(content)
        
        if pdfpage.contents:
            contents = pdfpage.contents
            #print(f"Contents type: {type(contents)}")  # 调试输出
            if isinstance(contents, list):
                content_strings = [get_content_string(content) for content in contents]
                page_info["contents"] = "\n".join(content_strings)
            else:
                page_info["contents"] = get_content_string(contents)
        else:
            page_info["contents"] = None


        # 提取图像信息
        for image in page.get_images(full=True):
            img_info = {
                "xref": image[0],
                "width": image[2],
                "height": image[3],
                "bpc": image[4],
                "colorspace": image[5],
                "file_ext": image[7]
            }
            page_info["images"].append(img_info)

        # 提取链接信息
        for link in page.get_links():
            link_info = {
                "kind": link["kind"],
                "page": link.get("page"),  # 使用 get 方法避免 KeyError
                "uri": link.get("uri", ""),
                "action": link.get("action", ""),
                "rect": link.get("rect")  # 使用 get 方法避免 KeyError
            }
            page_info["links"].append(link_info)

        # 提取注释信息
        for annot in page.annots():
            annot_info = {
                "type": annot.type[1],
                "text": annot.info.get("content", ""),
                "rect": annot.rect
            }
            page_info["annotations"].append(annot_info)

        # 提取字体信息
        for font in page.get_fonts(full=True):
            font_info = {
                "name": font[0],
                "embedded": font[1],
                "file": font[2],
                "size": font[3],
                "type": font[4]
            }
            page_info["fonts"].append(font_info)
        
        # 提取布局信息
        names = page_layout.names
        
        for box in page_layout.boxes:
            box_info = {
                "class": names[int(box.cls)],
                "confidence": float(box.conf),
                "coordinates": box.xyxy.tolist()  # 将 numpy 数组转换为列表
        }
            page_info["layout"].append(box_info)

        #info["pages"].append(page_info)

        return page_info
    '''

    with tqdm.tqdm(total=total_pages) as progress:
        for pageno, page in enumerate(PDFPage.create_pages(doc)):

            process_value = round((pageno/total_pages)*100, 2)            
            request_data = {"jobId":task_id, "progress": process_value, "progressTime": int(datetime.now().timestamp() * 1000)}
            progress_update_res = request_api(config["progress_update"], request_data)
            print(request_data)
            # print(type(progress_update_res))
            print(progress_update_res)
            if progress_update_res["code"]  == 200:
                if not progress_update_res["data"]: # false打断
                    raise CancelledError("task cancelled")

            if cancellation_event and cancellation_event.is_set():
                raise CancelledError("task cancelled")
            if pages and (pageno not in pages):
                continue
            progress.update()
            if callback:
                callback(progress)
            page.pageno = pageno
            pix = doc_zh[page.pageno].get_pixmap()
            image = np.fromstring(pix.samples, np.uint8).reshape(
                pix.height, pix.width, 3
            )[:, :, ::-1]
            page_layout = model.predict(image, imgsz=int(pix.height / 32) * 32)[0]
            
            logger.info(f"#############{page_layout}")
            # kdtree 是不可能 kdtree 的，不如直接渲染成图片，用空间换时间
            box = np.ones((pix.height, pix.width))
            h, w = box.shape
            vcls = ["abandon", "figure", "table", "isolate_formula", "formula_caption"]
            for i, d in enumerate(page_layout.boxes):
                if page_layout.names[int(d.cls)] not in vcls:
                    x0, y0, x1, y1 = d.xyxy.squeeze()
                    x0, y0, x1, y1 = (
                        np.clip(int(x0 - 1), 0, w - 1),
                        np.clip(int(h - y1 - 1), 0, h - 1),
                        np.clip(int(x1 + 1), 0, w - 1),
                        np.clip(int(h - y0 + 1), 0, h - 1),
                    )
                    box[y0:y1, x0:x1] = i + 2
            for i, d in enumerate(page_layout.boxes):
                if page_layout.names[int(d.cls)] in vcls:
                    x0, y0, x1, y1 = d.xyxy.squeeze()
                    x0, y0, x1, y1 = (
                        np.clip(int(x0 - 1), 0, w - 1),
                        np.clip(int(h - y1 - 1), 0, h - 1),
                        np.clip(int(x1 + 1), 0, w - 1),
                        np.clip(int(h - y0 + 1), 0, h - 1),
                    )
                    box[y0:y1, x0:x1] = 0
            layout[page.pageno] = box
            
            # 新建一个 xref 存放新指令流
            page.page_xref = doc_zh.get_new_xref()  # hack 插入页面的新 xref
            doc_zh.update_object(page.page_xref, "<<>>")
            doc_zh.update_stream(page.page_xref, b"")
            doc_zh[page.pageno].set_contents(page.page_xref)
            # 处理之前提取并保存信息
            #pre_process_info = extract_document_info(doc_zh, page, pageno, page_layout)
            #pre_process_all_pages_info.append(pre_process_info)
            
            interpreter.process_page(page)
            
            # 处理之后提取信息
            #post_process_info = extract_document_info(doc_zh, page, pageno, page_layout)
            #post_process_all_pages_info.append(post_process_info)
            
    # 保存所有页处理前的信息到一个文件
    #with open(f'pre_process_all_page.json', 'w', encoding='utf-8') as f:
    #    json.dump(pre_process_all_pages_info, f, ensure_ascii=False, indent=4)
    
    # 保存所有页处理后的信息到一个文件
    #with open('post_process_all_pages.json', 'w', encoding='utf-8') as f:
    #    json.dump(post_process_all_pages_info, f, ensure_ascii=False, indent=4)
    
    device.close()
    return obj_patch


def translate_stream(
    stream: bytes,    
    task_id: str = "",
    pages: Optional[list[int]] = None,
    lang_in: str = "",
    lang_out: str = "",
    service: str = "",
    thread: int = 0,
    vfont: str = "",
    vchar: str = "",
    callback: object = None,
    cancellation_event: asyncio.Event = None,
    model: OnnxModel = None,
    envs: Dict = None,
    prompt: Template = None,
    skip_subset_fonts: bool = False,
    ignore_cache: bool = False,
    **kwarg: Any,
):
    # print("task_id: ", task_id)
    font_list = [("tiro", None)]

    font_path = download_remote_fonts(lang_out.lower())
    noto_name = NOTO_NAME
    noto = Font(noto_name, font_path)
    font_list.append((noto_name, font_path))

    doc_en = Document(stream=stream)
    stream = io.BytesIO()
    doc_en.save(stream)
    doc_zh = Document(stream=stream)
    page_count = doc_zh.page_count
       
    # font_list = [("GoNotoKurrent-Regular.ttf", font_path), ("tiro", None)]
    font_id = {}
    for page in doc_zh:
        for font in font_list:
            font_id[font[0]] = page.insert_font(font[0], font[1])
    xreflen = doc_zh.xref_length()
    for xref in range(1, xreflen):
        for label in ["Resources/", ""]:  # 可能是基于 xobj 的 res
            try:  # xref 读写可能出错
                font_res = doc_zh.xref_get_key(xref, f"{label}Font")
                target_key_prefix = f"{label}Font/"
                if font_res[0] == "xref":
                    resource_xref_id = re.search("(\\d+) 0 R", font_res[1]).group(1)
                    xref = int(resource_xref_id)
                    font_res = ("dict", doc_zh.xref_object(xref))
                    target_key_prefix = ""

                if font_res[0] == "dict":
                    for font in font_list:
                        target_key = f"{target_key_prefix}{font[0]}"
                        font_exist = doc_zh.xref_get_key(xref, target_key)
                        if font_exist[0] == "null":
                            doc_zh.xref_set_key(
                                xref,
                                target_key,
                                f"{font_id[font[0]]} 0 R",
                            )
            except Exception:
                pass
    # print("locals: ", locals()["task_id"]) 
    fp = io.BytesIO()
    doc_zh.save(fp)    
    obj_patch: dict = translate_patch(fp, **locals())

    for obj_id, ops_new in obj_patch.items():
        # ops_old=doc_en.xref_stream(obj_id)
        # print(obj_id)
        # print(ops_old)
        # print(ops_new.encode())
        doc_zh.update_stream(obj_id, ops_new.encode())
    '''
    # 提取 doc_zh 的详细信息
    doc_zh_info_after = extract_document_info(doc_zh)

    # 保存为 JSON 文件
    with open('doc_zh_info_after.json', 'w', encoding='utf-8') as f:
        json.dump(doc_zh_info_after, f, ensure_ascii=False, indent=4)
    '''
    doc_en.insert_file(doc_zh)
    for id in range(page_count):
        doc_en.move_page(page_count + id, id * 2 + 1)
    if not skip_subset_fonts:
        doc_zh.subset_fonts(fallback=True)
        doc_en.subset_fonts(fallback=True)
    return (
        doc_zh.write(deflate=True, garbage=3, use_objstms=1),
        doc_en.write(deflate=True, garbage=3, use_objstms=1),
    )


def convert_to_pdfa(input_path, output_path):
    """
    Convert PDF to PDF/A format

    Args:
        input_path: Path to source PDF file
        output_path: Path to save PDF/A file
    """
    from pikepdf import Dictionary, Name, Pdf

    # Open the PDF file
    pdf = Pdf.open(input_path)

    # Add PDF/A conformance metadata
    metadata = {
        "pdfa_part": "2",
        "pdfa_conformance": "B",
        "title": pdf.docinfo.get("/Title", ""),
        "author": pdf.docinfo.get("/Author", ""),
        "creator": "PDF Math Translate",
    }

    with pdf.open_metadata() as meta:
        meta.load_from_docinfo(pdf.docinfo)
        meta["pdfaid:part"] = metadata["pdfa_part"]
        meta["pdfaid:conformance"] = metadata["pdfa_conformance"]

    # Create OutputIntent dictionary
    output_intent = Dictionary(
        {
            "/Type": Name("/OutputIntent"),
            "/S": Name("/GTS_PDFA1"),
            "/OutputConditionIdentifier": "sRGB IEC61966-2.1",
            "/RegistryName": "http://www.color.org",
            "/Info": "sRGB IEC61966-2.1",
        }
    )

    # Add output intent to PDF root
    if "/OutputIntents" not in pdf.Root:
        pdf.Root.OutputIntents = [output_intent]
    else:
        pdf.Root.OutputIntents.append(output_intent)

    # Save as PDF/A
    pdf.save(output_path, linearize=True)
    pdf.close()


def translate(
    files: list[str],
    output: str = "",
    pages: Optional[list[int]] = None,
    lang_in: str = "",
    lang_out: str = "",
    service: str = "",
    thread: int = 0,
    vfont: str = "",
    vchar: str = "",
    callback: object = None,
    compatible: bool = False,
    cancellation_event: asyncio.Event = None,
    model: OnnxModel = None,
    envs: Dict = None,
    prompt: Template = None,
    skip_subset_fonts: bool = False,
    ignore_cache: bool = False,
    **kwarg: Any,
):
    
    if not files:
        raise PDFValueError("No files to process.")

    missing_files = check_files(files)

    if missing_files:
        print("The following files do not exist:", file=sys.stderr)
        for file in missing_files:
            print(f"  {file}", file=sys.stderr)
        raise PDFValueError("Some files do not exist.")

    result_files = []

    for file in files:
        if type(file) is str and (
            file.startswith("http://") or file.startswith("https://")
        ):
            print("Online files detected, downloading...")
            try:
                r = requests.get(file, allow_redirects=True)
                if r.status_code == 200:
                    with tempfile.NamedTemporaryFile(
                        suffix=".pdf", delete=False
                    ) as tmp_file:
                        print(f"Writing the file: {file}...")
                        tmp_file.write(r.content)
                        file = tmp_file.name
                else:
                    r.raise_for_status()
            except Exception as e:
                raise PDFValueError(
                    f"Errors occur in downloading the PDF file. Please check the link(s).\nError:\n{e}"
                )
        filename = os.path.splitext(os.path.basename(file))[0]

        # If the commandline has specified converting to PDF/A format
        # --compatible / -cp
        if compatible:
            with tempfile.NamedTemporaryFile(
                suffix="-pdfa.pdf", delete=False
            ) as tmp_pdfa:
                print(f"Converting {file} to PDF/A format...")
                convert_to_pdfa(file, tmp_pdfa.name)
                doc_raw = open(tmp_pdfa.name, "rb")
                os.unlink(tmp_pdfa.name)
        else:
            doc_raw = open(file, "rb")
        s_raw = doc_raw.read()
        doc_raw.close()

        temp_dir = Path(tempfile.gettempdir())
        file_path = Path(file)
        try:
            if file_path.exists() and file_path.resolve().is_relative_to(
                temp_dir.resolve()
            ):
                file_path.unlink(missing_ok=True)
                logger.debug(f"Cleaned temp file: {file_path}")
        except Exception as e:
            logger.warning(f"Failed to clean temp file {file_path}", exc_info=True)
        
        # print("locals 中的所有内容：", locals())
        s_mono, s_dual = translate_stream(
            s_raw,
            task_id=kwarg["task_id"],
            **locals(),
        )
        file_mono = Path(output) / f"{filename}-mono.pdf"
        file_dual = Path(output) / f"{filename}-dual.pdf"
        doc_mono = open(file_mono, "wb")
        doc_dual = open(file_dual, "wb")
        doc_mono.write(s_mono)
        doc_dual.write(s_dual)
        doc_mono.close()
        doc_dual.close()
        result_files.append((str(file_mono), str(file_dual)))

    return result_files


def download_remote_fonts(lang: str):
    lang = lang.lower()
    LANG_NAME_MAP = {
        **{la: "GoNotoKurrent-Regular.ttf" for la in noto_list},
        **{
            la: f"SourceHanSerif{region}-Regular.ttf"
            for region, langs in {
                "CN": ["zh-cn", "zh-hans", "zh"],
                "TW": ["zh-tw", "zh-hant"],
                "JP": ["ja"],
                "KR": ["ko"],
            }.items()
            for la in langs
        },
    }
    font_name = LANG_NAME_MAP.get(lang, "GoNotoKurrent-Regular.ttf")

    # docker
    font_path = ConfigManager.get("NOTO_FONT_PATH", Path("/app", font_name).as_posix())
    if not Path(font_path).exists():
        font_path, _ = get_font_and_metadata(font_name)
        font_path = font_path.as_posix()

    logger.info(f"use font: {font_path}")

    return font_path
