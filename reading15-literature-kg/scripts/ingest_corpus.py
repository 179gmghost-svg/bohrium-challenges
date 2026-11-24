#!/usr/bin/env python3
"""
Source-isolated corpus ingestion, 4-tier PDF fallback extractor
(PyMuPDF -> pypdf -> pdfplumber -> Poppler pdftotext), and duplicate-serialization
detector for scientific literature KG construction (Harbor / Reading-15).
"""

import argparse
import hashlib
import json
import re
import shutil
import subprocess
import sys
import uuid
import xml.etree.ElementTree as ET
from pathlib import Path
from typing import Any, Dict, List, Optional, Tuple


def normalize_ws(text: str) -> str:
    return re.sub(r"\s+", " ", text or "").strip()


def sha256_text(text: str) -> str:
    return hashlib.sha256(normalize_ws(text).encode("utf-8")).hexdigest()


def load_json_safe(path: Path) -> Optional[Any]:
    if not path.exists():
        return None
    try:
        return json.loads(path.read_text(encoding="utf-8"))
    except Exception as exc:
        print(f"[WARN] Failed to parse JSON {path}: {exc}", file=sys.stderr)
        return None


def extract_paragraphs_from_obj(obj: Any, default_source_id: str) -> List[Dict[str, Any]]:
    """Flexibly extract paragraphs from heterogeneous Harbor material JSON formats."""
    paragraphs: List[Dict[str, Any]] = []
    if obj is None:
        return paragraphs

    def add_para(src_id: str, pid: str, text: str, section: str = "", loc_type: str = "jats_paragraph_id") -> None:
        cleaned = normalize_ws(text)
        if not cleaned:
            return
        paragraphs.append({
            "source_id": str(src_id or default_source_id),
            "paragraph_id": str(pid),
            "section": section,
            "location_type": loc_type,
            "text": cleaned,
        })

    if isinstance(obj, list):
        for idx, item in enumerate(obj, start=1):
            if isinstance(item, dict):
                src_id = item.get("source_id") or item.get("paper_id") or item.get("doc_id") or default_source_id
                pid = item.get("paragraph_id") or item.get("para_id") or item.get("id") or f"p-{idx:03d}"
                text = item.get("text") or item.get("content") or item.get("body") or ""
                section = item.get("section") or item.get("section_title") or ""
                add_para(src_id, pid, text, section)
            elif isinstance(item, str):
                add_para(default_source_id, f"p-{idx:03d}", item)
        return paragraphs

    if isinstance(obj, dict):
        for key in ("paragraphs", "items", "chunks", "blocks", "body_paragraphs"):
            if isinstance(obj.get(key), list):
                src_id = obj.get("source_id") or obj.get("paper_id") or default_source_id
                return extract_paragraphs_from_obj(obj[key], str(src_id))
        if isinstance(obj.get("sections"), list):
            src_id = str(obj.get("source_id") or obj.get("paper_id") or default_source_id)
            p_counter = 1
            for sec in obj["sections"]:
                if not isinstance(sec, dict):
                    continue
                sec_title = str(sec.get("title") or sec.get("heading") or "")
                sec_paras = sec.get("paragraphs") or sec.get("content") or []
                if isinstance(sec_paras, str):
                    add_para(src_id, sec.get("paragraph_id") or f"p-{p_counter:03d}", sec_paras, sec_title)
                    p_counter += 1
                elif isinstance(sec_paras, list):
                    for sp in sec_paras:
                        if isinstance(sp, dict):
                            pid = sp.get("paragraph_id") or sp.get("id") or f"p-{p_counter:03d}"
                            txt = sp.get("text") or sp.get("content") or ""
                            add_para(src_id, pid, txt, sec_title)
                        elif isinstance(sp, str):
                            add_para(src_id, f"p-{p_counter:03d}", sp, sec_title)
                        p_counter += 1
            return paragraphs
        for key in ("papers", "documents", "sources"):
            if isinstance(obj.get(key), list):
                for idx, doc in enumerate(obj[key], start=1):
                    if isinstance(doc, dict):
                        sid = str(doc.get("source_id") or doc.get("id") or f"paper_{idx}")
                        paragraphs.extend(extract_paragraphs_from_obj(doc, sid))
                return paragraphs
        if isinstance(obj.get("text"), str):
            for idx, chunk in enumerate(re.split(r"\n\s*\n", obj["text"]), start=1):
                add_para(default_source_id, f"p-{idx:03d}", chunk)
    return paragraphs


