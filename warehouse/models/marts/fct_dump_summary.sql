{{ config(materialized='incremental', on_schema_change='append_new_columns', **dump_partition_config()) }}

-- One row per dump: size and English root coverage (rooted lemmas / lemmas, as in the validation report), with the change from the previous dump.
with dumps as (
    select dump_id, prev_dump_id, last_modified, sha256, bytes
    from {{ ref('stg_dumps') }}
    where has_rows {{ new_dumps_only() }}
),

sections as (
    select
        dump_id,
        count(*) as sections,
        sum(case when lang = 'en' then 1 else 0 end) as english_sections
    from {{ ref('stg_sections') }}
    group by dump_id
),

words as (
    select
        dump_id,
        sum(case when is_lemma then 1 else 0 end) as english_lemmas,
        sum(case when is_lemma and is_rooted then 1 else 0 end) as rooted_lemmas,
        sum(case when is_rooted and only_via_affix then 1 else 0 end) as only_via_affix_words,
        sum(case when is_rooted and only_uncertain then 1 else 0 end) as only_uncertain_words
    from {{ ref('int_word_status') }}
    group by dump_id
),

stats as (
    select
        s.dump_id,
        s.sections,
        s.english_sections,
        w.english_lemmas,
        w.rooted_lemmas,
        w.only_via_affix_words,
        w.only_uncertain_words,
        round(100.0 * w.rooted_lemmas / nullif(w.english_lemmas, 0), 2) as coverage_pct
    from sections s
    join words w on w.dump_id = s.dump_id
)

select
    d.dump_id,
    d.prev_dump_id,
    d.last_modified,
    d.sha256,
    d.bytes,
    cur.sections,
    cur.english_sections,
    cur.english_lemmas,
    cur.rooted_lemmas,
    cur.only_via_affix_words,
    cur.only_uncertain_words,
    cur.coverage_pct,
    cur.sections - prev.sections as sections_delta,
    cur.rooted_lemmas - prev.rooted_lemmas as rooted_lemmas_delta,
    round(cur.coverage_pct - prev.coverage_pct, 2) as coverage_pct_delta
from dumps d
join stats cur on cur.dump_id = d.dump_id
left join stats prev on prev.dump_id = d.prev_dump_id
