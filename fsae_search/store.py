"""Build versioned JSON/SQLite indexes and recover original rule context."""
import hashlib
import json
from pathlib import Path
import re
import sqlite3

ROOT = Path(__file__).resolve().parents[1]
DATA = ROOT / 'data'
INDEX = DATA / 'rules.json'
DATABASE = DATA / 'rules.sqlite'
STOPWORDS = set('what are the rules rule on for a an of to and in is do does can i we how which requirements apply about must be'.split())


def encode(value):
    return json.dumps(value, ensure_ascii=False, allow_nan=False)


def build(pdf=ROOT / 'FSAE_Rules_2027_V1.pdf'):
    from .extract import extract, REFERENCE
    corpus, lines, stats = extract(pdf)
    for table in corpus['tables']:
        for match in REFERENCE.finditer(table.get('search_text', table['text'])):
            corpus['references'].append(dict(source_asset_id=table['asset_id'], target_rule_id=match[1],
                                              subclause=match[2], literal=match[0], text_offset=match.start(),
                                              extraction='explicit_regex', resolved=True))
    DATA.mkdir(exist_ok=True)
    temp_db = DATABASE.with_suffix('.sqlite.tmp')
    temp_db.unlink(missing_ok=True)
    conn = sqlite3.connect(temp_db)
    try:
        conn.executescript((ROOT / 'analysis/schema.sql').read_text())
        conn.execute('CREATE TABLE index_metadata (key TEXT PRIMARY KEY, value TEXT NOT NULL)')
        conn.execute('CREATE VIRTUAL TABLE units_fts USING fts5(unit_id UNINDEXED, content, tokenize="porter unicode61")')
        d = corpus['document']; did = d['document_id']; nodes = {r['rule_id']: r for r in corpus['rules']}
        conn.execute('INSERT INTO documents VALUES (?,?,?,?,?,?,?,?,?,?,?)',
                     (did, d['title'], d['year'], d['version'], d['published_date'], d['sha256'], d['filename'],
                      '/pdf/' + d['sha256'], d['page_count'], d['extraction_version'], d['review_status']))
        for ordinal, (category, title) in enumerate(corpus['categories'].items()):
            conn.execute('INSERT INTO categories VALUES (?,?,?,?)', (did, category, title, ordinal))
        for ordinal, rule in enumerate(corpus['rules']):
            rid = rule['rule_id']; parent = rule['parent_rule_id']
            conn.execute('INSERT INTO rules VALUES (?,?,?,?,?,?,?,?,?,?)',
                         (did, rid, rid.split('.')[0], parent if parent in nodes else None,
                          rule.get('missing_numbered_parent', rid.rsplit('.', 1)[0]), rule['kind'], ordinal,
                          rule['title'], rule['text'], 'extracted; visual details require source PDF'))
            for number, region in enumerate(rule['source']['regions']):
                conn.execute('INSERT INTO source_spans VALUES (?,?,?,?,?,?,?,?,?,?,?,?,?,?)',
                             (rid + ':region:' + str(number), did, rid, region['page'], str(region['page']), number,
                              *region['bbox'], 612, 792, 'source_region', None))
            for number in range(rule['source']['line_start'], rule['source']['line_end_exclusive']):
                line = lines[number]
                conn.execute('INSERT INTO source_spans VALUES (?,?,?,?,?,?,?,?,?,?,?,?,?,?)',
                             ('line:' + str(number), did, rid, line['page'], str(line['page']), number,
                              *line['bbox'], 612, 792, 'text', line['text']))
            conn.execute('INSERT INTO rule_annotations VALUES (?,?,?,?,?,?,?)',
                         (did, rid, 'visuals', encode(rule['visuals']), rid + ':region:0', 'layout_and_explicit_text', 'heuristic'))
        visual_ids = {}
        for rule in corpus['rules']:
            for visual in rule['visuals']['regions']:
                signature = encode(visual)
                aid = 'visual:' + hashlib.sha256(signature.encode()).hexdigest()[:12]
                if aid not in visual_ids:
                    span_id = aid + ':source'
                    conn.execute('INSERT INTO source_spans VALUES (?,?,?,?,?,?,?,?,?,?,?,?,?,?)',
                                 (span_id, did, None, visual['page'], str(visual['page']), 0,
                                  *visual['bbox'], 612, 792, 'source_region', None))
                    conn.execute('INSERT INTO assets VALUES (?,?,?,?,?,?,?,?)',
                                 (aid, did, 'figure', 'Visual content on page ' + str(visual['page']),
                                  span_id, None, encode(visual), 'not_transcribed'))
                    visual_ids[aid] = visual
                conn.execute('INSERT OR IGNORE INTO rule_assets VALUES (?,?,?,?,?)',
                             (did, rule['rule_id'], aid, 'contains', 'unreviewed'))
        for table in corpus['tables']:
            aid = table['asset_id']; span_id = 'table:' + aid
            bbox = table.get('bbox', [72, 65, 546, 745])
            conn.execute('INSERT INTO source_spans VALUES (?,?,?,?,?,?,?,?,?,?,?,?,?,?)',
                         (span_id, did, None, table['page'], str(table['page']), 0, *bbox, 612, 792, 'source_region', None))
            conn.execute('INSERT INTO assets VALUES (?,?,?,?,?,?,?,?)',
                         (aid, did, 'table', table['title'], span_id, table['text'], encode(table.get('rows')), table['review_status']))
        for number, ref in enumerate(corpus['references']):
            conn.execute('INSERT INTO cross_references VALUES (?,?,?,?,?,?,?,?,?,?,?,?)',
                         ('ref:' + str(number), did, ref.get('source_rule_id'), ref.get('source_asset_id'), did,
                          ref['target_rule_id'], None, ref['subclause'], ref['literal'], ref['text_offset'],
                          ref['extraction'], 'explicit; source backed'))
        for unit in corpus['search_units']:
            candidate = encode(unit['candidate'])
            conn.execute('INSERT INTO search_units VALUES (?,?,?,?,?,?,?,?)',
                         (unit['unit_id'], did, unit.get('rule_id'), unit.get('asset_id'),
                          'asset' if unit['role'] == 'table' else unit['role'], candidate,
                          hashlib.sha256(candidate.encode()).hexdigest(), 'context-v2'))
            context = ' '.join((c.get('title') or '') + ' ' + c.get('introductory_text', '') for c in unit['candidate']['context'])
            conn.execute('INSERT INTO units_fts VALUES (?,?)',
                         (unit['unit_id'], (unit.get('rule_id') or unit['asset_id']) + ' ' +
                          unit['candidate'].get('title', '') + ' ' + unit['candidate']['text'] + ' ' + context))
        conn.execute('INSERT INTO index_metadata VALUES (?,?)', ('pdf_sha256', d['sha256']))
        conn.commit()
        if list(conn.execute('PRAGMA foreign_key_check')):
            raise ValueError('Index contains invalid foreign keys')
        stats['reference_occurrences_including_tables'] = len(corpus['references'])
        conn.close()
        temp_index = INDEX.with_suffix('.json.tmp')
        temp_index.write_text(encode(corpus) + '\n')
        temp_index.replace(INDEX)
        temp_db.replace(DATABASE)
        (DATA / 'statistics.json').write_text(encode(stats) + '\n')
        return stats
    finally:
        conn.close()


