#!/usr/bin/env python3
"""
Scientific Literature Knowledge Graph Engine (v1.1.0):
- build: construct base graph from a paper extraction
- update: incrementally integrate a new paper while preserving existing node IDs
- query: run traceable graph queries with explicit undeterminable reporting
- export: generate knowledge_graph.json, GraphML, Markdown report, and Harbor result.json
"""

import argparse
import hashlib
import json
import re
import xml.etree.ElementTree as ET
from collections import defaultdict, deque
from pathlib import Path
from typing import Any, Dict, List, Optional, Set, Tuple


def load_json(path: Path) -> Any:
    return json.loads(path.read_text(encoding="utf-8"))


def save_json(path: Path, data: Any) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(data, ensure_ascii=False, indent=2), encoding="utf-8")


def drop_none_optional(obj: Dict[str, Any], keep_keys: Set[str]) -> Dict[str, Any]:
    """Remove None values for optional keys so exports stay clean without literal 'None' or noisy nulls."""
    return {k: v for k, v in obj.items() if v is not None or k in keep_keys}


def extract_contract_fields(case_json: Dict[str, Any]) -> List[str]:
    """Support all Harbor output_contract shapes (list or dict with standard key aliases)."""
    contract = case_json.get("output_contract")
    if isinstance(contract, list):
        return [str(x) for x in contract if isinstance(x, str)]
    if isinstance(contract, dict):
        for key in ("required_fields", "fields", "required", "keys", "output_fields"):
            val = contract.get(key)
            if isinstance(val, list):
                return [str(x) for x in val if isinstance(x, str)]
    return []


def normalize_name(name: str, rules: Dict[str, Any]) -> str:
    text = (name or "").strip()
    for src, dst in rules.get("unicode_replacements", {}).items():
        text = text.replace(src, dst)
    text = re.sub(r"\s+", " ", text).lower()
    synonyms = rules.get("safe_canonical_synonyms", {})
    if text in synonyms:
        return synonyms[text]
    return text


def deterministic_node_id(entity_type: str, canonical_key: str, scope: str, source_id: str) -> str:
    seed = f"{entity_type}|{canonical_key}"
    if scope != "concept_class":
        seed += f"|{scope}|{source_id}"
    digest = hashlib.sha1(seed.encode("utf-8")).hexdigest()[:8]
    prefix = entity_type[:3].upper()
    return f"N_{prefix}_{digest}"


def deterministic_edge_id(source: str, relation: str, target: str, source_id: str, conditions: str) -> str:
    seed = f"{source}|{relation}|{target}|{source_id}|{conditions}"
    digest = hashlib.sha1(seed.encode("utf-8")).hexdigest()[:8]
    return f"E_{digest}"


def check_homonym_collision(name_a: str, name_b: str, aliases_a: List[str], aliases_b: List[str], rules: Dict[str, Any]) -> Optional[str]:
    guarded = rules.get("guarded_homonyms", {})
    tokens_a = {t.strip() for t in [name_a] + aliases_a if t}
    tokens_b = {t.strip() for t in [name_b] + aliases_b if t}
    for acronym, senses in guarded.items():
        senses_lower = {s.lower() for s in senses}
        a_has_acr = any(t.upper() == acronym for t in tokens_a)
        b_has_acr = any(t.upper() == acronym for t in tokens_b)
        a_senses = {t.lower() for t in tokens_a if t.lower() in senses_lower}
        b_senses = {t.lower() for t in tokens_b if t.lower() in senses_lower}
        if (a_has_acr or a_senses) and (b_has_acr or b_senses):
            if a_senses and b_senses and a_senses != b_senses:
                return f"Guarded homonym '{acronym}' resolved to distinct senses: {sorted(a_senses)} vs {sorted(b_senses)}"
            if a_has_acr and not a_senses and b_has_acr and not b_senses:
                return f"Guarded homonym '{acronym}' lacks disambiguating full-form context in both papers"
    return None


