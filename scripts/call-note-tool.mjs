import { spawn } from 'node:child_process';
import { existsSync } from 'node:fs';
import { writeFile } from 'node:fs/promises';
import readline from 'node:readline';

const [, , toolName, markdownPath] = process.argv;

if (!toolName || !markdownPath) {
  console.error('usage: node call-note-tool.mjs <toolName> <markdown_path>');
  process.exit(1);
}

const statePath = process.env.NOTE_POST_MCP_STATE_PATH || '/tmp/note-state.json';
const screenshotDir = process.env.SCREENSHOT_DIR || '/tmp/screens';
const resultPath = process.env.NOTE_POST_RESULT_PATH || '';

if (!existsSync(markdownPath)) {
  console.error('記事ファイルが見つかりません:', markdownPath);
  process.exit(1);
}
if (!existsSync(statePath)) {
  console.error('認証stateが見つかりません:', statePath);
  process.exit(1);
}

const child = spawn('npx', ['--yes', '@gonuts555/note-post-mcp@latest', '--stdio'], {
  stdio: ['pipe', 'pipe', 'pipe'],
  env: {
    ...process.env,
    DEBUG: process.env.DEBUG || 'note-post-mcp:*'
  }
});

let initialized = false;
let finished = false;
let exitCode = 1;
let lastResult = null;

const request = {
  jsonrpc: '2.0',
  id: 'call1',
  method: 'tools/call',
  params: {
    name: toolName,
    arguments: {
      markdown_path: markdownPath,
      state_path: statePath,
      screenshot_dir: screenshotDir,
      timeout: 240000
    }
  }
};

const rl = readline.createInterface({ input: child.stdout });

function send(obj) {
  try {
    child.stdin.write(JSON.stringify(obj) + '\n');
  } catch (error) {
    console.error('stdin write failed:', error);
  }
}

rl.on('line', (line) => {
  if (!line.trim()) {
    return;
  }

  let msg;
  try {
    msg = JSON.parse(line);
  } catch {
    console.log(line);
    return;
  }

  if (msg.id === 'init') {
    if (msg.error) {
      initialized = true;
      console.error('initialize でエラー:', JSON.stringify(msg.error, null, 2));
      exitCode = 1;
      finished = true;
      try {
        child.stdin.end();
      } catch {}
      try {
        child.kill('SIGTERM');
      } catch {}
      return;
    }
    if (msg.result) {
      initialized = true;
      send(request);
      return;
    }
  }

  if (msg.id === 'call1' && (msg.result || msg.error)) {
    finished = true;
    if (msg.error) {
      console.error('MCP error:', JSON.stringify(msg.error, null, 2));
      exitCode = 1;
    } else {
      const result = msg.result || {};
      lastResult = result;
      console.log('=== RESULT ===');
      console.log(JSON.stringify(result, null, 2));
      const ok =
        result.success === true ||
        result.isError === false ||
        /published|success/i.test(JSON.stringify(result));
      exitCode = ok ? 0 : 1;
    }
    try {
      child.stdin.end();
    } catch {}
    return;
  }

  console.log(line);
});

child.stderr.on('data', (data) => {
  process.stderr.write(data);
});

const killTimer = setTimeout(() => {
  console.error('タイムアウト: 応答がありませんでした');
  try {
    child.kill('SIGKILL');
  } catch {}
}, 300000);

child.on('close', async (code) => {
  clearTimeout(killTimer);
  if (!initialized) {
    console.error('initialize 応答を受け取れませんでした');
  }
  if (!finished) {
    console.error('tools/call の結果を受け取れませんでした (code=' + code + ')');
  }
  if (exitCode === 0 && resultPath && lastResult) {
    try {
      await writeFile(resultPath, JSON.stringify(lastResult, null, 2), 'utf8');
      console.log(`Result written to ${resultPath}`);
    } catch (error) {
      console.error('結果ファイルの書き込みに失敗しました:', error);
    }
  }
  process.exit(exitCode);
});

send({
  jsonrpc: '2.0',
  id: 'init',
  method: 'initialize',
  params: {
    protocolVersion: '0.1.0',
    capabilities: {},
    clientInfo: {
      name: 'github-actions',
      version: '1.0.0'
    }
  }
});
