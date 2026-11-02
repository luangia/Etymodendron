// Copy the pipeline output (../data/out) into public/data so Vite serves and bundles it.
// Skips the copy when public/data is already newer than the source index.
import { cpSync, existsSync, mkdirSync, readFileSync, rmSync, statSync, writeFileSync } from "node:fs";
import { dirname, join } from "node:path";
import { fileURLToPath } from "node:url";

const here = dirname(fileURLToPath(import.meta.url));
const src = join(here, "..", "..", "data", "out");
const dest = join(here, "..", "public", "data");
const files = ["index.json", "languages.json"];

if (!existsSync(join(src, "index.json"))) {
  console.error(`No pipeline output at ${src}. Run: python3 -m etl.extract && python3 -m etl.run`);
  process.exit(1);
}
const fresh = existsSync(join(dest, "index.json")) &&
  statSync(join(dest, "index.json")).mtimeMs >= statSync(join(src, "index.json")).mtimeMs &&
  files.every((f) => existsSync(join(dest, f))) &&
  existsSync(join(src, "unrooted")) === existsSync(join(dest, "unrooted"));
if (fresh) {
  console.log("public/data is up to date");
} else {
  rmSync(dest, { recursive: true, force: true });
  mkdirSync(dest, { recursive: true });
  for (const f of files) cpSync(join(src, f), join(dest, f));
  cpSync(join(src, "roots"), join(dest, "roots"), { recursive: true });
  if (existsSync(join(src, "unrooted"))) cpSync(join(src, "unrooted"), join(dest, "unrooted"), { recursive: true });
  console.log(`copied ${src} -> public/data`);
}

// build.json: when the Wiktionary dump was published, for the About panel. Always rewritten (tiny).
const manifest = join(here, "..", "..", "data", "raw", "MANIFEST.json");
let dumpDate = null;
try {
  const m = JSON.parse(readFileSync(manifest, "utf8"));
  dumpDate = m.last_modified ? new Date(m.last_modified).toISOString().slice(0, 10) : null;
} catch {
  console.warn("no data/raw/MANIFEST.json: the About panel will not show the data date");
}
writeFileSync(join(dest, "build.json"), JSON.stringify({ dump_date: dumpDate, built: new Date().toISOString().slice(0, 10) }));