def dedup_provenance(prov_list: List[Dict[str, Any]]) -> List[Dict[str, Any]]:
    seen: Set[Tuple[str, str, str]] = set()
    out: List[Dict[str, Any]] = []
    for p in prov_list:
        key = (str(p.get("source_id", "")), str(p.get("paragraph_id", "")), str(p.get("quote", "")))
        if key not in seen:
            seen.add(key)
            out.append(drop_none_optional(p, {"source_id", "paragraph_id", "location_type", "quote", "evidence_strength"}))
    return out


def integrate_extraction(
    graph: Dict[str, Any],
    extraction: Dict[str, Any],
    rules: Dict[str, Any],
    is_incremental: bool,
) -> Dict[str, Any]:
    non_merge_scopes = set(rules.get("non_merge_scopes", []))
    non_merge_types = set(rules.get("non_merge_entity_types", []))

    existing_nodes_by_id: Dict[str, Dict[str, Any]] = {n["id"]: n for n in graph["nodes"]}
    existing_by_key: Dict[Tuple[str, str], List[Dict[str, Any]]] = defaultdict(list)
    for n in graph["nodes"]:
        existing_by_key[(n["type"], n["canonical_key"])].append(n)

    known_source_ids = {s["source_id"] for s in graph["sources"]}
    for s in extraction.get("sources", []):
        if s["source_id"] not in known_source_ids:
            graph["sources"].append(s)
            known_source_ids.add(s["source_id"])

    local_to_global_id: Dict[str, str] = {}
    added_node_ids: List[str] = []
    merged_node_ids: List[str] = []
    kept_separate_pairs: List[Tuple[str, str]] = []

    for raw_node in extraction.get("nodes", []):
        etype = raw_node["type"]
        scope = raw_node.get("scope") or ("metric_observation" if etype in non_merge_types else "concept_class")
        prov = raw_node.get("provenance", [])
        src_ids = sorted({p.get("source_id", "unknown") for p in prov if isinstance(p, dict)} | set(raw_node.get("source_ids", [])))
        primary_src = src_ids[0] if src_ids else "unknown"

        ckey = normalize_name(raw_node["name"], rules)
        aliases = list(dict.fromkeys(raw_node.get("aliases", [])))
        candidate_keys = [ckey] + [normalize_name(a, rules) for a in aliases]

        matched_node: Optional[Dict[str, Any]] = None
        for ck in candidate_keys:
            for cand in existing_by_key.get((etype, ck), []):
                if scope in non_merge_scopes or cand.get("scope") in non_merge_scopes or etype in non_merge_types:
                    if set(src_ids) != set(cand.get("source_ids", [])):
                        graph["alignment_log"].append({
                            "decision": "kept_separate",
                            "entity_a": f"{cand['name']} ({cand['id']})",
                            "entity_b": f"{raw_node['name']} ({primary_src})",
                            "canonical_id": None,
                            "rule_applied": "non_merge_scope_or_type",
                            "reason": f"Scope/type ({scope}/{etype}) represents paper-specific sample, metric, or conclusion and must not be merged across papers.",
                        })
                        kept_separate_pairs.append((cand["id"], raw_node.get("id", raw_node["name"])))
                    continue

                homonym_err = check_homonym_collision(
                    cand["name"], raw_node["name"], cand.get("aliases", []), aliases, rules
                )
                if homonym_err:
                    graph["alignment_log"].append({
                        "decision": "kept_separate",
                        "entity_a": f"{cand['name']} ({cand['id']})",
                        "entity_b": f"{raw_node['name']} ({primary_src})",
                        "canonical_id": None,
                        "rule_applied": "guarded_homonym_collision",
                        "reason": homonym_err,
                    })
                    graph["conflict_log"].append({
                        "conflict_id": f"CONF_{len(graph['conflict_log']) + 1:03d}",
                        "conflict_type": "homonym_collision",
                        "involved_ids": [cand["id"]],
                        "description": homonym_err,
                        "resolution_policy": "Kept separate as distinct nodes with explicit provenance.",
                        "provenance": dedup_provenance(cand.get("provenance", [])[:1] + prov[:1]),
                    })
                    kept_separate_pairs.append((cand["id"], raw_node.get("id", raw_node["name"])))
                    continue

                matched_node = cand
                break
            if matched_node:
                break

        if matched_node is not None:
            local_to_global_id[raw_node.get("id", raw_node["name"])] = matched_node["id"]
            if raw_node["name"] != matched_node["name"] and raw_node["name"] not in matched_node["aliases"]:
                matched_node["aliases"].append(raw_node["name"])
            for a in aliases:
                if a != matched_node["name"] and a not in matched_node["aliases"]:
                    matched_node["aliases"].append(a)
            matched_node["source_ids"] = sorted(set(matched_node.get("source_ids", [])) | set(src_ids))
            matched_node["provenance"] = dedup_provenance(matched_node.get("provenance", []) + prov)
            merged_node_ids.append(matched_node["id"])
            graph["alignment_log"].append({
                "decision": "merged",
                "entity_a": f"{matched_node['name']} ({matched_node['id']})",
                "entity_b": f"{raw_node['name']} ({primary_src})",
                "canonical_id": matched_node["id"],
                "rule_applied": "canonical_concept_match",
                "reason": f"Matched canonical key '{ckey}' under concept_class scope with compatible entity type '{etype}'.",
            })
        else:
            new_id = raw_node.get("id") if (not is_incremental and raw_node.get("id") and raw_node["id"] not in existing_nodes_by_id) else deterministic_node_id(etype, ckey, scope, primary_src)
            while new_id in existing_nodes_by_id:
                new_id = f"{new_id}_{primary_src}"
            new_node = {
                "id": new_id,
                "name": raw_node["name"],
                "canonical_key": ckey,
                "type": etype,
                "aliases": aliases,
                "scope": scope,
                "attributes": raw_node.get("attributes", {}),
                "source_ids": src_ids,
                "provenance": dedup_provenance(prov),
            }
            graph["nodes"].append(new_node)
            existing_nodes_by_id[new_id] = new_node
            existing_by_key[(etype, ckey)].append(new_node)
            for a in aliases:
                existing_by_key[(etype, normalize_name(a, rules))].append(new_node)
            local_to_global_id[raw_node.get("id", raw_node["name"])] = new_id
            added_node_ids.append(new_id)

    existing_edge_ids = {e["id"] for e in graph["edges"]}
    added_edge_ids: List[str] = []
    for raw_edge in extraction.get("edges", []):
        src = local_to_global_id.get(raw_edge["source"], raw_edge["source"])
        tgt = local_to_global_id.get(raw_edge["target"], raw_edge["target"])
        prov = dedup_provenance(raw_edge.get("provenance", []))
        edge_src_id = prov[0]["source_id"] if prov else "unknown"
        conditions = raw_edge.get("conditions") or ""
        eid = raw_edge.get("id") if (not is_incremental and raw_edge.get("id") and raw_edge["id"] not in existing_edge_ids) else deterministic_edge_id(src, raw_edge["relation"], tgt, edge_src_id, conditions)
        while eid in existing_edge_ids:
            eid = f"{eid}_{len(existing_edge_ids)}"
        edge_obj = drop_none_optional(
            {
                "id": eid,
                "source": src,
                "target": tgt,
                "relation": raw_edge["relation"],
                "claim_origin": raw_edge.get("claim_origin", "author_primary"),
                "conditions": conditions,
                "numeric_value": raw_edge.get("numeric_value"),
                "unit": raw_edge.get("unit"),
                "cross_paper": bool(raw_edge.get("cross_paper", False)),
                "provenance": prov,
            },
            {"id", "source", "target", "relation", "claim_origin", "conditions", "cross_paper", "provenance"},
        )
        for prev in graph["edges"]:
            if prev["source"] == src and prev["target"] == tgt:
                if {prev["relation"], edge_obj["relation"]} == {"SUPPORTS", "CONTRADICTS"}:
                    graph["conflict_log"].append({
                        "conflict_id": f"CONF_{len(graph['conflict_log']) + 1:03d}",
                        "conflict_type": "directional_contradiction",
                        "involved_ids": [prev["id"], eid],
                        "description": f"Conflicting relations ({prev['relation']} vs {edge_obj['relation']}) between {src} and {tgt}.",
                        "resolution_policy": "Both edges preserved with independent provenance and conditions.",
                        "provenance": dedup_provenance(prev["provenance"][:1] + prov[:1]),
                    })
                elif prev["relation"] == edge_obj["relation"] and prev.get("numeric_value") is not None and edge_obj.get("numeric_value") is not None and str(prev["numeric_value"]) != str(edge_obj["numeric_value"]):
                    u1 = f" {prev['unit']}" if prev.get("unit") else ""
                    u2 = f" {edge_obj['unit']}" if edge_obj.get("unit") else ""
                    graph["conflict_log"].append({
                        "conflict_id": f"CONF_{len(graph['conflict_log']) + 1:03d}",
                        "conflict_type": "metric_discrepancy",
                        "involved_ids": [prev["id"], eid],
                        "description": f"Different numeric values ({prev['numeric_value']}{u1} vs {edge_obj['numeric_value']}{u2}) for {src} -[{prev['relation']}]-> {tgt}.",
                        "resolution_policy": "Preserved both paper-scoped measurements without collapsing conditions.",
                        "provenance": dedup_provenance(prev["provenance"][:1] + prov[:1]),
                    })

        graph["edges"].append(edge_obj)
        existing_edge_ids.add(eid)
        added_edge_ids.append(eid)

    for c in extraction.get("conflict_log", []):
        graph["conflict_log"].append(c)
    for u in extraction.get("unreported_items", []):
        graph["unreported_items"].append(u)
    for ch in extraction.get("change_records", []):
        graph.setdefault("change_records", []).append(ch)

    if is_incremental:
        graph.setdefault("update_history", []).append({
            "operation": "incremental_update",
            "added_nodes": added_node_ids,
            "merged_nodes": sorted(set(merged_node_ids)),
            "kept_separate_count": len(kept_separate_pairs),
            "added_edges": added_edge_ids,
        })
    return graph


