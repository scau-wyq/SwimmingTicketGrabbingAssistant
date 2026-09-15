"""Check login and token endpoints, plus full endpoint list."""
import sys, os, json
os.environ['PYTHONIOENCODING'] = 'utf-8'
sys.stdout.reconfigure(encoding='utf-8', errors='replace')
from collections import defaultdict
from mitmproxy import io

flows = []
with open('traffic.log', 'rb') as f:
    for fl in io.FlowReader(f).stream():
        if isinstance(fl, dict): continue
        flows.append(fl)

# All wesais endpoints
wesais_hosts = {'api.wesais.com', 'xcx.wesais.com', 'apitest.wesais.cn'}
print("=" * 80)
print("=== ALL wesais endpoints (full list) ===")
print("=" * 80)
paths = defaultdict(list)
for fl in flows:
    if fl.request.pretty_host in wesais_hosts:
        key = (fl.request.method, fl.request.path)
        paths[key].append(fl)
for (method, path), fls in sorted(paths.items()):
    status = fls[0].response.status_code if fls[0].response else "?"
    print(f"  {len(fls):3d}x  {method:6s} {path}  [{status}]")

# Login endpoints
print("\n" + "=" * 80)
print("=== LOGIN & TOKEN FLOW ===")
print("=" * 80)
login_keys = ['/member/wxMember/miniLogin', '/member/wxMember/exToken',
              '/member/wxMember/login', '/user/wxUser/login']
for key in login_keys:
    matches = [fl for fl in flows
               if fl.request.host == 'api.wesais.com'
               and fl.request.path == key]
    if matches:
        for i, fl in enumerate(matches):
            status = fl.response.status_code if fl.response else "?"
            print(f"\n--- #{i+1} {fl.request.method} {key} [{status}] ---")
            rb = fl.request.text or ""
            if rb:
                print(f"  REQ:  {rb[:500]}")
            rbody = fl.response.text or "" if fl.response else ""
            if rbody:
                print(f"  RESP: {rbody[:500]}")
    else:
        print(f"  {key} — not found in log")

# Check if Authorization header is consistent across requests
print("\n" + "=" * 80)
print("=== AUTHORIZATION HEADER ANALYSIS ===")
print("=" * 80)
auths = []
for fl in flows:
    if fl.request.host == 'api.wesais.com':
        auth = fl.request.headers.get('Authorization', '')
        if auth:
            auths.append((fl.request.timestamp_start, fl.request.path, auth[:80]))
print(f"Total requests with Authorization: {len(auths)}")
unique_auths = set(a[2] for a in auths)
print(f"Unique Authorization headers: {len(unique_auths)}")
print(f"\nFirst 5 timestamps (epoch) and paths:")
for ts, path, auth in auths[:5]:
    print(f"  t={ts:.3f}  {path}  auth={auth}...")
print(f"\nLast 5 timestamps:")
for ts, path, auth in auths[-5:]:
    print(f"  t={ts:.3f}  {path}  auth={auth}...")

# Decode JWT payload for a few tokens
import base64
print("\n" + "=" * 80)
print("=== JWT DECODE ===")
print("=" * 80)
for i, (ts, path, auth) in enumerate(auths[:3]):
    parts = auth.split('.')
    if len(parts) >= 2:
        # Decode payload
        payload_b64 = parts[1]
        # Add padding
        payload_b64 += '=' * (4 - len(payload_b64) % 4)
        try:
            payload = json.loads(base64.urlsafe_b64decode(payload_b64))
            print(f"\nToken #{i+1} (path={path}):")
            print(f"  ct (timestamp): {payload.get('ct')}")
            print(f"  id: {payload.get('id')}")
            print(f"  aid: {payload.get('aid')}")
            print(f"  mid: {payload.get('mid')}")
            print(f"  tid: {payload.get('tid')}")
            params = payload.get('params', '')
            if isinstance(params, str):
                params = json.loads(params)
            print(f"  params: {json.dumps(params, ensure_ascii=False, indent=4)}")
        except Exception as e:
            print(f"  Decode error: {e}")
