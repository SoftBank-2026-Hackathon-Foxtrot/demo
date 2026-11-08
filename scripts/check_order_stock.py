"""Create isolated presentation rounds; never reset or delete earlier orders."""
import json
import os
import time
import uuid
from urllib.request import Request, urlopen
from urllib.error import HTTPError

BASE = os.environ.get("ORDER_DEMO_BASE_URL", "http://localhost:8000/api")
def api(path,sid=None,body=None,key=None):
    headers={"Content-Type":"application/json"}
    if sid:headers["X-Session"]=sid
    if key:headers["Idempotency-Key"]=key
    with urlopen(Request(BASE+path,data=json.dumps(body).encode() if body is not None else None,headers=headers,method="POST" if body is not None else "GET"),timeout=15) as response:return json.load(response)

sid=api('/login/stock-check-'+uuid.uuid4().hex[:8],body={})['sid']
key=uuid.uuid4().hex
first=api('/live/orders/prepare',sid,{'stock':7},key)
product=first['product_id']
assert first['stock']==7 and first['accepted']==0,first
batch=uuid.uuid4().hex
for _ in range(2):api('/live/orders',sid,{'count':9,'product_id':product},batch)
deadline=time.monotonic()+25
while time.monotonic()<deadline:
    result=api(f'/live/orders?product_id={product}',sid)
    if result['pending']==0 and result['accepted']==9:break
    time.sleep(.25)
assert (result['stock'],result['confirmed'],result['sold_out'])==(0,7,2),result
assert result['initial']-result['stock']==result['confirmed_qty'],result
api('/live/orders',sid,{'count':9,'product_id':product},batch)
retry=api('/live/orders/prepare',sid,{'stock':7},key)
assert retry['product_id']==product and retry['stock']==0 and retry['accepted']==9,retry
new=api('/live/orders/prepare',sid,{'stock':3},uuid.uuid4().hex)
assert new['product_id']!=product and new['stock']==3 and new['accepted']==0,new
old=api(f'/live/orders?product_id={product}',sid)
assert old['accepted']==9 and old['stock']==0,old
try:api('/live/orders/prepare',sid,{'stock':8},key)
except HTTPError as error:assert error.code==409
else:raise AssertionError('setup key reuse with different stock must fail')
print('PASS entered stock, real inventory exhaustion, no overselling, retries after sold-out, independent rounds, old orders retained')
