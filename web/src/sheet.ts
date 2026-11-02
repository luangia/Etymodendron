/**
 * The details panel as a phone bottom sheet: drag it by the handle or header, or drag the content
 * while the sheet is not fully open; it snaps to peek / half / full. While open, the content
 * scrolls normally, and pulling down from the top of the content shrinks the sheet.
 */

export type SheetState = "peek" | "half" | "full";

const PEEK = 168;          // px: title and first lines visible
const FLICK = 0.5;         // px/ms: a flick this fast moves one state in its direction

export class BottomSheet {
  state: SheetState = "peek";
  private enabled = false;

  constructor(
    private panel: HTMLElement,
    private body: HTMLElement,
    private handle: HTMLElement,
    /** selector for the parts that always drag the sheet (handle, header) */
    private grip: string,
    /** true while the layout is the phone one (the panel is a sheet, not a sidebar) */
    private isPhone: () => boolean,
    private onSettle: (state: SheetState) => void,
  ) {
    handle.addEventListener("click", () => this.set(this.state === "peek" ? "half" : "peek"));
    panel.addEventListener("touchstart", (e) => this.start(e), { passive: true });
    panel.addEventListener("touchmove", (e) => this.move(e), { passive: false });
    panel.addEventListener("touchend", (e) => this.end(e));
    panel.addEventListener("touchcancel", (e) => this.end(e));
    // re-check on every resize: media-query change events are not reliable across browsers
    const sync = () => {
      if (this.isPhone() !== this.enabled) this.enable(this.isPhone());
      else if (this.enabled) this.apply(false);
    };
    window.addEventListener("resize", sync);
    window.visualViewport?.addEventListener("resize", sync);
    this.enable(isPhone());
  }

  /** Phones only: on wider screens the panel is a normal sidebar. */
  private enable(on: boolean) {
    this.enabled = on;
    if (on) {
      this.state = "peek";
      this.apply(false);
    } else {
      this.panel.style.height = "";
      delete this.panel.dataset.sheet;
    }
  }

  set(state: SheetState) {
    if (!this.enabled) return;
    const changed = state !== this.state;
    this.state = state;
    this.apply(true);
    if (changed) this.onSettle(state);
  }

  private heights(): Record<SheetState, number> {
    const vh = window.visualViewport?.height ?? window.innerHeight;
    const top = document.querySelector(".topbar")?.getBoundingClientRect().bottom ?? 56;
    const full = Math.max(PEEK + 80, vh - top - 8);
    return { peek: PEEK, half: Math.min(Math.max(PEEK + 60, vh * 0.55), full), full };
  }

  private apply(animate: boolean) {
    this.panel.classList.toggle("dragging", !animate);
    this.panel.style.height = `${this.heights()[this.state]}px`;
    this.panel.dataset.sheet = this.state;
    this.handle.setAttribute("aria-expanded", String(this.state !== "peek"));
    if (!animate) requestAnimationFrame(() => this.panel.classList.remove("dragging"));
  }

  // ---------------------------------------------------------------- touch handling
  private drag: {
    y0: number; h0: number; onGrip: boolean; decided: boolean; dragging: boolean;
    // the two latest samples, for flick speed
    y: number; t: number; py: number; pt: number;
  } | null = null;

  private start(e: TouchEvent) {
    if (!this.enabled || e.touches.length !== 1) return;
    const y = e.touches[0].clientY;
    this.drag = {
      y0: y, h0: this.panel.getBoundingClientRect().height,
      onGrip: !!(e.target as Element).closest?.(this.grip), decided: false, dragging: false,
      y, t: e.timeStamp, py: y, pt: e.timeStamp,
    };
  }

  private move(e: TouchEvent) {
    const d = this.drag;
    if (!d) return;
    const y = e.touches[0].clientY;
    const dy = y - d.y0; // > 0: finger moving down
    if (!d.decided) {
      // decide on the first movement: some browsers commit to scrolling right away
      if (dy === 0) return;
      d.decided = true;
      const atTop = this.body.scrollTop <= 0;
      // resize the sheet from its grip, when it is not fully open, or when pulling down from the top;
      // otherwise let the content scroll
      d.dragging = d.onGrip || this.state === "peek" || (dy < 0 && this.state !== "full") || (dy > 0 && atTop);
      if (d.dragging) this.panel.classList.add("dragging");
    }
    if (!d.dragging) return;
    e.preventDefault(); // keep the browser from scrolling the content or bouncing the page
    const { peek, full } = this.heights();
    const h = Math.min(full, Math.max(peek * 0.6, d.h0 - dy));
    this.panel.style.height = `${h}px`;
    d.py = d.y;
    d.pt = d.t;
    d.y = y;
    d.t = e.timeStamp;
  }

  private end(e: TouchEvent) {
    const d = this.drag;
    this.drag = null;
    if (!d?.dragging) return;
    this.panel.classList.remove("dragging");
    const h = this.panel.getBoundingClientRect().height;
    // px/ms over the last move, ignored if the finger rested before lifting
    const velocity = e.timeStamp - d.t > 100 ? 0 : (d.y - d.py) / Math.max(1, d.t - d.pt);
    const hs = this.heights();
    const order: SheetState[] = ["peek", "half", "full"];
    let next = order.reduce((best, s) => (Math.abs(hs[s] - h) < Math.abs(hs[best] - h) ? s : best), "peek" as SheetState);
    if (Math.abs(velocity) > FLICK) {
      // a flick goes one state further in its direction from where the drag started
      const from = order.indexOf(this.state);
      next = order[Math.max(0, Math.min(2, from + (velocity < 0 ? 1 : -1)))];
    }
    const changed = next !== this.state;
    this.state = next;
    this.apply(true);
    if (changed || Math.abs(h - hs[next]) > 1) this.onSettle(next);
  }
}
