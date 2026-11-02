import {
  ancestry, BRANCH_LABEL, BRANCHES, branchCounts, crossBranch, EDGE_LABEL, langName, wiktionaryUrl, type VNode,
} from "./data";
import { orderHits } from "./search";
import type { Branch, Edge, IndexHit, RootDoc, RootMeta } from "./types";

export interface PanelContext {
  doc: RootDoc;
  meta: RootMeta;
  root: VNode;        // full tree of the root file
  view: VNode;        // currently centred node
  hitsFor(word: string): IndexHit[];
  rootMeta(i: number): RootMeta;
  rootByTerm(term: string): RootMeta | undefined;
  selectWord(v: VNode): void;
  recenter(v: VNode): void;
  openRoot(slug: string, word?: string, etym?: number): void;
  spotlight(words: VNode[] | null): void;
}

// --------------------------------------------------------------- tiny DOM helpers

type Child = Node | string | null | undefined | false;
function h<K extends keyof HTMLElementTagNameMap>(tag: K, cls?: string, ...kids: Child[]): HTMLElementTagNameMap[K] {
  const el = document.createElement(tag);
  if (cls) el.className = cls;
  for (const k of kids) if (k) el.append(k);
  return el;
}

function extLink(href: string, text: string, cls = "ext") {
  const a = h("a", cls, text);
  a.href = href;
  a.target = "_blank";
  a.rel = "noopener noreferrer";
  return a;
}

function button(text: string, cls: string, onClick: () => void, title?: string) {
  const b = h("button", cls, text);
  b.type = "button";
  if (title) b.title = title;
  b.addEventListener("click", onClick);
  return b;
}

function branchDot(b: Branch | null) {
  return h("span", `bdot b-${b ?? "pie"}`);
}

function wordChip(v: VNode, onClick: () => void) {
  const c = button("", `chip b-${v.branch ?? "pie"}`, onClick, `${v.term}${v.data.gloss ? ` — ${v.data.gloss}` : ""}`);
  c.append(branchDot(v.branch), v.term);
  return c;
}

function section(title: string, ...kids: Child[]) {
  return h("section", "psec", h("h3", "", title), ...kids);
}

function edgeNotes(e: Edge | undefined): HTMLElement | null {
  if (!e) return null;
  const notes: Child[] = [];
  if (e.uncertain) notes.push(h("span", "flag warn", "uncertain"));
  if (e.via === "sequence") notes.push(h("span", "flag", e.confirmed ? "from prose order, confirmed" : "from prose order"));
  if (e.via === "root") {
    notes.push(h("span", "flag", "root named in the English entry"));
  }
  if (e.link === "unresolved") notes.push(h("span", "flag", "no page under this form"));
  const wrap = h("div", "edge-notes", ...notes);
  if (e.uncertain && e.evidence) {
    const d = h("details", "evidence", h("summary", "", "why"), h("q", "", e.evidence));
    wrap.append(d);
  }
  return notes.length ? wrap : null;
}

// --------------------------------------------------------------- root / centred node

