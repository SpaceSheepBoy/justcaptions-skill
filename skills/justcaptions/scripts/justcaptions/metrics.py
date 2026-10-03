"""Optional setup/export counters. No file paths, transcript text or keys are sent."""
import os
import re
import json
import urllib.request
from . import api

def record(event, detail='', occurrence=''):
    journey=os.environ.get('JUSTCAPTIONS_METRICS_ID','')
    if not re.fullmatch('[a-f0-9]{32}',journey):
        return
    try:
        request=urllib.request.Request(api.base_url()+'/events',data=json.dumps({'journey':journey,'event':event,'detail':detail,'occurrence':occurrence}).encode(),headers={'Content-Type':'application/json','User-Agent':'justcaptions-skill/1.3'},method='POST')
        with urllib.request.urlopen(request,timeout=2):
            pass
    except Exception:
        pass  # counters never fail a user's caption job
