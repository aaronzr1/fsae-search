import argparse
import json
from pathlib import Path
import sys

from .store import ROOT, Store, build, encode

SAMPLES = ['What are the rules on brakes?',
           'What are the requirements for an EV shutdown circuit?',
           'What are the cockpit opening and driver egress requirements?']


def summary(output):
    fields = ('query', 'mode', 'strategy','cache_hit','full_rulebook_scan','source_units_checked','source_units_total',
              'complete', 'total_matches', 'matched_rule_count','total_evaluated', 'errors', 'seconds',
              'provider_requests_sent', 'usage', 'usage_complete', 'cost_usd', 'known_reported_cost_usd',
              'batch_count', 'scheduling_waves', 'estimated_input_tokens', 'estimated_cost_usd')
    data = {key: output[key] for key in fields if key in output}
    data['top_results'] = [dict(rule_id=r['rule_id'], probability=r.get('probability'), page=r['page_start'])
                           for r in output.get('results', [])[:10]]
    print(json.dumps(data, indent=2))


def main(argv=None):
    parser = argparse.ArgumentParser(description='Browse and semantically search Formula SAE rules.')
    commands = parser.add_subparsers(dest='command')
    commands.add_parser('build', help='Extract PDF and rebuild JSON/SQLite indexes.')
    commands.add_parser('import-experiments',help='Reuse completed full-section experiment scans in the query cache.')
    experiment = commands.add_parser('experiment', help='Compare bounded-cost retrieval strategies.')
    experiment.add_argument('--budget',type=float,default=0.40)
    experiment.add_argument('--sections',action='store_true')
    experiment.add_argument('--article-cascade',action='store_true')
    experiment.add_argument('--bundle',action='store_true')
    experiment.add_argument('--route-threshold',type=float,default=.1)
    server = commands.add_parser('serve', help='Start the local browser app.')
    server.add_argument('--port', type=int, default=8000)
    check = commands.add_parser('check', help='Check a running local server without making Jev requests.')
    check.add_argument('--port', type=int, default=8000)
    check.add_argument('--cached-query',action='store_true',help='Verify a previously cached sample via the semantic API.')
    search = commands.add_parser('search', help='Search every candidate with Jev, or use local keyword search.')
    search.add_argument('query')
    search.add_argument('--local', action='store_true')
    search.add_argument('--dry-run', action='store_true')
    search.add_argument('--vehicle', choices=['all', 'EV', 'IC'], default='all')
    search.add_argument('--top-k', type=int, default=50)
    search.add_argument('--threshold', type=float, default=0.5)
    search.add_argument('--strategy',choices=['sections','routed','rules'],default='sections')
    search.add_argument('--no-cache',action='store_true')
    search.add_argument('--out', type=Path)
    bundle=commands.add_parser('search-many',help='Share source text across up to eight questions in one scan.')
    bundle.add_argument('queries',nargs='+')
    bundle.add_argument('--top-k',type=int,default=50)
    bundle.add_argument('--out',type=Path,default=ROOT/'.cache/bundle-results.json')
    show = commands.add_parser('show', help='Show a rule and its surrounding section.')
    show.add_argument('rule_id')
    samples = commands.add_parser('samples', help='Run three sample queries sequentially and save results/usage.')
    samples.add_argument('--dry-run', action='store_true')
    samples.add_argument('--out', type=Path, default=ROOT / '.cache' / 'sample-queries.json')
    args = parser.parse_args(argv)
    if args.command == 'experiment':
        from .experiments import run,run_sections,run_article_cascade,run_bundle
        if args.bundle:run_bundle(args.budget)
        elif args.article_cascade:run_article_cascade(args.budget,route_threshold=args.route_threshold)
        else:(run_sections if args.sections else run)(args.budget)
        return
    if args.command == 'build':
        data = build()
        print(json.dumps({k:data[k] for k in ('numbered_nodes', 'search_units', 'rules_with_visual_notes', 'standalone_tables')}, indent=2))
        return
    if args.command in (None, 'serve'):
        from .web import create_app
        import uvicorn
        uvicorn.run(create_app(), host='127.0.0.1', port=getattr(args, 'port', 8000))
        return
    store = Store()
    if args.command=='search-many':
        from .bundles import search_many
        output=search_many(store,args.queries,args.top_k)
        args.out.parent.mkdir(parents=True,exist_ok=True);args.out.write_text(encode(output))
        print(json.dumps({k:output[k] for k in ('complete','seconds','usage','cost_usd','mean_allocated_cost_usd','provider_requests_sent')},indent=2))
        for result in output['queries']:print(result['query'],':',result['total_matches'],'matching sections')
        print('Saved results:',args.out)
        return
    if args.command=='import-experiments':
        from .retrieval import import_measured_runs
        print('Imported measured full-section scans:',import_measured_runs(store))
        return
    if args.command == 'check':
        import httpx
        import time
        with httpx.Client(base_url='http://127.0.0.1:' + str(args.port)) as client:
            response = client.get('/api/status'); response.raise_for_status()
            status = response.json()
            if args.cached_query:
                if status.get('default_strategy')!='sections':raise ValueError('Server needs a restart.')
                response=client.post('/api/searches',json={'query':'What are the rules on brakes?','top_k':5,'strategy':'sections'})
                response.raise_for_status();identifier=response.json()['id']
                for attempt in range(100):
                    job=client.get('/api/searches/'+identifier).json()
                    if job['status']!='running':break
                    time.sleep(.05)
                if job['status']!='done' or not job['output']['cache_hit'] or job['output']['provider_requests_sent']!=0:
                    raise ValueError('Cached semantic API check failed.')
                print('Cached semantic API: complete; 0 provider requests; $0 cost.')
            response = client.post('/api/local-search', json={'query':'brakes','top_k':5}); response.raise_for_status()
            results = response.json()['results']
            response = client.get('/api/rules/T.1.1.1'); response.raise_for_status()
            rule = response.json()
            pdf = client.get(rule['pdf_url'].split('#')[0], headers={'Range':'bytes=0-99'})
            if pdf.status_code != 206 or not rule['has_visual_content']:
                raise ValueError('PDF delivery or diagram note check failed.')
            print(json.dumps(dict(rules=status['rules'], search_units=status['search_units'],
                                  jev_configured=status['jev_configured'],
                                  local_matches=[r['rule_id'] for r in results], pdf_range_status=pdf.status_code,
                                  diagram_note=True, jev_requests_sent=0), indent=2))
        return
    if args.command == 'show':
        print(json.dumps(store.entry(args.rule_id.upper()), ensure_ascii=False, indent=2))
        return
    if args.command == 'search':
        if args.local:
            output = store.local_search(args.query, args.top_k)
        else:
            from .jev import configuration, plan, search as run_search
            if args.dry_run:
                _, settings = configuration()
                if args.strategy=='rules':output = plan(args.query, store.units, settings, args.vehicle)
                else:
                    from .retrieval import plan_sections
                    output=plan_sections(store,args.query,settings,args.vehicle,args.strategy)
            else:
                output = run_search(store, args.query, vehicle_type=args.vehicle, top_k=args.top_k, threshold=args.threshold,
                                    progress=lambda n,total: print(f'Checked {n}/{total} entries', file=sys.stderr),
                                    strategy=args.strategy,use_cache=not args.no_cache)
        if args.out:
            args.out.parent.mkdir(parents=True, exist_ok=True)
            args.out.write_text(encode(output) + '\n')
        summary(output)
        return
    if args.command == 'samples':
        from .jev import configuration, plan, search as run_search
        outputs = []
        for query in SAMPLES:
            if args.dry_run:
                _, settings = configuration()
                from .retrieval import plan_sections
                output = plan_sections(store,query,settings)
                output['results'] = store.local_search(query, 10)['results']
                output['preview_mode'] = 'local_keyword_results_not_Jev_decisions'
            else:
                output = run_search(store, query, top_k=100,
                                    progress=lambda n,total: print(f'Checked {n}/{total} rules', file=sys.stderr))
            outputs.append(output)
            args.out.parent.mkdir(parents=True, exist_ok=True)
            args.out.write_text(encode(outputs) + '\n')
            summary(output)
            if not args.dry_run and any(d['error'] == 'authentication_failed' for d in output['decisions']):
                break
        print('Saved results:', args.out)


if __name__ == '__main__':
    try:
        main()
    except (ValueError, FileNotFoundError):
        print('Unable to run. Check arguments/configuration or run the build command first.', file=sys.stderr)
        raise SystemExit(1)
