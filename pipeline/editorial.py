"""Coordinate editorial jobs through a shared AI routing session."""
from concurrent.futures import ThreadPoolExecutor

from ai_router import RoutingSession, candidates, invoke, load_registry, new_state
from curate import curate
from localize import localize


def enrich(items, sources, previous, enabled, now, call=invoke, config=None, session=None):
    config = config or load_registry()
    session = session or RoutingSession(new_state((previous or {}).get('router_state', {}), now), config.get('execution'))
    choices = [choice for task in ('news_translation', 'news_curation')
               for choice in candidates({**config, 'task':task}, session.state, now)]
    preferred = {p.get('supplier',p['id']) for p, _, _ in choices if p.get('routing_role') != 'fallback'}
    workers = min(2, session.max_requests, max(1,len(preferred)))
    if config['strategy'] == 'failover':
        workers = 1
    jobs = {'translation': lambda: localize(items,sources,previous,enabled,now,call,config,session),
            'curation': lambda: curate(items,previous,enabled,now,call,config,session)}
    order = config.get('execution',{}).get('task_order',['translation','curation'])
    # A single eligible primary supplier runs jobs in priority order, including input fetching.
    with ThreadPoolExecutor(max_workers=workers) as pool:
        futures = {name:pool.submit(jobs[name]) for name in order}
        results = {name:future.result() for name,future in futures.items()}
    _, report = results['curation']
    report['translation'] = results['translation']['translation_run']
    report['execution'] = {**session.report(), 'mode':'parallel_suppliers' if workers>1 else 'priority_serial',
                           'task_order':order}
    return {**(previous or {}), 'router_state':session.state}, report
