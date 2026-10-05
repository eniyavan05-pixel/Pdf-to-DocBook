# -*- coding: utf-8 -*-
import os
import re
import uuid
import tempfile
from datetime import datetime
from typing import List, Dict
import pymupdf
from lxml import etree
from fastapi import FastAPI, File, UploadFile, Request
from fastapi.responses import HTMLResponse, FileResponse, JSONResponse
from fastapi.templating import Jinja2Templates

# Resolve templates folder relative to api/main.py
BASE_DIR = os.path.dirname(os.path.abspath(__file__))
TEMPLATES_DIR = os.path.join(BASE_DIR, "..", "templates")

app = FastAPI(title="TTBS XML Studio - DocBook 5.0 Suite")
templates = Jinja2Templates(directory=TEMPLATES_DIR)

# Serverless-safe temporary directories using /tmp
UPLOADS_DIR = tempfile.gettempdir()
OUTPUTS_DIR = tempfile.gettempdir()

# DocBook 5.0 Namespaces
DOCBOOK_NS = "http://docbook.org/ns/docbook"
XLINK_NS = "http://www.w3.org/1999/xlink"
MML_NS = "http://www.w3.org/1998/Math/MathML"
XML_NS = "http://www.w3.org/XML/1998/namespace"

NS_MAP = {
    None: DOCBOOK_NS,
    "xlink": XLINK_NS,
    "mml": MML_NS,
    "xml": XML_NS
}

LIGATURE_MAP = {
    "\ufb00": "ff", "\ufb01": "fi", "\ufb02": "fl", "\ufb03": "ffi", "\ufb04": "ffl"
}

VALID_COMPOUND_WORDS = {
    "point", "aware", "driven", "based", "level", "order", "state", "rate",
    "free", "bound", "scale", "wise", "width", "time", "domain", "end",
    "one", "two", "three", "four", "five", "six", "seven", "eight", "nine",
    "ten", "first", "second", "third", "can", "catch", "as", "known", "built",
    "long", "short", "wide", "side", "line", "type", "fold", "page", "step", "established"
}

NUMBER_PREFIXES = {
    "twenty", "thirty", "forty", "fifty", "sixty", "seventy", "eighty", "ninety", "well", "all"
}

def clean_to_hex_entities(text):
    if not text:
        return ""
    for lig, replacement in LIGATURE_MAP.items():
        text = text.replace(lig, replacement)
    out_chars = []
    for char in text:
        cp = ord(char)
        if cp > 127:
            out_chars.append(f"&#x{cp:04X};" if cp <= 0xFFFF else f"&#x{cp:06X};")
        else:
            out_chars.append(char)
    text = "".join(out_chars)
    valid_xml = re.compile(r'[^\u0009\u000a\u000d\u0020-\ud7ff\ue000-\ufffd\U00010000-\U0010ffff]')
    return valid_xml.sub('', text)

def smart_title_case(text):
    if not text:
        return ""
    minor_words = {"and", "or", "but", "a", "an", "the", "as", "at", "by", "for", "in", "of", "on", "per", "to", "via"}
    words = text.split()
    res = []
    for i, w in enumerate(words):
        core = re.sub(r'[^a-zA-Z]', '', w).lower()
        if i > 0 and core in minor_words:
            res.append(w.lower())
        else:
            res.append(w.capitalize())
    return " ".join(res)

def post_process_clean_xml(xml_str):
    if not xml_str:
        return ""
    xml_str = re.sub(r'&amp;#x([0-9A-Fa-f]+);', r'&#x\1;', xml_str)
    xml_str = re.sub(r'&#x00A0;', ' ', xml_str)
    xml_str = xml_str.replace("’", "&#x2019;").replace("‘", "&#x2018;").replace("“", "&#x201C;").replace("”", "&#x201D;").replace("–", "&#x2013;").replace("—", "&#x2014;")
    return xml_str

