select
    dump_id,
    word,
    etym,
    root_slug,
    root_term,
    root_kind,
    uncertain,
    via_affix,
    shortcut
from {{ source('raw', 'raw_word_roots') }}
