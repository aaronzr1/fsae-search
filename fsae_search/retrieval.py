"""Source-complete section scans, explicit routed mode, and a shared exact-query cache."""
from collections import Counter, defaultdict
from datetime import datetime, timezone
import hashlib
import json
import math
from pathlib import Path
import re
import time
from uuid import uuid4

from .jev import JevClient, configuration, search_rules, PROMPT_VERSION, size
from .sections import SectionClient, section_units
from .store import ROOT, STOPWORDS, encode

STRATEGIES=('sections','routed','rules')
CACHE=ROOT/'.cache/query-cache'
ROUTE_THRESHOLD=.5
TERM_EXPANSIONS=[
    (r'brak|regenerat','brake pedal hydraulic caliper reservoir fluid braking mechanical regeneration'),
    (r'fastener|nyloc|nylock|loctite|bolt|nut|locking','fastener locking nylon torque thread critical safety wiring cotter'),
    (r'ground|bonding|carbon.fib','ground grounding conductive conductivity resistance firewall'),
    (r'cockpit|egress|driver.exit','cockpit opening template egress exit harness steering wheel'),
]


def source_supplement(store,query,exclude=()):
    """An independent free search; model scores never veto these source matches."""
    expansions=[terms for pattern,terms in TERM_EXPANSIONS if re.search(pattern,query,re.I)]
    expanded_query=query+' '+' '.join(expansions)
    local=store.local_search(expanded_query,120)['results']
    sections={u['rule_id']:u for u in section_units(store)};excluded=set(exclude);seen=set();results=[]
    for result in local:
        rid=result['rule_id'];sid='.'.join(rid.split('.')[:3]) if '.' in rid else rid
        if sid in excluded or sid in seen or sid not in sections:continue
        seen.add(sid);entry_id=sid
        while entry_id not in store.rules and entry_id not in store.tables and '.' in entry_id:entry_id=entry_id.rsplit('.',1)[0]
        results.append(dict(store.entry(entry_id),member_rule_ids=sections[sid]['member_rule_ids'],
                            match_method='expanded_keyword_search',lexical_score=result.get('lexical_score')))
    return results,expansions


def article_descriptors(store):
    sections=section_units(store); grouped=defaultdict(list)
    counts=[Counter(w.lower() for w in re.findall(r'[A-Za-z]{3,}',u['candidate']['text'])
                    if w.lower() not in STOPWORDS) for u in sections]
    frequency=Counter(w for terms in counts for w in terms)
    for unit,terms in zip(sections,counts):
        article='.'.join(unit['rule_id'].split('.')[:2]) if '.' in unit['rule_id'] else unit['rule_id']
        keywords=sorted(terms,key=lambda w:(terms[w]**.5)/(frequency[w]+1),reverse=True)[:14]
        grouped[article].append(unit['rule_id']+' / '+unit['candidate']['path']+' / '+', '.join(keywords))
    output=[]
    for aid,parts in grouped.items():
        title=store.rules[aid]['title'] if aid in store.rules else store.tables[aid]['title']
        output.append(dict(unit_id='article:'+aid,rule_id=aid,
                           candidate=dict(rule_id=aid,path=title or aid,text='\n'.join(parts))))
    return output,sections


def select_sections(store,query,descriptors,route,sections,route_threshold=ROUTE_THRESHOLD):
    articles={u['rule_id'] for u,d in zip(descriptors,route['decisions'])
              if d['status']=='error' or d['probability']>=route_threshold}
    selected={u['rule_id'] for u in sections if
              ('.'.join(u['rule_id'].split('.')[:2]) if '.' in u['rule_id'] else u['rule_id']) in articles}
    for result in store.local_search(query,30)['results']:
        rid=result['rule_id'];selected.add('.'.join(rid.split('.')[:3]) if '.' in rid else rid)
    seeds={rid for u in sections if u['rule_id'] in selected for rid in u['member_rule_ids']}
    for ref in store.corpus['references']:
        source=ref.get('source_rule_id') or ref.get('source_asset_id');target=ref['target_rule_id']
        if source in seeds:selected.add('.'.join(target.split('.')[:3]))
        if target in seeds:selected.add('.'.join(source.split('.')[:3]) if '.' in source else source)
    return [u for u in sections if u['rule_id'] in selected]