def parse_full_pdf(pdf_path, output_xml_path, doi="10.5040/9798216438984", book_title="Monograph"):
    doc = pymupdf.open(pdf_path)
    root = etree.Element(
        f"{{{DOCBOOK_NS}}}book",
        attrib={"version": "5.0", f"{{{XML_NS}}}lang": "en", "role": "fullText", f"{{{XML_NS}}}id": "b-root"},
        nsmap=NS_MAP
    )
    info_elem = etree.SubElement(root, f"{{{DOCBOOK_NS}}}info")
    etree.SubElement(info_elem, f"{{{DOCBOOK_NS}}}title").text = clean_to_hex_entities(book_title)

    for idx, page in enumerate(doc, 1):
        chap = etree.SubElement(root, f"{{{DOCBOOK_NS}}}chapter", attrib={"label": str(idx)})
        c_info = etree.SubElement(chap, f"{{{DOCBOOK_NS}}}info")
        etree.SubElement(c_info, f"{{{DOCBOOK_NS}}}title").text = f"Chapter {idx}"
        
        text = page.get_text()
        for line in text.splitlines():
            if line.strip():
                p = etree.SubElement(chap, f"{{{DOCBOOK_NS}}}para")
                p.text = clean_to_hex_entities(line.strip())

    doc.close()
    raw_xml = etree.tostring(root.getroottree(), pretty_print=True, xml_declaration=True, encoding="UTF-8").decode("utf-8")
    with open(output_xml_path, "w", encoding="utf-8") as f:
        f.write(post_process_clean_xml(raw_xml))

conversion_history: List[Dict] = []

@app.get("/", response_class=HTMLResponse)
async def serve_home(request: Request):
    return templates.TemplateResponse(request=request, name="index.html")

@app.get("/api/history")
async def get_history():
    return JSONResponse(conversion_history)

@app.post("/api/upload")
async def handle_upload(file: UploadFile = File(...)):
    file_id = str(uuid.uuid4())[:8]
    saved_filename = f"{file_id}_{file.filename}"
    saved_path = os.path.join(UPLOADS_DIR, saved_filename)

    content = await file.read()
    with open(saved_path, "wb") as f:
        f.write(content)

    doc = pymupdf.open(saved_path)
    total_pages = len(doc)
    doc.close()

    new_record = {
        "id": str(len(conversion_history) + 1),
        "name": file.filename,
        "date": datetime.now().strftime("%d %b %Y, %I:%M %p"),
        "size": f"{len(content) / (1024 * 1024):.2f} MB",
        "status": "Ready",
        "file_id": file_id,
        "pages": total_pages,
        "file_path": saved_path
    }
    conversion_history.insert(0, new_record)
    return JSONResponse({"status": "success", "file_info": new_record})

@app.post("/api/convert/{file_id}")
async def run_conversion(file_id: str):
    target = next((item for item in conversion_history if item.get("file_id") == file_id), None)
    if not target or not os.path.exists(target.get("file_path", "")):
        return JSONResponse({"status": "error", "message": "Source PDF file not found."}, status_code=404)

    target["status"] = "Processing"
    pdf_path = target["file_path"]
    out_xml_name = f"{os.path.splitext(target['name'])[0]}.xml"
    out_xml_path = os.path.join(OUTPUTS_DIR, f"{file_id}_{out_xml_name}")

    try:
        parse_full_pdf(pdf_path, out_xml_path, book_title=target['name'])
        target["status"] = "Done"
        target["xml_path"] = out_xml_path
        target["xml_filename"] = out_xml_name

        return JSONResponse({
            "status": "success",
            "download_url": f"/api/download/{target['id']}",
            "filename": out_xml_name
        })
    except Exception as err:
        target["status"] = "Failed"
        return JSONResponse({"status": "error", "message": str(err)}, status_code=500)

@app.get("/api/download/{item_id}")
async def download_xml_file(item_id: str):
    target = next((item for item in conversion_history if item.get("id") == item_id), None)
    if not target or "xml_path" not in target:
        return JSONResponse({"status": "error", "message": "XML output file not found."}, status_code=404)
    return FileResponse(target["xml_path"], filename=target.get("xml_filename", "document.xml"), media_type="application/xml")
