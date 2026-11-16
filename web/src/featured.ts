import type { RootMeta } from "./types";

/**
 * Roots the landing page picks from. Each is small enough to draw quickly, reaches English
 * through more than one branch, and includes words people know. Edit freely: a term that is
 * not in the index is skipped.
 */
export const FEATURED = [
  "*ph₂tḗr", //    father, paternal, patriot
  "*méh₂tēr", //   mother, maternal, metropolis
  "*bʰréh₂tēr", // brother, fraternal, friar
  "*swésōr", //    sister, cousin
  "*néwos", //     new, novel, neon
  "*nókʷts", //    night, nocturnal, equinox
  "*gʷṓws", //     cow, beef, butter
  "*h₁éḱwos", //   equestrian, hippopotamus
  "*wĺ̥kʷos", //    wolf, lycanthrope
  "*ḱm̥tóm", //     hundred, cent, hectare
  "*ḱwṓ", //       hound, canine, cynic
  "*h₁rewdʰ-", //  red, ruby, erythrocyte
  "*sweh₂d-", //   sweet, persuade, hedonism
  "*h₁nómn̥", //    name, noun, synonym
  "*dóru", //      tree, tar, dryad
  "*h₁ed-", //     eat, edible, comestible
];

/** "Surprise me" draws from every root whose tree is big enough to be interesting but quick to draw. */
const SURPRISE_MIN = 40;
const SURPRISE_MAX = 1500;

const pick = <T>(xs: T[]): T | undefined => xs[Math.floor(Math.random() * xs.length)];

export function featuredRoot(byTerm: Map<string, RootMeta>, current?: string): RootMeta | undefined {
  const pool = FEATURED.map((t) => byTerm.get(t)).filter((m): m is RootMeta => !!m);
  return pick(pool.filter((m) => m.slug !== current)) ?? pool[0];
}

export function surpriseRoot(roots: RootMeta[], current?: string): RootMeta | undefined {
  return pick(roots.filter((m) => m.words >= SURPRISE_MIN && m.words <= SURPRISE_MAX && m.slug !== current));
}