class Store:
    def __init__(self, index=INDEX, database=DATABASE):
        self.index_path, self.database = Path(index), Path(database)
        self.corpus = json.loads(self.index_path.read_text())
        self.document = self.corpus['document']
        self.rules = {r['rule_id']: r for r in self.corpus['rules']}
        self.tables = {t['asset_id']: t for t in self.corpus['tables']}
        self.units = self.corpus['search_units']
        self.by_unit = {u['unit_id']: u for u in self.units}
        self.pdf = ROOT / self.document['filename']
        if hashlib.sha256(self.pdf.read_bytes()).hexdigest() != self.document['sha256']:
            raise ValueError('PDF changed. Rebuild the index before searching.')
        with sqlite3.connect(self.database) as conn:
            sha = conn.execute('SELECT value FROM index_metadata WHERE key="pdf_sha256"').fetchone()
            if not sha or sha[0] != self.document['sha256']:
                raise ValueError('JSON/SQLite editions differ. Rebuild the index.')

    def entry(self, identifier, include_descendants=True):
        if identifier in self.tables:
            table = self.tables[identifier]
            return dict(rule_id=identifier, kind='table', title=table['title'], text=table.get('search_text', table['text']),
                        breadcrumb='PS / ' + table['title'], page_start=table['page'], page_end=table['page'],
                        pdf_url='/pdf/' + self.document['sha256'] + '#page=' + str(table['page']),
                        has_visual_content=False, visual_note=None, source_regions=[], children=[], rows=table.get('rows', []))
        rule = self.rules[identifier]
        descendants = [r for rid, r in self.rules.items() if rid.startswith(identifier + '.')]
        text = rule['text']
        if include_descendants and descendants:
            text += '\n\n' + '\n\n'.join(r['rule_id'] + (' ' + r['title'] if r['title'] else '') + '\n' + r['text'] for r in descendants)
        context = [self.corpus['categories'][identifier.split('.')[0]]]
        context += [self.rules[a]['title'] or a for a in rule['ancestor_rule_ids'] if a in self.rules]
        page_end = max([rule['source']['page_end']] + [r['source']['page_end'] for r in descendants]) if include_descendants else rule['source']['page_end']
        visual_rules=[rule]+descendants if include_descendants else [rule]
        has_visual=any(r['visuals']['has_visual_content'] for r in visual_rules)
        return dict(rule_id=identifier, kind=rule['kind'], title=rule['title'], text=text.strip(), own_text=rule['text'],
                    breadcrumb=' / '.join(context), page_start=rule['source']['page_start'], page_end=page_end,
                    pdf_url='/pdf/' + self.document['sha256'] + rule['source']['pdf_fragment'],
                    has_visual_content=has_visual, visual_note='See the PDF for diagram or visual details in this section; these are not transcribed.' if has_visual else None,
                    source_regions=rule['source']['regions'], children=rule['children'])

    def related(self, identifiers, limit=40):
        identifiers = set(identifiers); related = {}
        for ref in self.corpus['references']:
            source = ref.get('source_rule_id') or ref.get('source_asset_id')
            target = ref['target_rule_id']
            if source in identifiers and target not in identifiers and target in self.rules:
                related.setdefault(target, dict(rule_id=target, relation='referenced_by_match', via=[]))['via'].append(source)
        return [dict(self.entry(rid), **{'relation': item['relation'], 'via': sorted(set(item['via']))})
                for rid, item in list(related.items())[:limit]]

    def local_search(self, query, top_k=30):
        query = query.strip()
        if query.upper() in self.rules or query.upper() in self.tables:
            result = self.entry(query.upper())
            return dict(query=query, mode='local', results=[result], related=self.related([result['rule_id']]),
                        complete=True, usage=None, cost_usd=0, total_matches=1)
        terms = [term for term in re.findall(r'[\w]+', query.lower()) if term not in STOPWORDS]
        if not terms:
            return dict(query=query, mode='local', results=[], related=[], complete=True, usage=None, cost_usd=0, total_matches=0)
        expression = ' OR '.join('"' + term + '"' for term in terms)
        with sqlite3.connect(self.database) as conn:
            rows = conn.execute('SELECT unit_id, bm25(units_fts) FROM units_fts WHERE units_fts MATCH ? ORDER BY bm25(units_fts)',
                                (expression,)).fetchall()
        results = []
        for uid, score in rows[:top_k]:
            unit = self.by_unit[uid]
            results.append(dict(self.entry(unit.get('rule_id') or unit['asset_id']), unit_id=uid, lexical_score=-score))
        return dict(query=query, mode='local', results=results, related=self.related([r['rule_id'] for r in results]),
                    complete=True, usage=None, cost_usd=0, total_matches=len(rows))
