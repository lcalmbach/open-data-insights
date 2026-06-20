# ODI Interactive Tool — Population Simulator

## Context

This document captures the architecture discussion and all code produced in the Claude chat session for integrating an interactive demographic simulation tool into the ODI (open-data-insights.org) platform.

---

## ODI Tech Stack

- **Backend:** Python / Django
- **Database:** PostgreSQL
- **Charts:** Apache ECharts (chosen over Altair/Plotly)
- **Story rendering:** Django templates, story content stored as HTML in DB
- **Existing pipeline:** `graphics_template` (SQL + settings) → `graphics` (generated HTML + data)

---

## Architecture: Interactive Tool System

### Concept

Reuse the existing ODI story pipeline without introducing new content types or template machinery. The pattern mirrors the existing `biases_and_fallacies` story: pre-written content is stored in a table and retrieved by the normal `story_context` mechanism. The only difference is that the content field happens to contain self-contained interactive JS rather than static text.

Everything runs client-side — no server round-trip during interaction.

### Schema

Both tables go in the `report_generator` schema — they are framework artefacts (authored code and configuration), not subject matter data. This mirrors `graphics_template` and `graphics`.

### Database Tables

#### `report_generator.simulation_template`
One row per simulation tool. Holds the authored text and the widget code template with parameter placeholders.

```sql
CREATE TABLE report_generator.simulation_template (
    id                  SERIAL PRIMARY KEY,
    title               TEXT NOT NULL,
    text                TEXT,           -- intro/article text (HTML)
    js_template         TEXT,           -- widget HTML+JS with {{ param_key }} placeholders
    description         TEXT,           -- internal note on what this tool does
    created_at          TIMESTAMPTZ DEFAULT NOW(),
    updated_at          TIMESTAMPTZ DEFAULT NOW()
);
```

#### `report_generator.simulation_parameter`
One row per initial parameter per template. Each parameter is resolved at generation time — either from a hardcoded constant or a SQL expression against the opendata schema.

Field notes:
- `parameter_name` matches the placeholder key used in `js_template`
- `value` is `NUMERIC` (not text) so constants are validated at insert time
- DB-level `CHECK` constraints enforce that constants always have a `value` and SQL parameters always have a `sql_expression`
- `sort_order` controls display order in the admin

```sql
CREATE TABLE report_generator.simulation_parameter (
    id               SERIAL PRIMARY KEY,
    simulation_id    INTEGER NOT NULL
                         REFERENCES report_generator.simulation_template(id)
                         ON DELETE CASCADE,
    parameter_name   VARCHAR(100) NOT NULL,
    description      TEXT,
    parameter_type   VARCHAR(10) NOT NULL
                         CHECK (parameter_type IN ('constant', 'sql')),
    value            NUMERIC,        -- used when parameter_type = 'constant'
    sql_expression   TEXT,           -- used when parameter_type = 'sql'
                                     -- must return a single scalar value
    sort_order       INTEGER DEFAULT 0,

    UNIQUE (simulation_id, parameter_name),

    CONSTRAINT chk_constant_has_value
        CHECK (parameter_type != 'constant' OR value IS NOT NULL),
    CONSTRAINT chk_sql_has_expression
        CHECK (parameter_type != 'sql' OR sql_expression IS NOT NULL)
);
```

#### `report_generator.simulation` (generated output)
Stores the resolved, ready-to-render HTML after parameter injection. Regenerated annually or on demand, analogous to the `graphics` table.

```sql
CREATE TABLE report_generator.simulation (
    id                  SERIAL PRIMARY KEY,
    simulation_id       INTEGER NOT NULL
                            REFERENCES report_generator.simulation_template(id)
                            ON DELETE CASCADE,
    html                TEXT,           -- fully resolved widget HTML, ready for |safe
    parameters_used     JSONB,          -- snapshot of resolved parameter values
    generated_at        TIMESTAMPTZ DEFAULT NOW()
);
```

### Django Models

```python
# report_generator/models.py

from django.db import models


class SimulationTemplate(models.Model):
    title           = models.TextField()
    text            = models.TextField(blank=True)
    js_template     = models.TextField(
        help_text="Widget HTML+JS. Use {{ param_key }} for parameter placeholders."
    )
    description     = models.TextField(blank=True)
    created_at      = models.DateTimeField(auto_now_add=True)
    updated_at      = models.DateTimeField(auto_now=True)

    class Meta:
        db_table = '"report_generator"."simulation_template"'
        ordering = ['title']

    def __str__(self):
        return self.title


class SimulationParameter(models.Model):

    PARAMETER_TYPE_CHOICES = [
        ('constant', 'Constant'),
        ('sql',      'SQL Expression'),
    ]

    simulation       = models.ForeignKey(
        SimulationTemplate,
        on_delete=models.CASCADE,
        related_name='parameters'
    )
    parameter_name   = models.CharField(max_length=100)
    description      = models.TextField(blank=True)
    parameter_type   = models.CharField(max_length=10, choices=PARAMETER_TYPE_CHOICES)
    value            = models.DecimalField(
        max_digits=20, decimal_places=6,
        null=True, blank=True,
        help_text="Used when parameter_type is 'constant'."
    )
    sql_expression   = models.TextField(
        blank=True,
        help_text="Must return a single scalar. Used when parameter_type is 'sql'."
    )
    sort_order       = models.IntegerField(default=0)

    class Meta:
        db_table        = '"report_generator"."simulation_parameter"'
        ordering        = ['sort_order', 'parameter_name']
        unique_together = [('simulation', 'parameter_name')]

    def __str__(self):
        return f"{self.simulation.title} / {self.parameter_name}"

    def clean(self):
        from django.core.exceptions import ValidationError
        if self.parameter_type == 'constant' and self.value is None:
            raise ValidationError("A constant parameter requires a value.")
        if self.parameter_type == 'sql' and not self.sql_expression:
            raise ValidationError("A SQL parameter requires a sql_expression.")

    def resolve(self, cursor) -> float:
        """Resolve this parameter to a float value.
        Pass an open Django database cursor."""
        if self.parameter_type == 'constant':
            return float(self.value)
        cursor.execute(self.sql_expression)
        row = cursor.fetchone()
        if row is None:
            raise ValueError(
                f"SQL for parameter '{self.parameter_name}' returned no rows."
            )
        return float(row[0])


class Simulation(models.Model):
    simulation_template = models.ForeignKey(
        SimulationTemplate,
        on_delete=models.CASCADE,
        related_name='generated'
    )
    html                = models.TextField()
    parameters_used     = models.JSONField(default=dict)
    generated_at        = models.DateTimeField(auto_now_add=True)

    class Meta:
        db_table = '"report_generator"."simulation"'
        ordering = ['-generated_at']
        get_latest_by = 'generated_at'

    def __str__(self):
        return f"{self.simulation_template.title} ({self.generated_at:%Y-%m-%d})"
```

