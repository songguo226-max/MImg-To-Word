import os
import base64
import copy
import re
import tempfile
from zipfile import ZipFile
from dataclasses import dataclass
from typing import Callable
import xml.etree.ElementTree as ET

import pypandoc
from openai import OpenAI

BASE_DIR = os.path.dirname(os.path.abspath(__file__))
for _p in (os.path.join(BASE_DIR, 'pandoc.exe'), os.path.join(BASE_DIR, 'pandoc')):
    if os.path.isfile(_p):
        os.environ.setdefault('PYPANDOC_PANDOC', _p)
        break
W_NS = "http://schemas.openxmlformats.org/wordprocessingml/2006/main"
XML_NS = "http://www.w3.org/XML/1998/namespace"
ET.register_namespace("w", W_NS)

_MIME = {
    '.jpg':  'image/jpeg',
    '.jpeg': 'image/jpeg',
    '.png':  'image/png',
    '.webp': 'image/webp',
}
_BLANK_RE = re.compile(r"\{\{\s*BLANK\s*(?::\s*(short|medium|long)\s*)?\}\}", re.IGNORECASE)
_PLAIN_UNDERSCORE_RE = re.compile(r"(?<![A-Za-z0-9_＿])[_＿]{3,}(?![A-Za-z0-9_＿])")
_PLAIN_RULE_RE = re.compile(r"(?<![A-Za-z0-9])[—─]{3,}(?![A-Za-z0-9])")
_LATEX_BLANK_RE = re.compile(
    r"\\underline\s*\{\s*(?:\\quad|\\qquad|\\hspace\s*\{[^{}]*\}|[_＿\s]+)\s*\}",
    re.IGNORECASE,
)
_BLANK_WIDTHS = {
    "short": 6,
    "medium": 10,
    "long": 16,
}

_PROMPT = (
    "请识别图片中的全部数学公式和文字内容，以 Markdown 格式输出。"
    "行内公式用 $...$ 包裹，独立公式块用 $$...$$ 包裹。"
    "图片中如果出现填空横线、答案线、下划线空格，不要省略，也不要输出普通下划线；"
    "请按长度输出 {{BLANK:short}}、{{BLANK:medium}} 或 {{BLANK:long}}，"
    "例如“则 a 的值为 ____。”应输出“则 $a$ 的值为 {{BLANK:medium}}。”。"
    "只输出识别结果，不要添加解释或额外说明。"
)


@dataclass(frozen=True)
class RecognitionResult:
    markdown: str
    input_tokens: int
    output_tokens: int


def _read_image_as_data_url(img_path: str) -> str:
    ext = os.path.splitext(img_path)[1].lower()
    mime = _MIME.get(ext, 'image/jpeg')
    with open(img_path, 'rb') as f:
        b64 = base64.b64encode(f.read()).decode()
    return f"data:{mime};base64,{b64}"


def _blank_size_for_length(length: int) -> str:
    if length <= 5:
        return "short"
    if length <= 10:
        return "medium"
    return "long"


def normalize_blanks(markdown: str) -> str:
    def normalize_marker(match: re.Match) -> str:
        size = (match.group(1) or "medium").lower()
        return f"{{{{BLANK:{size}}}}}"

    def underscore_marker(match: re.Match) -> str:
        return f"{{{{BLANK:{_blank_size_for_length(len(match.group(0)))}}}}}"

    normalized = _BLANK_RE.sub(normalize_marker, markdown)
    normalized = _LATEX_BLANK_RE.sub("{{BLANK:medium}}", normalized)
    normalized = _PLAIN_UNDERSCORE_RE.sub(underscore_marker, normalized)
    normalized = _PLAIN_RULE_RE.sub(underscore_marker, normalized)
    return normalized


def _w(tag: str) -> str:
    return f"{{{W_NS}}}{tag}"


def _text_run(text: str, source_run: ET.Element) -> ET.Element:
    run = ET.Element(_w("r"))
    run_props = source_run.find(_w("rPr"))
    if run_props is not None:
        run.append(copy.deepcopy(run_props))
    text_node = ET.SubElement(run, _w("t"))
    if text[:1].isspace() or text[-1:].isspace():
        text_node.set(f"{{{XML_NS}}}space", "preserve")
    text_node.text = text
    return run


