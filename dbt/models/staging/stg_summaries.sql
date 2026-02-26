-- stg_summaries: Validated AI summaries linked to posts with quality scoring.
-- Source: raw_ai_summaries
-- Note: raw_api_response deliberately excluded from staging (large JSONB blob,
-- only needed for debugging in raw layer).

with validated_summaries as (
    select
        id,
        post_id,
        summary_text,
        tags,
        difficulty_classification,
        case
            when tags is null then true
            when length(summary_text) < 50 then true
            when tags = '[]'::jsonb then true
            else false
        end as is_low_quality,
        created_at
    from {{ source('raw', 'raw_ai_summaries') }}
)

select * from validated_summaries