def find_matching_nodes(graph: Dict[str, Any], query_str: str) -> List[Dict[str, Any]]:
    q = (query_str or "").strip().lower()
    if not q:
        return []
    matches = []
    for n in graph["nodes"]:
        hay = [n["id"].lower(), n["name"].lower(), n.get("canonical_key", "").lower()] + [a.lower() for a in n.get("aliases", [])]
        if any(q == h or q in h for h in hay):
            matches.append(n)
    return matches


def run_queries(graph: Dict[str, Any], queries_spec: Dict[str, Any]) -> List[Dict[str, Any]]:
    nodes_by_id = {n["id"]: n for n in graph["nodes"]}
    adj: Dict[str, List[Dict[str, Any]]] = defaultdict(list)
    for e in graph["edges"]:
        adj[e["source"]].append(e)
        adj[e["target"]].append(e)

    results: List[Dict[str, Any]] = []
    for q in queries_spec.get("queries", []):
        qid = q["query_id"]
        qtype = q["query_type"]
        question = q["question"]
        params = q.get("params", {})

        if qtype == "entity_neighborhood":
            seeds = find_matching_nodes(graph, params.get("entity_query", ""))
            if not seeds:
                results.append({
                    "query_id": qid,
                    "question": question,
                    "status": "undeterminable",
                    "matched_node_ids": [],
                    "matched_edge_ids": [],
                    "evidence_chains": [],
                    "undeterminable_reason": f"No entity matching '{params.get('entity_query')}' found in the graph.",
                })
                continue
            node_ids = {s["id"] for s in seeds}
            edge_ids: Set[str] = set()
            for sid in list(node_ids):
                for e in adj[sid]:
                    edge_ids.add(e["id"])
                    node_ids.add(e["source"])
                    node_ids.add(e["target"])
            matched_edges = [e for e in graph["edges"] if e["id"] in edge_ids]
            entry: Dict[str, Any] = {
                "query_id": qid,
                "question": question,
                "status": "answered" if matched_edges else "partial",
                "matched_node_ids": sorted(node_ids),
                "matched_edge_ids": sorted(edge_ids),
                "evidence_chains": [
                    {
                        "edge_id": e["id"],
                        "triple": f"{nodes_by_id[e['source']]['name']} -[{e['relation']}]-> {nodes_by_id[e['target']]['name']}",
                        "claim_origin": e["claim_origin"],
                        "conditions": e.get("conditions", ""),
                        "provenance": e["provenance"],
                    }
                    for e in matched_edges
                ],
            }
            if not matched_edges:
                entry["undeterminable_reason"] = "Entity exists, but no incident edges were reported in the corpus."
            results.append(entry)

        elif qtype == "cross_paper_compare":
            min_src = int(params.get("min_sources", 2))
            shared = [n for n in graph["nodes"] if len(set(n.get("source_ids", []))) >= min_src]
            if not shared:
                results.append({
                    "query_id": qid,
                    "question": question,
                    "status": "undeterminable",
                    "matched_node_ids": [],
                    "matched_edge_ids": [],
                    "evidence_chains": [],
                    "undeterminable_reason": f"No canonical entity appears across >= {min_src} independent sources.",
                })
                continue
            shared_ids = {n["id"] for n in shared}
            rel_edges = [e for e in graph["edges"] if e["source"] in shared_ids or e["target"] in shared_ids]
            results.append({
                "query_id": qid,
                "question": question,
                "status": "answered",
                "matched_node_ids": sorted(shared_ids),
                "matched_edge_ids": [e["id"] for e in rel_edges],
                "evidence_chains": [
                    drop_none_optional(
                        {
                            "edge_id": e["id"],
                            "triple": f"{nodes_by_id[e['source']]['name']} -[{e['relation']}]-> {nodes_by_id[e['target']]['name']}",
                            "conditions": e.get("conditions", ""),
                            "numeric_value": e.get("numeric_value"),
                            "unit": e.get("unit"),
                            "provenance": e["provenance"],
                        },
                        {"edge_id", "triple", "conditions", "provenance"},
                    )
                    for e in rel_edges
                ],
            })

        elif qtype == "conflict_audit":
            conflicts = graph.get("conflict_log", [])
            secondary_edges = [e for e in graph["edges"] if e.get("claim_origin") != "author_primary"] if params.get("include_secondary_citations", True) else []
            results.append({
                "query_id": qid,
                "question": question,
                "status": "answered",
                "matched_node_ids": sorted({nid for c in conflicts for nid in c.get("involved_ids", []) if nid in nodes_by_id}),
                "matched_edge_ids": sorted({eid for c in conflicts for eid in c.get("involved_ids", []) if eid not in nodes_by_id} | {e["id"] for e in secondary_edges}),
                "evidence_chains": [
                    {
                        "conflict_id": c["conflict_id"],
                        "conflict_type": c["conflict_type"],
                        "description": c["description"],
                        "resolution_policy": c.get("resolution_policy", ""),
                        "provenance": c.get("provenance", []),
                    }
                    for c in conflicts
                ] + [
                    {
                        "edge_id": e["id"],
                        "claim_origin": e["claim_origin"],
                        "triple": f"{nodes_by_id[e['source']]['name']} -[{e['relation']}]-> {nodes_by_id[e['target']]['name']}",
                        "provenance": e["provenance"],
                    }
                    for e in secondary_edges
                ],
            })

        elif qtype == "path_check":
            src_nodes = find_matching_nodes(graph, params.get("source_entity", ""))
            tgt_nodes = find_matching_nodes(graph, params.get("target_entity", ""))
            max_hops = int(params.get("max_hops", 3))
            if not src_nodes or not tgt_nodes:
                results.append({
                    "query_id": qid,
                    "question": question,
                    "status": "undeterminable",
                    "matched_node_ids": [],
                    "matched_edge_ids": [],
                    "evidence_chains": [],
                    "undeterminable_reason": f"Endpoint not found in corpus (source='{params.get('source_entity')}', target='{params.get('target_entity')}').",
                })
                continue
            target_set = {n["id"] for n in tgt_nodes}
            found_path: Optional[List[Dict[str, Any]]] = None
            queue = deque([(s["id"], []) for s in src_nodes])
            visited = {s["id"] for s in src_nodes}
            while queue and found_path is None:
                curr, path = queue.popleft()
                if len(path) >= max_hops:
                    continue
                for e in adj[curr]:
                    nxt = e["target"] if e["source"] == curr else e["source"]
                    new_path = path + [e]
                    if nxt in target_set:
                        found_path = new_path
                        break
                    if nxt not in visited:
                        visited.add(nxt)
                        queue.append((nxt, new_path))
            if found_path is None:
                results.append({
                    "query_id": qid,
                    "question": question,
                    "status": "undeterminable",
                    "matched_node_ids": sorted({n["id"] for n in src_nodes + tgt_nodes}),
                    "matched_edge_ids": [],
                    "evidence_chains": [],
                    "undeterminable_reason": f"No evidence-backed relation path within {max_hops} hops between '{params.get('source_entity')}' and '{params.get('target_entity')}' in the provided papers.",
                })
            else:
                path_nids = sorted({e["source"] for e in found_path} | {e["target"] for e in found_path})
                results.append({
                    "query_id": qid,
                    "question": question,
                    "status": "answered",
                    "matched_node_ids": path_nids,
                    "matched_edge_ids": [e["id"] for e in found_path],
                    "evidence_chains": [
                        {
                            "edge_id": e["id"],
                            "triple": f"{nodes_by_id[e['source']]['name']} -[{e['relation']}]-> {nodes_by_id[e['target']]['name']}",
                            "provenance": e["provenance"],
                        }
                        for e in found_path
                    ],
                })
    return results