def _blank_run(size: str) -> ET.Element:
    run = ET.Element(_w("r"))
    run_props = ET.SubElement(run, _w("rPr"))
    underline = ET.SubElement(run_props, _w("u"))
    underline.set(_w("val"), "single")
    text_node = ET.SubElement(run, _w("t"))
    text_node.set(f"{{{XML_NS}}}space", "preserve")
    text_node.text = "\u00a0" * _BLANK_WIDTHS.get(size, _BLANK_WIDTHS["medium"])
    return run


def _runs_for_blank_text(text: str, source_run: ET.Element) -> list[ET.Element]:
    runs = []
    cursor = 0
    for match in _BLANK_RE.finditer(text):
        if match.start() > cursor:
            runs.append(_text_run(text[cursor:match.start()], source_run))
        runs.append(_blank_run((match.group(1) or "medium").lower()))
        cursor = match.end()
    if cursor < len(text):
        runs.append(_text_run(text[cursor:], source_run))
    return runs


def _process_document_xml(xml_bytes: bytes) -> bytes:
    root = ET.fromstring(xml_bytes)
    parent_map = {child: parent for parent in root.iter() for child in parent}
    for text_node in list(root.findall(".//w:t", {"w": W_NS})):
        text = text_node.text or ""
        if not _BLANK_RE.search(text):
            continue
        run = parent_map.get(text_node)
        if run is None or run.tag != _w("r"):
            continue
        parent = parent_map.get(run)
        if parent is None:
            continue
        index = list(parent).index(run)
        parent.remove(run)
        for offset, replacement in enumerate(_runs_for_blank_text(text, run)):
            parent.insert(index + offset, replacement)
    return ET.tostring(root, encoding="utf-8", xml_declaration=True)


def apply_blank_placeholders_to_docx(output_path: str) -> None:
    output_dir = os.path.dirname(os.path.abspath(output_path)) or "."
    fd, temp_path = tempfile.mkstemp(suffix=".docx", dir=output_dir)
    os.close(fd)
    try:
        with ZipFile(output_path, "r") as source, ZipFile(temp_path, "w") as target:
            for item in source.infolist():
                content = source.read(item.filename)
                if item.filename == "word/document.xml":
                    content = _process_document_xml(content)
                target.writestr(item, content)
        os.replace(temp_path, output_path)
    finally:
        if os.path.exists(temp_path):
            os.remove(temp_path)


def recognize_image(
    img_path: str,
    cfg: dict,
    cb: Callable[[int, str], None],
) -> RecognitionResult:
    client = OpenAI(
        api_key=cfg['api_key'],
        base_url=cfg['base_url'],
    )
    model = cfg.get('model', 'moonshot-v1-8k-vision-preview')

    cb(10, "读取图片")
    data_url = _read_image_as_data_url(img_path)

    cb(30, f"调用模型 {model}")
    resp = client.chat.completions.create(
        model=model,
        messages=[
            {
                "role": "user",
                "content": [
                    {
                        "type": "image_url",
                        "image_url": {"url": data_url},
                    },
                    {"type": "text", "text": _PROMPT},
                ],
            }
        ],
        max_tokens=4096,
    )

    markdown = normalize_blanks(resp.choices[0].message.content)
    usage = resp.usage
    in_t = usage.prompt_tokens if usage else 0
    out_t = usage.completion_tokens if usage else 0
    return RecognitionResult(markdown=markdown, input_tokens=in_t, output_tokens=out_t)


def render_docx(markdown: str, output_path: str) -> None:
    markdown = normalize_blanks(markdown)
    pypandoc.convert_text(
        markdown,
        'docx',
        format='markdown',
        outputfile=output_path,
        extra_args=['--mathml'],
    )
    apply_blank_placeholders_to_docx(output_path)


def test_model_connection(cfg: dict) -> None:
    client = OpenAI(
        api_key=cfg['api_key'],
        base_url=cfg['base_url'],
        timeout=15,
    )
    model = cfg.get('model', 'moonshot-v1-8k-vision-preview')
    client.chat.completions.create(
        model=model,
        messages=[
            {
                "role": "user",
                "content": "请只回复 OK，用于测试连接。",
            }
        ],
        max_tokens=2,
    )


def convert_image(
    img_path: str,
    output_path: str,
    cfg: dict,
    cb: Callable[[int, str], None],
) -> tuple[int, int]:
    result = recognize_image(img_path, cfg, cb)
    cb(70, "转换为 Word")
    render_docx(result.markdown, output_path)
    cb(100, "写入完成")
    return result.input_tokens, result.output_tokens