def parse_jats_xml_snippets(xml_path: Path) -> Dict[str, str]:
    """Extract paragraph ID -> raw XML text mapping from secondary-publisher.xml."""
    mapping: Dict[str, str] = {}
    if not xml_path.exists():
        return mapping
    try:
        tree = ET.parse(xml_path)
        root = tree.getroot()
        for idx, elem in enumerate(root.iter(), start=1):
            tag = elem.tag.split("}")[-1]
            if tag == "p":
                pid = elem.attrib.get("id") or f"xml-p-{idx:03d}"
                raw_xml = ET.tostring(elem, encoding="unicode")
                mapping[pid] = normalize_ws(raw_xml)
    except Exception as exc:
        print(f"[WARN] Could not parse XML {xml_path}: {exc}", file=sys.stderr)
    return mapping


def _split_page_blocks(source_id: str, page_num: int, raw_text: str) -> List[Dict[str, Any]]:
    blocks = [normalize_ws(b) for b in re.split(r"\n\s*\n", raw_text or "") if normalize_ws(b)]
    if not blocks and normalize_ws(raw_text):
        blocks = [normalize_ws(raw_text)]
    out: List[Dict[str, Any]] = []
    for b_idx, blk in enumerate(blocks, start=1):
        out.append({
            "source_id": source_id,
            "paragraph_id": f"p{page_num}_b{b_idx}",
            "page": page_num,
            "section": f"Page {page_num}",
            "location_type": "pdf_page_extracted",
            "text": blk,
        })
    return out


def extract_pdf_fallback(
    pdf_path: Path, source_id: str, work_dir: Path
) -> Tuple[List[Dict[str, Any]], str, bool, List[str]]:
    """
    4-tier PDF extraction cascade: PyMuPDF (fitz) -> pypdf -> pdfplumber -> pdftotext.
    Any backend returning only whitespace automatically falls through to the next tier.
    Temp files for pdftotext are placed in work_dir (never %TEMP%) and removed in finally.
    """
    warnings: List[str] = []

    # Tier 1: PyMuPDF (fitz)
    try:
        import fitz  # type: ignore

        doc = fitz.open(str(pdf_path))
        paras: List[Dict[str, Any]] = []
        for page_num, page in enumerate(doc, start=1):
            paras.extend(_split_page_blocks(source_id, page_num, page.get_text("text") or ""))
        doc.close()
        if paras:
            return paras, "fitz", False, warnings
    except ImportError:
        pass
    except Exception as exc:
        warnings.append(f"fitz failed on '{pdf_path.name}': {exc}")

    # Tier 2: pypdf
    try:
        import pypdf  # type: ignore

        reader = pypdf.PdfReader(str(pdf_path))
        paras = []
        for page_num, page in enumerate(reader.pages, start=1):
            paras.extend(_split_page_blocks(source_id, page_num, page.extract_text() or ""))
        if paras:
            return paras, "pypdf", False, warnings
    except ImportError:
        pass
    except Exception as exc:
        warnings.append(f"pypdf failed on '{pdf_path.name}': {exc}")

    # Tier 3: pdfplumber
    try:
        import pdfplumber  # type: ignore

        paras = []
        with pdfplumber.open(str(pdf_path)) as pdf:
            for page_num, page in enumerate(pdf.pages, start=1):
                paras.extend(_split_page_blocks(source_id, page_num, page.extract_text() or ""))
        if paras:
            return paras, "pdfplumber", False, warnings
    except ImportError:
        pass
    except Exception as exc:
        warnings.append(f"pdfplumber failed on '{pdf_path.name}': {exc}")

    # Tier 4: Poppler pdftotext CLI (temp file written beside --output to avoid %TEMP% permission issues)
    pdftotext_bin = shutil.which("pdftotext")
    if pdftotext_bin:
        work_dir.mkdir(parents=True, exist_ok=True)
        tmp_txt = work_dir / f".tmp_pdftotext_{uuid.uuid4().hex[:8]}.txt"
        try:
            proc = subprocess.run(
                [pdftotext_bin, str(pdf_path), str(tmp_txt)],
                capture_output=True,
                text=True,
                timeout=60,
            )
            if proc.returncode == 0 and tmp_txt.exists():
                raw = tmp_txt.read_text(encoding="utf-8", errors="replace")
                pages = raw.split("\x0c")
                paras = []
                for page_num, page_text in enumerate(pages, start=1):
                    if normalize_ws(page_text):
                        paras.extend(_split_page_blocks(source_id, page_num, page_text))
                if paras:
                    return paras, "pdftotext", False, warnings
            else:
                warnings.append(f"pdftotext exited {proc.returncode} on '{pdf_path.name}': {proc.stderr.strip()}")
        except Exception as exc:
            warnings.append(f"pdftotext failed on '{pdf_path.name}': {exc}")
        finally:
            if tmp_txt.exists():
                try:
                    tmp_txt.unlink()
                except OSError:
                    pass

    warnings.append(f"PDF '{pdf_path.name}' yielded zero extractable text across all backends (fitz/pypdf/pdfplumber/pdftotext); needs_ocr_review=true.")
    return [], "none", True, warnings


