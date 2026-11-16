-- The newest dump only: what snap_sections compares against its current rows.
select s.*
from {{ ref('stg_sections') }} s
where s.dump_id = (select max(dump_id) from {{ ref('stg_dumps') }} where has_rows)
