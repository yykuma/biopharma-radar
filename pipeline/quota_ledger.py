"""Reserve daily requests before inference in a small GitHub-backed ledger."""
import base64
import json
import os
from datetime import datetime, timezone
from urllib.error import HTTPError
from urllib.parse import quote
from urllib.request import Request, urlopen

BRANCH = 'codex/ai-state'


class LedgerUnavailable(Exception):
    pass


def github(method, path, payload=None):
    token = os.environ.get('QUOTA_GITHUB_TOKEN')
    if not token:
        raise LedgerUnavailable('Missing ledger credential')
    request = Request('https://api.github.com' + path, method=method,
                      headers={'Authorization':'Bearer '+token, 'Accept':'application/vnd.github+json',
                               'X-GitHub-Api-Version':'2022-11-28', 'User-Agent':'BioPharmaRadar'},
                      data=json.dumps(payload).encode() if payload is not None else None)
    with urlopen(request,timeout=15) as response:
        return json.load(response)


def reserve_daily(provider, limit, now, api=github):
    repository = os.environ.get('GITHUB_REPOSITORY', 'yykuma/biopharma-radar')
    day = datetime.fromtimestamp(now,timezone.utc).strftime('%Y-%m-%d')
    reset_at = (int(now)//86400+1)*86400
    path = '/repos/'+repository+'/contents/state/'+quote(provider,safe='')+'-quota.json'
    for _ in range(3):
        sha = None
        try:
            stored = api('GET',path+'?ref='+quote(BRANCH,safe=''))
            sha = stored['sha']
            previous = json.loads(base64.b64decode(stored['content']))
            used = previous['used'] if previous['date']==day else 0
            if type(used) is not int or used<0:
                raise LedgerUnavailable('Invalid ledger count')
        except HTTPError as exc:
            if exc.code!=404:
                raise LedgerUnavailable('Cannot read ledger') from None
            used = 0
        except (KeyError,ValueError,TypeError):
            raise LedgerUnavailable('Invalid ledger state') from None
        record = {'date':day,'used':used,'limit':limit,'reset_at':reset_at}
        if used>=limit:
            return {**record,'reserved':False}
        record['used']+=1
        payload = {'message':'Reserve '+provider+' request', 'branch':BRANCH,
                   'content':base64.b64encode(json.dumps(record).encode()).decode()}
        if sha:
            payload['sha']=sha
        try:
            api('PUT',path,payload)
            return {**record,'reserved':True}
        except HTTPError as exc:
            if exc.code not in (409,422):
                raise LedgerUnavailable('Cannot save ledger') from None
    raise LedgerUnavailable('Ledger contention')