### Generation Logic

Called annually (or on demand) to resolve all parameters and render the widget HTML:

```python
# report_generator/services.py

from django.db import connection
from .models import SimulationTemplate, Simulation


def generate_simulation(simulation_id: int) -> Simulation:
    """
    Resolve all parameters for a SimulationTemplate, inject them into
    the js_template, and store the result as a new Simulation row.
    """
    template = SimulationTemplate.objects.get(pk=simulation_id)

    resolved = {}
    with connection.cursor() as cursor:
        for param in template.parameters.order_by('sort_order'):
            resolved[param.parameter_name] = param.resolve(cursor)

    # Inject resolved values as a JS const block prepended to the template
    js_baseline = "const BASELINE = " + _to_js_object(resolved) + ";\n"
    html = js_baseline + template.js_template

    sim = Simulation.objects.create(
        simulation_template=template,
        html=html,
        parameters_used=resolved,
    )
    return sim


def _to_js_object(d: dict) -> str:
    """Serialize a flat dict of floats to a JS object literal."""
    import json
    return json.dumps(d)
```

The widget JS then reads from `BASELINE` instead of hardcoded constants:

```javascript
// In js_template — replaces hardcoded constants
const INIT_POP           = BASELINE.init_pop;
const INIT_FOREIGN_SHARE = BASELINE.init_foreign_share;
const DEFAULT_TFR_SWISS  = BASELINE.default_tfr_swiss;
const DEFAULT_TFR_FOREIGN = BASELINE.default_tfr_foreign;
const DEFAULT_LE         = BASELINE.default_le;
const DEFAULT_IMM        = BASELINE.default_imm;
const DEFAULT_EMI        = BASELINE.default_emi;
```

### Example Parameter Rows

For the demographics simulator, `simulation_parameter` would contain:

| parameter_name | parameter_type | value | sql_expression |
|---|---|---|---|
| `init_pop` | `sql` | — | `SELECT SUM(bevoelkerung) FROM opendata.ds_bevoelkerung WHERE jahr = (SELECT MAX(jahr) FROM opendata.ds_bevoelkerung)` |
| `init_foreign_share` | `sql` | — | `SELECT ROUND(SUM(bevoelkerung) FILTER (WHERE staatsangehoerigkeit = 'A') / SUM(bevoelkerung)::numeric, 4) FROM opendata.ds_bevoelkerung WHERE jahr = (SELECT MAX(jahr) FROM opendata.ds_bevoelkerung)` |
| `default_tfr_swiss` | `constant` | `1.20` | — |
| `default_tfr_foreign` | `constant` | `2.00` | — |
| `default_le` | `constant` | `83.8` | — |
| `default_imm` | `constant` | `12500` | — |
| `default_emi` | `constant` | `10500` | — |

The SQL statements query the actual table names from your opendata schema — adjust to match your real dataset identifiers on `data.bs.ch`.

### Story Wiring

The `story_context` query retrieves the most recently generated output:

```sql
SELECT
    st.title,
    st.text,
    s.html
FROM report_generator.simulation_template st
JOIN report_generator.simulation s
    ON s.simulation_template_id = st.id
    AND s.generated_at = (
        SELECT MAX(generated_at)
        FROM report_generator.simulation
        WHERE simulation_template_id = st.id
    )
WHERE st.id = {{ filter_value }}
```

No new template tags, no new content category, no new Django views. The `html` field is output with `|safe` exactly as graphics and tables already are.

### Adding More Tools

Each new simulation is a new `SimulationTemplate` row with its own `SimulationParameter` rows. A new story focus pointing at the template `id` is all that's needed to publish it.

---

## Tools Roadmap

| Tool | Model | Key Parameters |
|---|---|---|
| Population simulator | Leslie matrix | TFR, life expectancy, immigration, emigration |
| EV share evolution | Bass diffusion S-curve | Fleet size, adoption rate, policy incentives, charging growth |
| Energy consumption | Building stock efficiency curve | Renovation rate, heat pump adoption, population growth |
| Dependency ratio | Derived from population sim | (feeds from demographic tool) |
| Housing demand | Household size × population | Household size trend, vacancy rate |

Note: some tools **compose** — the demographic simulator's output feeds housing demand and energy consumption. This is a powerful story-telling device.

---

## Simulation Model: Leslie Matrix

The population simulator uses an **age-structured Leslie matrix** model. At each annual time step:

1. **Survival:** each cohort ages one year, individuals survive according to an age-specific survival probability derived from life expectancy
2. **Fertility:** fertile-age cohorts (15–49) produce births via a Gaussian-shaped age-specific fertility schedule scaled to the TFR
3. **Migration:** net migration distributed across age groups with a working-age skew (20–40 peak)
4. **Naturalisation:** ~1% of foreign population becomes Swiss per year

### Basel-Stadt 2023 Baseline

Source: Statistisches Amt Basel-Stadt (StatA)

| Indicator | Value |
|---|---|
| Total population | 206'308 |
| Birth surplus | −255 (more deaths than births) |
| Net migration | +2'000/year |
| Life expectancy | 83.8 years |
| Foreign share | ~37% |
| Swiss TFR (approx.) | 1.20 |
| Foreign-born TFR (approx.) | 2.00 |

StatA middle scenario projects ~225'000 residents by 2045.

---

## Code: Population Projection Curve (ECharts)

Full standalone HTML widget. Uses ECharts instead of Chart.js to match ODI stack.

