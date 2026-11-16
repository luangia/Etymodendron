select
    dump_id,
    word,
    etym,
    reason,
    stuck_at
from {{ source('raw', 'raw_unrooted') }}
