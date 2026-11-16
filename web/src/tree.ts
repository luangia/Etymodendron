import * as d3 from "d3";
import { EDGE_LABEL, langName, type VNode } from "./data";

type HNode = d3.HierarchyPointNode<VNode>;

interface Callbacks {
  onWord(v: VNode): void;
  onRecenter(v: VNode): void;
  onCenter(): void;
}

const MIN_LEAF_GAP = 13;       // px of outer-ring arc per English word at zoom 1
const LEAF_LABEL_ROOM = 11;    // show a leaf label once it has this many px of arc on screen
const INNER_LABEL_ROOM = 30;   // ...and an intermediate label once it has this many

const point = (x: number, y: number): [number, number] => [y * Math.sin(x), -y * Math.cos(x)];

/**
 * The node drawn in place of v: an intermediate form with exactly one child is a step on a
 * straight chain (Latin → Old French → Middle English), so the drawing skips to the end of
 * the chain. The skipped steps stay in the view model: the panel and the tooltip list them.
 */
const drawn = (v: VNode): VNode => {
  let n = v;
  while (!n.english && n.children.length === 1) n = n.children[0];
  return n;
};

/** The steps skipped between a drawn node and the drawn node above it, top first. */
function skipped(d: HNode): VNode[] {
  const out: VNode[] = [];
  for (let n = d.data.parent; n && d.parent && n !== d.parent.data; n = n.parent) out.push(n);
  return out.reverse();
}

export class RadialTree {
  private svg: d3.Selection<SVGSVGElement, unknown, null, undefined>;
  private layer: d3.Selection<SVGGElement, unknown, null, undefined>;
  private zoom: d3.ZoomBehavior<SVGSVGElement, unknown>;
  private nodes: d3.Selection<SVGGElement, HNode, SVGGElement, unknown> | null = null;
  private links: d3.Selection<SVGPathElement, d3.HierarchyPointLink<VNode>, SVGGElement, unknown> | null = null;
  private byVNode = new Map<VNode, HNode>();
  private room = new Map<HNode, number>();
  private forced = new Set<HNode>();
  private onPath = new Set<HNode>();
  private radius = 300;
  private k = 1;
  private raf = 0;
  private insets = { top: 0, right: 0, bottom: 0 };

  constructor(svgEl: SVGSVGElement, private tooltip: HTMLElement, private cb: Callbacks) {
    this.svg = d3.select(svgEl);
    this.layer = this.svg.append("g").attr("class", "zoom-layer");
    this.zoom = d3.zoom<SVGSVGElement, unknown>()
      .scaleExtent([0.15, 14])
      .on("zoom", (ev: d3.D3ZoomEvent<SVGSVGElement, unknown>) => {
        this.layer.attr("transform", ev.transform.toString());
        this.k = ev.transform.k;
        // labels and dots keep their screen size: counter-scale them with one CSS variable
        svgEl.style.setProperty("--inv", String(1 / ev.transform.k));
        cancelAnimationFrame(this.raf);
        this.raf = requestAnimationFrame(() => this.updateLabels());
        this.hideTooltip();
      });
    this.svg.call(this.zoom).on("dblclick.zoom", null);
    new ResizeObserver(() => this.size()).observe(svgEl);
  }

  /** Screen areas covered by floating controls; the tree is fitted into what remains. */
  setInsets(top: number, right: number, bottom: number) {
    this.insets = { top, right, bottom };
  }

  private viewport() {
    const { width, height } = (this.svg.node() as SVGSVGElement).getBoundingClientRect();
    const w = Math.max(1, width - this.insets.right);
    const h = Math.max(1, height - this.insets.top - this.insets.bottom);
    return { w, h, cx: w / 2, cy: this.insets.top + h / 2 };
  }

  private size() {
    const { width, height } = (this.svg.node() as SVGSVGElement).getBoundingClientRect();
    this.svg.attr("viewBox", `0 0 ${Math.max(1, width)} ${Math.max(1, height)}`);
  }

