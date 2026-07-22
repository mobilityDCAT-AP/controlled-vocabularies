#!/usr/bin/env python3
from __future__ import annotations

import argparse
import html
import re
import sys
import zipfile
import xml.etree.ElementTree as ET
from dataclasses import dataclass
from pathlib import Path

NS_MAIN = "http://schemas.openxmlformats.org/spreadsheetml/2006/main"
NS_REL = "http://schemas.openxmlformats.org/officeDocument/2006/relationships"
DEPRECATED_VALUES = {"1", "true", "yes"}


@dataclass
class Concept:
    row_index: int
    uri: str
    label_en: str
    narrower: list[str]
    broader: str
    deprecated: bool


def parse_args() -> argparse.Namespace:
    script_dir = Path(__file__).resolve().parent
    vocabulary_dir = script_dir.parent
    default_xlsx = vocabulary_dir / f"{vocabulary_dir.name}.xlsx"

    parser = argparse.ArgumentParser(
        description=(
            "Generate the hierarchy tree in description-en.html from a vocabulary workbook "
            "using broader/narrower relationships while preserving Excel order and skipping "
            "deprecated concepts."
        )
    )
    parser.add_argument(
        "--xlsx",
        type=Path,
        default=default_xlsx,
        help="Path to the vocabulary .xlsx file",
    )
    parser.add_argument(
        "--output",
        type=Path,
        default=None,
        help="Path to description-en.html (auto-detected if omitted)",
    )
    parser.add_argument(
        "--sheet",
        default="Vocabulary",
        help="Worksheet name containing vocabulary concepts",
    )
    return parser.parse_args()


def parse_shared_strings(workbook: zipfile.ZipFile) -> list[str]:
    path = "xl/sharedStrings.xml"
    if path not in workbook.namelist():
        return []

    root = ET.fromstring(workbook.read(path))
    shared_strings: list[str] = []

    for item in root.findall(f"{{{NS_MAIN}}}si"):
        text_nodes = item.findall(f".//{{{NS_MAIN}}}t")
        shared_strings.append("".join((node.text or "") for node in text_nodes))

    return shared_strings


def resolve_sheet_path(workbook: zipfile.ZipFile, sheet_name: str) -> str:
    workbook_root = ET.fromstring(workbook.read("xl/workbook.xml"))
    rels_root = ET.fromstring(workbook.read("xl/_rels/workbook.xml.rels"))

    relationships: dict[str, str] = {}
    for relationship in rels_root:
        rel_id = relationship.attrib.get("Id")
        target = relationship.attrib.get("Target")
        if rel_id and target:
            relationships[rel_id] = target

    sheets_element = workbook_root.find(f"{{{NS_MAIN}}}sheets")
    if sheets_element is None:
        raise ValueError("Workbook has no sheets element.")

    for sheet in sheets_element:
        if sheet.attrib.get("name") != sheet_name:
            continue
        relation_id = sheet.attrib.get(f"{{{NS_REL}}}id")
        if not relation_id:
            break
        target = relationships.get(relation_id)
        if not target:
            break
        return f"xl/{target}" if not target.startswith("xl/") else target

    available = ", ".join(sheet.attrib.get("name", "") for sheet in sheets_element)
    raise ValueError(f"Sheet '{sheet_name}' not found. Available sheets: {available}")


def parse_uri_list(value: str) -> list[str]:
    if not value:
        return []
    return [part.strip() for part in value.split(",") if part.strip()]


def parse_cell_value(cell: ET.Element, shared_strings: list[str]) -> str:
    cell_type = cell.attrib.get("t")
    value_node = cell.find(f"{{{NS_MAIN}}}v")

    if cell_type == "s" and value_node is not None:
        index = int(value_node.text)
        return shared_strings[index] if index < len(shared_strings) else ""

    if cell_type == "inlineStr":
        inline_string = cell.find(f"{{{NS_MAIN}}}is")
        if inline_string is None:
            return ""
        text_nodes = inline_string.findall(f".//{{{NS_MAIN}}}t")
        return "".join((node.text or "") for node in text_nodes)

    return "" if value_node is None or value_node.text is None else value_node.text


