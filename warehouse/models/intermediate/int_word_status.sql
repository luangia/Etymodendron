-- One row per (dump, English word): which PIE roots it reaches, or why it reaches none.
-- Matches the site and etl/report.py: a word is rooted if it reaches any PIE file, and coverage
-- is counted over English lemmas (words with at least one lemma section).
with roots as (
    select
        dump_id,
        word,
        string_agg(distinct root_slug, ',' order by root_slug) as root_slugs,
        count(distinct root_slug) as n_roots,
        min(case when via_affix then 1 else 0 end) = 1 as only_via_affix,
        min(case when uncertain then 1 else 0 end) = 1 as only_uncertain
    from {{ ref('stg_word_roots') }}
    group by dump_id, word
),

reasons as (
    select dump_id, word, reason, stuck_at
    from (
        select
            u.*,
            row_number() over (partition by dump_id, word order by etym) as rn
        from {{ ref('stg_unrooted') }} u
    ) ranked
    where rn = 1
),

lemmas as (
    select distinct dump_id, word
    from {{ ref('stg_sections') }}
    where lang = 'en' and lemma
),

words as (
    select dump_id, word from roots
    union distinct
    select dump_id, word from reasons
)

select
    w.dump_id,
    w.word,
    l.word is not null as is_lemma,
    r.root_slugs is not null as is_rooted,
    r.root_slugs,
    coalesce(r.n_roots, 0) as n_roots,
    coalesce(r.only_via_affix, false) as only_via_affix,
    coalesce(r.only_uncertain, false) as only_uncertain,
    case when r.root_slugs is null then u.reason end as unrooted_reason,
    case when r.root_slugs is null then u.stuck_at end as stuck_at
from words w
left join roots r on r.dump_id = w.dump_id and r.word = w.word
left join reasons u on u.dump_id = w.dump_id and u.word = w.word
left join lemmas l on l.dump_id = w.dump_id and l.word = w.word
