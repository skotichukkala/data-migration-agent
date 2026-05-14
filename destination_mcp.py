import os
import json
from typing import Dict, Any

import requests
from requests.auth import HTTPBasicAuth
from mcp.server import FastMCP

try:
    from dotenv import load_dotenv
    load_dotenv()
except Exception:
    pass


def _env(name: str, default: str = "") -> str:
    v = os.getenv(name, default)
    if not v:
        raise RuntimeError(f"Missing required env var: {name}")
    return v


def _client():
    # Hard-coded values
    base_url = "https://localhost:9200"
    user = _env("DEST_USER", "admin") 
    pwd = _env("DEST_PWD", "password")

    s = requests.Session()
    s.auth = HTTPBasicAuth(user, pwd)
    s.headers.update({"Content-Type": "application/json"})
    s.verify = False  
    return base_url, s


def main():
    mcp = FastMCP("Destination MCP (OpenSearch, STDIO)")

    @mcp.tool(description="Index (create/update) one document in OpenSearch.")
    def index_document(doc: Dict[str, Any]) -> Dict[str, Any]:
        """
        doc = { "index": "users", "id": "user:101", "body": { ... } }
        """
        base, s = _client()
        index = doc.get("index")
        _id = doc.get("id")
        body = doc.get("body")
        if not index or not _id or not isinstance(body, dict):
            return {"error": "doc must include 'index'(str), 'id'(str), and 'body'(object)"}

        url = f"{base}/{index}/_doc/{_id}"
        r = s.put(url, data=json.dumps(body))
        try:
            data = r.json()
        except Exception:
            data = {"text": r.text}
        return {"status": r.status_code, "response": data}

    @mcp.tool(description="Fetch a document from OpenSearch by index and id.")
    def get_document(index: str, id: str) -> Dict[str, Any]:
        base, s = _client()
        url = f"{base}/{index}/_doc/{id}"
        r = s.get(url)
        if r.status_code == 404:
            return {"status": 404, "error": "not_found"}
        try:
            data = r.json()
        except Exception:
            data = {"text": r.text}
        return {"status": r.status_code, "response": data}

    print("[DEST][DEBUG] Tools: index_document, get_document", flush=True)
    mcp.run(transport="stdio")


if __name__ == "__main__":
    main()
