select
    dump_id,
    section_key,
    lang,
    word,
    pos,
    etym,
    entries,
    lemma,
    has_ety,
    n_edges,
    edges_hash,
    edges,
    gloss
from {{ source('raw', 'raw_sections') }}
