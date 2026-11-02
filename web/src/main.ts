import "./style.css";
import {
  ancestry, BRANCH_LABEL, BRANCHES, branchCounts, buildView, findById, findWord, langName, loadBuildInfo, loadIndex,
  loadLanguages, loadRoot, type VNode,
} from "./data";
import { renderMissPanel, renderRootPanel, renderUnrootedPanel, renderWordPanel, type PanelContext } from "./panel";
import { attachSearch, WordSearch } from "./search";
import { BottomSheet } from "./sheet";
import { RadialTree } from "./tree";
import type { Branch, IndexHit, RootDoc, RootMeta, SearchIndex, UnrootedInfo } from "./types";

const $ = <T extends HTMLElement>(id: string) => document.getElementById(id) as T;
const els = {
  svg: document.getElementById("tree") as unknown as SVGSVGElement,
  tooltip: $("tooltip"),
  status: $("status"),
  crumbs: $("crumbs"),
  legend: $("legend"),
  panel: $("panel"),
  body: $("panel-body"),
  handle: $("sheet-handle"),
  search: $<HTMLInputElement>("search"),
  list: $<HTMLUListElement>("search-list"),
  affix: $<HTMLInputElement>("affix-toggle"),
};

const DEFAULT_ROOT = "*ph₂tḗr";

interface State {
  index: SearchIndex;
  byTerm: Map<string, RootMeta>;
  bySlug: Map<string, RootMeta>;
  meta: RootMeta | null;
  doc: RootDoc | null;
  root: VNode | null;
  view: VNode | null;
  selected: VNode | null;
  includeAffix: boolean;
  pinnedBranch: Branch | null;
  /** a searched word that has no tree to show: the panel explains why */
  note: { kind: "unrooted"; word: string; info: UnrootedInfo } | { kind: "miss"; query: string } | null;
}
let S: State;
let loadToken = 0;

const tree = new RadialTree(els.svg, els.tooltip, {
  onWord: (v) => selectWord(v),
  onRecenter: (v) => recenter(v),
  onCenter: () => {
    if (!S.selected && !S.note) return;
    S.note = null;
    selectWord(null);
  },
});

// ------------------------------------------------------------------ status

function status(msg: string, isError = false) {
  els.status.textContent = msg;
  els.status.classList.toggle("error", isError);
  els.status.hidden = !msg;
}

// ------------------------------------------------------------------ navigation

async function openRoot(slug: string, word?: string, etym = 0, centerId?: string) {
  const meta = S.bySlug.get(slug);
  if (!meta) return status(`Unknown root "${slug}"`, true);
  const token = ++loadToken;
  status(`Loading ${meta.term}…`);
  let doc: RootDoc;
  try {
    doc = await loadRoot(slug);
  } catch (e) {
    return status(`Could not load ${meta.term}: ${(e as Error).message}`, true);
  }
  if (token !== loadToken) return; // a newer navigation won
  status("");
  S.note = null;

  // a word that reaches this root only through an affix needs affix paths shown
  if (word && !S.includeAffix) {
    const hit = S.index.words[word]?.find((h) => S.index.roots[h[0]].slug === slug && (h[1] === etym || etym === 0));
    if (hit && hit[2] & 2) setAffix(true, false);
  }
  S.meta = meta;
  S.doc = doc;
  S.root = buildView(doc.tree, S.includeAffix);
  S.view = (centerId && findById(S.root, centerId)) || S.root;
  S.selected = null;
  draw();
  if (word) {
    const v = findWord(S.root, word, etym);
    if (v) selectWord(v, true);
    else status(`“${word}” is not drawn under ${meta.term} with the current filter.`);
  }
}

function draw() {
  if (!S.view) return;
  paintCrumbs();
  paintLegend();
  syncInsets(); // the legend's height decides where the tree fits
  tree.render(S.view);
  showPanel();
  writeHash();
}

function recenter(v: VNode) {
  if (!S.root) return;
  S.note = null;
  S.view = v;
  S.selected = null;
  draw();
}

function selectWord(v: VNode | null, focus = false) {
  if (!S.root || !S.view) return;
  if (v) S.note = null;
  if (v && !ancestry(v).includes(S.view)) {
    // the word is outside the centred subtree: go back to the root view first
    S.view = S.root;
    S.selected = v;
    paintCrumbs();
    paintLegend();
    syncInsets();
    tree.render(S.view);
  }
  S.selected = v;
  tree.select(v);
  if (v && focus) tree.focus(v);
  showPanel();
  writeHash();
  if (v) expandSheet(true);
}

