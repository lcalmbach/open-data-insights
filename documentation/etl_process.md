# story template

## Data sources
### ods
ods datasets can be updated automatically via the ods api. ods datasets start with the the prefix ds followed by the ods-key. 

### Custom
you may import any table and update it manually. currently there is *basel_people* with famous people from basel and*historic_events* with historic events in basel.

## metadata

| Field       | Description                        |
|-------------|------------------------------------|
| active      | Non-active datasets are not synced |
| has data sql      | query returning a value cnt. if cnt > 0 then check if is due check is present and matched. this is mainly for daily reports |
| publish conditions      | A query that returns 1 if the dataset is due for publication and 0 if not. Mainly used for daily insights to only publish when interesting data is available. IG for the extreme temperature insight, the inshgt is published, if the temperature exceeds the 95 percentile threshold, for air quality, the quality index parameter has to be 3 and greater (alert) etc.  |
| most recent sql      | for daily reports: on publish day, it is checked what the last day with data is. e.g. some datasets are not updated over the weekend, so the last day is friday. finding the last day allows to set this day as the reference point for the report. |
| title      | title of the dataset |



