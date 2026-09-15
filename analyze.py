"""List all paths under the wesais domains."""
from collections import defaultdict
from mitmproxy import io

flows = []
with open('traffic.log', 'rb') as f:
    for fl in io.FlowReader(f).stream():
        if isinstance(fl, dict):
            continue
        flows.append(fl)

# Focus on wesais domains
wesais_hosts = {'api.wesais.com', 'xcx.wesais.com', 'apitest.wesais.cn'}
target_flows = [fl for fl in flows if fl.request.pretty_host in wesais_hosts]
print(f"Flows under wesais domains: {len(target_flows)}\n")

# Show all unique paths
paths = defaultdict(list)
for fl in target_flows:
    key = (fl.request.pretty_host, fl.request.method, fl.request.path)
    paths[key].append(fl)

print("=== All endpoints ===")
for (host, method, path), fls in sorted(paths.items()):
    print(f"{len(fls):3d}  {host:20s} {method:6s} {path}")

print("\n" + "="*80)
print("=== Sample response for each endpoint ===")
for (host, method, path), fls in sorted(paths.items()):
    fl = fls[0]
    status = fl.response.status_code if fl.response else "?"
    rbody = (fl.response.text or "")[:200] if fl.response else ""
    print(f"\n--- {host} {method} {path} [{status}] ({len(fls)}x) ---")
    if rbody:
        print(f"  resp: {rbody}")