function showPanel() {
  if (!S.doc || !S.meta || !S.root || !S.view) return;
  const ctx: PanelContext = {
    doc: S.doc,
    meta: S.meta,
    root: S.root,
    view: S.view,
    hitsFor: (w) => S.index.words[w] ?? [],
    rootMeta: (i) => S.index.roots[i],
    rootByTerm: (t) => S.byTerm.get(t),
    selectWord: (v) => selectWord(v, true),
    recenter,
    openRoot: (slug, word, etym) => void openRoot(slug, word, etym),
    spotlight: (words) => {
      tree.spotlight(words);
      if (words) expandSheet(false);
    },
  };
  if (S.note?.kind === "unrooted") renderUnrootedPanel(els.body, S.note.word, S.note.info);
  else if (S.note?.kind === "miss") renderMissPanel(els.body, S.note.query);
  else if (S.selected) renderWordPanel(els.body, ctx, S.selected);
  else renderRootPanel(els.body, ctx);
  els.body.scrollTop = 0;
}

/** Show a searched word that has no tree (no PIE root, or not in the data at all). */
function showNote(note: NonNullable<State["note"]>) {
  S.note = note;
  S.selected = null;
  tree.select(null);
  showPanel();
  writeHash();
  expandSheet(true);
}

// ------------------------------------------------------------------ chrome

function paintCrumbs() {
  els.crumbs.replaceChildren();
  if (!S.view) return;
  const path = ancestry(S.view).reverse();
  path.forEach((n, i) => {
    if (i > 0) els.crumbs.append(Object.assign(document.createElement("span"), { className: "sep", textContent: "›" }));
    const b = document.createElement("button");
    b.type = "button";
    b.className = "crumb" + (n === S.view ? " current" : "");
    const lang = document.createElement("span");
    lang.className = "crumb-lang";
    lang.textContent = langName(n.lang);
    b.append(lang, document.createTextNode(` ${n.term}`));
    if (n === S.view) b.setAttribute("aria-current", "true");
    else b.addEventListener("click", () => recenter(n));
    els.crumbs.append(b);
  });
  // long chains: keep the current end visible
  els.crumbs.scrollLeft = els.crumbs.scrollWidth;
}

function paintLegend() {
  els.legend.replaceChildren();
  if (!S.view) return;
  const counts = branchCounts(S.view);
  for (const b of BRANCHES) {
    const n = counts.get(b);
    if (!n) continue;
    const btn = document.createElement("button");
    btn.type = "button";
    btn.className = `legend-item b-${b}`;
    btn.setAttribute("aria-pressed", String(S.pinnedBranch === b));
    const key = document.createElement("span");
    key.className = "key";
    btn.append(key, document.createTextNode(`${BRANCH_LABEL[b]} `));
    const c = document.createElement("span");
    c.className = "count";
    c.textContent = n.toLocaleString();
    btn.append(c);
    btn.addEventListener("pointerenter", () => tree.focusBranch(b));
    btn.addEventListener("pointerleave", () => tree.focusBranch(S.pinnedBranch));
    btn.addEventListener("click", () => {
      S.pinnedBranch = S.pinnedBranch === b ? null : b;
      tree.focusBranch(S.pinnedBranch);
      paintLegend();
    });
    els.legend.append(btn);
  }
  tree.focusBranch(S.pinnedBranch);
}

function setAffix(on: boolean, redraw = true) {
  S.includeAffix = on;
  els.affix.checked = on;
  if (!redraw || !S.doc) return;
  const viewId = S.view?.id, selId = S.selected?.id;
  S.root = buildView(S.doc.tree, on);
  S.view = (viewId && findById(S.root, viewId)) || S.root;
  const sel = selId ? findById(S.root, selId) : null;
  S.selected = null;
  draw();
  if (sel) selectWord(sel);
}

// ------------------------------------------------------------------ URL state: #r=<slug>&c=<node id>&w=<word>&e=<etym>&a=1

function writeHash() {
  if (!S.meta) return;
  const p = new URLSearchParams({ r: S.meta.slug });
  if (S.view && S.view !== S.root) p.set("c", S.view.id);
  if (S.selected) {
    p.set("w", S.selected.term);
    if (S.selected.data.etym) p.set("e", String(S.selected.data.etym));
  }
  if (S.includeAffix) p.set("a", "1");
  if (S.note?.kind === "unrooted") p.set("u", S.note.word);
  const next = `#${p.toString()}`;
  if (location.hash !== next) history.replaceState(null, "", next);
}

function readHash() {
  const p = new URLSearchParams(location.hash.slice(1));
  return { r: p.get("r"), c: p.get("c") ?? undefined, w: p.get("w") ?? undefined, e: Number(p.get("e") ?? 0),
    a: p.get("a") === "1", u: p.get("u") ?? undefined };
}

// ------------------------------------------------------------------ theme & layout

function setupTheme() {
  const btn = $("theme-toggle");
  const current = () => document.documentElement.dataset.theme ??
    (matchMedia("(prefers-color-scheme: dark)").matches ? "dark" : "light");
  btn.addEventListener("click", () => {
    const next = current() === "dark" ? "light" : "dark";
    document.documentElement.dataset.theme = next;
    try {
      localStorage.setItem("etymodendron-theme", next);
    } catch { /* private mode: theme just won't persist */ }
  });
}

