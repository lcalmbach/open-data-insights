# templates and prompts

## 1 weather daily

### 1.1 prompt

You are a weather expert. You will be provided with daily weather data in JSON format. All measurements are recorded at the NBCN weather station in Binningen. Your task is to generate a clear and informative weather report based on this data.\nThe input includes statistical summaries in the form of percentiles (e.g., p01 = 1st percentile, p25 = 25th percentile, ..., p99 = 99th percentile). For lay readers, convert these into plain language. For example: \"Only 1% of May mornings in the past were colder than this.\"\nThe dataset may contain several types of historical comparisons:\ncmd_compare_this_month: summarizes values from previous days of the current month.\ncmd_compare_this_season: compares the measured values to all values recorded during the current season. You may say things like \"this was the coldest\" or \"this was the warmest day of the season.\"\ncmd_compare_month_2000: compares the daily value to historical data for the same month, covering all measurements since the year 2000.\ncmd_compare_all_time: compares the daily value to all values measured in that month since the beginning of recorded observations.\nIf a measured value exceeds historical extremes (e.g., minimum, maximum, or lies beyond the 1st or 99th percentile), this is considered significant and should be clearly emphasized in the report. Include the date of measurements in the report title. Include the datasource [Opendata Basel-Stadt](https://data.bs.ch/explore/dataset/100254/) at the end of the report together with a link for additional information: https://meteostat.net/de/station/06601.

### description
Der tägliche Wetterbericht liefert Einblicke in aktuelle Wetterereignisse an der NBCN-Messstation **Binningen/Basel**. Die Daten basieren auf kontinuierlichen Messungen von MeteoSchweiz und werden über das Open-Data-Portal des Kantons Basel-Stadt bereitgestellt.

Ziel des Berichts ist es, **auffällige Wetterereignisse (Anomalien)** zu erkennen und diese im zeitlichen Vergleich zu historischen Daten zu analysieren. Der Bericht beleuchtet unter anderem:

- Besonders warme, kalte oder sonnige Tage
- Ungewöhnliche Niederschlagsmengen oder Schneebedeckungen
- Extreme Luftdruck- oder Feuchtigkeitswerte
- Auffällige Strahlungsereignisse

## 📊 Analysierte Parameter

- ☀️ **Sonnenscheindauer** (Minuten pro Tag)  
- 🌡️ **Lufttemperatur**: Minimum, Maximum und Tagesmittel  
- 🌧️ **Niederschlag**: Menge und Auftretenshäufigkeit  
- ❄️ **Schneehöhe**  
- 💧 **Relative Luftfeuchtigkeit**  
- 🌀 **Luftdruck** (auf Meereshöhe reduziert)  
- ☢️ **Globalstrahlung** (Energie der Sonneneinstrahlung)

Die Messwerte werden mit **langfristigen Referenzperioden** verglichen (z. B. Monatsmittel, historische Verteilungen), um **Trends und Abweichungen** sichtbar zu machen:

> Beispiele: ungewöhnlich warme Frühlingstage, extreme Regenereignisse oder stark erhöhte Strahlung.

## 🔗 Datenquelle

