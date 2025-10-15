import { promises as fs } from 'node:fs';
import { basename, join, resolve } from 'node:path';
import matter from 'gray-matter';

const [, , articlePathArg, noteUrlArg] = process.argv;

if (!articlePathArg) {
  console.error('usage: node mark-posted.mjs <article_path> [note_url]');
  process.exit(1);
}

const workspace = process.env.GITHUB_WORKSPACE || process.cwd();
const postedDir = resolve(workspace, process.env.POSTED_DIR || 'articles-posted');

async function main() {
  const articlePath = resolve(articlePathArg);
  const raw = await fs.readFile(articlePath, 'utf8');
  const parsed = matter(raw);

  parsed.data = {
    ...parsed.data,
    posted_at: new Date().toISOString(),
  };

  if (noteUrlArg) {
    parsed.data.note_url = noteUrlArg;
  }

  const output = matter.stringify(parsed.content.trim() ? `${parsed.content.trim()}\n` : '', parsed.data, { lineWidth: 120 });

  await fs.mkdir(postedDir, { recursive: true });
  const destination = join(postedDir, basename(articlePath));
  await fs.writeFile(destination, output, 'utf8');
  await fs.unlink(articlePath);

  console.log(`Moved posted article to ${destination}`);

  if (process.env.GITHUB_OUTPUT) {
    await fs.appendFile(process.env.GITHUB_OUTPUT, `path=${destination}\n`);
  }
}

main().catch((error) => {
  console.error('Failed to mark article as posted:', error);
  process.exitCode = 1;
});
