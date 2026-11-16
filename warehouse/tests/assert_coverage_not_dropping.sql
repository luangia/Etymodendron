-- Coverage should only move a little between dumps. A drop is how the ignored {{ "{{ety}}" }}
-- template would have shown up: thousands of words losing their root at once.
select dump_id, prev_dump_id, coverage_pct, coverage_pct_delta
from {{ ref('fct_dump_summary') }}
where coverage_pct_delta < -{{ var('max_coverage_drop_pts') }}
