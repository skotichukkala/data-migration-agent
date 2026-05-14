Migration Agent (Splunk to OpenSearch)
An automated data migration pipeline built with the Strands agent framework and MCP (Model Context Protocol). This system orchestrates four specialized agents to fetch, transform, and verify records moving from a source log system (Splunk) to a search engine (OpenSearch).

🚀 Architecture Overview
The pipeline operates as a linear chain of responsibility:

Form Intake Agent: Normalizes the migration request.

Source Agent: Communicates with the Source MCP to fetch raw data from Splunk via SPL queries.

Transform Agent: Communicates with the Transform MCP to map Splunk fields into OpenSearch-compatible JSON.

Destination Agent: Communicates with the Destination MCP to index the data into OpenSearch and verify the write.

🛠️ Components
1. main_agent.py (The Orchestrator)
The central logic that initializes MCP clients, binds agents to their respective tools, and executes the migration flow.

Source MCP: Connected via streamable-http.

Transform & Destination MCPs: Connected via stdio.

2. source_mcp.py
A FastMCP server that connects to Splunk.

Tool: get_entity_by_id

Logic: Executes an export job using the Splunk SDK to retrieve specific user or order entities from a defined index.

3. transform_mcp.py
A FastMCP server that handles data schema translation.

Tool: apply_mapping

Logic: Uses Pydantic models to ensure the data is validated and correctly formatted for the destination's schema (e.g., prepending ID prefixes like user:).

4. destination_mcp.py
A FastMCP server that interacts with the OpenSearch REST API.

Tools: index_document, get_document

Logic: Performs PUT requests to index data and GET requests to verify successful migration.

⚙️ Setup & Environment
Prerequisites
Python 3.10+

Splunk Instance (with API access)

OpenSearch Instance

Environment Variables (.env)
Create a .env file in the root directory with the following:

Ini, TOML
# Splunk Configuration
SPLUNK_HOST=localhost
SPLUNK_PORT=8089
SPLUNK_USERNAME=admin
SPLUNK_PASSWORD=your_password
SPLUNK_SCHEME=https

# MCP Configuration
SOURCE_MCP_URL=http://127.0.0.1:8000/mcp/
Installation
Install dependencies:

Bash
pip install requests splunk-sdk mcp pydantic python-dotenv strands
🏃 Running the Pipeline
Step 1: Start the Source MCP (HTTP)
The Source MCP must run as a standalone server because the Main Agent connects to it via HTTP:

Bash
python source_mcp.py
Step 2: Run the Migration Agent
In a new terminal window, run the orchestrator. This will automatically spawn the Transform and Destination MCPs via stdio:

Bash
python main_agent.py
🔍 Example Workflow
The agent processes a form like this:

JSON
{
  "source": {"type": "splunk", "index": "main"},
  "destination": {"type": "opensearch", "index": "users", "idPrefix": "user:"},
  "data": {"kind": "user", "id": 103}
}
Output: A full migration report including the raw source record, the transformed document, and the OpenSearch verification status.