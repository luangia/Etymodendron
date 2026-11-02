// Shapes of the JSON written by etl/export.py

export type EdgeType = "inherited" | "borrowed" | "derived" | "root" | "component";

export interface Edge {
  type: EdgeType;
  /** page = stated on the child's own page; sequence = implied by "from A, from B" prose order */
  via: "page" | "sequence" | "etymon" | "root";
  uncertain?: boolean;
  evidence?: string;
  confirmed?: boolean;
  /** "loose" = matched ignoring diacritics, "unresolved" = no page with that title */
  link?: "loose" | "unresolved";
  sources: string[];
}

export interface TreeNode {
  lang: string;
  term: string;
  edge?: Edge;
  children?: TreeNode[];
  // English leaves only
  etym?: number | null;
  gloss?: string | null;
  pos?: string[];
  path_uncertain?: boolean;
  via_affix?: boolean;
}

export interface RootDoc {
  root: {
    lang: string;
    term: string;
    kind: "root" | "lexeme";
    gloss: string | null;
    page_exists: boolean;
    homograph_ids: string[] | null;
  };
  parents: { term: string; kind: string; uncertain: boolean; path: string[]; edges: Edge[] }[];
  stats: { english_sections: number; english_words: number; uncertain_paths: number; via_affix: number };
  tree: TreeNode;
}

export interface RootMeta {
  slug: string;
  term: string;
  kind: "root" | "lexeme";
  words: number;
  words_incl_affix: number;
}

/** word -> [root index, etymology number (0 = only one), flags (1 uncertain, 2 via affix, 4 route not stated)] */
export type IndexHit = [number, number, number];

export interface SearchIndex {
  roots: RootMeta[];
  words: Record<string, IndexHit[]>;
  glosses: Record<string, Record<string, string | null>>;
}

/** "unknown": linked straight to the PIE root, with no route through other languages stated */
export type Branch = "germanic" | "romance" | "greek" | "other" | "unknown";

/** data/unrooted/<letter>.json: English words with no PIE root. Row: [word, reason index, stop lang?, stop term?] */
export interface UnrootedShard {
  reasons: string[];
  words: [string, number, string?, string?][];
}

export interface UnrootedInfo {
  reason: string;
  /** where the traced history stops, when known */
  lang?: string;
  term?: string;
}
