-- The newest dump only: what snap_word_status compares against its current rows.
select w.*
from {{ ref('int_word_status') }} w
where w.dump_id = (select max(dump_id) from {{ ref('stg_dumps') }} where has_rows)
