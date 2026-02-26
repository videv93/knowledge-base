-- Assert no duplicate author names exist in stg_authors after normalization.
-- This test passes when query returns zero rows.

select
    author_name,
    count(*) as name_count
from {{ ref('stg_authors') }}
group by author_name
having count(*) > 1