export function renderRootPanel(body: HTMLElement, ctx: PanelContext) {
  const { doc, view, root } = ctx;
  const atRoot = view === root;
  body.replaceChildren();

  const title = h("header", "phead");
  title.append(
    h("div", "eyebrow", atRoot ? `Proto-Indo-European ${doc.root.kind === "root" ? "root" : "word"}` : langName(view.lang)),
    h("h2", "pterm", view.term),
  );
  if (atRoot && doc.root.gloss) title.append(h("p", "gloss", doc.root.gloss));
  if (!atRoot && view.edge && view.parent) {
    title.append(h("p", "gloss", `${EDGE_LABEL[view.edge.type]} ${langName(view.parent.lang)} ${view.parent.term}`));
  }
  title.append(extLink(wiktionaryUrl(view.lang, view.term), "Wiktionary ↗"));
  body.append(title);

  // counts per branch
  const counts = branchCounts(view);
  const total = [...counts.values()].reduce((a, b) => a + b, 0);
  const bar = h("div", "bbar");
  bar.setAttribute("role", "img");
  bar.setAttribute("aria-label", BRANCHES.filter((b) => counts.get(b)).map((b) => `${BRANCH_LABEL[b]} ${counts.get(b)}`).join(", "));
  const legend = h("ul", "blegend");
  for (const b of BRANCHES) {
    const n = counts.get(b);
    if (!n) continue;
    const seg = h("span", `seg b-${b}`);
    seg.style.flexGrow = String(n);
    bar.append(seg);
    legend.append(h("li", "", branchDot(b), `${BRANCH_LABEL[b]} `, h("strong", "", n.toLocaleString())));
  }
  body.append(section(`${view.words.toLocaleString()} English word${view.words === 1 ? "" : "s"}`,
    total ? bar : null, legend,
    atRoot && doc.stats.via_affix ? h("p", "muted small",
      `${doc.stats.via_affix.toLocaleString()} more reach this root only through an affix (re-, -tion…). Use the checkbox above the tree to show them.`) : null));

  // surprising cognates
  const groups = crossBranch(view);
  if (groups.size) {
    const all = [...groups.values()].flat();
    let lit = false;
    const toggle = button("Highlight on tree", "btn small", () => {
      lit = !lit;
      ctx.spotlight(lit ? all : null);
      toggle.textContent = lit ? "Clear highlight" : "Highlight on tree";
      toggle.setAttribute("aria-pressed", String(lit));
    });
    toggle.setAttribute("aria-pressed", "false");
    const rows = h("div", "cog-rows");
    for (const [b, words] of groups) {
      rows.append(h("div", "cog-row", h("span", "cog-branch", branchDot(b), BRANCH_LABEL[b]),
        h("div", "chips", ...words.map((w) => wordChip(w, () => ctx.selectWord(w))))));
    }
    body.append(section("Surprising cognates",
      h("p", "muted small", "Same ancestor, different routes into English."), rows, toggle));
  }

  if (atRoot) {
    if (doc.parents.length) {
      const list = h("ul", "plain");
      for (const p of doc.parents) {
        const meta = ctx.rootByTerm(p.term);
        const label = `${p.term}${p.kind === "suffix" ? " (suffix)" : ""}`;
        const item = meta ? button(label, "linklike", () => ctx.openRoot(meta.slug)) : h("span", "", label);
        list.append(h("li", "", item, p.uncertain ? h("span", "flag warn", "uncertain") : null));
      }
      body.append(section("Derived from", list));
    }
    if (doc.root.homograph_ids) {
      body.append(h("p", "note", `Wiktionary lists several roots with this form (${doc.root.homograph_ids.join(", ")}). ` +
        "Words are grouped by form, so some may belong to a different homograph."));
    }
  } else {
    body.append(section("Path from the root", chainList(ancestry(view).reverse(), ctx)));
  }
  body.append(sourceNote());
}

// --------------------------------------------------------------- word