def export_graphml(graph: Dict[str, Any], out_path: Path) -> None:
    ns = "http://graphml.graphdrawing.org/xmlns"
    ET.register_namespace("", ns)
    root = ET.Element(f"{{{ns}}}graphml")
    keys = [
        ("d0", "node", "name", "string"),
        ("d1", "node", "type", "string"),
        ("d2", "node", "sources", "string"),
        ("d3", "edge", "relation", "string"),
        ("d4", "edge", "claim_origin", "string"),
        ("d5", "edge", "provenance", "string"),
    ]
    for kid, kfor, kname, ktype in keys:
        ET.SubElement(root, f"{{{ns}}}key", id=kid, **{"for": kfor, "attr.name": kname, "attr.type": ktype})
    g_el = ET.SubElement(root, f"{{{ns}}}graph", id="scientific_kg", edgedefault="directed")
    for n in graph["nodes"]:
        n_el = ET.SubElement(g_el, f"{{{ns}}}node", id=str(n["id"]))
        ET.SubElement(n_el, f"{{{ns}}}data", key="d0").text = str(n.get("name") or "")
        ET.SubElement(n_el, f"{{{ns}}}data", key="d1").text = str(n.get("type") or "")
        ET.SubElement(n_el, f"{{{ns}}}data", key="d2").text = ",".join(str(s) for s in n.get("source_ids", []) if s)
    for e in graph["edges"]:
        e_el = ET.SubElement(g_el, f"{{{ns}}}edge", id=str(e["id"]), source=str(e["source"]), target=str(e["target"]))
        ET.SubElement(e_el, f"{{{ns}}}data", key="d3").text = str(e.get("relation") or "")
        ET.SubElement(e_el, f"{{{ns}}}data", key="d4").text = str(e.get("claim_origin") or "")
        prov_summary = "; ".join(f"{p['source_id']}:{p['paragraph_id']}" for p in e.get("provenance", []) if p.get("source_id"))
        ET.SubElement(e_el, f"{{{ns}}}data", key="d5").text = prov_summary
    out_path.write_text(ET.tostring(root, encoding="unicode", xml_declaration=True), encoding="utf-8")