def detect_duplicate_sources(sources_text: Dict[str, str], sources_meta: Dict[str, Dict[str, Any]]) -> List[Dict[str, Any]]:
    flags: List[Dict[str, Any]] = []
    sids = sorted(sources_text.keys())
    token_sets = {sid: set(re.findall(r"[a-z0-9]+", sources_text[sid].lower())) for sid in sids}
    for i in range(len(sids)):
        for j in range(i + 1, len(sids)):
            a, b = sids[i], sids[j]
            doi_a = (sources_meta.get(a, {}).get("doi") or "").strip().lower()
            doi_b = (sources_meta.get(b, {}).get("doi") or "").strip().lower()
            if doi_a and doi_b and doi_a == doi_b:
                flags.append({
                    "source_a": a,
                    "source_b": b,
                    "reason": f"Identical DOI ({doi_a}); treat as duplicate serialization, not cross-paper evidence.",
                })
                continue
            ta, tb = token_sets[a], token_sets[b]
            if ta and tb:
                jaccard = len(ta & tb) / max(1, len(ta | tb))
                if jaccard >= 0.90:
                    flags.append({
                        "source_a": a,
                        "source_b": b,
                        "reason": f"High lexical overlap (Jaccard={jaccard:.2f}); likely duplicate format of same paper.",
                    })
    return flags


