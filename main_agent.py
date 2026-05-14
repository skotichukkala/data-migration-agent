import json
import os
import re
import sys
from typing import Any, Dict, Optional

from dotenv import load_dotenv
from strands import Agent
from strands.tools.mcp.mcp_client import MCPClient

# MCP transports
from mcp.client.streamable_http import streamablehttp_client   
from mcp import stdio_client, StdioServerParameters            


# -----------------------------
# Agent system prompts
# -----------------------------

FORM_PROMPT = """
You are the Form Intake Agent.
You receive a JSON object from a UI form with fields:
{
  "source": {"type":"splunk","index": "..."},
  "destination": {"type":"opensearch","index":"...","idPrefix":"..."},
  "data": {"kind":"user|order","id": number}
}

Your job:
- Validate presence and types.
- Normalize values:
  - kind must be "user" or "order" (lowercase)
  - id must be an integer
  - source.index default "main" (Splunk)
  - destination.type must be "opensearch" (for now)
  - destination.index default: "users" if kind=user else "orders"
  - destination.idPrefix default: "user:" if kind=user else "order:"

Output: pure JSON ONLY (no prose, no code fences) with the shape:
{
  "kind": "user|order",
  "id": 123,
  "sourceIndex": "main",
  "destination": "opensearch",
  "destIndex": "users|orders|...",
  "destIdPrefix": "user:|order:|..."
}
"""

SOURCE_PROMPT = """
You are the Source Agent.
You can ONLY call the tool:
  get_entity_by_id(kind, id, index)
Return the raw JSON ONLY (no prose). If nothing is found, return:
{"error":"not_found"}.
"""

TRANSFORM_PROMPT = """
You are the Transform Agent.
You can ONLY call the tool:
  apply_mapping(kind, mappingVersion, destination, record, destIndex, destIdPrefix)
Return transformed JSON ONLY (no prose).
"""

DEST_PROMPT = """
You are the Destination Agent for OpenSearch.
You can call:
  - index_document(doc)
  - get_document(index, id)
Always return pure JSON only (no prose).
"""


# -----------------------------
# Helpers
# -----------------------------
# LLM might return in text or content
def _extract_text(result_obj) -> str:
    t = getattr(result_obj, "text", None) or getattr(result_obj, "content", None)
    return t if isinstance(t, str) else str(result_obj)
# LLM might add extra fences around the object
def _clean_fenced_json(s: str) -> str:
    s = s.strip()
    if s.startswith("```"):
        s = re.sub(r"^```(?:json)?\s*", "", s)
        s = re.sub(r"\s*```$", "", s)
    return s
# LLM might add extra text
def _parse_json_loose(s: str) -> Dict[str, Any]:
    s = _clean_fenced_json(s)
    try:
        return json.loads(s)
    except Exception:
        m = re.search(r"\{.*\}", s, re.DOTALL)
        if not m:
            raise
        return json.loads(m.group(0))


# -----------------------------
# Orchestrator
# -----------------------------

