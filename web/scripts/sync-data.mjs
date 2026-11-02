// Copy the pipeline output (../data/out) into public/data so Vite serves and bundles it.
// Skips the copy when public/data is already newer than the source index.
import { cpSync, existsSync, mkdirSync, rmSync, statSync } from "node:fs";
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
  files.every((f) => existsSync(join(dest, f)));
if (fresh) {
  console.log("public/data is up to date");
} else {
  rmSync(dest, { recursive: true, force: true });
  mkdirSync(dest, { recursive: true });
  for (const f of files) cpSync(join(src, f), join(dest, f));
  cpSync(join(src, "roots"), join(dest, "roots"), { recursive: true });
  console.log(`copied ${src} -> public/data`);
}