def ingest(input_dir: Path, work_dir: Path) -> Dict[str, Any]:
    warnings: List[str] = []
    case_json = load_json_safe(input_dir / "case.json") or {}
    manifest = load_json_safe(input_dir / "corpus-manifest.json")
    primary_obj = load_json_safe(input_dir / "primary-material.json")
    secondary_obj = load_json_safe(input_dir / "secondary-material.json")
    merged_material = load_json_safe(input_dir / "material.json")
    xml_snippets = parse_jats_xml_snippets(input_dir / "secondary-publisher.xml")

    sources_meta: Dict[str, Dict[str, Any]] = {}
    paragraphs: List[Dict[str, Any]] = []
    extraction_backend = "json_jats"
    needs_ocr_review = False

    if isinstance(manifest, dict):
        entries = manifest.get("sources") or manifest.get("papers") or manifest.get("documents") or []
    elif isinstance(manifest, list):
        entries = manifest
    else:
        entries = []

    for idx, entry in enumerate(entries):
        if not isinstance(entry, dict):
            continue
        sid = str(entry.get("source_id") or entry.get("id") or ("primary" if idx == 0 else f"secondary_{idx}"))
        role = entry.get("paper_role") or ("primary" if idx == 0 else "secondary")
        sources_meta[sid] = {
            "source_id": sid,
            "paper_role": role,
            "doi": entry.get("doi"),
            "title": entry.get("title"),
            "authors": entry.get("authors") if isinstance(entry.get("authors"), list) else [],
            "license": entry.get("license"),
            "source_hash": entry.get("source_hash") or entry.get("sha256"),
            "location_type": "jats_paragraph_id",
        }

    if primary_obj is not None:
        p_sid = str((primary_obj.get("source_id") if isinstance(primary_obj, dict) else None) or "primary")
        if p_sid not in sources_meta:
            sources_meta[p_sid] = {
                "source_id": p_sid,
                "paper_role": "primary",
                "doi": (primary_obj.get("doi") if isinstance(primary_obj, dict) else None) or case_json.get("doi"),
                "title": (primary_obj.get("title") if isinstance(primary_obj, dict) else None) or case_json.get("title"),
                "authors": (primary_obj.get("authors") if isinstance(primary_obj, dict) else None) or case_json.get("authors") or [],
                "license": primary_obj.get("license") if isinstance(primary_obj, dict) else None,
                "source_hash": None,
                "location_type": "jats_paragraph_id",
            }
        paragraphs.extend(extract_paragraphs_from_obj(primary_obj, p_sid))

    if secondary_obj is not None:
        s_sid = str((secondary_obj.get("source_id") if isinstance(secondary_obj, dict) else None) or "secondary")
        if s_sid not in sources_meta:
            sources_meta[s_sid] = {
                "source_id": s_sid,
                "paper_role": "secondary",
                "doi": secondary_obj.get("doi") if isinstance(secondary_obj, dict) else None,
                "title": secondary_obj.get("title") if isinstance(secondary_obj, dict) else None,
                "authors": (secondary_obj.get("authors") if isinstance(secondary_obj, dict) else None) or [],
                "license": secondary_obj.get("license") if isinstance(secondary_obj, dict) else None,
                "source_hash": None,
                "location_type": "jats_paragraph_id",
            }
        sec_paras = extract_paragraphs_from_obj(secondary_obj, s_sid)
        for sp in sec_paras:
            if sp["paragraph_id"] in xml_snippets:
                sp["xml_snippet"] = xml_snippets[sp["paragraph_id"]]
        paragraphs.extend(sec_paras)

    if not paragraphs and merged_material is not None:
        paragraphs.extend(extract_paragraphs_from_obj(merged_material, "primary"))

    if not paragraphs:
        pdf_files = sorted(input_dir.glob("*.pdf"))
        backends_used: List[str] = []
        for idx, pdf_path in enumerate(pdf_files):
            sid = "primary" if idx == 0 else f"secondary_{idx}"
            pdf_paras, backend, ocr_flag, pdf_warns = extract_pdf_fallback(pdf_path, sid, work_dir)
            warnings.extend(pdf_warns)
            backends_used.append(backend)
            if ocr_flag:
                needs_ocr_review = True
            paragraphs.extend(pdf_paras)
            if sid not in sources_meta:
                sources_meta[sid] = {
                    "source_id": sid,
                    "paper_role": "primary" if idx == 0 else "secondary",
                    "doi": None,
                    "title": pdf_path.stem,
                    "authors": [],
                    "license": None,
                    "source_hash": None,
                    "location_type": "pdf_page_extracted",
                }
        if backends_used:
            extraction_backend = ",".join(dict.fromkeys(backends_used))

    sources_text: Dict[str, List[str]] = {}
    for p in paragraphs:
        sid = p["source_id"]
        sources_text.setdefault(sid, []).append(p["text"])
        if sid not in sources_meta:
            sources_meta[sid] = {
                "source_id": sid,
                "paper_role": "primary" if not sources_meta else "secondary",
                "doi": None,
                "title": None,
                "authors": [],
                "license": None,
                "source_hash": None,
                "location_type": p["location_type"],
            }

    joined_texts = {sid: "\n".join(chunks) for sid, chunks in sources_text.items()}
    for sid, full_txt in joined_texts.items():
        if not sources_meta[sid].get("source_hash"):
            sources_meta[sid]["source_hash"] = sha256_text(full_txt)

    duplicate_flags = detect_duplicate_sources(joined_texts, sources_meta)
    for df in duplicate_flags:
        warnings.append(f"DUPLICATE_SOURCE_WARNING: {df['source_a']} vs {df['source_b']}: {df['reason']}")

    has_pdf_pages = any(p["location_type"] == "pdf_page_extracted" for p in paragraphs)
    return {
        "case_id": case_json.get("case_id", "unknown_case"),
        "extraction_backend": extraction_backend,
        "has_pdf_pagination": has_pdf_pages,
        "needs_ocr_review": needs_ocr_review,
        "xml_verification_available": bool(xml_snippets),
        "sources": list(sources_meta.values()),
        "paragraph_count": len(paragraphs),
        "paragraphs": paragraphs,
        "duplicate_source_flags": duplicate_flags,
        "warnings": warnings,
    }


def main() -> None:
    parser = argparse.ArgumentParser(description="Ingest scientific corpus with strict source isolation.")
    parser.add_argument("--input-dir", required=True, help="Directory containing case.json and corpus materials")
    parser.add_argument("--output", required=True, help="Output path for corpus_index.json")
    args = parser.parse_args()

    out_path = Path(args.output)
    out_path.parent.mkdir(parents=True, exist_ok=True)
    result = ingest(Path(args.input_dir), out_path.parent)
    out_path.write_text(json.dumps(result, ensure_ascii=False, indent=2), encoding="utf-8")
    print(json.dumps({
        "status": "ok",
        "case_id": result["case_id"],
        "extraction_backend": result["extraction_backend"],
        "needs_ocr_review": result["needs_ocr_review"],
        "sources": [s["source_id"] for s in result["sources"]],
        "paragraph_count": result["paragraph_count"],
        "warnings": result["warnings"],
    }, ensure_ascii=False, indent=2))


if __name__ == "__main__":
    main()
