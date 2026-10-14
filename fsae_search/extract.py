"""Deterministic extraction for the supplied 2027 V1 layout, with PDF provenance."""
import collections
import hashlib
import json
from pathlib import Path
import re

import fitz

ROOT = Path(__file__).resolve().parents[1]
PDF = ROOT / 'FSAE_Rules_2027_V1.pdf'
PREFIX = r'(?:GR|AD|PS|V|F|T|VE|IC|EV|IN|S|D)'
RULE = re.compile(r'^(' + PREFIX + r'(?:\.\d+){1,3})(?=\s|$)')
REFERENCE = re.compile(r'\b(' + PREFIX + r'(?:\.\d+){1,3})(?:\.([a-z]))?\b')
CATEGORY = re.compile(r'^(' + PREFIX + r')\s*[-–]\s*(.+)$')
TABLE = re.compile(r'^Table ([A-Z]+-\d+)\s+(.+)$')


def extract(pdf=PDF):
    pdf = Path(pdf)
    doc = fitz.open(pdf)
    for page_number, page in enumerate(doc, 1):
        label = re.search(r'Page\s+(\d+)\s+of\s+' + str(len(doc)), page.get_text())
        assert label and int(label[1]) == page_number, 'Printed/PDF page mismatch'
    sha = hashlib.sha256(pdf.read_bytes()).hexdigest()
    document_id = 'fsae:2027:v1:' + sha[:12]
    bookmark_titles = {}
    bookmark_pages = {}
    categories = {}
    for level, title, page in doc.get_toc():
        if level == 1:
            m = CATEGORY.match(title)
            assert m, title
            categories[m[1]] = m[2].strip()
        else:
            rid, heading = title.split(' ', 1)
            bookmark_titles[rid] = re.sub(r'\s+\)', ')', heading.strip())
            bookmark_pages[rid] = page

    # A separate line stream retains provenance and allows later layout review.
    lines, starts = [], []
    for page_index, page in enumerate(doc):
        if page_index < 4:  # Cover, contents, revision summary are not rules.
            continue
        page_lines = []
        for block in page.get_text('dict')['blocks']:
            for line in block.get('lines', []):
                text = ''.join(span['text'] for span in line['spans']).strip()
                x0, y0, x1, y1 = line['bbox']
                if not text or y0 >= 745:
                    continue
                page_lines.append(dict(page=page_index + 1, bbox=[round(v, 3) for v in line['bbox']], text=text))
        # Word places rule IDs and their titles in separate text runs on one row.
        page_lines.sort(key=lambda line: (round(line['bbox'][1], 1), line['bbox'][0]))
        for line in page_lines:
            position = len(lines)
            lines.append(line)
            if abs(line['bbox'][0] - 72.024) > 0.2:
                continue  # Inline references and table cells are not definitions.
            table = TABLE.match(line['text'])
            if table:
                starts.append((position, '@table:' + table[1]))
                continue
            m = RULE.match(line['text'])
            category = CATEGORY.match(line['text'])
            if m:
                starts.append((position, m[1]))
            elif category:
                starts.append((position, category[1]))

    ids = [rid for _, rid in starts if '.' in rid]
    assert len(ids) == len(set(ids)), 'Duplicate rule definitions'
    assert set(bookmark_titles) <= set(ids), 'Missing bookmarked definition'
    nodes, tables = [], []
    for number, (start, rid) in enumerate(starts):
        end = starts[number + 1][0] if number + 1 < len(starts) else len(lines)
        source = lines[start:end]
        if rid.startswith('@table:'):
            match = TABLE.match(source[0]['text'])
            tables.append(dict(asset_id=rid[len('@table:'):], kind='table', title=match[2],
                               page=source[0]['page'], text='\n'.join(line['text'] for line in source),
                               line_start=start, line_end_exclusive=end,
                               review_status='Cell relationships and headings require visual review'))
            continue
        if '.' not in rid:
            continue
        raw = '\n'.join(line['text'] for line in source)
        text = re.sub(r'^' + re.escape(rid) + r'\s*', '', raw).strip()
        title = bookmark_titles.get(rid)
        if title:
            text = re.sub(r'^' + re.escape(title) + r'\s*', '', text, flags=re.IGNORECASE).strip()
        depth = rid.count('.')
        ancestors = ['.'.join(rid.split('.')[:k]) for k in range(1, depth + 1)]
        next_line = lines[end] if end < len(lines) else None
        region_last_page = next_line['page'] if next_line else len(doc)
        regions = []
        for page_number in range(source[0]['page'], region_last_page + 1):
            top = source[0]['bbox'][1] if page_number == source[0]['page'] else 65
            bottom = next_line['bbox'][1] if next_line and page_number == next_line['page'] else 745
            if bottom > top:
                regions.append(dict(page=page_number, bbox=[72, top, 546, bottom]))
        nodes.append(dict(
            node_id=document_id + ':' + rid, rule_id=rid, document_id=document_id,
            kind={1: 'article', 2: 'section', 3: 'paragraph'}[depth],
            parent_rule_id=rid.rsplit('.', 1)[0], ancestor_rule_ids=ancestors,
            title=title, text=text, children=[],
            source=dict(page_start=source[0]['page'], page_end=source[-1]['page'],
                        line_start=start, line_end_exclusive=end,
                        start_bbox=source[0]['bbox'],
                        pdf_fragment='#page=' + str(source[0]['page']), regions=regions),
        ))
    by_id = {node['rule_id']: node for node in nodes}
    for node in nodes:
        numbered_parent = node['parent_rule_id']
        if '.' in numbered_parent and numbered_parent not in by_id:
            node['missing_numbered_parent'] = numbered_parent
            # The supplied PDF skips D.8.1 but prints D.8.1.1 through D.8.1.7.
            # Attach to the nearest actual heading; never invent a source rule.
            node['parent_rule_id'] = numbered_parent.rsplit('.', 1)[0]
        parent = by_id.get(node['parent_rule_id'])
        if parent:
            parent['children'].append(node['rule_id'])
        else:
            assert node['parent_rule_id'] in categories

    refs = []
    for node in nodes:
        for m in REFERENCE.finditer(node['text']):
            target, suffix = m[1], m[2]
            if target == node['rule_id'] and suffix is None:
                continue
            refs.append(dict(source_rule_id=node['rule_id'], target_rule_id=target,
                             subclause=suffix, literal=m[0],
                             text_offset=m.start(), resolved=target in by_id,
                             extraction='explicit_regex'))

    # Keep visual regions at rule granularity; simple underlines must not flag
    # every rule on a page. Diagrams are mostly vectors, not raster images.
    vector_pages = []
    visuals = []
    for page_index, page in enumerate(doc):
        paths = [path for path in page.get_drawings()
                 if path['rect'].y0 >= 65 and path['rect'].y1 <= 745]
        if paths:
            vector_pages.append(page_index + 1)
        for rect in page.cluster_drawings():
            if rect.y0 >= 65 and rect.y1 <= 745 and rect.width >= 35 and rect.height >= 35:
                visuals.append(dict(page=page_index + 1, bbox=list(rect), kind='vector_region'))
        for image in page.get_image_info():
            rect = fitz.Rect(image['bbox'])
            if rect.y0 >= 65 and rect.width >= 35 and rect.height >= 35:
                visuals.append(dict(page=page_index + 1, bbox=list(rect), kind='image'))
    for node in nodes:
        regions = [visual for visual in visuals if any(
            span['page'] == visual['page'] and
            fitz.Rect(span['bbox']).intersects(fitz.Rect(visual['bbox']))
            for span in node['source']['regions'])]
        mentions = bool(re.search(r'\b(?:figure|diagram|illustration)\b|template shown|shown below', node['text'], re.I))
        node['visuals'] = dict(has_visual_content=bool(regions or mentions),
                              detection='vector/image region overlap or explicit text reference',
                              regions=regions, mentions_visual=mentions,
                              note='See the linked PDF for diagrams or visual details; these are not transcribed.' if regions or mentions else None)
        node['extraction_notes'] = [node['visuals']['note']] if node['visuals']['note'] else []

    # The supplied edition's standalone tables have known, verified columns.
    # PyMuPDF sometimes returns an extra empty column from a dangling border.
    headers = {'PS-1': ['Submission', 'Refer to', 'Required format', 'File format', 'Penalty group'],
               'PS-2': ['Penalty group', 'Penalty points per 24 hours', 'Not submitted after deadline']}
    for table in tables:
        page = doc[table['page'] - 1]
        found = list(page.find_tables().tables)
        table_number = int(table['asset_id'].split('-')[1]) - 1
        if table['asset_id'] in headers and table_number < len(found):
            detected = found[table_number]
            names = headers[table['asset_id']]
            table['rows'] = [dict(zip(names, [(value or '').replace('\n', ' ').strip() for value in row[:len(names)]]))
                             for row in detected.extract()]
            table['bbox'] = list(detected.bbox)
            table['notes'] = re.findall(r'Note \(\d+\):[^\n]+', table['text'])
            table['search_text'] = '\n'.join(' | '.join(k + ': ' + v for k, v in row.items()) for row in table['rows'])
            table['search_text'] += '\n' + '\n'.join(table['notes'])
            table['review_status'] = 'Column mapping checked against source; original PDF remains authoritative'

    units = []
    for node in nodes:
        if node['children'] and not node['text']:
            continue
        if not node['text']:
            continue
        context = []
        for ancestor in node['ancestor_rule_ids']:
            parent = by_id.get(ancestor)
            context.append(dict(rule_id=ancestor,
                                title=parent['title'] if parent else categories.get(ancestor),
                                introductory_text=parent['text'] if parent else ''))
        context.append(dict(rule_id=node['rule_id'], title=node['title'], introductory_text=''))
        units.append(dict(unit_id=node['node_id'] + ':own', rule_id=node['rule_id'],
                          role='parent_introduction' if node['children'] else 'leaf',
                          candidate=dict(rule_id=node['rule_id'], text=node['text'], context=context)))
    for table in tables:
        units.append(dict(unit_id=document_id + ':table:' + table['asset_id'], role='table',
                          asset_id=table['asset_id'], rule_id=None,
                          candidate=dict(asset_id=table['asset_id'], title=table['title'], text=table.get('search_text', table['text']),
                                         context=[dict(rule_id='PS', title=categories['PS'], introductory_text='')])))

    leaves = [node for node in nodes if not node['children']]
    by_category = []
    for category, title in categories.items():
        group = [node for node in nodes if node['rule_id'].split('.')[0] == category]
        by_category.append(dict(category=category, title=title,
                                articles=sum(node['kind'] == 'article' for node in group),
                                sections=sum(node['kind'] == 'section' for node in group),
                                paragraphs=sum(node['kind'] == 'paragraph' for node in group),
                                leaves=sum(not node['children'] for node in group),
                                nodes=len(group)))
    statistics = dict(
        pages=len(doc), categories=len(categories), numbered_nodes=len(nodes),
        articles=sum(node['kind'] == 'article' for node in nodes),
        sections=sum(node['kind'] == 'section' for node in nodes),
        paragraphs=sum(node['kind'] == 'paragraph' for node in nodes),
        leaves=len(leaves), leaves_by_depth=dict(collections.Counter(node['kind'] for node in leaves)),
        substantive_leaf_rules=sum(bool(node['text']) for node in leaves), standalone_tables=len(tables),
        pages_with_body_vector_paths=vector_pages,
        search_units=len(units), parent_introduction_units=sum(unit['role'] == 'parent_introduction' for unit in units),
        explicit_reference_occurrences=len(refs),
        unique_reference_edges=len({(ref['source_rule_id'], ref['target_rule_id'], ref['subclause']) for ref in refs}),
        unresolved_references=[ref for ref in refs if not ref['resolved']],
        multi_page_leaf_rules=[node['rule_id'] for node in leaves if node['source']['page_end'] > node['source']['page_start']],
        own_text_characters=sum(len(node['text']) for node in nodes), by_category=by_category,
        validation=dict(duplicate_definitions=0, bookmark_definitions_checked=len(bookmark_titles),
                        printed_page_labels_checked=len(doc),
                        missing_numbered_parents=sorted({node['missing_numbered_parent'] for node in nodes if 'missing_numbered_parent' in node}),
                        bookmark_page_mismatches=[rid for rid, page in bookmark_pages.items() if by_id[rid]['source']['page_start'] != page],
                        no_text_leaf_rules=[node['rule_id'] for node in leaves if not node['text']]),
    )
    corpus = dict(schema_version=1,
                  document=dict(document_id=document_id, filename=pdf.name, sha256=sha,
                                title=doc.metadata['title'], year=2027, version='1.0',
                                published_date='2026-09-01', page_count=len(doc),
                                extraction_version='layout-index-v2',
                                coordinate_system='PDF points, top-left origin, 612 x 792 pages',
                                review_status='provisional; tables, formulas, graphics and applicability need review'),
                  categories=categories, rules=nodes, tables=tables, references=refs, search_units=units)
    statistics['rules_with_visual_notes'] = sum(node['visuals']['has_visual_content'] for node in nodes)
    doc.close()
    return corpus, lines, statistics
