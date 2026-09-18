"""Focus on the critical endpoints: order/create, ticket sale, login."""
import sys, os
os.environ['PYTHONIOENCODING'] = 'utf-8'
sys.stdout.reconfigure(encoding='utf-8', errors='replace')

from mitmproxy import io

flows = []
with open('traffic.log', 'rb') as f:
    for fl in io.FlowReader(f).stream():
        if isinstance(fl, dict):
            continue
        flows.append(fl)

def show_flows(label, path_key):
    matches = [fl for fl in flows
               if fl.request.host == 'api.wesais.com'
               and fl.request.path == path_key
               and fl.request.method == 'POST']
    print(f"\n{'='*80}\n### {label} — {len(matches)} request(s)\n{'='*80}")
    for i, fl in enumerate(matches):
        status = fl.response.status_code if fl.response else "?"
        print(f"\n--- #{i+1} POST {path_key} [{status}] ---")
        print("REQUEST HEADERS:")
        for k, v in fl.request.headers.items():
            if k.lower() in ('cookie','authorization','user-agent','content-type','x-forwarded-for','host','accept','referer'):
                print(f"  {k}: {v[:300]}")
        print("REQUEST BODY:")
        rb = fl.request.text or ""
        if rb:
            print(f"  {rb[:2000]}")
        else:
            print("  <empty>")
        print("RESPONSE BODY:")
        if fl.response:
            rbody = fl.response.text or ""
            if rbody:
                print(f"  {rbody[:2000]}")
            else:
                print("  <empty>")

# Focus on order create
show_flows("SUBMIT ORDER (shop/order/create)", "/shop/order/create")

# Ticket sale info
show_flows("GET TICKET ONE", "/ticket/wxTicketSale/getTicketOne")
show_flows("GET SALE TICKET LIST", "/ticket/wxTicketSale/getSaleTicketList")
show_flows("GET DATE LIST", "/ticket/wxTicketSale/getDateList")