```html
<style>
@import url('https://fonts.googleapis.com/css2?family=DM+Serif+Display&family=DM+Sans:wght@300;400;500&display=swap');
*{box-sizing:border-box;margin:0;padding:0;}
.sim{font-family:'DM Sans',sans-serif;color:var(--color-text-primary);padding:1.5rem 0;}
.sim h1{font-family:'DM Serif Display',serif;font-size:1.6rem;font-weight:400;line-height:1.2;margin-bottom:.25rem;}
.subtitle{font-size:.8rem;color:var(--color-text-secondary);margin-bottom:1.5rem;letter-spacing:.04em;text-transform:uppercase;}
.baseline-bar{display:grid;grid-template-columns:repeat(4,1fr);gap:10px;margin-bottom:1.5rem;}
.b-card{background:var(--color-background-secondary);border-radius:8px;padding:.75rem 1rem;}
.b-label{font-size:11px;color:var(--color-text-secondary);text-transform:uppercase;letter-spacing:.05em;margin-bottom:4px;}
.b-val{font-size:1.2rem;font-weight:500;}
.b-note{font-size:10px;color:var(--color-text-tertiary);margin-top:2px;}
.panels{display:grid;grid-template-columns:220px 1fr;gap:1.5rem;align-items:start;}
.controls{display:flex;flex-direction:column;gap:1rem;}
.ctrl-group{background:var(--color-background-secondary);border-radius:10px;padding:1rem;}
.ctrl-group-title{font-size:10px;text-transform:uppercase;letter-spacing:.07em;color:var(--color-text-secondary);margin-bottom:.75rem;font-weight:500;}
.ctrl{margin-bottom:.6rem;}
.ctrl:last-child{margin-bottom:0;}
.ctrl-header{display:flex;justify-content:space-between;align-items:baseline;margin-bottom:4px;}
.ctrl-label{font-size:12px;color:var(--color-text-secondary);}
.ctrl-val{font-size:12px;font-weight:500;}
input[type=range]{width:100%;cursor:pointer;}
.scenario-btns{display:flex;gap:6px;margin-bottom:1rem;flex-wrap:wrap;}
.scen-btn{font-family:'DM Sans',sans-serif;font-size:11px;padding:4px 10px;border:0.5px solid var(--color-border-secondary);border-radius:20px;background:transparent;color:var(--color-text-secondary);cursor:pointer;}
.scen-btn:hover,.scen-btn.active{background:var(--color-text-primary);color:var(--color-background-primary);border-color:var(--color-text-primary);}
.outcome-bar{display:grid;grid-template-columns:repeat(3,1fr);gap:8px;margin-top:1rem;}
.o-card{border-radius:8px;padding:.75rem;text-align:center;}
.o-card.grow{background:rgba(29,158,117,.12);border:0.5px solid rgba(29,158,117,.3);}
.o-card.shrink{background:rgba(226,75,74,.1);border:0.5px solid rgba(226,75,74,.3);}
.o-card.neutral{background:var(--color-background-secondary);border:0.5px solid var(--color-border-tertiary);}
.o-label{font-size:10px;text-transform:uppercase;letter-spacing:.05em;color:var(--color-text-secondary);margin-bottom:4px;}
.o-val{font-size:1.1rem;font-weight:500;}
.o-subval{font-size:11px;color:var(--color-text-secondary);margin-top:2px;}
</style>

<div class="sim">
  <h1>Bevölkerungsentwicklung Basel-Stadt</h1>
  <div class="subtitle">Interaktiver Simulator · Basisjahr 2023 · Projektion 50 Jahre</div>

  <div class="baseline-bar">
    <div class="b-card"><div class="b-label">Einwohner 2023</div><div class="b-val">206'308</div><div class="b-note">Quelle: StatA BS</div></div>
    <div class="b-card"><div class="b-label">Geburtenüberschuss</div><div class="b-val" style="color:#e24b4a;">−255</div><div class="b-note">mehr Todesfälle als Geburten</div></div>
    <div class="b-card"><div class="b-label">Wanderungssaldo</div><div class="b-val" style="color:#1D9E75;">+2'000</div><div class="b-note">Nettomigration p.a.</div></div>
    <div class="b-card"><div class="b-label">Lebenserwartung</div><div class="b-val">83.8 J.</div><div class="b-note">Schweizer Durchschnitt</div></div>
  </div>

  <div class="scenario-btns">
    <button class="scen-btn active" onclick="applyScenario('status_quo',this)">Status quo</button>
    <button class="scen-btn" onclick="applyScenario('high_migration',this)">Hohe Zuwanderung</button>
    <button class="scen-btn" onclick="applyScenario('low_migration',this)">Tiefe Zuwanderung</button>
    <button class="scen-btn" onclick="applyScenario('baby_boom',this)">Baby-Boom</button>
    <button class="scen-btn" onclick="applyScenario('aging_city',this)">Schrumpfende Stadt</button>
  </div>

  <div class="panels">
    <div class="controls">
      <div class="ctrl-group">
        <div class="ctrl-group-title">Natürliche Bevölkerungsbewegung</div>
        <div class="ctrl">
          <div class="ctrl-header"><span class="ctrl-label">Gesamtfertilitätsrate (TFR)</span><span class="ctrl-val" id="tfr-out">1.45</span></div>
          <input type="range" id="tfr" min="0.8" max="4.0" step="0.05" value="1.45">
        </div>
        <div class="ctrl">
          <div class="ctrl-header"><span class="ctrl-label">Lebenserwartung (Jahre)</span><span class="ctrl-val" id="le-out">83.8</span></div>
          <input type="range" id="le" min="60" max="100" step="0.5" value="83.8">
        </div>
      </div>
      <div class="ctrl-group">
        <div class="ctrl-group-title">Migration</div>
        <div class="ctrl">
          <div class="ctrl-header"><span class="ctrl-label">Zuzüge pro Jahr</span><span class="ctrl-val" id="imm-out">12'500</span></div>
          <input type="range" id="imm" min="0" max="30000" step="500" value="12500">
        </div>
        <div class="ctrl">
          <div class="ctrl-header"><span class="ctrl-label">Wegzüge pro Jahr</span><span class="ctrl-val" id="emi-out">10'500</span></div>
          <input type="range" id="emi" min="0" max="30000" step="500" value="10500">
        </div>
      </div>
    </div>

    <div>
      <div id="echart" style="width:100%;height:300px;"></div>
      <div class="outcome-bar" id="outcomes"></div>
    </div>
  </div>
</div>

<script src="https://cdnjs.cloudflare.com/ajax/libs/echarts/5.4.3/echarts.min.js"></script>
<script>
const INIT_POP = 206308;
const BASE_YEAR = 2023;
const YEARS = 50;
const AGE_GROUPS = 101;

const SCENARIOS = {
  status_quo:    {tfr:1.45, le:83.8, imm:12500, emi:10500},
  high_migration:{tfr:1.45, le:83.8, imm:20000, emi:10500},
  low_migration: {tfr:1.45, le:83.8, imm:7000,  emi:10500},
  baby_boom:     {tfr:2.5,  le:83.8, imm:12500, emi:10500},
  aging_city:    {tfr:1.2,  le:83.8, imm:7000,  emi:14000},
};

function makeSurvival(le) {
  const s = new Array(AGE_GROUPS).fill(0);
  for (let a = 0; a < AGE_GROUPS - 1; a++) {
    const q = 0.0005 * Math.exp(0.08 * a);
    const adj = Math.max(0, (a - le * 0.7)) / 15;
    s[a] = Math.min(0.999, Math.max(0.001, Math.exp(-(q + adj*adj*0.05))));
  }
  s[AGE_GROUPS-1] = 0;
  return s;
}

function makeFertility(tfr) {
  const f = new Array(AGE_GROUPS).fill(0);
  const mu = 30, sigma = 6;
  let tot = 0;
  for (let a = 15; a <= 49; a++) { f[a] = Math.exp(-0.5*Math.pow((a-mu)/sigma,2)); tot += f[a]; }
  const scale = tfr / (tot * 2);
  for (let a = 15; a <= 49; a++) f[a] *= scale;
  return f;
}

function initPop(total) {
  const raw = [3.8,3.8,3.9,3.9,3.8,3.7,3.6,3.6,3.5,3.5,3.5,3.6,3.6,3.6,3.7,4.0,4.2,4.5,4.8,5.0,5.5,5.8,5.8,5.6,5.4,5.2,5.0,5.0,5.0,5.0,5.2,5.5,5.8,6.0,6.2,6.5,6.8,7.0,7.0,6.8,6.5,6.2,6.0,5.8,5.5,5.2,5.0,4.8,4.5,4.2,4.0,3.8,3.6,3.5,3.4,3.5,3.6,3.7,3.8,3.8,3.5,3.2,3.0,2.8,2.6,2.4,2.2,2.0,1.9,1.8,1.7,1.6,1.5,1.4,1.3,1.2,1.1,1.0,0.9,0.8,0.7,0.6,0.5,0.4,0.35,0.3,0.25,0.2,0.15,0.1,0.08,0.06,0.04,0.03,0.02,0.015,0.01,0.008,0.005,0.003,0.001];
  const tot = raw.reduce((s,v)=>s+v,0);
  return raw.map(v => v/tot*total);
}

function migrationByAge(net) {
  const w = new Array(AGE_GROUPS).fill(0);
  for (let a = 0; a < AGE_GROUPS; a++) {
    if (a<5) w[a]=0.6; else if (a<15) w[a]=0.4;
    else if (a<40) w[a]=1.5-Math.abs(a-28)/30;
    else if (a<65) w[a]=0.3; else w[a]=0.1;
  }
  const ws = w.reduce((s,v)=>s+v,0);
  return w.map(v => net*v/ws);
}

function project(tfr, le, imm, emi) {
  const survival = makeSurvival(le);
  const fertility = makeFertility(tfr);
  const netMigAge = migrationByAge(imm - emi);
  let pop = initPop(INIT_POP);
  const totalSeries=[pop.reduce((s,v)=>s+v,0)];
  const naturalSeries=[0], migrationSeries=[0];
  for (let y=0; y<YEARS; y++) {
    const newPop = new Array(AGE_GROUPS).fill(0);
    let births = 0;
    for (let a=15; a<=49; a++) births += fertility[a]*pop[a];
    newPop[0] = births;
    for (let a=1; a<AGE_GROUPS; a++) newPop[a] = pop[a-1]*survival[a-1];
    const prevTotal = pop.reduce((s,v)=>s+v,0);
    const naturalChange = newPop.reduce((s,v)=>s+v,0) - prevTotal;
    for (let a=0; a<AGE_GROUPS; a++) newPop[a] = Math.max(0, newPop[a]+netMigAge[a]);
    pop = newPop;
    totalSeries.push(pop.reduce((s,v)=>s+v,0));
    naturalSeries.push(Math.round(naturalChange));
    migrationSeries.push(imm-emi);
  }
  return {totalSeries, naturalSeries, migrationSeries};
}

function fmt(n) { return Math.round(n).toLocaleString('de-CH'); }
function fmtSign(n) { const r=Math.round(n); return (r>=0?'+':'')+r.toLocaleString('de-CH'); }

const labels = Array.from({length:YEARS+1}, (_,i) => BASE_YEAR+i);
const isDark = window.matchMedia('(prefers-color-scheme: dark)').matches;
const textColor = isDark ? '#aaa' : '#666';
const gridColor = isDark ? 'rgba(255,255,255,0.06)' : 'rgba(0,0,0,0.06)';

const myChart = echarts.init(document.getElementById('echart'), null, {renderer:'svg'});

myChart.setOption({
  animation: false,
  grid: {left:64, right:72, top:16, bottom:36},
  tooltip: {
    trigger:'axis', axisPointer:{type:'line'},
    formatter(params) {
      const year = params[0].axisValue;
      let s = `<div style="font-size:12px;font-weight:500;margin-bottom:4px">${year}</div>`;
      params.forEach(p => {
        const v = p.seriesIndex===0 ? fmt(p.value) : fmtSign(p.value);
        s += `<div style="display:flex;gap:8px;align-items:center;font-size:11px">
          <span style="display:inline-block;width:8px;height:8px;border-radius:50%;background:${p.color}"></span>
          <span style="flex:1">${p.seriesName}</span>
          <span style="font-weight:500">${v}</span></div>`;
      });
      return s;
    }
  },
  xAxis: {type:'category', data:labels, axisLine:{lineStyle:{color:gridColor}}, axisTick:{show:false}, axisLabel:{color:textColor,fontSize:11,interval:9}},
  yAxis: [
    {type:'value', name:'Einwohner', nameTextStyle:{color:textColor,fontSize:11}, axisLabel:{color:textColor,fontSize:11,formatter:v=>fmt(v)}, splitLine:{lineStyle:{color:gridColor}}, axisLine:{show:false}, axisTick:{show:false}},
    {type:'value', name:'Veränderung/Jahr', nameTextStyle:{color:textColor,fontSize:11}, axisLabel:{color:textColor,fontSize:11,formatter:v=>fmtSign(v)}, splitLine:{show:false}, axisLine:{show:false}, axisTick:{show:false}, position:'right'}
  ],
  series: [
    {name:'Bevölkerung', type:'line', yAxisIndex:0, smooth:true, symbol:'none', lineStyle:{color:'#378ADD',width:2.5}, areaStyle:{color:{type:'linear',x:0,y:0,x2:0,y2:1,colorStops:[{offset:0,color:'rgba(55,138,221,.15)'},{offset:1,color:'rgba(55,138,221,.01)'}]}}, data:[]},
    {name:'Natürliches Wachstum', type:'line', yAxisIndex:1, smooth:true, symbol:'none', lineStyle:{color:'#1D9E75',width:1.5,type:'dashed'}, data:[]},
    {name:'Nettomigration', type:'line', yAxisIndex:1, smooth:true, symbol:'none', lineStyle:{color:'#D85A30',width:1.5,type:'dotted'}, data:[]},
  ]
});

function run() {
  const tfr = parseFloat(document.getElementById('tfr').value);
  const le  = parseFloat(document.getElementById('le').value);
  const imm = parseInt(document.getElementById('imm').value);
  const emi = parseInt(document.getElementById('emi').value);
  document.getElementById('tfr-out').textContent = tfr.toFixed(2);
  document.getElementById('le-out').textContent  = le.toFixed(1);
  document.getElementById('imm-out').textContent = imm.toLocaleString('de-CH');
  document.getElementById('emi-out').textContent = emi.toLocaleString('de-CH');
  const {totalSeries, naturalSeries, migrationSeries} = project(tfr, le, imm, emi);
  myChart.setOption({series:[
    {data: totalSeries},
    {data: [null,...naturalSeries.slice(1)]},
    {data: [null,...migrationSeries.slice(1)]},
  ]});
  const final = totalSeries[YEARS];
  const change = final - INIT_POP;
  const pct = change/INIT_POP*100;
  const annRate = (Math.pow(final/INIT_POP, 1/YEARS)-1)*100;
  const netMigTotal = (imm-emi)*YEARS;
  const cl = Math.abs(pct)<2?'neutral':(change>0?'grow':'shrink');
  document.getElementById('outcomes').innerHTML = `
    <div class="o-card ${cl}">
      <div class="o-label">Bevölkerung 2073</div>
      <div class="o-val">${fmt(final)}</div>
      <div class="o-subval">${fmtSign(Math.round(change))} (${pct>=0?'+':''}${pct.toFixed(1)}%)</div>
    </div>
    <div class="o-card ${annRate>0?'grow':annRate<-0.1?'shrink':'neutral'}">
      <div class="o-label">Jährl. Wachstumsrate</div>
      <div class="o-val">${annRate>=0?'+':''}${annRate.toFixed(2)}%</div>
      <div class="o-subval">⌀ pro Jahr</div>
    </div>
    <div class="o-card ${(imm-emi)>0?'grow':(imm-emi)<0?'shrink':'neutral'}">
      <div class="o-label">Nettomigration kum.</div>
      <div class="o-val">${fmtSign(netMigTotal)}</div>
      <div class="o-subval">über 50 Jahre</div>
    </div>`;
}

function applyScenario(key, btn) {
  document.querySelectorAll('.scen-btn').forEach(b=>b.classList.remove('active'));
  btn.classList.add('active');
  const s = SCENARIOS[key];
  document.getElementById('tfr').value = s.tfr;
  document.getElementById('le').value  = s.le;
  document.getElementById('imm').value = s.imm;
  document.getElementById('emi').value = s.emi;
  run();
}

document.querySelectorAll('input[type=range]').forEach(el=>el.addEventListener('input',()=>{
  document.querySelectorAll('.scen-btn').forEach(b=>b.classList.remove('active'));
  run();
}));
run();
</script>
```