def parse_concepts(xlsx_path: Path, sheet_name: str) -> tuple[str, list[Concept]]:
    with zipfile.ZipFile(xlsx_path) as workbook:
        shared_strings = parse_shared_strings(workbook)
        sheet_path = resolve_sheet_path(workbook, sheet_name)
        sheet_root = ET.fromstring(workbook.read(sheet_path))

    sheet_data = sheet_root.find(f"{{{NS_MAIN}}}sheetData")
    if sheet_data is None:
        return "", []

    concepts: list[Concept] = []
    concept_table_started = False
    vocabulary_uri = ""

    for row in sheet_data.findall(f"{{{NS_MAIN}}}row"):
        row_index = int(row.attrib.get("r", "0"))
        cells_by_column: dict[str, str] = {}

        for cell in row.findall(f"{{{NS_MAIN}}}c"):
            cell_ref = cell.attrib.get("r", "")
            column_match = re.match(r"[A-Z]+", cell_ref)
            if not column_match:
                continue
            column = column_match.group(0)
            cells_by_column[column] = parse_cell_value(cell, shared_strings).strip()

        if cells_by_column.get("A", "") == "ConceptScheme URI":
            vocabulary_uri = cells_by_column.get("B", "").strip()

        uri = cells_by_column.get("A", "")
        if uri == "URI":
            concept_table_started = True
            continue
        if not concept_table_started:
            continue
        if not uri:
            continue
        if vocabulary_uri:
            vocabulary_prefix = vocabulary_uri.rstrip("/") + "/"
            if uri != vocabulary_uri and not uri.startswith(vocabulary_prefix):
                continue
        if not re.match(r"^https?://", uri):
            continue

        label_en = cells_by_column.get("B", "")
        broader = cells_by_column.get("F", "")
        deprecated_raw = cells_by_column.get("G", "").lower()

        concepts.append(
            Concept(
                row_index=row_index,
                uri=uri,
                label_en=label_en,
                narrower=parse_uri_list(cells_by_column.get("E", "")),
                broader=broader,
                deprecated=deprecated_raw in DEPRECATED_VALUES,
            )
        )

    return vocabulary_uri, concepts


def concept_fragment(uri: str) -> str:
    return uri.rsplit("/", 1)[-1]


def build_children_map(
    vocabulary_uri: str, concepts: list[Concept]
) -> tuple[dict[str, Concept], dict[str, list[str]]]:
    by_uri = {concept.uri: concept for concept in concepts}
    children_by_parent: dict[str, list[str]] = {concept.uri: [] for concept in concepts}

    # Preserve explicit narrower order from Excel.
    for parent in concepts:
        if parent.deprecated:
            continue
        seen_children: set[str] = set()
        for child_uri in parent.narrower:
            child = by_uri.get(child_uri)
            if child is None or child.deprecated:
                continue
            if child_uri in seen_children:
                continue
            seen_children.add(child_uri)
            children_by_parent[parent.uri].append(child_uri)

    # Use broader as a fallback only for top-level parents lacking explicit narrower values.
    for child in concepts:
        if child.deprecated or not child.broader:
            continue
        parent = by_uri.get(child.broader)
        if parent is None or parent.deprecated:
            continue
        is_top_level_parent = not parent.broader or parent.broader == vocabulary_uri
        if parent.narrower or not is_top_level_parent:
            continue
        if child.uri not in children_by_parent[parent.uri]:
            children_by_parent[parent.uri].append(child.uri)

    return by_uri, children_by_parent


def select_render_roots(
    vocabulary_uri: str,
    concepts: list[Concept],
    by_uri: dict[str, Concept],
    children_by_parent: dict[str, list[str]],
) -> list[Concept]:
    incoming: set[str] = set()
    for child_uris in children_by_parent.values():
        incoming.update(child_uris)

    def remove_incoming_root_duplicates(roots: list[Concept]) -> list[Concept]:
        filtered = [root for root in roots if root.uri not in incoming]
        return filtered if filtered else roots

    non_deprecated = [concept for concept in concepts if not concept.deprecated]

    direct_scheme_children = [
        concept for concept in non_deprecated if vocabulary_uri and concept.broader == vocabulary_uri
    ]

    root_candidates = [concept for concept in non_deprecated if not concept.broader]
    root_uris = {concept.uri for concept in root_candidates}

    orphan_roots = [
        concept
        for concept in non_deprecated
        if concept.broader
        and concept.uri not in root_uris
        and (concept.broader not in by_uri or by_uri[concept.broader].deprecated)
    ]

    if direct_scheme_children:
        return remove_incoming_root_duplicates(direct_scheme_children)

    combined_roots = root_candidates + orphan_roots
    if len(combined_roots) == 1:
        only_root = combined_roots[0]
        child_uris = children_by_parent.get(only_root.uri, [])
        children = [by_uri[child_uri] for child_uri in child_uris if child_uri in by_uri]
        if children:
            broader_child_count: dict[str, int] = {}
            for concept in non_deprecated:
                if concept.broader:
                    broader_child_count[concept.broader] = broader_child_count.get(concept.broader, 0) + 1

            filtered_children = [
                child
                for child in children
                if child.narrower or broader_child_count.get(child.uri, 0) < 3
            ]
            candidate_children = filtered_children if filtered_children else children
            return remove_incoming_root_duplicates(candidate_children)

    if combined_roots:
        return remove_incoming_root_duplicates(combined_roots)

    # Fallback: use nodes without incoming links in the computed tree.
    fallback_roots = [concept for concept in non_deprecated if concept.uri not in incoming]
    candidate_roots = fallback_roots if fallback_roots else non_deprecated
    return remove_incoming_root_duplicates(candidate_roots)


