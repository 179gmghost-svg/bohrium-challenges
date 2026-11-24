#!/usr/bin/env python3
"""
Automated Provenance, Verbatim Quote, Metadata Isolation, Page-Para Consistency,
JSON Schema & Multi-Shape Harbor output_contract Auditor (v1.1.0).
Exits 0 on PASS, 2 on FAIL with structured error codes.
"""

import argparse
import json
import re
import sys
from pathlib import Path
from typing import Any, Dict, List, Optional, Tuple


FABRICATED_PAGE_RE = re.compile(r"\b(page\s*\d+|p\.\s*\d+|pp\.\s*\d+)\b", re.IGNORECASE)
PDF_PARA_PREFIX_RE = re.compile(r"^p(\d+)_b\d+$", re.IGNORECASE)
ALLOWED_ENTITY_TYPES = {
    "Researcher", "Material", "Method", "Task", "Metric", "Conclusion", "Dataset", "Condition"
}
ALLOWED_RELATIONS = {
    "USES", "COMPARES", "OUTPERFORMS", "MEASURES", "SUPPORTS", "CONTRADICTS", "DERIVES_FROM", "APPLIES_TO"
}


def norm_for_match(text: str) -> str:
    return re.sub(r"\s+", " ", (text or "")).strip().lower()


def extract_contract_fields(case_json: Dict[str, Any]) -> List[str]:
    contract = case_json.get("output_contract")
    if isinstance(contract, list):
        return [str(x) for x in contract if isinstance(x, str)]
    if isinstance(contract, dict):
        for key in ("required_fields", "fields", "required", "keys", "output_fields"):
            val = contract.get(key)
            if isinstance(val, list):
                return [str(x) for x in val if isinstance(x, str)]
    return []


def audit(
    result: Dict[str, Any],
    graph: Dict[str, Any],
    corpus_index: Dict[str, Any],
    case_json: Dict[str, Any],
    schema_path: Optional[Path] = None,
) -> Dict[str, Any]:
    errors: List[Dict[str, str]] = []
    warnings: List[Dict[str, str]] = []

    def add_err(code: str, msg: str) -> None:
        errors.append({"code": code, "message": msg})

    def add_warn(code: str, msg: str) -> None:
        warnings.append({"code": code, "message": msg})

    # 1. Build (source_id, paragraph_id) -> normalized paragraph text
    para_map: Dict[Tuple[str, str], str] = {}
    for p in corpus_index.get("paragraphs", []):
        para_map[(str(p["source_id"]), str(p["paragraph_id"]))] = norm_for_match(p["text"])
    has_pdf_pagination = bool(corpus_index.get("has_pdf_pagination", False))

    # 2. Check top-level fields, case_id & multi-shape output_contract
    for req_top in ("case_id", "status", "knowledge_graph", "query_results"):
        if req_top not in result:
            add_err("MISSING_TOP_LEVEL", f"Missing mandatory top-level field '{req_top}' in result.json.")

    expected_case_id = case_json.get("case_id")
    if expected_case_id and result.get("case_id") != expected_case_id:
        add_err("CASE_ID_MISMATCH", f"result.json case_id='{result.get('case_id')}' != case.json case_id='{expected_case_id}'.")

    contract_fields = extract_contract_fields(case_json)
    for req_key in contract_fields:
        if req_key not in result:
            add_err("MISSING_CONTRACT_FIELD", f"Missing required output_contract field '{req_key}' in result.json.")

    # 3. Check root metadata isolation across sources
    sources = graph.get("sources", [])
    primary_dois = {s.get("doi") for s in sources if s.get("paper_role") == "primary" and s.get("doi")}
    for s in sources:
        if s.get("paper_role") != "primary" and s.get("doi") and s.get("doi") in primary_dois:
            add_err("METADATA_LEAKAGE", f"Secondary source '{s['source_id']}' shares primary DOI '{s['doi']}'.")

    # 4. Audit nodes, edges, quotes & page/para_id consistency
    quotes_total = 0
    quotes_verified = 0

    def check_prov(owner_label: str, prov: Dict[str, Any]) -> None:
        nonlocal quotes_total, quotes_verified
        quotes_total += 1
        sid = str(prov.get("source_id", ""))
        pid = str(prov.get("paragraph_id", ""))
        quote = str(prov.get("quote", ""))
        page_val = prov.get("page")

        if not has_pdf_pagination and FABRICATED_PAGE_RE.search(pid):
            add_err("FABRICATED_PDF_PAGE", f"{owner_label} fabricates PDF page number '{pid}' in a JATS-only corpus.")
        if page_val is not None:
            m = PDF_PARA_PREFIX_RE.match(pid)
            if m and int(m.group(1)) != int(page_val):
                add_warn("PAGE_PARA_MISMATCH", f"{owner_label} has page={page_val} but paragraph_id='{pid}'.")
        if (sid, pid) not in para_map:
            add_err("INVALID_LOCATION", f"{owner_label} cites non-existent (source_id='{sid}', paragraph_id='{pid}').")
        elif norm_for_match(quote) not in para_map[(sid, pid)]:
            add_err("QUOTE_MISMATCH", f"{owner_label} quote not found verbatim in ({sid}, {pid}): '{quote[:80]}'.")
        else:
            quotes_verified += 1

    node_ids = set()
    for n in graph.get("nodes", []):
        nid = n.get("id", "<missing_id>")
        node_ids.add(nid)
        if n.get("type") not in ALLOWED_ENTITY_TYPES:
            add_err("INVALID_ENTITY_TYPE", f"Node '{nid}' has unsupported entity type '{n.get('type')}'.")
        provs = n.get("provenance", [])
        if not provs:
            add_err("MISSING_PROVENANCE", f"Node '{nid}' ({n.get('name')}) lacks provenance.")
            continue
        for prov in provs:
            check_prov(f"Node '{nid}'", prov)

    for e in graph.get("edges", []):
        eid = e.get("id", "<missing_edge_id>")
        if e.get("source") not in node_ids or e.get("target") not in node_ids:
            add_err("DANGLING_EDGE", f"Edge '{eid}' references undefined node(s): {e.get('source')} -> {e.get('target')}.")
        if e.get("relation") not in ALLOWED_RELATIONS:
            add_err("INVALID_RELATION", f"Edge '{eid}' has unsupported relation '{e.get('relation')}'.")
        provs = e.get("provenance", [])
        if not provs:
            add_err("MISSING_PROVENANCE", f"Edge '{eid}' lacks provenance.")
            continue
        prov_sources = {str(p.get("source_id", "")) for p in provs}
        if len(prov_sources) > 1 and not e.get("cross_paper") and e.get("numeric_value") is not None:
            add_err("CROSS_PAPER_COLLAPSE", f"Edge '{eid}' collapses numeric values across sources {sorted(prov_sources)} without cross_paper flag.")
        for prov in provs:
            check_prov(f"Edge '{eid}'", prov)

    # 5. Audit query count and undeterminable explanations
    qresults = result.get("query_results", [])
    if len(qresults) < 3:
        add_err("INSUFFICIENT_QUERIES", f"Expected >= 3 executed queries, found {len(qresults)}.")
    for q in qresults:
        if q.get("status") == "undeterminable" and not q.get("undeterminable_reason"):
            add_err("UNDETERMINABLE_NO_REASON", f"Query '{q.get('query_id')}' marked undeterminable without 'undeterminable_reason'.")

    # 6. Optional jsonschema validation if jsonschema is installed and --schema is provided
    schema_checked = False
    if schema_path and schema_path.exists():
        try:
            import jsonschema  # type: ignore

            schema_obj = json.loads(schema_path.read_text(encoding="utf-8"))
            jsonschema.validate(instance=graph, schema=schema_obj)
            schema_checked = True
        except ImportError:
            add_warn("SCHEMA_LIB_UNAVAILABLE", "Optional 'jsonschema' package not installed; skipped Draft 2020-12 validator.")
        except Exception as exc:
            add_err("SCHEMA_VALIDATION_ERROR", f"knowledge_graph.json failed schema validation: {exc}")

    if len(sources) >= 2 and not graph.get("alignment_log"):
        add_warn("EMPTY_ALIGNMENT_LOG", "Multi-source graph has an empty alignment_log; verify cross-paper decisions were logged.")

    passed = len(errors) == 0
    return {
        "status": "PASS" if passed else "FAIL",
        "error_count": len(errors),
        "warning_count": len(warnings),
        "quotes_verified": quotes_verified,
        "quotes_total": quotes_total,
        "contract_fields": contract_fields,
        "schema_checked": schema_checked,
        "errors": errors,
        "warnings": warnings,
    }