---

## Code: Animated Population Pyramid with Swiss/Foreign Split (ECharts)

Key design decisions:
- **Two independent grids** (left = male, right = female) with mirrored x-axes — this is the only reliable way to get perfect row alignment in ECharts for a butterfly chart
- Left x-axis is `inverse: true` so bars grow outward from centre
- **Four series:** Swiss male, Foreign male, Swiss female, Foreign female — stacked within each side
- Age groups aggregated to 5-year cohorts (standard demographic convention)
- Animation at 130ms/frame via `setInterval`; year slider for manual scrubbing
- Naturalisation modelled at ~1%/year (foreign → Swiss)
- Foreign-born age distribution skewed toward working age (20–40)

```html
<style>
@import url('https://fonts.googleapis.com/css2?family=DM+Serif+Display&family=DM+Sans:wght@300;400;500&display=swap');
*{box-sizing:border-box;margin:0;padding:0;}
.wrap{font-family:'DM Sans',sans-serif;color:var(--color-text-primary);padding:1.5rem 0;}
h1{font-family:'DM Serif Display',serif;font-size:1.6rem;font-weight:400;line-height:1.2;margin-bottom:.25rem;}
.subtitle{font-size:.8rem;color:var(--color-text-secondary);margin-bottom:1.25rem;letter-spacing:.04em;text-transform:uppercase;}
.scenario-btns{display:flex;gap:6px;margin-bottom:1rem;flex-wrap:wrap;}
.scen-btn{font-family:'DM Sans',sans-serif;font-size:11px;padding:4px 10px;border:0.5px solid var(--color-border-secondary);border-radius:20px;background:transparent;color:var(--color-text-secondary);cursor:pointer;}
.scen-btn:hover,.scen-btn.active{background:var(--color-text-primary);color:var(--color-background-primary);border-color:var(--color-text-primary);}
.layout{display:grid;grid-template-columns:220px 1fr;gap:1.5rem;align-items:start;}
.ctrl-group{background:var(--color-background-secondary);border-radius:10px;padding:1rem;margin-bottom:1rem;}
.ctrl-group:last-child{margin-bottom:0;}
.cgt{font-size:10px;text-transform:uppercase;letter-spacing:.07em;color:var(--color-text-secondary);margin-bottom:.75rem;font-weight:500;}
.ctrl{margin-bottom:.55rem;}.ctrl:last-child{margin-bottom:0;}
.ctrl-header{display:flex;justify-content:space-between;margin-bottom:3px;}
.ctrl-label{font-size:11px;color:var(--color-text-secondary);}
.ctrl-val{font-size:11px;font-weight:500;}
input[type=range]{width:100%;cursor:pointer;}
.swiss-accent{color:#378ADD;}.foreign-accent{color:#D85A30;}
.playbar{display:flex;align-items:center;gap:8px;margin-top:.5rem;}
.play-btn{font-family:'DM Sans',sans-serif;font-size:11px;padding:4px 12px;border:0.5px solid var(--color-border-secondary);border-radius:20px;background:transparent;color:var(--color-text-primary);cursor:pointer;}
.play-btn:hover{background:var(--color-background-secondary);}
.year-display{font-family:'DM Serif Display',serif;font-size:1.8rem;text-align:right;}
.year-sub{font-size:10px;color:var(--color-text-secondary);text-align:right;margin-top:-3px;}
.stat-row{display:grid;grid-template-columns:repeat(4,1fr);gap:7px;margin-top:.75rem;}
.s-card{background:var(--color-background-secondary);border-radius:8px;padding:.55rem .7rem;}
.s-label{font-size:10px;color:var(--color-text-secondary);text-transform:uppercase;letter-spacing:.03em;margin-bottom:2px;}
.s-val{font-size:.95rem;font-weight:500;}
.legend{display:flex;gap:14px;font-size:11px;color:var(--color-text-secondary);margin-top:.5rem;flex-wrap:wrap;}
.leg-box{width:10px;height:10px;border-radius:2px;display:inline-block;margin-right:3px;vertical-align:middle;}
</style>

<div class="wrap">
  <h1>Alterspyramide Basel-Stadt</h1>
  <div class="subtitle">Schweizer &amp; Ausländische Bevölkerung · Projektion 2023–2073</div>
  <div class="scenario-btns">
    <button class="scen-btn active" onclick="applyScenario('status_quo',this)">Status quo</button>
    <button class="scen-btn" onclick="applyScenario('high_migration',this)">Hohe Zuwanderung</button>
    <button class="scen-btn" onclick="applyScenario('low_migration',this)">Tiefe Zuwanderung</button>
    <button class="scen-btn" onclick="applyScenario('baby_boom',this)">Baby-Boom</button>
    <button class="scen-btn" onclick="applyScenario('aging_city',this)">Schrumpfende Stadt</button>
  </div>
  <div class="layout">
    <div>
      <div class="ctrl-group">
        <div class="cgt">Schweizer Bevölkerung</div>
        <div class="ctrl">
          <div class="ctrl-header"><span class="ctrl-label">TFR Schweizer</span><span class="ctrl-val swiss-accent" id="tfr-ch-out">1.20</span></div>
          <input type="range" id="tfr-ch" min="0.8" max="4.0" step="0.05" value="1.20">
        </div>
        <div class="ctrl">
          <div class="ctrl-header"><span class="ctrl-label">Lebenserwartung (J.)</span><span class="ctrl-val swiss-accent" id="le-out">83.8</span></div>
          <input type="range" id="le" min="60" max="100" step="0.5" value="83.8">
        </div>
      </div>
      <div class="ctrl-group">
        <div class="cgt">Ausländische Bevölkerung</div>
        <div class="ctrl">
          <div class="ctrl-header"><span class="ctrl-label">TFR Ausländer</span><span class="ctrl-val foreign-accent" id="tfr-f-out">2.00</span></div>
          <input type="range" id="tfr-f" min="0.8" max="4.0" step="0.05" value="2.00">
        </div>
        <div class="ctrl">
          <div class="ctrl-header"><span class="ctrl-label">Zuzüge pro Jahr</span><span class="ctrl-val foreign-accent" id="imm-out">12'500</span></div>
          <input type="range" id="imm" min="0" max="30000" step="500" value="12500">
        </div>
        <div class="ctrl">
          <div class="ctrl-header"><span class="ctrl-label">Wegzüge pro Jahr</span><span class="ctrl-val foreign-accent" id="emi-out">10'500</span></div>
          <input type="range" id="emi" min="0" max="30000" step="500" value="10500">
        </div>
      </div>
      <div class="ctrl-group">
        <div class="cgt">Animation</div>
        <div class="playbar">
          <button class="play-btn" id="play-btn" onclick="togglePlay()">▶ Play</button>
          <input type="range" id="year-slider" min="0" max="50" step="1" value="0" style="flex:1">
        </div>
        <div style="margin-top:.6rem;">
          <div class="year-display" id="year-label">2023</div>
          <div class="year-sub">Jahr der Projektion</div>
        </div>
      </div>
    </div>
    <div>
      <div id="pyramid" style="width:100%;height:430px;"></div>
      <div class="legend">
        <span><span class="leg-box" style="background:#378ADD"></span>Schweizer Männer</span>
        <span><span class="leg-box" style="background:#7ab8e8"></span>Ausländer Männer</span>
        <span><span class="leg-box" style="background:#D85A30"></span>Schweizer Frauen</span>
        <span><span class="leg-box" style="background:#e89a7a"></span>Ausländerinnen Frauen</span>
      </div>
      <div class="stat-row" id="stats"></div>
    </div>
  </div>
</div>

<script src="https://cdnjs.cloudflare.com/ajax/libs/echarts/5.4.3/echarts.min.js"></script>
<script>
const INIT_POP=206308,INIT_FOREIGN_SHARE=0.37,BASE_YEAR=2023,YEARS=50,AG=101;
const AGE_LABELS=Array.from({length:21},(_,i)=>i===20?'100+':String(i*5)+'–'+(i*5+4));

const SCENARIOS={
  status_quo:    {tfrCh:1.20,tfrF:2.00,le:83.8,imm:12500,emi:10500},
  high_migration:{tfrCh:1.20,tfrF:2.00,le:83.8,imm:20000,emi:10500},
  low_migration: {tfrCh:1.20,tfrF:2.00,le:83.8,imm:7000, emi:10500},
  baby_boom:     {tfrCh:2.0, tfrF:2.80,le:83.8,imm:12500,emi:10500},
  aging_city:    {tfrCh:1.0, tfrF:1.50,le:83.8,imm:7000, emi:14000},
};

function makeSurvival(le){
  const s=new Array(AG).fill(0);
  for(let a=0;a<AG-1;a++){
    const q=0.0005*Math.exp(0.08*a);
    const adj=Math.max(0,(a-le*0.7))/15;
    s[a]=Math.min(0.999,Math.max(0.001,Math.exp(-(q+adj*adj*0.05))));
  }
  s[AG-1]=0;return s;
}
function makeFertility(tfr){
  const f=new Array(AG).fill(0);
  const mu=30,sigma=6;let tot=0;
  for(let a=15;a<=49;a++){f[a]=Math.exp(-0.5*Math.pow((a-mu)/sigma,2));tot+=f[a];}
  const sc=tfr/(tot*2);for(let a=15;a<=49;a++)f[a]*=sc;
  return f;
}
function initPop(total,fShare){
  const raw=[3.8,3.8,3.9,3.9,3.8,3.7,3.6,3.6,3.5,3.5,3.5,3.6,3.6,3.6,3.7,4.0,4.2,4.5,4.8,5.0,5.5,5.8,5.8,5.6,5.4,5.2,5.0,5.0,5.0,5.0,5.2,5.5,5.8,6.0,6.2,6.5,6.8,7.0,7.0,6.8,6.5,6.2,6.0,5.8,5.5,5.2,5.0,4.8,4.5,4.2,4.0,3.8,3.6,3.5,3.4,3.5,3.6,3.7,3.8,3.8,3.5,3.2,3.0,2.8,2.6,2.4,2.2,2.0,1.9,1.8,1.7,1.6,1.5,1.4,1.3,1.2,1.1,1.0,0.9,0.8,0.7,0.6,0.5,0.4,0.35,0.3,0.25,0.2,0.15,0.1,0.08,0.06,0.04,0.03,0.02,0.015,0.01,0.008,0.005,0.003,0.001];
  const tot=raw.reduce((s,v)=>s+v,0);
  const base=raw.map(v=>v/tot*total);
  const fw=raw.map((v,a)=>a<5?v*0.5:a<15?v*0.4:a<50?v*1.4:a<65?v*0.8:v*0.3);
  const fTot=fw.reduce((s,v)=>s+v,0);
  const foreign=fw.map(v=>v/fTot*total*fShare);
  const swiss=base.map((v,i)=>Math.max(0,v-foreign[i]));
  return{swiss,foreign};
}
function migrationByAge(net){
  const w=new Array(AG).fill(0);
  for(let a=0;a<AG;a++){
    if(a<5)w[a]=0.6;else if(a<15)w[a]=0.3;
    else if(a<40)w[a]=1.5-Math.abs(a-28)/30;
    else if(a<65)w[a]=0.3;else w[a]=0.1;
  }
  const ws=w.reduce((s,v)=>s+v,0);
  return w.map(v=>net*v/ws);
}
function agg5(pop){
  const out=[];
  for(let g=0;g<20;g++){let s=0;for(let a=g*5;a<g*5+5&&a<AG;a++)s+=pop[a];out.push(s);}
  out.push(pop[100]);return out;
}
function projectAll(tfrCh,tfrF,le,imm,emi){
  const sCh=makeSurvival(le),sF=makeSurvival(le-2);
  const fCh=makeFertility(tfrCh),fF=makeFertility(tfrF);
  const immByAge=migrationByAge(imm),emigByAge=migrationByAge(emi);
  let{swiss,foreign}=initPop(INIT_POP,INIT_FOREIGN_SHARE);
  const frames=[{ch:agg5(swiss),f:agg5(foreign)}];
  for(let y=0;y<YEARS;y++){
    const nCh=new Array(AG).fill(0),nF=new Array(AG).fill(0);
    let bCh=0,bF=0;
    for(let a=15;a<=49;a++){bCh+=fCh[a]*swiss[a];bF+=fF[a]*foreign[a];}
    nCh[0]=bCh;nF[0]=bF;
    for(let a=1;a<AG;a++){nCh[a]=swiss[a-1]*sCh[a-1];nF[a]=foreign[a-1]*sF[a-1];}
    const totAll=swiss.reduce((s,v)=>s+v,0)+foreign.reduce((s,v)=>s+v,0);
    for(let a=0;a<AG;a++){
      const fFrac=totAll>0?foreign[a]/totAll:0;
      const cFrac=totAll>0?swiss[a]/totAll:0;
      nF[a]=Math.max(0,nF[a]-emigByAge[a]*fFrac*2+immByAge[a]);
      nCh[a]=Math.max(0,nCh[a]-emigByAge[a]*cFrac*0.3);
      const nat=nF[a]*0.01;nF[a]-=nat;nCh[a]+=nat;
    }
    swiss=nCh;foreign=nF;
    frames.push({ch:agg5(swiss),f:agg5(foreign)});
  }
  return frames;
}

let allFrames=[],currentFrame=0,playing=false,timer=null;
const isDark=window.matchMedia('(prefers-color-scheme: dark)').matches;
const textColor=isDark?'#aaa':'#666';
const gridColor=isDark?'rgba(255,255,255,0.06)':'rgba(0,0,0,0.06)';
const chart=echarts.init(document.getElementById('pyramid'),null,{renderer:'svg'});

function buildOption(frame){
  const{ch,f}=allFrames[frame];
  const maxVal=Math.max(...ch.map((v,i)=>(v+f[i])/2))*1.18;
  const chM=ch.map(v=>Math.round(v/2));
  const fM=f.map(v=>Math.round(v/2));
  const chFem=ch.map(v=>Math.round(v/2));
  const fFem=f.map(v=>Math.round(v/2));
  return{
    animation:true,animationDuration:350,animationEasing:'cubicOut',
    grid:[
      {left:16, right:'50%', top:8, bottom:32},
      {left:'50%', right:16, top:8, bottom:32},
    ],
    tooltip:{trigger:'axis',axisPointer:{type:'shadow'},
      formatter(params){
        const ag=AGE_LABELS[params[0].dataIndex];
        const chMv=params[0]?params[0].value||0:0;
        const fMv =params[1]?params[1].value||0:0;
        const chFv=params[2]?params[2].value||0:0;
        const fFv =params[3]?params[3].value||0:0;
        const fmt=v=>Math.round(v).toLocaleString('de-CH');
        return`<div style="font-size:12px;font-weight:500;margin-bottom:4px">${ag} Jahre</div>
          <div style="font-size:11px;margin-bottom:2px"><b>Männer:</b> CH ${fmt(chMv)} · Ausl. ${fmt(fMv)}</div>
          <div style="font-size:11px"><b>Frauen:</b> CH ${fmt(chFv)} · Ausl. ${fmt(fFv)}</div>`;
      }
    },
    xAxis:[
      {gridIndex:0,type:'value',min:0,max:maxVal,inverse:true,
       axisLabel:{color:textColor,fontSize:10,formatter:v=>Math.round(v/1000)+'k'},
       splitLine:{lineStyle:{color:gridColor}},axisLine:{show:false},axisTick:{show:false}},
      {gridIndex:1,type:'value',min:0,max:maxVal,inverse:false,
       axisLabel:{color:textColor,fontSize:10,formatter:v=>Math.round(v/1000)+'k'},
       splitLine:{lineStyle:{color:gridColor}},axisLine:{show:false},axisTick:{show:false}},
    ],
    yAxis:[
      {gridIndex:0,type:'category',data:AGE_LABELS,
       axisLabel:{color:textColor,fontSize:9},axisLine:{show:false},axisTick:{show:false},splitLine:{show:false}},
      {gridIndex:1,type:'category',data:AGE_LABELS,
       axisLabel:{show:false},axisLine:{show:false},axisTick:{show:false},splitLine:{show:false}},
    ],
    series:[
      {name:'CH Männer',    type:'bar',xAxisIndex:0,yAxisIndex:0,stack:'male',
       data:chM, barMaxWidth:18,itemStyle:{color:'#378ADD'}},
      {name:'Ausl. Männer', type:'bar',xAxisIndex:0,yAxisIndex:0,stack:'male',
       data:fM,  barMaxWidth:18,itemStyle:{color:'#7ab8e8'}},
      {name:'CH Frauen',    type:'bar',xAxisIndex:1,yAxisIndex:1,stack:'female',
       data:chFem,barMaxWidth:18,itemStyle:{color:'#D85A30'}},
      {name:'Ausl. Frauen', type:'bar',xAxisIndex:1,yAxisIndex:1,stack:'female',
       data:fFem, barMaxWidth:18,itemStyle:{color:'#e89a7a'}},
    ]
  };
}

function updateStats(frame){
  const{ch,f}=allFrames[frame];
  const totCh=Math.round(ch.reduce((s,v)=>s+v,0));
  const totF=Math.round(f.reduce((s,v)=>s+v,0));
  const total=totCh+totF;
  const foreignPct=(totF/total*100).toFixed(1);
  const all=ch.map((v,i)=>v+f[i]);
  const elderly=Math.round(all.slice(13).reduce((s,v)=>s+v,0));
  const youth=Math.round(all.slice(0,4).reduce((s,v)=>s+v,0));
  const dep=((elderly+youth)/(total-elderly-youth)*100).toFixed(1);
  document.getElementById('stats').innerHTML=`
    <div class="s-card"><div class="s-label">Gesamt</div><div class="s-val">${total.toLocaleString('de-CH')}</div></div>
    <div class="s-card"><div class="s-label">Schweizer</div><div class="s-val swiss-accent">${totCh.toLocaleString('de-CH')}</div></div>
    <div class="s-card"><div class="s-label">Ausländer</div><div class="s-val foreign-accent">${totF.toLocaleString('de-CH')} <span style="font-size:.75rem;font-weight:400">(${foreignPct}%)</span></div></div>
    <div class="s-card"><div class="s-label">Altersquotient</div><div class="s-val">${dep}%</div></div>`;
}

function showFrame(f){
  currentFrame=Math.max(0,Math.min(YEARS,f));
  document.getElementById('year-slider').value=currentFrame;
  document.getElementById('year-label').textContent=BASE_YEAR+currentFrame;
  chart.setOption(buildOption(currentFrame));
  updateStats(currentFrame);
}
function togglePlay(){
  playing=!playing;
  document.getElementById('play-btn').textContent=playing?'⏸ Pause':'▶ Play';
  if(playing){
    if(currentFrame>=YEARS)showFrame(0);
    timer=setInterval(()=>{
      if(currentFrame>=YEARS){clearInterval(timer);playing=false;document.getElementById('play-btn').textContent='▶ Play';return;}
      showFrame(currentFrame+1);
    },130);
  }else{clearInterval(timer);}
}
function recompute(){
  if(playing){clearInterval(timer);playing=false;document.getElementById('play-btn').textContent='▶ Play';}
  const tfrCh=parseFloat(document.getElementById('tfr-ch').value);
  const tfrF=parseFloat(document.getElementById('tfr-f').value);
  const le=parseFloat(document.getElementById('le').value);
  const imm=parseInt(document.getElementById('imm').value);
  const emi=parseInt(document.getElementById('emi').value);
  document.getElementById('tfr-ch-out').textContent=tfrCh.toFixed(2);
  document.getElementById('tfr-f-out').textContent=tfrF.toFixed(2);
  document.getElementById('le-out').textContent=le.toFixed(1);
  document.getElementById('imm-out').textContent=imm.toLocaleString('de-CH');
  document.getElementById('emi-out').textContent=emi.toLocaleString('de-CH');
  allFrames=projectAll(tfrCh,tfrF,le,imm,emi);
  showFrame(currentFrame);
}
function applyScenario(key,btn){
  document.querySelectorAll('.scen-btn').forEach(b=>b.classList.remove('active'));
  btn.classList.add('active');
  const s=SCENARIOS[key];
  document.getElementById('tfr-ch').value=s.tfrCh;
  document.getElementById('tfr-f').value=s.tfrF;
  document.getElementById('le').value=s.le;
  document.getElementById('imm').value=s.imm;
  document.getElementById('emi').value=s.emi;
  recompute();
}
document.querySelectorAll('#tfr-ch,#tfr-f,#le,#imm,#emi').forEach(el=>el.addEventListener('input',()=>{
  document.querySelectorAll('.scen-btn').forEach(b=>b.classList.remove('active'));
  recompute();
}));
document.getElementById('year-slider').addEventListener('input',e=>{
  if(playing){clearInterval(timer);playing=false;document.getElementById('play-btn').textContent='▶ Play';}
  showFrame(parseInt(e.target.value));
});
recompute();
</script>
```