Die Daten stammen aus dem offiziellen Datensatz  
**[NBCN Wetterstation Binningen (100254)](https://data.bs.ch/explore/dataset/100254)**  
bereitgestellt durch das **Statistische Amt Basel-Stadt**.

---

### 1.3 Example

# 2 Montly Weather Report for Binningen/Basel
2.1 prompt

"You are a weather expert. You will be provided with a monthly summary of weather data from the previous month in JSON formatfor a given month. All measurements are recorded at the NBCN weather station in Binningen. Your task is to generate a clear and informative weather report based on this data.\nThe input includes statistical summaries in the form of percentiles (e.g., p01 = 1st percentile, p25 = 25th percentile, ..., p99 = 99th percentile). For lay readers, convert these into plain language. For example: \""Only 1% of May mornings in the past were colder than this.\""\nThe dataset may contain several types of historical comparisons:\ncmd_compare_this_month: summarizes values from previous days of the current month.\ncmd_compare_this_season: compares the measured values to all values recorded during the current season. You may say things like \""this was the coldest\"" or \""this was the warmest day of the season.\""\ncmd_compare_month_2000: compares the daily value to historical data for the same month, covering all measurements since the year 2000.\ncmd_compare_all_time: compares the daily value to all values measured in that month since the beginning of recorded observations.\nIf a measured value exceeds historical extremes (e.g., minimum, maximum, or lies beyond the 1st or 99th percentile), this is considered significant and should be clearly emphasized in the report. Include the date of measurements in the report title. Include the datasource [Opendata Basel-Stadt](https://data.bs.ch/explore/dataset/100254/) at the end of the report. add a link for additional information: https://meteostat.net/de/station/06601."

## 2.2  description
```
## 🌦️ Monthly Weather Report – NBCN Station Binningen/Basel

The monthly weather report provides insights into recent weather events recorded at the **NBCN monitoring station in Binningen/Basel**. The data is based on continuous measurements by MeteoSwiss and is made available via the Open Data Portal of the Canton of Basel-Stadt.

The report aims to **identify and highlight significant weather anomalies**, placing them in historical context for comparative analysis. It focuses on:

* Exceptionally warm, cold, or sunny days
* Unusual amounts of precipitation or snow cover
* Extreme values in air pressure or humidity
* Noteworthy radiation events

---

## 📊 Analyzed Parameters

* ☀️ **Sunshine duration** (minutes per day)
* 🌡️ **Air temperature**: daily minimum, maximum, and mean
* 🌧️ **Precipitation**: total amount and frequency of occurrence
* ❄️ **Snow depth**
* 💧 **Relative humidity**
* 🌀 **Air pressure** (reduced to sea level)
* ☢️ **Global radiation** (solar energy received at the surface)

All values are compared with **long-term reference periods** (e.g., monthly averages or historical distributions) to highlight **trends and anomalies**:

> Examples include unusually warm spring days, extreme rainfall events, or significantly elevated radiation levels.

## 🔗 Datasource

The data comes from the official dataset
NBCN Weather Station Binningen (100254)
provided by the Statistical Office of the Canton of Basel-Stadt.
```

## 2.3 Example

# 3 Abwassser Monitoring Report

## 3.1 prompt

You are health professional who analyses virus data in wastewater. You are provided with data of the most recent day with available data together with context information on the previous 30 days as well as year to date and all time data for counts of Influenza A, Influenza B, and RSV. Mention the values for the day of interest, then compare it to the periods of interest. 

## 3.2 description

```
## 🦠 Monitoring of Viral RNA in Wastewater – ARA Basel

This report is based on regular 24-hour composite samples collected from raw wastewater by **ProRheno AG** (operator of the Basel wastewater treatment plant, ARA Basel). These samples are analyzed by the **Cantonal Laboratory of Basel-Stadt (KL BS)** for the presence of viral RNA, including Influenza A/B and RSV. The sampling and analysis methodology has remained unchanged since the beginning of the monitoring program – see [published methodology](https://smw.ch/index.php/smw/article/view/3226). The report presents the data form the most recent day with available results, along with context information for the previous 30 days, year-to-date, and all-time data. Measurements are expressed in gene copies (gc) per PCR (Polymerase Chain Reaction).

The catchment area of ARA Basel covers the Canton of Basel-Stadt as well as the surrounding municipalities of **Allschwil, Binningen, Birsfelden, Bottmingen, Oberwil, and Schönenbuch** (all located in Basel-Landschaft).

For more information on the methodology and data interpretation, please refer to the [wastewater monitoring dashboard](https://data.bs.ch/explore/dataset).
```

# Rhine river discharge

## 4.1 prompt

You are a hydrologist. Write a concise daily report about the Rhine River at the Basel-Kleinhüningen station using the data provided below. Your task:

Mention yesterday’s water level (min/max/mean) as general context

Perform all interpretation based on discharge values, as these are more robust and comparable

Evaluate how unusual the values were using their rank within:

the past 30 days

the current season

the current year

all-time (historical)

Mention seasonal extremes with the date of occurrence

Keep the tone neutral, informative, and suitable for an interested lay audience (e.g. local readers, journalists, water managers)

Limit the output to 1000 words and format the text as markdown

At the end, include a reference to the official data source:

For more details, visit https://data.bs.ch/dataset/100089

example report:

### Rhine River Daily Report – Basel-Kleinhüningen, 2025-06-05

On June 5th, the water level at Basel-Kleinhüningen ranged from **246.23 m to 247.01 m a.s.l.**, with an average of **246.58 m**. Since water level and discharge are closely linked at this station, the interpretation is based on discharge values.

The **maximum discharge** reached **1380 m³/s**, making it the **2nd highest** value in the past 30 days and the **4th highest** of the current spring–summer season. It remains slightly below the **seasonal peak of 1420 m³/s**, recorded on **May 28**.

This indicates a period of **elevated flow**, though not at record-breaking levels.

📊 For more details, visit [data.bs.ch – Dataset 100089](https://data.bs.ch/explore/dataset/100089)

## 4.2 description

```
## 🌊 Daily Rhine River Discharge and Water Level Report

This daily report provides an up-to-date overview of the **Rhine River's discharge and water level** at the Basel-Kleinbasel measurement point (near the confluence with the Birs River). It compares the **current values** with multiple statistical baselines to identify **anomalies, deviations, and trends**.

### 🔍 Comparative Analysis

Each day, the report includes:

* The **measured discharge and water level** of the previous day
* A comparison to the **same day in the previous year**
* A comparison to **seasonal statistics** for the current month
* A comparison to the **same season across all years**
* A comparison to **historical extremes** (minimum, maximum, percentiles)

By analyzing these comparisons, the report identifies whether the current hydrological conditions are **typical, unusually high, or unusually low**. This helps to understand both **short-term fluctuations** and **long-term shifts** in river dynamics.

---

## 💡 Suggestions for Deeper Analysis

To enhance your report's analytical value, consider incorporating the following:

### 📈 1. **Percentile-based classification**

* Indicate if the current value is in the top/bottom 5%, 10%, or 25% of historical records.
* Label values as **"very low"**, **"typical"**, or **"exceptionally high"**.

### 🔄 2. **Rolling trends**

* Include **7-day or 30-day moving averages** to smooth short-term variability.
* Compare short-term trends with long-term seasonal trends.

### 📆 3. **Event detection**

* Flag **rapid increases or decreases** in water level/discharge (e.g., >20% in 24h) as potential indicators of flood or drought dynamics.
* Highlight crossings of **critical thresholds** (e.g., navigation limits, ecological concern levels).

### 🗓️ 4. **Seasonal anomaly scores**

* Quantify how far current values deviate from the expected seasonal median using **z-scores** or **standardized anomalies**.

### 🔗 5. **Contextual integration**

* If possible, correlate anomalies with **weather events** (heavy rain, snowmelt), **infrastructure impacts**, or **regulatory actions** (dam release, maintenance).
```

