import type { Branch, Edge, RootDoc, SearchIndex, TreeNode, UnrootedShard } from "./types";

const BASE = `${import.meta.env.BASE_URL}data/`;

async function getJSON<T>(path: string): Promise<T> {
  const res = await fetch(BASE + path);
  if (!res.ok) throw new Error(`${path}: HTTP ${res.status}`);
  return res.json() as Promise<T>;
}

export const loadIndex = () => getJSON<SearchIndex>("index.json");

export const loadUnrootedShard = (letter: string) => getJSON<UnrootedShard>(`unrooted/${letter}.json`);

/** Written by scripts/sync-data.mjs: the date of the Wiktionary dump the data was built from. */
export const loadBuildInfo = () => getJSON<{ dump_date: string | null; built: string }>("build.json");

let languages: Record<string, string> = {};
export async function loadLanguages() {
  try {
    languages = await getJSON<Record<string, string>>("languages.json");
  } catch {
    languages = {}; // names are a nicety; codes still work
  }
}
// etymology-only languages have no entries of their own, so the dump has no name for them
const ETYMOLOGY_ONLY: Record<string, string> = {
  xno: "Anglo-Norman", "la-lat": "Late Latin", "la-vul": "Vulgar Latin", "la-med": "Medieval Latin",
  "la-new": "New Latin", "la-ecc": "Ecclesiastical Latin", "la-cla": "Classical Latin", "la-ren": "Renaissance Latin",
  "grc-koi": "Koine Greek", "grc-att": "Attic Greek", "grc-ion": "Ionic Greek", "fro-nor": "Old Northern French",
  "fro-pic": "Picard Old French", "gem-pro": "Proto-Germanic", "en-GB": "British English", "en-US": "American English",
};
export const langName = (code: string) => languages[code] ?? ETYMOLOGY_ONLY[code] ?? code;

const rootCache = new Map<string, Promise<RootDoc>>();
export function loadRoot(slug: string): Promise<RootDoc> {
  let p = rootCache.get(slug);
  if (!p) {
    p = getJSON<RootDoc>(`roots/${encodeURIComponent(slug)}.json`);
    p.catch(() => rootCache.delete(slug));
    rootCache.set(slug, p);
  }
  return p;
}

// ------------------------------------------------------------ branches

export const BRANCHES: Branch[] = ["germanic", "romance", "greek", "other", "unknown"];
export const BRANCH_LABEL: Record<Branch, string> = {
  germanic: "Germanic",
  romance: "Latin & Romance",
  greek: "Greek",
  other: "Other",
  unknown: "Route not stated",
};

const GERMANIC = new Set(("en enm ang sco gem-pro gmw-pro gmq-pro non goh gmh de nl dum odt osx gml nds got fy ofs frr stq " +
  "da sv is no nb nn fo yi lb frk gsw bar af li vls zea gmq-oda gmq-osw gmw-ecg wym ksh pdc pfl swg vmf").split(" "));
const ROMANCE = new Set(("itc-pro la osc xum xfa fro frm fr xno pro oc ca es osp pt gl roa-opt roa-oit it ro rup ruo sc rm " +
  "fur lld lad vec nap scn lmo pms lij wa nrf frp an ast mwl ext co dlm roa-opn roa-ocat lzd egl rgn").split(" "));
const GREEK = new Set("grk-pro grc gkm el gmy pnt tsd cpg".split(" "));
const PREFIX: [string, Branch][] = [
  ["gem-", "germanic"], ["gmw-", "germanic"], ["gmq-", "germanic"], ["gme-", "germanic"],
  ["enm-", "germanic"], ["ang-", "germanic"], ["de-", "germanic"], ["nl-", "germanic"],
  ["itc-", "romance"], ["la-", "romance"], ["roa-", "romance"], ["fro-", "romance"], ["fr-", "romance"],
  ["it-", "romance"], ["es-", "romance"], ["pt-", "romance"],
  ["grk-", "greek"], ["grc-", "greek"], ["el-", "greek"],
];

/** Branch of a language, or null for Proto-Indo-European itself. */
export function family(code: string): Branch | null {
  if (code === "ine-pro") return null;
  if (GERMANIC.has(code)) return "germanic";
  if (ROMANCE.has(code)) return "romance";
  if (GREEK.has(code)) return "greek";
  for (const [p, b] of PREFIX) if (code.startsWith(p)) return b;
  return "other";
}

// ------------------------------------------------------------ view model

export interface VNode {
  /** path of child indexes in the JSON tree, e.g. "0.3.1"; stable across filtering */
  id: string;
  lang: string;
  term: string;
  edge?: Edge;
  data: TreeNode;
  parent: VNode | null;
  children: VNode[];
  /** English words formed from this English word (fatherhood, godfather...): listed, not drawn */
  derivatives: VNode[];
  /** the branch the path entered when it left PIE */
  branch: Branch | null;
  english: boolean;
  words: number;
}

function make(n: TreeNode, parent: VNode | null, id: string, branch: Branch | null): VNode {
  return { id, lang: n.lang, term: n.term, edge: n.edge, data: n, parent, children: [], derivatives: [],
    branch, english: n.lang === "en", words: 0 };
}

/**
 * Build the drawable tree. English words hang on the outer ring; English words derived from
 * them become `derivatives` so the ring stays readable. Affix-only paths are dropped unless asked.
 */