export function renderWordPanel(body: HTMLElement, ctx: PanelContext, v: VNode) {
  body.replaceChildren();
  const chain = ancestry(v);
  const parent = v.parent;

  const head = h("header", "phead");
  const pos = v.data.pos?.length ? v.data.pos.join(", ") : "";
  head.append(
    h("div", "eyebrow", `English${v.data.etym ? ` · etymology ${v.data.etym}` : ""}${pos ? ` · ${pos}` : ""}`),
    h("h2", "pterm", v.term),
  );
  if (v.data.gloss) head.append(h("p", "gloss", v.data.gloss));
  head.append(extLink(wiktionaryUrl("en", v.term), "Wiktionary ↗"));
  body.append(head);

  // how it entered English
  if (v.edge && parent) {
    const how = h("div", "arrival");
    const kind = v.edge.type === "inherited" ? "Inherited" : v.edge.type === "borrowed" ? "Borrowed" :
      v.edge.type === "component" ? "Formed" : v.edge.type === "root" ? "Traced" : "Derived";
    const prep = v.edge.type === "component" ? "from" : v.edge.type === "root" ? "to" : "from";
    how.append(h("span", `type-badge t-${v.edge.type}`, kind), ` ${prep} ${langName(parent.lang)} `, h("em", "", parent.term));
    if (v.branch === "unknown") {
      how.append(h("div", "muted small", "Wiktionary links this word straight to the root; the route through other languages is not stated."));
    } else if (v.branch) {
      how.append(h("div", "muted small", branchDot(v.branch), ` came through the ${BRANCH_LABEL[v.branch]} branch`));
    }
    if (v.data.path_uncertain) how.append(h("div", "flag warn block", "At least one step on this path is uncertain."));
    body.append(how);
  }

  body.append(section("Ancestry", chainList([...chain].reverse(), ctx)));

  // other branches of the same root
  const groups = crossBranch(ctx.root, 5);
  if (v.branch && groups.size) {
    const rows = h("div", "cog-rows");
    for (const [b, words] of groups) {
      if (b === v.branch) continue;
      rows.append(h("div", "cog-row", h("span", "cog-branch", branchDot(b), BRANCH_LABEL[b]),
        h("div", "chips", ...words.map((w) => wordChip(w, () => ctx.selectWord(w))))));
    }
    if (rows.childElementCount) {
      const all = [v, ...[...groups.entries()].filter(([b]) => b !== v.branch).flatMap(([, w]) => w)];
      body.append(section("Cognates by another route", rows,
        button("Highlight on tree", "btn small", () => ctx.spotlight(all))));
    }
  }

  if (v.derivatives.length) {
    const max = 40;
    const chips = h("div", "chips", ...v.derivatives.slice(0, max).map((d) => wordChip(d, () => ctx.selectWord(d))));
    if (v.derivatives.length > max) chips.append(h("span", "muted small", `+${v.derivatives.length - max} more`));
    body.append(section(`Formed from ${v.term} (${v.derivatives.length})`, chips));
  }

  // other roots this word is traced to
  const etym = v.data.etym ?? 0;
  const hits = orderHits(ctx.hitsFor(v.term)).filter((x) => x[1] === etym || etym === 0 || x[1] === 0);
  const others = hits.filter((x) => ctx.rootMeta(x[0]).slug !== ctx.meta.slug);
  if (others.length) {
    const list = h("ul", "plain");
    for (const [ri, e, flags] of others.slice(0, 12)) {
      const m = ctx.rootMeta(ri);
      list.append(h("li", "", button(m.term, "linklike", () => ctx.openRoot(m.slug, v.term, e)),
        flags & 1 ? h("span", "flag warn", "uncertain") : null,
        flags & 2 ? h("span", "flag", "via affix") : null,
        flags & 4 ? h("span", "flag", "route not stated") : null));
    }
    body.append(section("Also traced to", list));
  }
  body.append(sourceNote(v.edge));
}

function chainList(nodes: VNode[], ctx: PanelContext) {
  const ol = h("ol", "chain");
  nodes.forEach((n, i) => {
    const li = h("li", `step b-${n.branch ?? "pie"}${n.edge?.uncertain ? " uncertain" : ""}`);
    if (i > 0 && n.edge) {
      li.append(h("div", "edge-label", h("span", `type-badge t-${n.edge.type}`, EDGE_LABEL[n.edge.type] ?? n.edge.type)));
      const notes = edgeNotes(n.edge);
      if (notes) li.append(notes);
    }
    const row = h("div", "step-row", branchDot(n.branch));
    const term = n.english
      ? button(n.term, "linklike strong", () => ctx.selectWord(n), "Show this word")
      : button(n.term, "linklike strong", () => ctx.recenter(n), "Centre the tree here");
    row.append(h("span", "step-lang", langName(n.lang)), term, extLink(wiktionaryUrl(n.lang, n.term), "↗", "ext icon"));
    li.append(row);
    ol.append(li);
  });
  return ol;
}

function sourceNote(e?: Edge) {
  const p = h("p", "source-note", "Data: ", extLink("https://en.wiktionary.org/", "English Wiktionary", "plain-link"),
    " contributors, via ", extLink("https://kaikki.org/", "kaikki.org", "plain-link"), " · ",
    extLink("https://creativecommons.org/licenses/by-sa/4.0/", "CC BY-SA 4.0", "plain-link"), ".");
  if (e?.sources?.length) p.append(` Last step stated on: ${e.sources.join(", ")}.`);
  return p;
}