def evaluate_sections(store,query,vehicle_type,settings,key,strategy='sections',progress=None):
    candidates=section_units(store);route=None
    if strategy=='routed':
        descriptors,candidates=article_descriptors(store)
        route=SectionClient(key,settings).evaluate(query,descriptors,vehicle_type)
        if not route['complete']:
            # A failed route must never silently drop a branch; scan all text.
            selected=candidates
        else:
            selected=select_sections(store,query,descriptors,route,candidates)
    else:selected=candidates
    if not selected:
        selected=candidates  # No plausible route: full scan, not an unsupported empty answer.
    outcome=SectionClient(key,settings).evaluate(query,selected,vehicle_type,progress)
    if route:
        outcome['batches']=route['batches']+outcome['batches']
        outcome['seconds']+=route['seconds']
        outcome['provider_requests_sent']+=route['provider_requests_sent']
        if route['usage'] and outcome['usage']:
            for k in ('input_tokens','output_tokens'):outcome['usage'][k]+=route['usage'][k]
        else:outcome['usage']=None
        outcome['usage_complete']=outcome['usage_complete'] and route['usage_complete']
        known=outcome['usage']['input_tokens']/1e6*settings.price_per_million if outcome['usage'] else None
        outcome['known_reported_cost_usd']=known
        outcome['cost_usd']=known if outcome['usage_complete'] else None
        outcome['routing_complete']=route['complete']
    outcome['decisions']=[dict(d,unit_id=u['unit_id'],rule_id=u['rule_id'],member_rule_ids=u['member_rule_ids'])
                           for u,d in zip(selected,outcome['decisions'])]
    outcome.update(strategy=strategy,query=query,mode='jev',vehicle_type=vehicle_type,
                   document_id=store.document['document_id'],model_requested=settings.model,
                   models_resolved=sorted({d['model'] for d in outcome['decisions'] if d['model']}),
                   total_evaluated=len(selected),source_units_checked=sum(len(u['member_unit_ids']) for u in selected),
                   source_units_total=len(store.units),full_rulebook_scan=len(selected)==len(candidates),
                   errors=sum(d['status']=='error' for d in outcome['decisions']),
                   completed_at=datetime.now(timezone.utc).isoformat())
    return outcome


def cache_key(store,query,vehicle_type,settings,strategy):
    fingerprint=dict(pdf=store.document['sha256'],extractor=store.document['extraction_version'],
                     corpus=hashlib.sha256(encode(store.corpus).encode()).hexdigest(),
                     query=' '.join(query.split()),vehicle_type=vehicle_type,model=settings.model,strategy=strategy,
                     prompt=PROMPT_VERSION if strategy=='rules' else SectionClient.prompt_version,
                     route_version='outline-tfidf-v1' if strategy=='routed' else None,
                     batch_bytes=settings.batch_bytes,pair_bytes=settings.pair_bytes,
                     grouping_version='16-source-sections-v1')
    return hashlib.sha256(encode(fingerprint).encode()).hexdigest()


def write_cache(path,outcome,max_entries=256):
    if not outcome['complete']:return
    path.parent.mkdir(parents=True,exist_ok=True)
    slim={k:v for k,v in outcome.items() if k not in ('results','related','uncertain')}
    temp=path.with_name(path.name+'.'+uuid4().hex+'.tmp')
    temp.write_text(encode(slim));temp.replace(path)
    files=sorted(path.parent.glob('*.json'),key=lambda p:p.stat().st_mtime,reverse=True)
    for old in files[max_entries:]:old.unlink(missing_ok=True)


def present(store,outcome,top_k=50,threshold=.5):
    output=dict(outcome);decisions=output['decisions'];strategy=output.get('strategy','rules')
    ordered=sorted((d for d in decisions if d['status']=='scored'),key=lambda d:(-d['probability'],d['rule_id']))
    matches=[d for d in ordered if d['probability']>=threshold]
    def entry(d):
        rid=d['rule_id']
        # D.8.1 is an implicit numbering group, not a heading in the PDF.
        while rid not in store.rules and rid not in store.tables and '.' in rid:rid=rid.rsplit('.',1)[0]
        e=store.entry(rid,include_descendants=strategy!='rules')
        return dict(e,probability=d['probability'],unit_id=d['unit_id'],score_scope='rule' if strategy=='rules' else 'section',
                    member_rule_ids=d.get('member_rule_ids',[rid]))
    results=[entry(d) for d in matches[:top_k]]
    member_ids={rid for r in results for rid in r['member_rule_ids']}|{r['rule_id'] for r in results}
    output.update(results=results,total_matches=len(matches),threshold=threshold,
                  matched_rule_count=len({rid for d in matches for rid in d.get('member_rule_ids',[d['rule_id']])}),
                  related=store.related(member_ids),
                  uncertain=[entry(d) for d in ordered if .2<=d['probability']<threshold],
                  score_scope='rule' if strategy=='rules' else 'section')
    output['source_matches'],output['expanded_terms']=source_supplement(store,output.get('query',''),[r['rule_id'] for r in results])
    return output


