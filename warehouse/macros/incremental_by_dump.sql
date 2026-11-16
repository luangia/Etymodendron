{#
  Config for models with one partition per dump. Re-running a dump replaces its rows:
  BigQuery overwrites the dump_id partition, duckdb deletes and re-inserts that dump.
#}
{% macro dump_partition_config() %}
  {%- if target.type == 'bigquery' -%}
    {{ return({'incremental_strategy': 'insert_overwrite',
               'partition_by': {'field': 'dump_id', 'data_type': 'date'}}) }}
  {%- else -%}
    {{ return({'incremental_strategy': 'delete+insert', 'unique_key': 'dump_id'}) }}
  {%- endif -%}
{% endmacro %}

{# Only dumps newer than what the model already has. #}
{% macro new_dumps_only(column='dump_id') %}
  {%- if is_incremental() -%}
    and {{ column }} > (select coalesce(max(dump_id), date '1900-01-01') from {{ this }})
  {%- endif -%}
{% endmacro %}
