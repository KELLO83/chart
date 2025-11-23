## Sequential Thinking MCP

A Model Context Protocol (MCP) server that exposes a structured, reflective thinking tool for complex reasoning workflows.

### Features
- **Stepwise reasoning**: Break problems into ordered thoughts with explicit numbering.
- **Dynamic planning**: Increase/decrease the planned number of thoughts at any point.
- **Branching**: Fork alternative reasoning paths and keep them labeled.
- **Revision friendly**: Revisit prior thoughts and mark them as revisions.
- **Hypothesis verification**: Iterate until a validated conclusion emerges.

### Tool: `sequential_thinking`
Facilitates detailed thought-by-thought reasoning.

**Inputs**
- `thought` *(string)* – Current thinking step text.
- `nextThoughtNeeded` *(boolean)* – Request another thought step.
- `thoughtNumber` *(integer)* – Index for the current thought.
- `totalThoughts` *(integer)* – Estimated total thoughts planned.
- `isRevision` *(boolean, optional)* – Marks the thought as a revision.
- `revisesThought` *(integer, optional)* – Reference to the thought being revised.
- `branchFromThought` *(integer, optional)* – Thought number where a branch begins.
- `branchId` *(string, optional)* – Identifier for the branch.
- `needsMoreThoughts` *(boolean, optional)* – Signal that the plan needs to expand.

### Usage Scenarios
- Complex analysis and planning that evolves as new info appears.
- Designs or investigations requiring explicit reasoning trails.
- Tasks where irrelevant info must be filtered through deliberate steps.
- Maintaining context across long multi-step solutions.

### Installation / Configuration

#### NPX (general clients, VS Code, Claude Desktop, etc.)
```json
{
  "mcpServers": {
    "sequential-thinking": {
      "command": "npx",
      "args": [
        "-y",
        "@modelcontextprotocol/server-sequential-thinking"
      ]
    }
  }
}
```
Run once from the terminal to verify:
```bash
npx -y @modelcontextprotocol/server-sequential-thinking --help
```

#### Docker
```json
{
  "mcpServers": {
    "sequential-thinking": {
      "command": "docker",
      "args": [
        "run",
        "--rm",
        "-i",
        "mcp/sequentialthinking"
      ]
    }
  }
}
```
To build the image locally:
```bash
docker build -t mcp/sequentialthinking -f src/sequentialthinking/Dockerfile .
```

### Client-specific notes
- **Claude Desktop**: add the NPX configuration to `claude_desktop_config.json`.
- **VS Code**: either open `MCP: Open User Configuration` and paste the JSON above, or add `.vscode/mcp.json` for workspace-level settings. Quick-install badges are available for both stable and Insiders releases.
- **Other clients**: any MCP-compatible tool that supports NPX or Docker commands can reuse the snippets above.

### Environment variables
- Set `DISABLE_THOUGHT_LOGGING=true` to suppress the logging output from the sequential-thinking server.

### License
Licensed under the MIT License. See the upstream repository for full terms.
