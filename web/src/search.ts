import { loadUnrootedShard } from "./data";
import type { IndexHit, SearchIndex, UnrootedInfo, UnrootedShard } from "./types";

const MAX_RESULTS = 8;

export interface Suggestion {
  word: string;
  hits: IndexHit[];
  /** set when the word is in Wiktionary but reaches no PIE root */
  unrooted?: UnrootedInfo;
}

/**
 * Which root to open for a word: a stated chain first, then a bare {{root}} link (route not stated),
 * and last a path that only reaches the root through an affix (-al, re-...). Ties keep index order.
 */
export function orderHits(hits: IndexHit[]): IndexHit[] {
  const rank = ([, , f]: IndexHit) => (f & 2 ? 4 : f & 4 ? 2 : 0) + (f & 1 ? 1 : 0);
  return hits.map((h, i) => [h, i] as const).sort((a, b) => rank(a[0]) - rank(b[0]) || a[1] - b[1]).map(([h]) => h);
}

// must match search_fold() in etl/export.py, which names the unrooted shards
const fold = (s: string) => s.normalize("NFD").replace(/\p{M}/gu, "").toLowerCase();
const shardOf = (key: string) => (key[0] >= "a" && key[0] <= "z" ? key[0] : "_");

function lowerBound(keys: string[], key: string) {
  let lo = 0, hi = keys.length;
  while (lo < hi) {
    const mid = (lo + hi) >> 1;
    if (keys[mid] < key) lo = mid + 1;
    else hi = mid;
  }
  return lo;
}

interface LoadedShard {
  keys: string[];
  rows: UnrootedShard["words"];
  reasons: string[];
}

/** Prefix search over every English word in the index, accent- and case-insensitive. */
export class WordSearch {
  private keys: string[];
  private words: string[];
  private shards = new Map<string, LoadedShard | null>();
  private pending = new Map<string, Promise<void>>();

  constructor(private index: SearchIndex) {
    const entries = Object.keys(index.words).map((w) => [fold(w), w] as const);
    entries.sort((a, b) => (a[0] < b[0] ? -1 : a[0] > b[0] ? 1 : 0));
    this.keys = entries.map((e) => e[0]);
    this.words = entries.map((e) => e[1]);
  }

  /**
   * Fetch the unrooted words for this query's first letter, if not loaded yet.
   * Returns null when nothing needs loading; failures just leave search to rooted words.
   */
  ensureShard(q: string): Promise<void> | null {
    const key = fold(q.trim());
    if (!key) return null;
    const k = shardOf(key);
    if (this.shards.has(k)) return null;
    let p = this.pending.get(k);
    if (!p) {
      p = loadUnrootedShard(k)
        .then((d) => {
          const rows = d.words.map((r) => [fold(r[0]), r] as const);
          rows.sort((a, b) => (a[0] < b[0] ? -1 : a[0] > b[0] ? 1 : 0));
          this.shards.set(k, { keys: rows.map((r) => r[0]), rows: rows.map((r) => r[1]), reasons: d.reasons });
        })
        .catch(() => void this.shards.set(k, null))
        .finally(() => this.pending.delete(k));
      this.pending.set(k, p);
    }
    return p;
  }

  query(q: string): Suggestion[] {
    const key = fold(q.trim());
    if (!key) return [];
    const found: Suggestion[] = [];
    for (let i = lowerBound(this.keys, key); i < this.keys.length && found.length < 400 && this.keys[i].startsWith(key); i++) {
      const word = this.words[i];
      found.push({ word, hits: orderHits(this.index.words[word]) });
    }
    const shard = this.shards.get(shardOf(key));
    if (shard) {
      let n = 0;
      for (let i = lowerBound(shard.keys, key); i < shard.keys.length && n < 400 && shard.keys[i].startsWith(key); i++, n++) {
        found.push({ word: shard.rows[i][0], hits: [], unrooted: this.info(shard, shard.rows[i]) });
      }
    }
    // exact match first, then plain lowercase words, then shorter; a word without a root counts as
    // three letters longer, so "coffee" still comes before "coffeeless" but loses ties to rooted words
    const rank = (s: Suggestion) => (fold(s.word) === key ? 0 : 1) * 1000 + (s.unrooted ? 3 : 0) +
      (/^[a-z]+$/.test(s.word) ? 0 : 100) + s.word.length;
    return found.sort((a, b) => rank(a) - rank(b) || a.word.localeCompare(b.word)).slice(0, MAX_RESULTS);
  }

  /** Exact lookup of a word with no root (for shared links). */
  async lookupUnrooted(word: string): Promise<UnrootedInfo | null> {
    await this.ensureShard(word);
    const shard = this.shards.get(shardOf(fold(word)));
    if (!shard) return null;
    for (let i = lowerBound(shard.keys, fold(word)); i < shard.keys.length && shard.keys[i] === fold(word); i++) {
      if (shard.rows[i][0] === word) return this.info(shard, shard.rows[i]);
    }
    return null;
  }

  private info(shard: LoadedShard, row: UnrootedShard["words"][number]): UnrootedInfo {
    return { reason: shard.reasons[row[1]] ?? "unknown", lang: row[2], term: row[3] };
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
  onMiss: (query: string) => void,
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
      if (s.unrooted) {
        r.classList.add("none");
        r.textContent = "no PIE root";
      } else {
        const shown = s.hits.slice(0, 2);
        r.textContent = shown.map(rootTerm).join(" · ") + (s.hits.length > shown.length ? ` +${s.hits.length - shown.length}` : "");
      }
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

  const refresh = () => {
    items = search.query(input.value);
    active = items.length ? 0 : -1;
    paint();
  };
  input.addEventListener("input", () => {
    refresh();
    const q = input.value;
    search.ensureShard(q)?.then(() => {
      if (input.value === q) refresh();
    });
  });
  input.addEventListener("keydown", (ev) => {
    if (ev.key === "ArrowDown" || ev.key === "ArrowUp") {
      if (!items.length) return;
      ev.preventDefault();
      active = (active + (ev.key === "ArrowDown" ? 1 : -1) + items.length) % items.length;
      paint();
    } else if (ev.key === "Enter") {
      ev.preventDefault();
      if (items.length) pick(active >= 0 ? active : 0);
      else if (input.value.trim()) {
        const q = input.value.trim();
        // the shard may still be loading: wait for it before saying the word isn't there
        Promise.resolve(search.ensureShard(q)).then(() => {
          items = search.query(q);
          if (items.length && fold(items[0].word) === fold(q)) pick(0);
          else {
            close();
            onMiss(q);
          }
        });
      }
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
