import os
from typing import Any, Dict
from dotenv import load_dotenv
from mcp.server import FastMCP
import splunklib.client as splunk_client
from splunklib.results import JSONResultsReader


def _env(name: str, default: str) -> str:
    v = os.getenv(name, default)
    if v is None:
        raise RuntimeError(f"Missing env var: {name}")
    return v


def connect_splunk():
    print("[SRC][DEBUG] Connecting to Splunk ...", flush=True)
    host = _env("SPLUNK_HOST", "localhost")
    port = int(_env("SPLUNK_PORT", "8089"))
    user = _env("SPLUNK_USERNAME", "admin")
    pwd  = _env("SPLUNK_PASSWORD", "password")
    scheme = os.getenv("SPLUNK_SCHEME", "https") 
    return splunk_client.connect(
        host=host, port=port, username=user, password=pwd, scheme=scheme, verify=False
    )

#helper function
def _coerce_types(kind: str, rec: Dict[str, Any]) -> Dict[str, Any]:
    def as_int(x):
        try: return int(x)
        except: return x
    def as_float(x):
        try: return float(x)
        except: return x
    def as_bool(x):
        s = str(x).lower()
        if s in ("true","1","yes","y"): return True
        if s in ("false","0","no","n"): return False
        return x

    if kind == "user":
        if "user_id" in rec: rec["user_id"] = as_int(rec["user_id"])
        if "active"  in rec: rec["active"]  = as_bool(rec["active"])
    else:
        if "order_id" in rec: rec["order_id"] = as_int(rec["order_id"])
        if "amount"   in rec: rec["amount"]   = as_float(rec["amount"])
    return rec


def fetch_from_splunk(service, kind: str, entity_id: int, index: str) -> Dict[str, Any]:
    print(f"[SRC][DEBUG] Fetching: kind={kind}, id={entity_id}, index={index}", flush=True)

    if kind == "user":
        where = f'(user_id="{entity_id}" OR userid="{entity_id}" OR userId="{entity_id}" OR id="{entity_id}")'
        wanted = "user_id name email active"
    else:
        where = f'(order_id="{entity_id}" OR orderId="{entity_id}" OR id="{entity_id}")'
        wanted = "order_id amount currency status"

    spl = (
        f'search index="{index}" {where} earliest=-7d latest=now '
        f'| sort - _time '
        f'| fields {wanted} '
        f'| head 1'
    )
    print(f"[SRC][DEBUG] SPL: {spl}", flush=True)

    stream = service.jobs.export(
        spl, search_mode="normal", earliest_time="-7d", latest_time="now", output_mode="json"
    )
    rr = JSONResultsReader(stream)

    for item in rr:
        if not isinstance(item, dict):
            print(f"[SRC][DEBUG] (message) {item}", flush=True)
            continue
        row = item.get("result", item)
        rec = {k: v for k, v in row.items() if not str(k).startswith("_")}
        rec = _coerce_types(kind, rec)
        print("[SRC][DEBUG] Raw record:", rec, flush=True)
        return rec

    raise ValueError(f"No record found for kind={kind} id={entity_id} in index={index} (last 7d)")


def main():
    load_dotenv()
    service = connect_splunk()
    mcp = FastMCP("Source MCP (Splunk)")

    @mcp.tool(description="Fetch a raw record from Splunk by kind ('user'|'order') and id.")
    def get_entity_by_id(kind: str, id: int, index: str) -> Dict[str, Any]:
        k = str(kind).lower()
        if k not in ("user","order"):
            raise ValueError("kind must be 'user' or 'order'")
        return fetch_from_splunk(service, k, int(id), index)

    print("[SRC][DEBUG] Tools: get_entity_by_id", flush=True)
    print("[SRC][DEBUG] Starting HTTP server on :8000 ...", flush=True)
    mcp.run(transport="streamable-http")


if __name__ == "__main__":
    main()