---

## ODI Integration Notes

### Django rendering

The story pipeline retrieves `title`, `text`, and `html` from `simulations` and concatenates them in order. The `html` field is a complete self-contained widget and is output with `|safe`.

### ECharts loading

The `html` field from `simulations` is output directly with `|safe`, exactly as graphics and tables already are. No new template tags needed.

### ECharts loading

If ECharts is not yet loaded globally in `base.html`, add it once:

```html
<script src="{% static 'js/echarts.min.js' %}"></script>
```

Then strip the CDN `<script>` tag from the widget HTML before storing it in the `html` field — ECharts will already be available on the page.

### JS scoping

Each widget's JS should be wrapped in an IIFE to avoid variable collisions if multiple simulations ever appear on the same page:

```javascript
(function() {
  // all widget JS here — isolated scope
})();
```

### Real age structure

The synthetic `raw[]` age distribution array in the widget code should eventually be replaced with real STATPOP data from `data.bs.ch` dataset `100007`. Fetch once in Python, serialize to a JS array, and store it directly in the `html` field as a hardcoded constant.

---

## Next Steps

- [ ] Create `report_generator.simulation_template`, `report_generator.simulation_parameter`, `report_generator.simulation` tables
- [ ] Run Django migrations for the three new models
- [ ] Register models in Django admin
- [ ] Implement `generate_simulation()` service and wire to a management command or admin action
- [ ] Add `story_context` query using the join on latest `generated_at` (see Story Wiring above)
- [ ] Create story + focus with `filter_value = 1` pointing at demographics template
- [ ] Write article text (demographics explainer + Basel context) → store in `simulation_template.text`
- [ ] Insert `simulation_parameter` rows for demographics (check real opendata table names first)
- [ ] Refactor widget JS to read from `BASELINE` object instead of hardcoded constants
- [ ] Decide: projection curve only, pyramid only, or combined widget → store in `js_template`
- [ ] Fetch real Basel-Stadt age pyramid from `data.bs.ch/explore/dataset/100007`
- [ ] Replace synthetic age distribution array with real STATPOP data (inject via `BASELINE`)
- [ ] Strip ECharts CDN tag from `js_template` (load via `base.html` static instead)
- [ ] Wrap widget JS in IIFE for scope safety
