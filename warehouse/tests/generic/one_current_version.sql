{# A snapshot must have at most one open (dbt_valid_to is null) version per key. #}
{% test one_current_version(model, column_name) %}
select {{ column_name }}, count(*) as n
from {{ model }}
where dbt_valid_to is null
group by {{ column_name }}
having count(*) > 1
{% endtest %}