  render(view: VNode) {
    const h = d3.hierarchy(view, (d) => d.children.map(drawn));
    const leaves = h.leaves().length;
    this.radius = Math.max(170, (leaves * MIN_LEAF_GAP) / (2 * Math.PI));
    const layout = d3.cluster<VNode>()
      .size([2 * Math.PI, 1])
      .separation((a, b) => (a.parent === b.parent ? 1 : 1.5));
    const root = layout(h);

    // intermediate forms sit on rings by depth; English words always on the outer ring
    const maxInner = d3.max(root.descendants().filter((d) => d.children), (d) => d.depth) ?? 0;
    const innerR = this.radius * (maxInner > 0 ? 0.8 : 0.5);
    for (const d of root.descendants()) {
      d.y = d.depth === 0 ? 0 : d.children ? (innerR * d.depth) / Math.max(1, maxInner) : this.radius;
    }
    this.byVNode = new Map(root.descendants().map((d) => [d.data, d]));
    this.computeRoom(root);

    this.layer.selectAll("*").remove();
    this.layer.style("opacity", 0).transition().duration(350).style("opacity", 1);

    const rings = [...new Set(root.descendants().map((d) => d.y))].filter((r) => r > 0);
    this.layer.append("g").attr("class", "rings").selectAll("circle").data(rings).join("circle").attr("r", (r) => r);

    const linkGen = d3.linkRadial<d3.HierarchyPointLink<VNode>, HNode>().angle((d) => d.x).radius((d) => d.y);
    this.links = this.layer.append("g").attr("class", "links")
      .selectAll<SVGPathElement, d3.HierarchyPointLink<VNode>>("path")
      .data(root.links())
      .join("path")
      .attr("class", (l) => {
        // a collapsed chain is uncertain if any of its steps is
        const uncertain = [...skipped(l.target), l.target.data].some((n) => n.edge?.uncertain);
        return `link b-${l.target.data.branch ?? "pie"}${uncertain ? " uncertain" : ""}`;
      })
      .attr("d", linkGen);

    this.nodes = this.layer.append("g").attr("class", "nodes")
      .selectAll<SVGGElement, HNode>("g")
      .data(root.descendants())
      .join("g")
      .attr("class", (d) => {
        const kind = d.depth === 0 ? "center" : d.data.english ? "word" : "inner";
        return `node ${kind} b-${d.data.branch ?? "pie"}${d.data.derivatives.length ? " has-deriv" : ""}`;
      })
      .attr("transform", (d) => `translate(${point(d.x, d.y)})`);

    const inner = this.nodes.append("g").attr("class", "s");
    inner.append("circle").attr("class", "hit").attr("r", 12);
    inner.append("circle").attr("class", "dot").attr("r", (d) => (d.depth === 0 ? 7 : d.data.english ? 3.2 : 4.2));
    inner.append("text")
      .attr("class", "label")
      .each(function (d) {
        const t = d3.select(this);
        if (d.depth === 0) {
          t.attr("y", -14).attr("text-anchor", "middle").text(d.data.term);
        } else if (!d.children) {
          const deg = (d.x * 180) / Math.PI - 90;
          const flip = d.x > Math.PI;
          t.attr("transform", `rotate(${flip ? deg + 180 : deg})`)
            .attr("x", flip ? -7 : 7).attr("dy", "0.32em")
            .attr("text-anchor", flip ? "end" : "start")
            .text(d.data.term + (d.data.derivatives.length ? " +" : ""));
        } else {
          t.attr("x", 7).attr("dy", "-0.45em").text(d.data.term);
        }
      });

    this.nodes
      .on("pointerenter", (ev: PointerEvent, d) => this.showTooltip(ev, d))
      .on("pointermove", (ev: PointerEvent) => this.moveTooltip(ev))
      .on("pointerleave", () => this.hideTooltip())
      .on("click", (ev: MouseEvent, d) => {
        ev.stopPropagation();
        this.hideTooltip();
        if (d.depth === 0) this.cb.onCenter();
        else if (d.data.english) this.cb.onWord(d.data);
        else this.cb.onRecenter(d.data);
      });
    this.svg.on("click", () => this.cb.onCenter());

    this.nodes.filter((d) => d.depth === 0).raise(); // keep the centre label above crowded inner rings
    this.forced.clear();
    this.select(null);
    this.fit(false);
  }

  /** Arc length available to each node's label, from its neighbours on the same ring. */
  private computeRoom(root: HNode) {
    this.room.clear();
    const byRing = d3.group(root.descendants().filter((d) => d.depth > 0), (d) => d.y);
    for (const [r, ring] of byRing) {
      ring.sort((a, b) => a.x - b.x);
      ring.forEach((d, i) => {
        if (ring.length === 1) return this.room.set(d, 2 * Math.PI * r);
        const prev = ring[(i - 1 + ring.length) % ring.length].x;
        const next = ring[(i + 1) % ring.length].x;
        const gap = Math.min((d.x - prev + 2 * Math.PI) % (2 * Math.PI), (next - d.x + 2 * Math.PI) % (2 * Math.PI));
        this.room.set(d, gap * r);
      });
    }
  }

  private updateLabels() {
    if (!this.nodes) return;
    const k = this.k;
    // highlighted paths get their intermediate labels sooner, but still only where they fit
    this.nodes.classed("lbl", (d) =>
      d.depth === 0 || this.forced.has(d) ||
      (this.room.get(d) ?? 0) * k >= (d.children ? (this.onPath.has(d) ? 12 : INNER_LABEL_ROOM) : LEAF_LABEL_ROOM));
  }

