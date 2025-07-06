templates = {
    "summary_no_group": """SELECT 
        MIN({0}) AS min_value,
        percentile_cont(0.01) WITHIN GROUP (ORDER BY {0}) AS p01,
        percentile_cont(0.05) WITHIN GROUP (ORDER BY {0}) AS p05,
        percentile_cont(0.25) WITHIN GROUP (ORDER BY {0}) AS p25,
        percentile_cont(0.75) WITHIN GROUP (ORDER BY {0}) AS p75,
        percentile_cont(0.95) WITHIN GROUP (ORDER BY {0}) AS p95,
        percentile_cont(0.99) WITHIN GROUP (ORDER BY {0}) AS p99,
        MAX({0}) AS max_value
    FROM opendata.{1}
    WHERE {0} IS NOT NULL {2};"""
}