class FormPipeline:
    def __init__(self):
        self.source_client: Optional[MCPClient] = None
        self.transform_client: Optional[MCPClient] = None
        self.dest_client: Optional[MCPClient] = None

        self.form_agent: Optional[Agent] = None
        self.source_agent: Optional[Agent] = None
        self.transform_agent: Optional[Agent] = None
        self.dest_agent: Optional[Agent] = None

    def start(self):
        load_dotenv()

        # 1) Form Intake Agent (no tools)
        self.form_agent = Agent(system_prompt=FORM_PROMPT, tools=[])

        # 2) Source MCP (HTTP)
        source_url = os.getenv("SOURCE_MCP_URL", "http://127.0.0.1:8000/mcp/")
        self.source_client = MCPClient(lambda: streamablehttp_client(source_url))

        # 3) Transform MCP (STDIO)
        self.transform_client = MCPClient(lambda: stdio_client(
            StdioServerParameters(command=sys.executable, args=["transform_mcp.py"])))

        # 4) Destination MCP (STDIO)
        self.dest_client = MCPClient(lambda: stdio_client(
            StdioServerParameters(command=sys.executable, args=["destination_mcp.py"])))

        # open MCP clients
        self.source_client.__enter__()
        self.transform_client.__enter__()
        self.dest_client.__enter__()

        # discover tools
        source_tools = self.source_client.list_tools_sync()
        transform_tools = self.transform_client.list_tools_sync()
        dest_tools = self.dest_client.list_tools_sync()

        # bind agents
        self.source_agent = Agent(system_prompt=SOURCE_PROMPT, tools=source_tools)
        self.transform_agent = Agent(system_prompt=TRANSFORM_PROMPT, tools=transform_tools)
        self.dest_agent = Agent(system_prompt=DEST_PROMPT, tools=dest_tools)

        print("Form → Source → Transform → Destination → Verify")

    def stop(self):
        try:
            if self.source_client is not None:
                self.source_client.__exit__(None, None, None)
        finally:
            try:
                if self.transform_client is not None:
                    self.transform_client.__exit__(None, None, None)
            finally:
                if self.dest_client is not None:
                    self.dest_client.__exit__(None, None, None)

    def submit_form(self, form_json: Dict[str, Any]) -> Dict[str, Any]:
        # --- Agent 1: Form Intake (normalize)
        form_text = json.dumps(form_json)
        intake_result = self.form_agent(  
            f"Normalize this form: {form_text}"
        )
        intake_text = _extract_text(intake_result)
        task = _parse_json_loose(intake_text)

        # Required fields after normalization
        kind = str(task["kind"]).lower()
        entity_id = int(task["id"])
        source_index = task.get("sourceIndex", "main")
        dest = task.get("destination", "opensearch")
        dest_index = task.get("destIndex", "users" if kind == "user" else "orders")
        dest_id_prefix = task.get("destIdPrefix", "user:" if kind == "user" else "order:")

        # --- Agent 2: Source fetch
        source_instr = f"Use get_entity_by_id(kind='{kind}', id={entity_id}, index='{source_index}')"
        src_out = self.source_agent(source_instr)  
        src_text = _extract_text(src_out)
        source_record = _parse_json_loose(src_text)

        required = "user_id" if kind == "user" else "order_id"
        if not isinstance(source_record, dict) or required not in source_record or "error" in source_record:
            return {
                "ok": False,
                "message": source_record.get("error", f"missing '{required}' in source record"),
                "task": task,
                "source": source_record,
                "transformed": None,
                "destination_index": None,
                "destination_verify": None,
            }

        # --- Agent 3: Transform
        transform_instr = (
            f"Use apply_mapping(kind='{kind}', "
            f"destination='{dest}', record={json.dumps(source_record)}, "
            f"destIndex='{dest_index}', destIdPrefix='{dest_id_prefix}')"
        )
        tx_out = self.transform_agent(transform_instr)  
        tx_text = _extract_text(tx_out)
        transformed = _parse_json_loose(tx_text)

        # --- Agent 4: Destination (index + verify)
        doc_json = json.dumps(transformed)
        idx_out = self.dest_agent(f"Use index_document(doc={doc_json})")  
        idx_text = _extract_text(idx_out)
        index_result = _parse_json_loose(idx_text)

        verify_out = self.dest_agent(  
            f"Use get_document(index='{transformed['index']}', id='{transformed['id']}')"
        )
        verify_text = _extract_text(verify_out)
        verify_result = _parse_json_loose(verify_text)

        # verify
        wrote_body = transformed.get("body", {})
        try:
            read_source = verify_result.get("response", {}).get("_source", {})
        except Exception:
            read_source = {}

        ok_equivalent = (wrote_body == read_source)

        return {
            "ok": bool(ok_equivalent),
            "message": "Migrated & verified" if ok_equivalent else "Posted, but verification differs",
            "task": task,
            "source": source_record,
            "transformed": transformed,
            "destination_index": index_result,
            "destination_verify": verify_result,
            "equivalent": ok_equivalent,
            "diff_hint": None if ok_equivalent else {
                "expected_body": wrote_body,
                "actual_body": read_source
            }
        }


# -----------------------------
# In process form
# -----------------------------

if __name__ == "__main__":
    pipeline = FormPipeline()
    pipeline.start()

    # UI Form
    example_form = {
        "source": {"type": "splunk", "index": "main"},
        "destination": {"type": "opensearch", "index": "users", "idPrefix": "user:"},
        "data": {"kind": "user", "id": 103},
    }

    result = pipeline.submit_form(example_form)
    print("\n=== RESULT ===")
    print(json.dumps(result, indent=2))

    pipeline.stop()