def search(store,query,*,vehicle_type='all',top_k=50,threshold=.5,progress=None,strategy='sections',use_cache=True):
    if not query.strip() or len(query)>2000 or vehicle_type not in ('all','EV','IC') or strategy not in STRATEGIES:
        raise ValueError('Invalid query, vehicle type or strategy.')
    if type(top_k) is not int or not 1<=top_k<=2000 or not math.isfinite(threshold) or not 0<=threshold<=1:
        raise ValueError('Invalid result count or threshold.')
    key,settings=configuration()
    direct=query.strip().upper()
    if direct in store.rules or direct in store.tables:
        output=store.local_search(direct,top_k)
        output.update(strategy='direct',provider_requests_sent=0,usage=dict(input_tokens=0,output_tokens=0),cache_hit=False)
        return output
    cache_path=CACHE/(cache_key(store,query,vehicle_type,settings,strategy)+'.json')
    cache_allowed=use_cache and settings.model not in ('jev-latest','jev-preview')
    if cache_allowed and cache_path.exists():
        try:outcome=json.loads(cache_path.read_text())
        except (ValueError,OSError):outcome=None
        if outcome and outcome.get('complete'):
            outcome['original_scan']=dict(usage=outcome['usage'],cost_usd=outcome['cost_usd'],seconds=outcome['seconds'])
            outcome.update(cache_hit=True,usage=dict(input_tokens=0,output_tokens=0),usage_complete=True,
                           cost_usd=0,known_reported_cost_usd=0,provider_requests_sent=0,seconds=0,query=query,batches=[])
            if progress:progress(outcome['total_evaluated'],outcome['total_evaluated'])
            return present(store,outcome,top_k,threshold)
    if strategy=='rules':
        outcome=search_rules(store,query,vehicle_type=vehicle_type,top_k=2000,threshold=0,
                             progress=progress,client=JevClient(key,settings))
        outcome.update(strategy='rules',full_rulebook_scan=True,source_units_checked=len(store.units),
                       source_units_total=len(store.units))
    else:outcome=evaluate_sections(store,query,vehicle_type,settings,key,strategy,progress)
    outcome['cache_hit']=False
    if cache_allowed:write_cache(cache_path,outcome)
    return present(store,outcome,top_k,threshold)


def plan_sections(store,query,settings,vehicle_type='all',strategy='sections'):
    # Routed mode uses all text as an upper-bound plan, because the route isn't
    # known until evaluated. Never issue a paid routing call just to estimate.
    units=section_units(store)
    client=SectionClient('planning-only',settings)
    batches,skipped=client.pack(query,units,vehicle_type)
    bytes_count=sum(size(body) for body,_ in batches)
    return dict(mode='dry_run',strategy=strategy,comparisons=len(units),source_units=len(store.units),
                batch_count=len(batches),concurrency=settings.concurrency,request_bytes=bytes_count,
                estimated_input_tokens=round(bytes_count/4),estimated_cost_usd=bytes_count/4/1e6*settings.price_per_million,
                oversized_units=[units[i]['unit_id'] for i in skipped],provider_requests_sent=0,usage=None,cost_usd=0,
                estimate_note='JSON bytes / 4 estimate. Routed strategy varies and adds the outline-routing cost.')


def import_measured_runs(store,directory=ROOT/'.cache/optimization'):
    """Reuse completed experiments with the exact same source, model and prompt."""
    _,settings=configuration();units=section_units(store);count=0
    summary=json.loads((directory/'summary.json').read_text())
    queries={r['case']:r['query'] for r in summary['rows']}
    for case,query in queries.items():
        path=directory/(case+'-sections.json')
        if not path.exists():continue
        raw=json.loads(path.read_text())
        if not raw['complete'] or any(d['model']!=settings.model for d in raw['decisions']):continue
        if raw['units']!=units:continue
        raw.pop('units');raw.pop('surfaced_rule_ids',None)
        raw['decisions']=[dict(d,unit_id=u['unit_id'],rule_id=u['rule_id'],member_rule_ids=u['member_rule_ids'])
                          for u,d in zip(units,raw['decisions'])]
        raw.update(strategy='sections',query=query,mode='jev',vehicle_type='all',document_id=store.document['document_id'],
                   model_requested=settings.model,models_resolved=[settings.model],total_evaluated=len(units),
                   source_units_checked=len(store.units),source_units_total=len(store.units),full_rulebook_scan=True,
                   errors=0,cache_origin='measured experiment',cache_hit=False)
        write_cache(CACHE/(cache_key(store,query,'all',settings,'sections')+'.json'),raw);count+=1
    return count
