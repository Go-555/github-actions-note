import { promises as fs } from 'node:fs';
import { extname, join, resolve } from 'node:path';

const workspace = process.env.GITHUB_WORKSPACE || process.cwd();
const queueDir = resolve(workspace, process.env.QUEUE_DIR || 'articles-queue');

async function main() {
  let entries;
  try {
    entries = await fs.readdir(queueDir, { withFileTypes: true });
  } catch (error) {
    if (error.code === 'ENOENT') {
      console.log('Queue directory not found; nothing to post.');
      return;
    }
    throw error;
  }

  const candidates = entries
    .filter((dirent) => dirent.isFile() && extname(dirent.name).toLowerCase() === '.md')
    .sort((a, b) => a.name.localeCompare(b.name));

  if (candidates.length === 0) {
    console.log('No articles waiting in the queue.');
    if (process.env.GITHUB_OUTPUT) {
      await fs.appendFile(process.env.GITHUB_OUTPUT, 'path=\n');
    }
    return;
  }

  const next = candidates[0].name;
  const fullPath = join(queueDir, next);
  console.log(`Selected article: ${fullPath}`);

  if (process.env.GITHUB_OUTPUT) {
    await fs.appendFile(process.env.GITHUB_OUTPUT, `path=${fullPath}\n`);
  }
}

main().catch((error) => {
  console.error('Failed to select next article:', error);
  process.exitCode = 1;
});