def export_markdown_report(graph: Dict[str, Any], query_results: List[Dict[str, Any]], out_path: Path) -> None:
    nodes_by_id = {n["id"]: n for n in graph["nodes"]}
    lines = [
        "# Scientific Literature Knowledge Graph Report",
        "",
        f"- **Topic:** {graph.get('topic') or 'N/A'}",
        f"- **Sources:** {len(graph['sources'])} ({', '.join(s['source_id'] for s in graph['sources'])})",
        f"- **Nodes:** {len(graph['nodes'])} | **Edges:** {len(graph['edges'])} | **Alignments:** {len(graph['alignment_log'])} | **Conflicts:** {len(graph['conflict_log'])}",
        "",
        "## Graph Overview (Mermaid)",
        "```mermaid",
        "graph LR",
    ]
    for e in graph["edges"][:40]:
        s_name = nodes_by_id[e["source"]]["name"].replace('"', "'")
        t_name = nodes_by_id[e["target"]]["name"].replace('"', "'")
        lines.append(f'  {e["source"]}["{s_name}"] -->|"{e["relation"]}"| {e["target"]}["{t_name}"]')
    lines.extend(["```", "", "## Alignment Decisions"])
    for a in graph["alignment_log"]:
        lines.append(f"- **{a['decision']}**: `{a['entity_a']}` vs `{a['entity_b']}` — {a['reason']}")
    lines.extend(["", "## Conflicts & Preserved Discrepancies"])
    if not graph["conflict_log"]:
        lines.append("- None detected.")
    for c in graph["conflict_log"]:
        lines.append(f"- **{c['conflict_id']} ({c['conflict_type']})**: {c['description']} *(Policy: {c.get('resolution_policy', '')})*")
    lines.extend(["", "## Executed Queries"])
    for q in query_results:
        lines.append(f"- **{q['query_id']}** (`{q['status']}`): {q['question']}")
        if q.get("undeterminable_reason"):
            lines.append(f"  - *Undeterminable reason:* {q['undeterminable_reason']}")
    out_path.write_text("\n".join(lines) + "\n", encoding="utf-8")


