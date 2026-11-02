import type { IndexHit, SearchIndex } from "./types";

const MAX_RESULTS = 8;

export interface Suggestion {
  word: string;
  hits: IndexHit[];
}

/**
 * Which root to open for a word: a stated chain first, then a bare {{root}} link (route not stated),
 * and last a path that only reaches the root through an affix (-al, re-...). Ties keep index order.
 */
export function orderHits(hits: IndexHit[]): IndexHit[] {
  const rank = ([, , f]: IndexHit) => (f & 2 ? 4 : f & 4 ? 2 : 0) + (f & 1 ? 1 : 0);
  return hits.map((h, i) => [h, i] as const).sort((a, b) => rank(a[0]) - rank(b[0]) || a[1] - b[1]).map(([h]) => h);
}

const fold = (s: string) => s.normalize("NFD").replace(/\p{M}/gu, "").toLowerCase();

/** Prefix search over every English word in the index, accent- and case-insensitive. */
export class WordSearch {
  private keys: string[];
  private words: string[];

  constructor(private index: SearchIndex) {
    const entries = Object.keys(index.words).map((w) => [fold(w), w] as const);
    entries.sort((a, b) => (a[0] < b[0] ? -1 : a[0] > b[0] ? 1 : 0));
    this.keys = entries.map((e) => e[0]);
    this.words = entries.map((e) => e[1]);
  }

  query(q: string): Suggestion[] {
    const key = fold(q.trim());
    if (!key) return [];
    let lo = 0, hi = this.keys.length;
    while (lo < hi) {
      const mid = (lo + hi) >> 1;
      if (this.keys[mid] < key) lo = mid + 1;
      else hi = mid;
    }
    const found: string[] = [];
    for (let i = lo; i < this.keys.length && found.length < 400 && this.keys[i].startsWith(key); i++) {
      found.push(this.words[i]);
    }
    // exact match first, then plain lowercase words, then shorter
    const rank = (w: string) => (fold(w) === key ? 0 : 1) * 1000 + (/^[a-z]+$/.test(w) ? 0 : 100) + w.length;
    return found
      .sort((a, b) => rank(a) - rank(b) || a.localeCompare(b))
      .slice(0, MAX_RESULTS)
      .map((word) => ({ word, hits: orderHits(this.index.words[word]) }));
  }

  has(word: string) {
    return word in this.index.words;
  }
}

/** Wire the combobox: keyboard navigation, pointer selection, ARIA state. */
export function attachSearch(
  input: HTMLInputElement,
  list: HTMLUListElement,
  search: WordSearch,
  rootTerm: (hit: IndexHit) => string,
  onPick: (s: Suggestion) => void,
) {
  const box = input.parentElement!;
  let items: Suggestion[] = [];
  let active = -1;

  const close = () => {
    list.hidden = true;
    box.setAttribute("aria-expanded", "false");
    input.removeAttribute("aria-activedescendant");
    active = -1;
  };

  const paint = () => {
    list.replaceChildren();
    items.forEach((s, i) => {
      const li = document.createElement("li");
      li.id = `sugg-${i}`;
      li.role = "option";
      li.setAttribute("aria-selected", String(i === active));
      const w = document.createElement("span");
      w.className = "sugg-word";
      w.textContent = s.word;
      const r = document.createElement("span");
      r.className = "sugg-roots";
      const shown = s.hits.slice(0, 2);
      r.textContent = shown.map(rootTerm).join(" · ") + (s.hits.length > shown.length ? ` +${s.hits.length - shown.length}` : "");
      li.append(w, r);
      li.addEventListener("pointerdown", (ev) => {
        ev.preventDefault();
        pick(i);
      });
      list.append(li);
    });
    list.hidden = items.length === 0;
    box.setAttribute("aria-expanded", String(!list.hidden));
    if (active >= 0) input.setAttribute("aria-activedescendant", `sugg-${active}`);
    else input.removeAttribute("aria-activedescendant");
  };

  const pick = (i: number) => {
    const s = items[i];
    if (!s) return;
    input.value = s.word;
    close();
    input.blur();
    onPick(s);
  };

  input.addEventListener("input", () => {
    items = search.query(input.value);
    active = items.length ? 0 : -1;
    paint();
  });
  input.addEventListener("keydown", (ev) => {
    if (ev.key === "ArrowDown" || ev.key === "ArrowUp") {
      if (!items.length) return;
      ev.preventDefault();
      active = (active + (ev.key === "ArrowDown" ? 1 : -1) + items.length) % items.length;
      paint();
    } else if (ev.key === "Enter") {
      ev.preventDefault();
      pick(active >= 0 ? active : 0);
    } else if (ev.key === "Escape") {
      close();
    }
  });
  input.addEventListener("focus", () => {
    if (input.value) {
      items = search.query(input.value);
      paint();
    }
  });
  input.addEventListener("blur", () => setTimeout(close, 120));
  document.addEventListener("keydown", (ev) => {
    const typing = ev.target instanceof HTMLInputElement || ev.target instanceof HTMLTextAreaElement;
    if (ev.key === "/" && !typing) {
      ev.preventDefault();
      input.focus();
      input.select();
    }
  });
}
