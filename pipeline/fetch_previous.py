"""Load published state; fail rather than silently lose history on network errors."""
import urllib.request
import urllib.error
from pathlib import Path
import json
import os

try:
    request = urllib.request.Request(
        os.environ.get('SITE_URL', 'https://biopharma-radar.pages.dev').rstrip('/')+'/data/latest.json',
        headers={'User-Agent':'BioPharmaRadar/1.0 (+https://github.com/yykuma/biopharma-radar)', 'Accept':'application/json'})
    with urllib.request.urlopen(request,timeout=25) as response:
        data=response.read()
        if not isinstance(json.loads(data).get('items'),list):raise ValueError('Invalid snapshot')
        Path('previous.json').write_bytes(data)
except urllib.error.HTTPError as exc:
    if exc.code!=404:raise
    print('No previous deployment; bootstrapping.')
