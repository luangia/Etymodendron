// Fail before uploading if dist/ breaks Cloudflare Pages limits (files per deployment, size per file).
import { readdirSync, statSync } from "node:fs";
import { join } from "node:path";

const MAX_FILES = 20000;
const MAX_FILE_BYTES = 25 * 1024 * 1024;
const dist = new URL("../dist/", import.meta.url).pathname;

let files = 0, total = 0, largest = { path: "", size: 0 };
const walk = (dir) => {
  for (const name of readdirSync(dir)) {
    const p = join(dir, name);
    const s = statSync(p);
    if (s.isDirectory()) walk(p);
    else {
      files++;
      total += s.size;
      if (s.size > largest.size) largest = { path: p.slice(dist.length), size: s.size };
    }
  }
};
walk(dist);
const mb = (b) => (b / 1024 / 1024).toFixed(1);
console.log(`dist: ${files.toLocaleString()} files, ${mb(total)} MB; largest ${largest.path} (${mb(largest.size)} MB)`);
const problems = [];
if (files > MAX_FILES) problems.push(`${files} files is over the ${MAX_FILES} per-deployment limit`);
if (largest.size > MAX_FILE_BYTES) problems.push(`${largest.path} is over the 25 MB per-file limit`);
if (problems.length) {
  console.error(problems.join("\n"));
  process.exit(1);
}