  fit(animate = true) {
    const { w, h, cx, cy } = this.viewport();
    const reach = this.radius + 100; // room for outer labels
    const k = Math.min(2.2, Math.max(0.15, Math.min(w, h) / (2 * reach)));
    const t = d3.zoomIdentity.translate(cx, cy).scale(k);
    (animate ? this.svg.transition().duration(550) : this.svg).call(this.zoom.transform as never, t);
  }

  zoomBy(f: number) {
    this.svg.transition().duration(250).call(this.zoom.scaleBy as never, f);
  }

  /** Bring a word into view: zoom until its label has room, keeping the centre-to-word path on screen. */
  focus(v: VNode) {
    const d = this.byVNode.get(this.drawnAncestor(v));
    if (!d) return;
    const { w, h, cx, cy } = this.viewport();
    const [x, y] = point(d.x, d.y);
    const room = this.room.get(d) ?? 10;
    // readable, but never so close that the path back to the centre leaves the screen
    const fitPath = (Math.min(w, h) * 0.9) / Math.max(1, Math.hypot(x, y) + 80);
    const k = Math.max(this.k, Math.min(fitPath * 2, (LEAF_LABEL_ROOM + 3) / Math.max(room, 0.5), 8));
    const t = d3.zoomIdentity.translate(cx, cy).scale(k).translate(-x / 2, -y / 2);
    this.svg.transition().duration(650).call(this.zoom.transform as never, t);
  }

  private drawnAncestor(v: VNode): VNode {
    let n: VNode | null = v;
    while (n && !this.byVNode.has(n)) n = n.parent;
    return n ?? v;
  }

  /** Highlight the path from the centre to one word (or clear with null). */
  select(v: VNode | null) {
    this.spotlight(v ? [v] : null, "selected");
  }

  /** Highlight the paths to several words, e.g. cognates that arrived through different branches. */
  spotlight(words: VNode[] | null, mode: "selected" | "cognates" = "cognates") {
    if (!this.nodes || !this.links) return;
    const on = new Set<HNode>();
    this.forced.clear();
    for (const w of words ?? []) {
      const d = this.byVNode.get(this.drawnAncestor(w));
      if (!d) continue;
      this.forced.add(d);
      for (let a: HNode | null = d; a; a = a.parent) on.add(a);
    }
    this.onPath = on;
    const active = on.size > 0;
    this.svg.classed("has-focus", active).classed("cognate-mode", active && mode === "cognates");
    this.nodes.classed("on", (d) => on.has(d)).classed("target", (d) => this.forced.has(d) && !d.children);
    this.links.classed("on", (l) => on.has(l.target));
    this.links.filter((l) => on.has(l.target)).raise();
    this.nodes.filter((d) => on.has(d)).raise();
    this.updateLabels();
  }

  focusBranch(branch: string | null) {
    this.svg.attr("data-branch", branch ?? null);
  }

  // -------------------------------------------------------------- tooltip
  private showTooltip(ev: PointerEvent, d: HNode) {
    if (ev.pointerType === "touch") return;
    const v = d.data;
    const tip = this.tooltip;
    tip.replaceChildren();
    const strong = document.createElement("strong");
    strong.textContent = v.term;
    const lang = document.createElement("span");
    lang.className = "tip-lang";
    lang.textContent = langName(v.lang);
    tip.append(strong, lang);
    if (v.edge && v.parent && d.parent) {
      const e = document.createElement("div");
      e.className = "tip-edge";
      e.textContent = `${EDGE_LABEL[v.edge.type] ?? v.edge.type} ${langName(v.parent.lang)} ${v.parent.term}` +
        (v.edge.uncertain ? " (uncertain)" : "");
      tip.append(e);
      const via = skipped(d).slice(0, -1); // the immediate parent is already named above
      if (via.length) {
        const p = document.createElement("div");
        p.className = "tip-via";
        p.textContent = `via ${via.map((n) => `${langName(n.lang)} ${n.term}`).join(" → ")}`;
        tip.append(p);
      }
    }
    if (v.english && v.data.gloss) {
      const g = document.createElement("div");
      g.className = "tip-gloss";
      g.textContent = v.data.gloss;
      tip.append(g);
    }
    if (!v.english && d.depth > 0) {
      const h = document.createElement("div");
      h.className = "tip-hint";
      h.textContent = `${v.words} English word${v.words === 1 ? "" : "s"} · click to centre here`;
      tip.append(h);
    }
    tip.hidden = false;
    this.moveTooltip(ev);
  }

  private moveTooltip(ev: PointerEvent) {
    const tip = this.tooltip;
    if (tip.hidden) return;
    const host = tip.parentElement!.getBoundingClientRect();
    const x = ev.clientX - host.left, y = ev.clientY - host.top;
    const w = tip.offsetWidth, h = tip.offsetHeight;
    tip.style.left = `${Math.min(host.width - w - 8, x + 14)}px`;
    tip.style.top = `${y + h + 20 > host.height ? y - h - 12 : y + 16}px`;
  }

  private hideTooltip() {
    this.tooltip.hidden = true;
  }
}
