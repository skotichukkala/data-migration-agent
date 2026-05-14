from typing import Literal, Dict, Any
from pydantic import BaseModel, Field, ValidationError
from mcp.server import FastMCP

class OpenSearchDoc(BaseModel):
    index: str
    id: str
    body: Dict[str, Any]


def to_opensearch(kind: str, record: Dict[str, Any], dest_index: str, dest_id_prefix: str) -> Dict[str, Any]:
    if kind == "user":
        if "user_id" not in record:
            raise ValueError("Missing 'user_id' for user mapping (opensearch)")
        doc = OpenSearchDoc(
            index=dest_index,
            id=f"{dest_id_prefix}{int(record['user_id'])}",
            body={
                "user_id": int(record["user_id"]),
                "name": record.get("name", ""),
                "email": record.get("email", ""),
                "active": bool(record.get("active", False)),
            }
        )
        return doc.model_dump()

    if kind == "order":
        if "order_id" not in record:
            raise ValueError("Missing 'order_id' for order mapping (opensearch)")
        doc = OpenSearchDoc(
            index=dest_index,
            id=f"{dest_id_prefix}{int(record['order_id'])}",
            body={
                "order_id": int(record["order_id"]),
                "amount": float(record.get("amount", 0)),
                "currency": record.get("currency", "USD"),
                "status": record.get("status", "UNKNOWN"),
            }
        )
        return doc.model_dump()

    raise ValueError("Unknown kind; use 'user' or 'order'.")


def route_mapping(destination: str, kind: str, record: Dict[str, Any], dest_index: str, dest_id_prefix: str) -> Dict[str, Any]:
    d = destination.lower()
    if d == "opensearch":
        return to_opensearch(kind, record, dest_index, dest_id_prefix)
    raise ValueError(f"Unsupported destination '{destination}'. Try 'opensearch'.")


def main():
    mcp = FastMCP("Transform MCP (Mapping)")

    @mcp.tool(description="Apply mapping to a record for a destination")
    def apply_mapping(
        kind: Literal["user","order"],
        destination: Literal["opensearch"],
        record: Dict[str, Any],
        destIndex: str = "",
        destIdPrefix: str = ""
    ) -> Dict[str, Any]:
        if not destIndex:
            destIndex = "users" if kind == "user" else "orders"
        if not destIdPrefix:
            destIdPrefix = "user:" if kind == "user" else "order:"

        try:
            return route_mapping(destination, kind, record, destIndex, destIdPrefix)
        except ValidationError as ve:
            raise ValueError(f"Validation failed for destination '{destination}': {ve}")

    print("[XFORM][DEBUG] Tools: apply_mapping (supports 'opensearch')", flush=True)
    mcp.run(transport="stdio")  


if __name__ == "__main__":
    main()
