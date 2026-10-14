"""Several questions share each source chunk; none of the source is pruned."""
from .jev import JevClient,size
from .sections import section_units,section_body


def bundle_body(queries,units,settings,vehicle_type):
    single=section_body('',units,list(range(len(units))),settings,vehicle_type)
    single['state'].pop('query')
    questions={};positions=[]
    for unit,position in units_with_positions(units):
        for query_index,query in enumerate(queries):
            index=position*len(queries)+query_index
            questions['pair_'+str(index)]=dict(type='noul',instructions=dict(query=query,
                question='Could SECTION '+unit['rule_id']+' in source help with any aspect of query? Follow guidance; include related constraints.'))
            positions.append(index)
    single['questions']=questions
    return single,positions


def units_with_positions(units):
    return [(unit,unit['_position']) for unit in units]


class BundleClient(JevClient):
    prompt_version='complete-section-bundles-v1'

    def __init__(self,key,settings,queries,sections,**kwargs):
        super().__init__(key,settings,**kwargs)
        self.queries=queries;self.sections=sections

    def pack(self,query,units,vehicle_type='all'):
        batches=[];group=[];skipped=[]
        for position,unit in enumerate(self.sections):
            unit=dict(unit,_position=position)
            body,_=bundle_body(self.queries,group+[unit],self.settings,vehicle_type)
            if group and (len(group)>=16 or size(body)>self.settings.batch_bytes or
                          size(body['state'])+max(size(q) for q in body['questions'].values())>self.settings.pair_bytes):
                batches.append(bundle_body(self.queries,group,self.settings,vehicle_type));group=[]
            solo,_=bundle_body(self.queries,[unit],self.settings,vehicle_type)
            if size(solo['state'])+max(size(q) for q in solo['questions'].values())>self.settings.pair_bytes:
                skipped.extend(position*len(self.queries)+i for i in range(len(self.queries)));continue
            group.append(unit)
        if group:batches.append(bundle_body(self.queries,group,self.settings,vehicle_type))
        return batches,skipped


def evaluate_bundle(store,queries,settings,key,client_class=BundleClient,**client_kwargs):
    if not 1<=len(queries)<=8 or any(not isinstance(q,str) or not q.strip() or len(q)>2000 for q in queries):
        raise ValueError('Provide between one and eight queries of 1–2,000 characters.')
    sections=section_units(store)
    expanded=[dict(u,query_index=i) for u in sections for i in range(len(queries))]
    client=client_class(key,settings,queries,sections,**client_kwargs)
    raw=client.evaluate('',expanded)
    per_query=[]
    for i,query in enumerate(queries):
        decisions=[dict(d,unit_id=u['unit_id'],rule_id=u['rule_id'],member_rule_ids=u['member_rule_ids'])
                   for u,d in zip(expanded,raw['decisions']) if u['query_index']==i]
        per_query.append(dict(query=query,decisions=decisions))
    raw.pop('decisions');raw['queries']=per_query
    return raw


def search_many(store,queries,top_k=50):
    from .jev import configuration
    from .retrieval import present
    key,settings=configuration()
    raw=evaluate_bundle(store,queries,settings,key)
    results=[]
    for item in raw['queries']:
        outcome=dict(item,strategy='sections',mode='jev',score_scope='section',
                     complete=all(d['status']=='scored' for d in item['decisions']),
                     errors=sum(d['status']=='error' for d in item['decisions']),
                     full_rulebook_scan=True,source_units_checked=len(store.units),source_units_total=len(store.units))
        results.append(present(store,outcome,top_k))
    raw['queries']=results
    raw['mean_allocated_cost_usd']=raw['cost_usd']/len(queries) if raw['cost_usd'] is not None else None
    raw['cost_allocation_note']='Shared bundle usage is measured. Mean cost per query is an equal allocation, not separately reported usage.'
    return raw