def build_tree(
    vocabulary_uri: str, concepts: list[Concept]
) -> tuple[list[Concept], dict[str, Concept], dict[str, list[str]]]:
    by_uri, children_by_parent = build_children_map(vocabulary_uri, concepts)
    roots = select_render_roots(vocabulary_uri, concepts, by_uri, children_by_parent)
    return roots, by_uri, children_by_parent


def render_tree_html(
    roots: list[Concept], by_uri: dict[str, Concept], children_by_parent: dict[str, list[str]]
) -> str:
    def render_node(uri: str, depth: int, lineage: set[str], lines: list[str]) -> None:
        if uri in lineage:
            return

        concept = by_uri[uri]
        indent = "  " * depth
        lines.append(f'{indent}<li id="">')
        lines.append(
            f'{indent}  <a href="#/{concept_fragment(concept.uri)}">'
            f"{html.escape(concept.label_en)}</a>"
        )

        child_uris = [
            child_uri
            for child_uri in children_by_parent.get(uri, [])
            if child_uri in by_uri and not by_uri[child_uri].deprecated
        ]
        if child_uris:
            lines.append(f"{indent}  <ul>")
            next_lineage = set(lineage)
            next_lineage.add(uri)
            for child_uri in child_uris:
                render_node(child_uri, depth + 2, next_lineage, lines)
            lines.append(f"{indent}  </ul>")

        lines.append(f"{indent}</li>")

    lines: list[str] = []
    lines.append("<div class=\"display\">")
    lines.append("  <ul class=\"tree\">")

    for root in roots:
        render_node(root.uri, 2, set(), lines)

    lines.append("  </ul>")
    lines.append("</div>")
    return "\n".join(lines)


def replace_tree_block(document: str, generated_tree: str) -> str:
    display_marker = '<div class="display">'
    toc_marker = '<div id="toc"></div>'

    display_start = document.find(display_marker)
    toc_start = document.find(toc_marker)

    if display_start != -1:
        if toc_start == -1:
            toc_start = len(document)
        if toc_start <= display_start:
            raise ValueError("Unexpected display/toc ordering in description-en.html")

        display_end = document.rfind("</div>", display_start, toc_start)
        if display_end == -1:
            raise ValueError("Could not find display block end in description-en.html")
        return document[:display_start] + generated_tree + document[display_end + len("</div>") :]

    if toc_start != -1:
        return document[:toc_start] + generated_tree + "\n\n" + document[toc_start:]

    trimmed = document.rstrip()
    return trimmed + "\n\n" + generated_tree + "\n"


def resolve_output_path(xlsx_path: Path, output_arg: Path | None) -> Path:
    if output_arg is not None:
        return output_arg.resolve()

    vocabulary_dir = xlsx_path.parent
    candidate_standard = vocabulary_dir / "sections" / "description-en.html"
    candidate_latest = vocabulary_dir / "latest" / "sections" / "description-en.html"

    if candidate_standard.exists():
        return candidate_standard.resolve()
    if candidate_latest.exists():
        return candidate_latest.resolve()
    return candidate_standard.resolve()


def main() -> int:
    args = parse_args()

    xlsx_path = args.xlsx.resolve()
    output_path = resolve_output_path(xlsx_path, args.output)

    if not xlsx_path.exists():
        print(f"Error: xlsx file not found at {xlsx_path}", file=sys.stderr)
        return 1
    if not output_path.exists():
        print(f"Error: output file not found at {output_path}", file=sys.stderr)
        return 1

    vocabulary_uri, concepts = parse_concepts(xlsx_path, args.sheet)
    if not vocabulary_uri:
        print("Error: ConceptScheme URI not found in the workbook metadata.", file=sys.stderr)
        return 1
    if not concepts:
        print("Error: no concepts parsed from workbook.", file=sys.stderr)
        return 1

    roots, by_uri, children_by_parent = build_tree(vocabulary_uri, concepts)
    generated_tree = render_tree_html(roots, by_uri, children_by_parent)

    original_document = output_path.read_text(encoding="utf-8")
    updated_document = replace_tree_block(original_document, generated_tree)
    output_path.write_text(updated_document, encoding="utf-8")

    rendered_nodes = sum(1 for concept in concepts if not concept.deprecated)
    print(
        f"Updated {output_path} from {xlsx_path} (roots: {len(roots)}, "
        f"non-deprecated concepts: {rendered_nodes})."
    )

    return 0


if __name__ == "__main__":
    raise SystemExit(main())