def main() -> None:
    parser = argparse.ArgumentParser(description="Validate scientific KG and Harbor result.json.")
    parser.add_argument("--result", required=True)
    parser.add_argument("--graph", required=True)
    parser.add_argument("--corpus-index", required=True)
    parser.add_argument("--case-json", required=True)
    parser.add_argument("--schema", default=None, help="Optional path to kg_schema.json")
    parser.add_argument("--audit-out", default=None, help="Optional path to save quality_audit.json")
    parser.add_argument("--embed-audit", action="store_true", help="Embed quality_audit summary into result.json")
    args = parser.parse_args()

    result_path = Path(args.result)
    result = json.loads(result_path.read_text(encoding="utf-8"))
    graph = json.loads(Path(args.graph).read_text(encoding="utf-8"))
    corpus_index = json.loads(Path(args.corpus_index).read_text(encoding="utf-8"))
    case_json = json.loads(Path(args.case_json).read_text(encoding="utf-8")) if Path(args.case_json).exists() else {}
    schema_path = Path(args.schema) if args.schema else None

    report = audit(result, graph, corpus_index, case_json, schema_path)

    if args.audit_out:
        out_p = Path(args.audit_out)
        out_p.parent.mkdir(parents=True, exist_ok=True)
        out_p.write_text(json.dumps(report, ensure_ascii=False, indent=2), encoding="utf-8")

    if args.embed_audit:
        result["quality_audit"] = {
            "status": report["status"],
            "error_count": report["error_count"],
            "warning_count": report["warning_count"],
            "quotes_verified": report["quotes_verified"],
            "quotes_total": report["quotes_total"],
            "contract_fields": report["contract_fields"],
        }
        result_path.write_text(json.dumps(result, ensure_ascii=False, indent=2), encoding="utf-8")

    print(json.dumps(report, ensure_ascii=False, indent=2))
    sys.exit(0 if report["status"] == "PASS" else 2)


if __name__ == "__main__":
    main()
