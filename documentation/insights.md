Insights Documentation
======================

- [Monthly Reports](#markdown-mermaid)
  - [11 	Dog population in Basel](#markdown-mermaid)
    - [General](#markdown-mermaid)
    - [publish conditions](#markdown-mermaid)
    - [insight structre](#markdown-mermaid)
    - [description](#markdown-mermaid)
    - [system promt](#markdown-mermaid)
    - [user prompt](#markdown-mermaid)
    - [context data](#markdown-mermaid)
    - [tables](#markdown-mermaid)
    - [graphics](#markdown-mermaid)
    - [ideas](#markdown-mermaid)
      - [Maximum number of dogs and time series since 1970:](#markdown-mermaid)
    - [last verified](#markdown-mermaid)
- [Daily Reports](#markdown-mermaid)
  - [12 Extreme Temperature Report for Basel](#markdown-mermaid)
    - [publish conditions](#markdown-mermaid)
    - [insight strucktre](#markdown-mermaid)
    - [system promt](#markdown-mermaid)
    - [user prompt](#markdown-mermaid)
    - [description](#markdown-mermaid)
    - [context data](#markdown-mermaid)
    - [tables](#markdown-mermaid)
    - [graphics](#markdown-mermaid)
    - [ideas](#markdown-mermaid)
    - [last verified](#markdown-mermaid)
  - [id title](#markdown-mermaid)
    - [publish conditions](#markdown-mermaid)
    - [insight strucktre](#markdown-mermaid)
    - [system promt](#markdown-mermaid)
    - [user prompt](#markdown-mermaid)
    - [description](#markdown-mermaid)
    - [context data](#markdown-mermaid)
    - [tables](#markdown-mermaid)
    - [graphics](#markdown-mermaid)
    - [ideas](#markdown-mermaid)


# Monthly Reports

## 11 	Dog population in Basel

### General
uses datasets: 	
- 6: 100446
- 10: 100444
- 25: 100445

### publish conditions
Published yearly if data is available for past year. 

### insight structre
create title: yes
create lead: yes

### description
This analysis presents data on dog breeds and dog names in Basel. It highlights the most popular breeds and names for a given year and illustrates the trend in the number of registered dogs over time, including developments before and after the COVID-19 pandemic. The report is generated on January 10 every year.

### system promt
use general

### user prompt
You are an expert in dog demographics and long-term trends. You are provided with structured data for the reference period :reference_period, as well as data for the pre-COVID reference year (2019) and the earliest available year (2008). Based on this data, write a clear, insightful, and well-organized analysis.

Begin with a summary of the number of registered dogs in the reference period, including the total number as well as counts for male and female dogs. Identify the three most common dog breeds during this period. Then, list the three most popular names for male and female dogs. You are also given a list of newly registered dog names for the year; highlight a selection of unusual, humorous, or pop-culture-inspired names, such as those referencing TV shows, cartoons, or movies.

Discuss how the total number of dogs has evolved since 2008. Identify any clear upward or downward trends. If there is a noticeable increase in dog registrations around 2020–2021, suggest a possible link to the COVID-19 pandemic, such as increased demand for companionship during lockdowns.

### context data

0. General-info
0. numbers_last_year
0. top-five-breeds
0. oldest_dog_all_time
0. oldest-dog
0. numbers_2019
0. top-five-names
0. new_names_number
0. new_names_list

### tables

Top 10 Most Popular Dog Names in :reference_period_year

### graphics

Annual Number of Dogs in Basel by Sex

### ideas
Data is available for dogs by community, these could be integrated combining e.g. dogs per capita.

#### Maximum number of dogs and time series since 1970:
```
WITH base AS (
    SELECT jahr, sum(anzahl_hunde) AS total_dogs
    FROM opendata.ds_100445
	group by jahr
),
max_dogs as (
	select max(total_dogs) as number from base
)
SELECT b.jahr, b.total_dogs
FROM base b
JOIN max_dogs m ON m.number = b.total_dogs

SELECT jahr, sum(anzahl_hunde) AS total_dogs
    FROM opendata.ds_100445
	group by jahr
	order by jahr
```

### last verified
py manage.py generate_stories --id=11 --date=2023-01-01 --force
2025-10-4: added oldes dog age and breakdown by commune

# Daily Reports

## 12 Extreme Temperature Report for Basel

### publish conditions
Published daily, if temperature is above 95percentile for the month

### insight strucktre
create title: yes
create lead: yes

### system promt
auto

### user prompt
You are a weather expert. You publish an analysis on an exceptionally hot day exceeding the 95 percentile for the maximum temperature. You will be provided temperature and radiation data for :reference_period, together with comparison data for various periods: last 30 days, this season, year to date and all time. All measurements are recorded at the NBCN weather station in Binningen. Your task is to generate a clear and informative weather report based on this data.

Start by describing the min, max and average temperature of the day of interest. If the temperature_percentile_all_time is smaller than 99%, call it an unusually warm day; if it is higher than 99% call it an exceptionally hot day and mention the percentile value.

Then mention the statistics of the last 30 days, of the current season and finally of all years for this season. Mention the date and value for the hottest day for all years on this month and for all years and all months.

The input includes statistical summaries in the form of percentiles (e.g., p01 = 1st percentile, p25 = 25th percentile, ..., p99 = 99th percentile). For lay readers, convert these into plain language. For example: \"Only 1% of May mornings in the past were colder than this.

The dataset may contain several types of historical 
comparisons:

cmd_compare_this_month: summarizes values from previous days of the current month.\ncmd_compare_this_season: compares the measured values to all values recorded during the current season. You may say things like \"this was the coldest\" or \"this was the warmest day of the season.

ncmd_compare_month_2000: compares the daily value to historical data for the same month, covering all measurements since the year 2000.

cmd_compare_all_time: compares the daily value to all values measured in that month since the beginning of recorded observations.

A measured value exceeds historical extremes (e.g., minimum, maximum, or lies beyond the 1st or 99th percentile); this is considered significant and should be clearly emphasized in the report. Include the date of measurements in the report title.

### description

The **extreme temperature** analysis is triggered if the maximum temperature at the NBCN meteo station \*\*Binningen/Basel \*\* exceeds the 95 percentile or is below 5th percentile for the given month . This means that 95% of all maximum temperatures measured during the current month in the past were colder or warmer than the temperature of the day of interest. The temperature and sunshine duration values will then be compared to various historical periods.

The aim of the report is to **identify notable weather events (anomalies)** and compare them with historic data.

### context data
- General-Info
- general_stats_last_30days
- general_stats_this_year
- rank_this_year
- all_time_minimum_maximum_temperature
- top_5_hottest_month_days

### tables
- Top 5 Maximum Temperatures in :reference_period_month since 1865

### graphics
- Min, Max and Average Temperatures in :reference_period_month

### ideas
- add info whether heat wave info: if the current day is part of heatwave (>= 3 days above 25C (3 summer days)) also show this insight, if day is part of heatwave, even if < 95th percentile>
- create extreme low temperature report
- 

### last verified
2025-10-05
py manage.py generate_stories --id=12 --date=2023-07-25 --force

## 17 Daily Airtraffic at mulhouse airport

### publish conditions

### insight strucktre
create title: yes
create lead:

### system promt
### user prompt

### description

### context data

### tables

### graphics

### ideas

### last verified
2025-10-05: I now delete the last recrod if passengers are lower than 10000. it seems that often there are uncomplete records, which get eventually overwritten but you cannot tell when looking at the data.

py manage.py generate_stories --id=17 --date=2025-09-30 --force


---
## id title

### publish conditions

### insight strucktre
create title: yes
create lead:

### system promt
### user prompt

### description

### context data

### tables

### graphics

### ideas


