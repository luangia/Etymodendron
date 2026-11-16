{{ config(materialized='incremental', on_schema_change='append_new_columns', **dump_partition_config()) }}

-- English words whose PIE roots changed since the previous dump: the change a site visitor would see.
--   gained_root / lost_root   the word started or stopped reaching any PIE root
--   roots_changed             rooted on both sides, but in a different set of root files
--   added_word / removed_word the English word appeared or disappeared
with pairs as (
    select dump_id, prev_dump_id
    from {{ ref('stg_dumps') }}
    where has_rows and prev_dump_id is not null {{ new_dumps_only() }}
),

sides as (
    select
        p.dump_id, p.prev_dump_id, w.word,
        1 as in_cur, 0 as in_prev,
        w.root_slugs as cur_roots, cast(null as {{ dbt.type_string() }}) as prev_roots,
        case when w.is_rooted then 1 else 0 end as cur_rooted, 0 as prev_rooted,
        w.unrooted_reason as cur_reason, cast(null as {{ dbt.type_string() }}) as prev_reason
    from pairs p
    join {{ ref('int_word_status') }} w on w.dump_id = p.dump_id
    union all
    select
        p.dump_id, p.prev_dump_id, w.word,
        0, 1,
        cast(null as {{ dbt.type_string() }}), w.root_slugs,
        0, case when w.is_rooted then 1 else 0 end,
        cast(null as {{ dbt.type_string() }}), w.unrooted_reason
    from pairs p
    join {{ ref('int_word_status') }} w on w.dump_id = p.prev_dump_id
),

keyed as (
    select
        dump_id, prev_dump_id, word,
        max(in_cur) = 1 as in_cur, max(in_prev) = 1 as in_prev,
        max(cur_roots) as root_slugs, max(prev_roots) as prev_root_slugs,
        max(cur_rooted) = 1 as rooted, max(prev_rooted) = 1 as prev_rooted,
        max(cur_reason) as unrooted_reason, max(prev_reason) as prev_unrooted_reason
    from sides
    group by dump_id, prev_dump_id, word
),

classified as (
    select
        *,
        case
            when not in_prev then 'added_word'
            when not in_cur then 'removed_word'
            when rooted and not prev_rooted then 'gained_root'
            when prev_rooted and not rooted then 'lost_root'
            when rooted and coalesce(root_slugs, '') != coalesce(prev_root_slugs, '') then 'roots_changed'
        end as change_type
    from keyed
)

select
    dump_id,
    prev_dump_id,
    word,
    change_type,
    prev_root_slugs,
    root_slugs,
    prev_unrooted_reason,
    unrooted_reason
from classified
where change_type is not null
