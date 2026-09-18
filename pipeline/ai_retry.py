"""Resume cached AI work independently of RSS collection and persist cooldowns."""
import argparse
import base64
import hashlib
import json
import os
import time
from pathlib import Path
from urllib.error import HTTPError
from urllib.parse import quote

from ai_router import BRIEFING_VERSION, candidates, load_registry
from curate import VERSION, digest
from quota_ledger import BRANCH, github


def pending_tasks(snapshot, config, now):
    items = snapshot.get('items', [])
    tasks = []
    if any(not a.get('title_zh') and a.get('language') != 'zh' for a in items):
        tasks.append('news_translation')
    if any(a.get('editorial', {}).get('version') != VERSION or
           a.get('editorial', {}).get('fingerprint') != digest(a) for a in items):
        tasks.append('news_curation')
    visible, events = [], set()
    for a in items:
        event = a.get('event_id', str(a['id']))
        if a.get('editorial', {}).get('category') != 'marketing' and event not in events:
            visible.append(a)
            events.add(event)
    selected = visible[:min(40, config['max_input_articles'])]
    input_digest = hashlib.sha256(json.dumps([(a['id'], a['title']) for a in selected]).encode()).hexdigest()
    briefing = snapshot.get('briefing', {})
    reusable = (briefing.get('format_version') == BRIEFING_VERSION and briefing.get('generated_at') and
                (now - briefing['generated_at'] < config['summary_interval_hours'] * 3600 or
                 briefing.get('input_digest') == input_digest))
    if selected and not reusable:
        tasks.append('news_summary')
    return tasks


def next_retry(snapshot, config, now):
    tasks = pending_tasks(snapshot, config, now)
    state = snapshot.get('briefing', {}).get('router_state', {})
    earliest = now + 120
    checkpoints = sorted({earliest, *(max(earliest, t) for t in state.get('cooldowns', {}).values())})
    for when in checkpoints:
        if any(candidates({**config, 'task': task}, state, when) for task in tasks):
            return int(when)
    return None


def reader_content(snapshot):
    return {
        'items': [{k: a.get(k) for k in ('id', 'title', 'excerpt', 'title_zh', 'summary_zh',
                                       'editorial', 'event_id', 'related_article_ids')} for a in snapshot.get('items', [])],
        'briefing': {k: snapshot.get('briefing', {}).get(k) for k in ('text', 'generated_at', 'references')},
    }


def state_path():
    repo = os.environ.get('GITHUB_REPOSITORY', 'yykuma/biopharma-radar')
    return '/repos/' + repo + '/contents/state/ai-router.json'


def read_state(api=github):
    try:
        result = api('GET', state_path() + '?ref=' + quote(BRANCH, safe=''))
    except HTTPError as exc:
        if exc.code == 404:
            return None, None
        raise
    record = json.loads(base64.b64decode(result['content']))
    if not isinstance(record.get('router_state'), dict) or not isinstance(record.get('saved_at'), int):
        raise ValueError('Invalid persisted AI state')
    return record, result['sha']


def restore_state(snapshot, record):
    if record and record['saved_at'] >= snapshot.get('updated_at', 0):
        snapshot.setdefault('briefing', {})['router_state'] = record['router_state']
        for article in snapshot.get('items', []):
            attempt = record.get('translation_attempts', {}).get(str(article['id']))
            if attempt and not article.get('title_zh') and attempt['fingerprint'] == digest(article):
                article.update(content_fingerprint=attempt['fingerprint'],
                               translation={'status': 'pending', 'last_attempt_at': attempt['last_attempt_at']})
    return snapshot


def save_state(snapshot, retry_at, now, api=github):
    record = {'saved_at': now, 'next_retry_at': retry_at,
              'pending_tasks': pending_tasks(snapshot, load_registry(), now),
              'translation_attempts': {str(a['id']): {'fingerprint': digest(a),
                  'last_attempt_at': a['translation']['last_attempt_at']} for a in snapshot.get('items', [])
                  if not a.get('title_zh') and a.get('translation', {}).get('last_attempt_at')},
              'router_state': snapshot.get('briefing', {}).get('router_state', {})}
    # Publishing jobs share a GitHub concurrency group, including collection runs.
    _, sha = read_state(api)
    payload = {'message': 'Checkpoint AI retry state', 'branch': BRANCH,
               'content': base64.b64encode(json.dumps(record).encode()).decode()}
    if sha:
        payload['sha'] = sha
    api('PUT', state_path(), payload)


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument('mode', choices=['restore', 'finish'])
    parser.add_argument('--previous', type=Path, default=Path('previous.json'))
    parser.add_argument('--snapshot', type=Path, default=Path('frontend/public/data/latest.json'))
    parser.add_argument('--ai-only', action='store_true')
    args = parser.parse_args()
    previous = json.loads(args.previous.read_text()) if args.previous.exists() else {}
    if args.mode == 'restore':
        previous = restore_state(previous, read_state()[0])
        args.previous.write_text(json.dumps(previous, ensure_ascii=False))
        return
    snapshot = json.loads(args.snapshot.read_text())
    now = int(time.time())
    retry_at = next_retry(snapshot, load_registry(), now)
    publish = not args.ai_only or reader_content(previous) != reader_content(snapshot)
    save_state(snapshot, retry_at, now)
    with open(os.environ['GITHUB_OUTPUT'], 'a') as output:
        output.write(f"publish={'true' if publish else 'false'}\nretry_at={retry_at or ''}\n")
    print(json.dumps({'publish': publish, 'next_retry_at': retry_at,
                      'pending_tasks': pending_tasks(snapshot, load_registry(), now)}))


if __name__ == '__main__':
    main()
