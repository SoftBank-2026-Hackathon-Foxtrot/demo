"""Local integration check; creates test orders without resetting existing data."""
import json
import time
import uuid
from urllib.error import HTTPError
from urllib.request import Request, urlopen

BASE = "http://localhost:8000/api"

def api(path, sid=None, method="GET", body=None, key=None):
    headers={"Content-Type":"application/json"}
    if sid: headers["X-Session"]=sid
    if key: headers["Idempotency-Key"]=key
    request=Request(BASE+path, data=json.dumps(body).encode() if body is not None else (b"" if method=="POST" else None),method=method,headers=headers)
    with urlopen(request,timeout=15) as response:return json.load(response)

def rejects(path,sid,status,**kwargs):
    try:api(path,sid,**kwargs)
    except HTTPError as error:assert error.code==status,(error.code,error.read())
    else:raise AssertionError(f"expected {status}")

sid=api('/login/order-check-'+uuid.uuid4().hex[:8],method='POST')['sid']
try:
    rejects('/live/orders',None,401)
    before=api('/live/orders/prepare',sid,method='POST')
    key=uuid.uuid4().hex
    api('/live/orders',sid,method='POST',body={'count':5},key=key)
    api('/live/orders',sid,method='POST',body={'count':5},key=key)
    rejects('/live/orders',sid,422,method='POST',body={'count':0},key=uuid.uuid4().hex)
    rejects('/live/orders',sid,422,method='POST',body={'count':101},key=uuid.uuid4().hex)
    end=time.monotonic()+20
    while time.monotonic()<end:
        mine=api('/me/requests',sid)
        if len(mine)==5 and all(row['status']=='CONFIRMED' for row in mine):break
        time.sleep(.25)
    assert len(mine)==5,mine
    assert all(row['status']=='CONFIRMED' for row in mine),mine
    after=api('/live/orders',sid)
    assert after['initial']-after['stock']==after['confirmed_qty'],after
    assert after['accepted']==after['confirmed']+after['pending']+after['sold_out'],after
    assert after['accepted']>=before['accepted']+5,(before,after)
    assert len(api('/me/requests',sid))==5
    print('PASS auth, batch bounds, retry idempotency, actual worker confirmations, stock invariant, DB snapshot counts')
finally:
    api('/logout',sid,method='POST')