def main() -> None:
    parser = argparse.ArgumentParser(description="Scientific Literature Knowledge Graph Engine")
    sub = parser.add_subparsers(dest="cmd", required=True)

    p_build = sub.add_parser("build")
    p_build.add_argument("--extraction", required=True)
    p_build.add_argument("--rules", required=True)
    p_build.add_argument("--output", required=True)

    p_upd = sub.add_parser("update")
    p_upd.add_argument("--base-graph", required=True)
    p_upd.add_argument("--extraction", required=True)
    p_upd.add_argument("--rules", required=True)
    p_upd.add_argument("--output", required=True)

    p_qry = sub.add_parser("query")
    p_qry.add_argument("--graph", required=True)
    p_qry.add_argument("--queries", required=True)
    p_qry.add_argument("--output", required=True)

    p_exp = sub.add_parser("export")
    p_exp.add_argument("--graph", required=True)
    p_exp.add_argument("--query-results", required=True)
    p_exp.add_argument("--case-json", required=True)
    p_exp.add_argument("--corpus-index", required=True)
    p_exp.add_argument("--output-dir", required=True)

    args = parser.parse_args()

    if args.cmd == "build":
        extraction = load_json(Path(args.extraction))
        rules = load_json(Path(args.rules))
        graph = {
            "schema_version": "1.1.0",
            "topic": extraction.get("topic", ""),
            "sources": [],
            "nodes": [],
            "edges": [],
            "alignment_log": [],
            "conflict_log": [],
            "update_history": [],
            "change_records": [],
            "unreported_items": [],
        }
        graph = integrate_extraction(graph, extraction, rules, is_incremental=False)
        save_json(Path(args.output), graph)
        print(f"Built base KG: {len(graph['nodes'])} nodes, {len(graph['edges'])} edges -> {args.output}")

    elif args.cmd == "update":
        graph = load_json(Path(args.base_graph))
        extraction = load_json(Path(args.extraction))
        rules = load_json(Path(args.rules))
        graph = integrate_extraction(graph, extraction, rules, is_incremental=True)
        save_json(Path(args.output), graph)
        print(f"Incrementally updated KG: {len(graph['nodes'])} nodes, {len(graph['edges'])} edges -> {args.output}")

    elif args.cmd == "query":
        graph = load_json(Path(args.graph))
        qspec = load_json(Path(args.queries))
        qres = run_queries(graph, qspec)
        save_json(Path(args.output), {"queries": qres})
        print(f"Executed {len(qres)} queries -> {args.output}")

    elif args.cmd == "export":
        graph = load_json(Path(args.graph))
        qres_wrap = load_json(Path(args.query_results))
        query_results = qres_wrap.get("queries", qres_wrap) if isinstance(qres_wrap, dict) else qres_wrap
        case_json = load_json(Path(args.case_json)) if Path(args.case_json).exists() else {}
        corpus_idx = load_json(Path(args.corpus_index)) if Path(args.corpus_index).exists() else {}

        out_dir = Path(args.output_dir)
        out_dir.mkdir(parents=True, exist_ok=True)

        save_json(out_dir / "knowledge_graph.json", graph)
        export_graphml(graph, out_dir / "knowledge_graph.graphml")
        export_markdown_report(graph, query_results, out_dir / "knowledge_graph_report.md")

        status = "success"
        if corpus_idx.get("needs_ocr_review"):
            status = "undeterminable"
        elif corpus_idx.get("warnings") and len(graph["sources"]) < 2 and len(corpus_idx.get("sources", [])) >= 2:
            status = "partial"

        result_payload: Dict[str, Any] = {
            "case_id": case_json.get("case_id", corpus_idx.get("case_id", "unknown_case")),
            "status": status,
            "sources": graph["sources"],
            "knowledge_graph": {
                "node_count": len(graph["nodes"]),
                "edge_count": len(graph["edges"]),
                "nodes": graph["nodes"],
                "edges": graph["edges"],
            },
            "alignment_log": graph["alignment_log"],
            "conflict_log": graph["conflict_log"],
            "update_history": graph.get("update_history", []),
            "query_results": query_results,
            "unreported_items": graph["unreported_items"],
            "change_records": graph.get("change_records", []),
            "warnings": corpus_idx.get("warnings", []),
            "artifacts": [
                "knowledge_graph.json",
                "knowledge_graph.graphml",
                "knowledge_graph_report.md",
                "quality_audit.json",
            ],
        }

        for rk in extract_contract_fields(case_json):
            if rk not in result_payload:
                if rk in ("answer", "summary", "conclusion"):
                    result_payload[rk] = (
                        f"Constructed provenance-bound KG with {len(graph['nodes'])} nodes, "
                        f"{len(graph['edges'])} edges, and {len(query_results)} traceable queries."
                    )
                elif rk in ("evidence", "provenance"):
                    result_payload[rk] = [p for e in graph["edges"] for p in e.get("provenance", [])]
                elif rk in ("uncertainties", "limitations"):
                    result_payload[rk] = graph["unreported_items"]
                else:
                    result_payload[rk] = ""

        save_json(out_dir / "result.json", result_payload)
        print(f"Exported Harbor deliverables -> {out_dir}")


if __name__ == "__main__":
    main()