const mobile = matchMedia("(max-width: 760px)");
let sheetTimer = 0;
// phones: the details panel is a bottom sheet; once it settles, re-fit the tree above it
const sheet = new BottomSheet(els.panel, els.body, els.handle, ".sheet-handle, .phead", () => mobile.matches, (state) => {
  clearTimeout(sheetTimer);
  sheetTimer = window.setTimeout(() => {
    syncInsets();
    if (state === "full") return; // the tree is covered anyway
    if (S.selected) tree.focus(S.selected);
    else tree.fit();
  }, 320);
});
function expandSheet(open: boolean) {
  if (!mobile.matches) return;
  if (!open) sheet.set("peek");
  else if (sheet.state === "peek") sheet.set("half");
}
function syncInsets() {
  // the breadcrumbs and legend float over the top of the stage, and on phones the details
  // sheet covers the bottom: fit the tree into the space between
  const stage = els.svg.getBoundingClientRect();
  const controls = document.querySelector(".controls")!.getBoundingClientRect();
  const top = Math.max(0, controls.bottom - stage.top + 4);
  tree.setInsets(top, 0, mobile.matches ? Math.max(0, stage.bottom - els.panel.getBoundingClientRect().top) : 0);
}

function setupLayout() {
  mobile.addEventListener("change", () => {
    syncInsets();
    tree.fit();
  });
  new ResizeObserver(syncInsets).observe(els.panel);
  new ResizeObserver(syncInsets).observe(document.querySelector(".controls")!);
  $("zoom-in").addEventListener("click", () => tree.zoomBy(1.6));
  $("zoom-out").addEventListener("click", () => tree.zoomBy(1 / 1.6));
  $("zoom-fit").addEventListener("click", () => tree.fit());
  els.affix.addEventListener("change", () => setAffix(els.affix.checked));
  document.querySelector(".brand")!.addEventListener("click", (ev) => {
    ev.preventDefault();
    const m = S.byTerm.get(DEFAULT_ROOT) ?? S.index.roots[0];
    void openRoot(m.slug);
  });
}

// ------------------------------------------------------------------ about / FAQ

function setupAbout() {
  const dialog = $<HTMLDialogElement>("about");
  $("about-btn").addEventListener("click", () => dialog.showModal());
  $("about-close").addEventListener("click", () => dialog.close());
  // a click on the backdrop lands on the dialog element itself
  dialog.addEventListener("click", (ev) => {
    if (ev.target === dialog) dialog.close();
  });

  loadBuildInfo()
    .then(({ dump_date }) => {
      if (!dump_date) return;
      const when = new Date(`${dump_date}T00:00:00Z`).toLocaleDateString(undefined,
        { year: "numeric", month: "long", day: "numeric", timeZone: "UTC" });
      $("about-date").textContent =
        `It reflects the Wiktionary data published on ${when}. Edits made on Wiktionary since then aren’t included yet.`;
    })
    .catch(() => { /* keep the generic sentence */ });
}

// ------------------------------------------------------------------ boot

async function main() {
  setupTheme();
  setupLayout();
  setupAbout();
  syncInsets();
  status("Loading word index…");
  let index: SearchIndex;
  try {
    [index] = await Promise.all([loadIndex(), loadLanguages()]);
  } catch (e) {
    return status(`Could not load data: ${(e as Error).message}. Run "npm run sync-data".`, true);
  }
  S = {
    index,
    byTerm: new Map(index.roots.map((r) => [r.term, r])),
    bySlug: new Map(index.roots.map((r) => [r.slug, r])),
    meta: null, doc: null, root: null, view: null, selected: null,
    includeAffix: false, pinnedBranch: null, note: null,
  };
  const search = new WordSearch(index);
  attachSearch(els.search, els.list, search, (h: IndexHit) => index.roots[h[0]].term, (s) => {
    if (s.unrooted) return showNote({ kind: "unrooted", word: s.word, info: s.unrooted });
    const best = s.hits[0];
    void openRoot(index.roots[best[0]].slug, s.word, best[1]);
  }, (query) => showNote({ kind: "miss", query }));
  els.search.disabled = false;
  els.search.placeholder = "Search an English word…";

  const route = readHash();
  if (route.a) setAffix(true, false);
  const start = (route.r && S.bySlug.get(route.r)) || S.byTerm.get(DEFAULT_ROOT) || index.roots[0];
  await openRoot(start.slug, route.w, route.e, route.c);
  if (route.u && !route.w) {
    const info = await search.lookupUnrooted(route.u);
    if (info) showNote({ kind: "unrooted", word: route.u, info });
  }
  window.addEventListener("hashchange", () => {
    const r = readHash();
    if (r.r && r.r !== S.meta?.slug) void openRoot(r.r, r.w, r.e, r.c);
  });
}

void main();
