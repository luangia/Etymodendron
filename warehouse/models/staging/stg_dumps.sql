-- One row per dump. prev_dump_id is the previous dump whose rows are still in the raw tables,
-- so a diff is only computed when both sides are actually there.
with dumps as (
    select * from {{ source('raw', 'raw_dumps') }}
),

with_rows as (
    select dump_id, lag(dump_id) over (order by dump_id) as prev_dump_id
    from (select distinct dump_id from {{ source('raw', 'raw_sections') }}) d
)

select
    d.dump_id,
    d.url,
    d.last_modified,
    d.sha256,
    d.bytes,
    d.sections,
    d.word_roots,
    d.unrooted,
    d.loaded_at,
    w.dump_id is not null as has_rows,
    w.prev_dump_id,
    row_number() over (order by d.dump_id) as dump_seq
from dumps d
left join with_rows w on w.dump_id = d.dump_id
