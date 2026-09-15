"""Run two independent editorial tasks with shared supplier reservations."""
from concurrent.futures import ThreadPoolExecutor

from ai_router import RoutingSession, invoke, load_registry, new_state
from curate import curate
from localize import localize


def enrich(items, sources, previous, enabled, now, call=invoke, config=None):
    config = config or load_registry()
    session = RoutingSession(new_state((previous or {}).get('router_state', {}), now), config.get('execution'))
    # The tasks mutate disjoint fields; grouping and publishing wait for both.
    with ThreadPoolExecutor(max_workers=min(2,session.max_requests)) as pool:
        translation = pool.submit(localize, items, sources, previous, enabled, now, call, config, session)
        classification = pool.submit(curate, items, previous, enabled, now, call, config, session)
        translation_result = translation.result()
        _, report = classification.result()
    report['translation'] = translation_result['translation_run']
    report['execution'] = {'mode': 'parallel_suppliers', 'concurrency_limit': session.max_requests,
                           'supplier_limits': session.supplier_limits, 'default_supplier_limit': 1,
                           'max_observed_per_supplier': session.observed_by_supplier, 'max_observed_parallel': session.max_parallel,
                           'attempts': session.attempts}
    return {**(previous or {}), 'router_state': session.state}, report
