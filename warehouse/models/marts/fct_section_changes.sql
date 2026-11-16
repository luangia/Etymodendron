{{ config(materialized='incremental', on_schema_change='append_new_columns', **dump_partition_config()) }}

-- What changed in each section's parsed ancestry since the previous dump.
--
-- Sections are matched by content first, within one (lang, word, part of speech): when an editor
-- inserts a new etymology at the top of a page, every existing one shifts down a number. Matching
-- by key alone would call all of them edited; matching by content calls them renumbered and the
-- new one added.
--   renumbered  the same edges, now under a different etymology number
--   edited      the same key, different edges, and neither side matched anything else by content
--   added       a new section (section_key set, prev_section_key null)
--   removed     a section that is gone (section_key null, prev_section_key set)
with pairs as (
    select dump_id, prev_dump_id
    from {{ ref('stg_dumps') }}
    where has_rows and prev_dump_id is not null {{ new_dumps_only() }}
),

cur as (
    select
        p.dump_id, p.prev_dump_id, s.section_key, s.lang, s.word, s.pos, s.etym,
        s.edges_hash, s.n_edges, s.edges,
        row_number() over (
            partition by p.dump_id, s.lang, s.word, s.pos, s.edges_hash order by s.etym
        ) as rn
    from pairs p
    join {{ ref('stg_sections') }} s on s.dump_id = p.dump_id
),

prev as (
    select
        p.dump_id, s.section_key, s.lang, s.word, s.pos, s.etym,
        s.edges_hash, s.n_edges, s.edges,
        row_number() over (
            partition by p.dump_id, s.lang, s.word, s.pos, s.edges_hash order by s.etym
        ) as rn
    from pairs p
    join {{ ref('stg_sections') }} s on s.dump_id = p.prev_dump_id
),

-- same content on both sides (the nth copy pairs with the nth copy)
matched as (
    select c.dump_id, c.section_key, p.section_key as prev_section_key, c.etym, p.etym as prev_etym
    from cur c
    join prev p
        on p.dump_id = c.dump_id and p.lang = c.lang and p.word = c.word and p.pos = c.pos
        and p.edges_hash = c.edges_hash and p.rn = c.rn
),

cur_left as (
    select c.* from cur c
    where not exists (select 1 from matched m where m.dump_id = c.dump_id and m.section_key = c.section_key)
),

prev_left as (
    select p.* from prev p
    where not exists (select 1 from matched m where m.dump_id = p.dump_id and m.prev_section_key = p.section_key)
),

edited as (
    select c.dump_id, c.section_key
    from cur_left c
    join prev_left p on p.dump_id = c.dump_id and p.section_key = c.section_key
),

changes as (
    select
        m.dump_id, m.section_key, m.prev_section_key, 'renumbered' as change_type
    from matched m
    where m.etym != m.prev_etym
    union all
    select e.dump_id, e.section_key, e.section_key, 'edited'
    from edited e
    union all
    select c.dump_id, c.section_key, cast(null as {{ dbt.type_string() }}), 'added'
    from cur_left c
    where not exists (select 1 from edited e where e.dump_id = c.dump_id and e.section_key = c.section_key)
    union all
    select p.dump_id, cast(null as {{ dbt.type_string() }}), p.section_key, 'removed'
    from prev_left p
    where not exists (select 1 from edited e where e.dump_id = p.dump_id and e.section_key = p.section_key)
)

select
    x.dump_id,
    pr.prev_dump_id,
    x.change_type,
    x.section_key,
    x.prev_section_key,
    coalesce(c.lang, p.lang) as lang,
    coalesce(c.word, p.word) as word,
    coalesce(c.pos, p.pos) as pos,
    c.etym,
    p.etym as prev_etym,
    p.n_edges as prev_n_edges,
    c.n_edges,
    case when x.change_type != 'renumbered' then p.edges end as prev_edges,
    case when x.change_type != 'renumbered' then c.edges end as edges
from changes x
join pairs pr on pr.dump_id = x.dump_id
left join cur c on c.dump_id = x.dump_id and c.section_key = x.section_key
left join prev p on p.dump_id = x.dump_id and p.section_key = x.prev_section_key
