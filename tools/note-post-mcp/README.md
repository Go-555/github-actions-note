# Note Post MCP

[![GitHub](https://img.shields.io/badge/GitHub-Go--555%2Fnote--post--mcp-blue?logo=github)](https://github.com/Go-555/note-post-mcp)

The Universal MCP Server exposes tools for automated posting and draft saving to note.com. It reads Markdown files containing titles, body text, and tags, then publishes them to your note.com account using Playwright automation.

## Installation

### Prerequisites
- Node.js 18+
- A note.com account
- `note-state.json` authentication state file (obtained via separate login script)
- Set `NOTE_POST_MCP_STATE_PATH` in your environment (optional, defaults to `~/.note-state.json`)

### Get an authentication state file
- You need to obtain a `note-state.json` file containing your note.com authentication state.
- This can be generated using a Playwright login script that saves the browser's storage state after successful authentication.
- Store this file securely and reference it via `NOTE_POST_MCP_STATE_PATH` or pass it as a parameter.

### Install from GitHub
```bash
git clone https://github.com/Go-555/note-post-mcp.git
cd note-post-mcp
npm install
npm run build
```

### Or install from npm (if published)
```bash
npm install -g note-post-mcp
```

## Setup: Claude Code (CLI)

Use this one-liner (replace with your real values):

```bash
claude mcp add Note Post MCP -s user -e NOTE_POST_MCP_STATE_PATH="/path/to/note-state.json" -- npx @gonuts555/note-post-mcp@latest
```

To remove:

```bash
claude mcp remove Note Post MCP
```

## Setup: Cursor

Create `.cursor/mcp.json` in your client (do not commit it here):

```json
{
  "mcpServers": {
    "note-post-mcp": {
      "command": "npx",
      "args": ["@gonuts555/note-post-mcp@latest"],
      "env": {
        "NOTE_POST_MCP_STATE_PATH": "/path/to/note-state.json"
      },
      "autoStart": true
    }
  }
}
```

## Other Clients and Agents

<details>
<summary>VS Code</summary>

Install via URI or CLI:

```bash
code --add-mcp '{"name":"note-post-mcp","command":"npx","args":["@gonuts555/note-post-mcp@latest"],"env":{"NOTE_POST_MCP_STATE_PATH":"/path/to/note-state.json"}}'
```

</details>

<details>
<summary>Claude Desktop</summary>

Add to your Claude Desktop configuration file (`claude_desktop_config.json`):

```json
{
  "mcpServers": {
    "note-post-mcp": {
      "command": "npx",
      "args": ["@gonuts555/note-post-mcp@latest"],
      "env": {
        "NOTE_POST_MCP_STATE_PATH": "/path/to/note-state.json"
      }
    }
  }
}
```

</details>

<details>
<summary>LM Studio</summary>

- Command: `npx`
- Args: `["@gonuts555/note-post-mcp@latest"]`
- Env: `NOTE_POST_MCP_STATE_PATH=/path/to/note-state.json`

</details>

<details>
<summary>Goose</summary>

- Type: STDIO
- Command: `npx`
- Args: `@gonuts555/note-post-mcp@latest`
- Enabled: true

</details>

<details>
<summary>opencode</summary>

Example `~/.config/opencode/opencode.json`:

```json
{
  "$schema": "https://opencode.ai/config.json",
  "mcp": {
    "note-post-mcp": {
      "type": "local",
      "command": ["npx", "@gonuts555/note-post-mcp@latest"],
      "enabled": true,
      "env": {
        "NOTE_POST_MCP_STATE_PATH": "/path/to/note-state.json"
      }
    }
  }
}
```

</details>

<details>
<summary>Qodo Gen</summary>

Add a new MCP and paste the standard JSON config from above.

</details>

<details>
<summary>Windsurf</summary>

Add the following to your Windsurf MCP configuration:

```json
{
  "note-post-mcp": {
    "command": "npx",
    "args": ["@gonuts555/note-post-mcp@latest"],
    "env": {
      "NOTE_POST_MCP_STATE_PATH": "/path/to/note-state.json"
    }
  }
}
```

</details>

## Setup: Codex (TOML)

Add the following to your Codex TOML configuration.

Example (Serena):

```toml
[mcp_servers.serena]
command = "uvx"
args = ["--from", "git+https://github.com/oraios/serena", "serena", "start-mcp-server", "--context", "codex"]
```

This server (minimal):

```toml
[mcp_servers.note-post-mcp]
command = "npx"
args = ["@gonuts555/note-post-mcp@latest"]
# Optional environment variables:
# NOTE_POST_MCP_STATE_PATH = "/path/to/note-state.json"
# NOTE_POST_MCP_TIMEOUT = "180000"
# MCP_NAME = "note-post-mcp"
```

## Configuration (Env)

- `NOTE_POST_MCP_STATE_PATH`: Path to the note.com authentication state file (default: `~/.note-state.json`)
- `NOTE_POST_MCP_TIMEOUT`: Timeout in milliseconds for browser operations (default: `180000`)
- `MCP_NAME`: Server name override (default: `note-post-mcp`)

## Available Tools

### publish_note

Publishes an article to note.com from a Markdown file.

- **Inputs**:
  - `markdown_path` (string, required): Path to the Markdown file containing title, body, and tags
  - `thumbnail_path` (string, optional): Path to the thumbnail image file
  - `state_path` (string, optional): Path to the note.com authentication state file
  - `screenshot_dir` (string, optional): Directory to save screenshots
  - `timeout` (number, optional): Timeout in milliseconds

- **Outputs**: JSON object with:
  - `success` (boolean): Whether the operation succeeded
  - `url` (string): URL of the published article
  - `screenshot` (string): Path to the screenshot
  - `message` (string): Success message

### save_draft

Saves a draft article to note.com from a Markdown file.

- **Inputs**:
  - `markdown_path` (string, required): Path to the Markdown file containing title, body, and tags
  - `thumbnail_path` (string, optional): Path to the thumbnail image file
  - `state_path` (string, optional): Path to the note.com authentication state file
  - `screenshot_dir` (string, optional): Directory to save screenshots
  - `timeout` (number, optional): Timeout in milliseconds

- **Outputs**: JSON object with:
  - `success` (boolean): Whether the operation succeeded
  - `url` (string): URL of the draft editor page
  - `screenshot` (string): Path to the screenshot
  - `message` (string): Success message

## Markdown File Format

Your Markdown file should follow this format:

```markdown
---
title: Your Article Title
tags:
  - tag1
  - tag2
---

Your article body content goes here.

You can include URLs and they will be automatically expanded by note.com.
```

Alternatively, you can use array notation for tags:

```markdown
---
title: Your Article Title
tags: [tag1, tag2]
---

Your article body content goes here.
```

Or use a simple `#` heading for the title if no front matter is present:

```markdown
# Your Article Title

Your article body content goes here.
```

## Example invocation (MCP tool call)

```json
{
  "name": "publish_note",
  "arguments": {
    "markdown_path": "/path/to/article.md",
    "thumbnail_path": "/path/to/thumbnail.png",
    "state_path": "/path/to/note-state.json"
  }
}
```

For saving a draft:

```json
{
  "name": "save_draft",
  "arguments": {
    "markdown_path": "/path/to/draft.md"
  }
}
```

## Troubleshooting

- **Authentication errors**: Ensure your `note-state.json` file is valid and up-to-date. You may need to regenerate it if your session has expired.
- **Ensure Node 18+**: Run `node -v` to verify your Node.js version.
- **Build errors**: Run `npm install` and `npm run build` to ensure all dependencies are installed and TypeScript is compiled.
- **Local runs**: After building, test locally with `npx note-post-mcp` (it will wait for MCP messages on stdin).
- **Inspect publish artifacts**: Run `npm pack --dry-run` to see what files will be included in the published package.
- **Timeout issues**: If operations are timing out, increase `NOTE_POST_MCP_TIMEOUT` or pass a larger `timeout` parameter.
- **Playwright browser not installed**: Run `npx playwright install chromium` to install the required browser.

## References

- [MCP SDK Documentation](https://modelcontextprotocol.io/docs/sdks)
- [MCP Architecture](https://modelcontextprotocol.io/docs/learn/architecture)
- [MCP Server Concepts](https://modelcontextprotocol.io/docs/learn/server-concepts)
- [MCP Server Specification](https://modelcontextprotocol.io/specification/2025-06-18/server/index)
- [Playwright Documentation](https://playwright.dev/)

## Name Consistency & Troubleshooting

- Always use CANONICAL_ID (`note-post-mcp`) for identifiers and keys.
- Use CANONICAL_DISPLAY (`Note Post MCP`) only for UI labels.
- Do not mix different names across clients.

### Consistency Matrix

- npm package name → `note-post-mcp`
- Binary name → `note-post-mcp`
- MCP server name (SDK metadata) → `note-post-mcp`
- Env default MCP_NAME → `note-post-mcp`
- Client registry key → `note-post-mcp`
- UI label → `Note Post MCP`

### Conflict Cleanup

- Remove any old entries with different names and re-add with `note-post-mcp`.
- Ensure global `.mcp.json` or client registries only use `note-post-mcp` for keys.
- **Cursor**: Configure in the UI only. This project does not include `.cursor/mcp.json`.

### Example

- **Correct**: `"mcpServers": { "note-post-mcp": { "command": "npx", "args": ["@gonuts555/note-post-mcp@latest"] } }`
- **Incorrect**: Using different keys like `"NotePost"` or `"note_post"` (will conflict with `note-post-mcp`)

## License

MIT

