-- A real dump-to-dump change is small. A big swing means the dump or the parser broke.
select dump_id, prev_dump_id, sections, sections_delta
from {{ ref('fct_dump_summary') }}
where prev_dump_id is not null
  and abs(sections_delta) > {{ var('max_section_change_pct') }} / 100.0 * (sections - sections_delta)