export function buildView(tree: TreeNode, includeAffix: boolean): VNode {
  const keepWord = (n: TreeNode) => includeAffix || !n.via_affix;

  function derivative(n: TreeNode, parent: VNode, id: string): VNode | null {
    const v = make(n, parent, id, parent.branch);
    (n.children ?? []).forEach((c, i) => {
      if (c.lang !== "en") return; // a later borrowing back into another language: not shown here
      const d = derivative(c, v, `${id}.${i}`);
      if (d) v.derivatives.push(d);
    });
    return keepWord(n) || v.derivatives.length ? v : null;
  }

  function build(n: TreeNode, parent: VNode | null, id: string, above: Branch | null): VNode | null {
    // an English word hanging straight off a PIE node has no stated route, so no branch
    const branch = above ?? (n.lang === "en" && parent ? "unknown" : family(n.lang));
    const v = make(n, parent, id, parent ? branch : null);
    (n.children ?? []).forEach((c, i) => {
      const cid = `${id}.${i}`;
      if (v.english && c.lang === "en") {
        const d = derivative(c, v, cid);
        if (d) v.derivatives.push(d);
      } else {
        const cv = build(c, v, cid, parent ? branch : null);
        if (cv) v.children.push(cv);
      }
    });
    if (!parent) return v;
    if (v.english) return keepWord(n) || v.children.length || v.derivatives.length ? v : null;
    return v.children.length ? v : null;
  }

  const root = build(tree, null, "0", null)!;
  const count = (v: VNode): number =>
    (v.words = (v.english ? 1 : 0) + v.children.reduce((s, c) => s + count(c), 0) +
      v.derivatives.reduce((s, d) => s + countDeriv(d), 0));
  const countDeriv = (d: VNode): number => 1 + d.derivatives.reduce((s, x) => s + countDeriv(x), 0);
  count(root);
  return root;
}

export function findById(root: VNode, id: string): VNode | null {
  if (root.id === id) return root;
  for (const c of [...root.children, ...root.derivatives]) {
    if (id === c.id || id.startsWith(c.id + ".")) return findById(c, id);
  }
  return null;
}

/** Find an English word (and etymology number, 0 = the only one) anywhere in the view. */
export function findWord(root: VNode, word: string, etym: number): VNode | null {
  let fallback: VNode | null = null;
  const stack = [root];
  while (stack.length) {
    const v = stack.pop()!;
    if (v.english && v.term === word) {
      const e = v.data.etym ?? 0;
      if (e === etym || etym === 0) return v;
      fallback ??= v;
    }
    stack.push(...v.children, ...v.derivatives);
  }
  return fallback;
}

/** The node and its ancestors up to the PIE root, nearest first. */
export function ancestry(v: VNode): VNode[] {
  const out: VNode[] = [];
  for (let n: VNode | null = v; n; n = n.parent) out.push(n);
  return out;
}

export function englishLeaves(v: VNode): VNode[] {
  const out: VNode[] = [];
  const stack = [v];
  while (stack.length) {
    const n = stack.pop()!;
    if (n.english) out.push(n);
    else stack.push(...n.children);
  }
  return out;
}

/**
 * "Surprising" cognates: English words from the same ancestor that reached English through
 * different branches (father / paternal / patriarch). Picks a few readable examples per branch.
 */
export function crossBranch(v: VNode, perBranch = 4): Map<Branch, VNode[]> {
  const groups = new Map<Branch, VNode[]>();
  for (const w of englishLeaves(v)) {
    if (!w.branch || w.branch === "unknown") continue;
    const g = groups.get(w.branch) ?? [];
    g.push(w);
    groups.set(w.branch, g);
  }
  // no frequency data: words that many other English words are built on tend to be the familiar ones
  const score = (w: VNode) =>
    (w.data.path_uncertain ? 100 : 0) + (/^[a-z]+$/.test(w.term) ? 0 : 50) + (w.data.via_affix ? 30 : 0) +
    w.term.length - 2 * Math.min(w.derivatives.length, 15);
  const out = new Map<Branch, VNode[]>();
  for (const b of BRANCHES) {
    const g = groups.get(b);
    if (!g?.length) continue;
    const seen = new Set<string>();
    const picked = [...g]
      .sort((a, c) => score(a) - score(c) || a.term.localeCompare(c.term))
      .filter((w) => !seen.has(w.term) && seen.add(w.term))
      .slice(0, perBranch);
    out.set(b, picked);
  }
  return out.size >= 2 ? out : new Map();
}

export function branchCounts(v: VNode): Map<Branch, number> {
  const m = new Map<Branch, number>();
  for (const w of englishLeaves(v)) if (w.branch) m.set(w.branch, (m.get(w.branch) ?? 0) + w.words);
  return m;
}

// ------------------------------------------------------------ links & labels

// Wiktionary entry names drop some diacritics (Latin and Old English macrons, Old English dots)
const STRIP: Record<string, RegExp> = {
  la: /[̄̆]/g, ang: /[̄̆̇]/g, enm: /[̄̆]/g, osx: /[̄]/g,
  goh: /[̄]/g, grc: /[̄̆]/g, non: /[̄]/g,
};

export function wiktionaryUrl(lang: string, term: string): string {
  const name = langName(lang);
  const bare = term.replace(/^\*/, "");
  if (term.startsWith("*") || lang.endsWith("-pro")) {
    return `https://en.wiktionary.org/wiki/Reconstruction:${encodeURIComponent(name.replace(/ /g, "_"))}/${encodeURIComponent(bare)}`;
  }
  const re = STRIP[lang];
  const title = re ? bare.normalize("NFD").replace(re, "").normalize("NFC") : bare;
  return `https://en.wiktionary.org/wiki/${encodeURIComponent(title.replace(/ /g, "_"))}#${encodeURIComponent(name.replace(/ /g, "_"))}`;
}

export const EDGE_LABEL: Record<string, string> = {
  inherited: "inherited from",
  borrowed: "borrowed from",
  derived: "derived from",
  root: "from the root",
  component: "formed from",
};
