"""
Management command: create or refresh the BFS Sterbetafeln simulation template.

Idempotent — safe to re-run. Creates/updates SimulationTemplate +
SimulationParameter rows, then generates a fresh Simulation HTML snapshot.
"""

import json

from django.core.management.base import BaseCommand
from django.db import connection

from reports.models.simulation import SimulationParameter, SimulationTemplate
from reports.models.graphic_template import StoryTemplateGraphic
from reports.models.story_template import StoryTemplate, StoryTemplateFocus
from reports.models.lookups import GraphType, Period, PeriodDirection
from reports.services.simulation_processor import generate_simulation

CURRENT_YEAR = 2026
TITLE = "BFS Sterbetafeln · Lebenserwartung Schweiz"

INTRO_TEXT = """\
<p>Die <strong>Sterbetafeln</strong> des Bundesamts für Statistik (BFS) zeigen, wie viele Jahre
eine Person statistisch gesehen noch zu leben hat – abhängig vom aktuellen Alter und Geschlecht.
Die Daten reichen von 1876 bis ins Jahr 2150 (Projektionen) und spiegeln eindrücklich, wie stark
sich die Lebenserwartung über Generationen verbessert hat.</p>
<p>Wählen Sie Ihr Geschlecht und geben Sie Ihr Geburtsjahr ein. Das Diagramm zeigt Ihre
aktuelle Restlebenserwartung sowie deren Entwicklung seit Ihrer Geburt – ein Fenster auf
medizinischen Fortschritt und demographischen Wandel.</p>"""

# ── ODI widget template ───────────────────────────────────────────────────────
# __DATA__ is replaced at build time with the embedded life-table JSON.
# BASELINE.current_year is injected at generation time by simulation_processor.

JS_TEMPLATE = """\
<style>
.st-w *,.st-w *::before,.st-w *::after{box-sizing:border-box;}
.st-w{font-size:14px;color:var(--color-text-primary,#111);}
.st-controls{display:flex;align-items:center;gap:2rem;margin-bottom:1.5rem;flex-wrap:wrap;}
.st-sex-tog{display:flex;gap:6px;}
.st-sex-btn{font-size:12px;padding:5px 18px;border:1px solid var(--color-border-secondary,#ccc);border-radius:20px;background:transparent;color:var(--color-text-secondary,#888);cursor:pointer;transition:all .15s;}
.st-sex-btn.active{background:var(--color-text-primary,#111);color:var(--color-background-primary,#fff);border-color:var(--color-text-primary,#111);}
.st-yr-wrap{display:flex;align-items:center;gap:10px;}
.st-yr-wrap label{font-size:12px;color:var(--color-text-secondary,#888);white-space:nowrap;}
.st-yr-range{width:200px;cursor:pointer;}
.st-yr-disp{font-size:1.1rem;font-weight:500;min-width:40px;}
.st-cards{display:grid;grid-template-columns:repeat(4,1fr);gap:10px;margin-bottom:1.5rem;}
.st-card{background:var(--color-background-secondary,#f5f5f5);border-radius:8px;padding:.75rem 1rem;}
.st-card-lbl{font-size:10px;text-transform:uppercase;letter-spacing:.05em;color:var(--color-text-secondary,#999);margin-bottom:4px;}
.st-card-val{font-size:1.2rem;font-weight:500;}
.st-sec{font-size:10px;text-transform:uppercase;letter-spacing:.06em;color:var(--color-text-tertiary,#bbb);margin:1.4rem 0 .4rem;}
@media(max-width:600px){.st-cards{grid-template-columns:repeat(2,1fr);}.st-controls{flex-direction:column;align-items:flex-start;}}
</style>

<div class="st-w">
  <div class="st-controls">
    <div class="st-sex-tog">
      <button class="st-sex-btn active" id="st-btn-f">Frau</button>
      <button class="st-sex-btn"        id="st-btn-m">Mann</button>
    </div>
    <div class="st-yr-wrap">
      <label>Geburtsjahr</label>
      <input type="range" class="st-yr-range" id="st-birth-yr" min="1930" max="2024" value="1970">
      <span class="st-yr-disp" id="st-yr-disp">1970</span>
    </div>
  </div>

  <div class="st-cards">
    <div class="st-card">
      <div class="st-card-lbl">Geburtsjahr</div>
      <div class="st-card-val" id="st-c-birth">1970</div>
    </div>
    <div class="st-card">
      <div class="st-card-lbl">Alter <span id="st-yr-lbl"></span></div>
      <div class="st-card-val" id="st-c-age">—</div>
    </div>
    <div class="st-card">
      <div class="st-card-lbl">Verbleibende Jahre</div>
      <div class="st-card-val" id="st-c-rem">—</div>
    </div>
    <div class="st-card">
      <div class="st-card-lbl">Erw. Sterbejahr</div>
      <div class="st-card-val" id="st-c-death">—</div>
    </div>
  </div>

  <div class="st-sec">Ihr Leben im Überblick</div>
  <div id="st-chart-tl" style="height:90px;"></div>

  <div class="st-sec">Verbleibende Lebenserwartung · Entwicklung seit Geburt</div>
  <div id="st-chart-tr" style="height:300px;"></div>

  <div class="st-sec" id="st-sec-tbl"></div>
  <div id="st-chart-tb" style="height:260px;"></div>
</div>

<script src="https://cdn.jsdelivr.net/npm/echarts@5.4.3/dist/echarts.min.js"></script>
<script>
(function(){
const DATA=__DATA__;
const CURRENT_YEAR=BASELINE.current_year;
const CF='#c0657e',CM='#378ADD';
let sex='f',birthYear=1970;

document.getElementById('st-yr-lbl').textContent=CURRENT_YEAR;
document.getElementById('st-sec-tbl').textContent='Sterbetafel '+CURRENT_YEAR+' · Verbleibende Jahre nach Alter';

const cTL=echarts.init(document.getElementById('st-chart-tl'),null,{renderer:'svg'});
const cTR=echarts.init(document.getElementById('st-chart-tr'),null,{renderer:'svg'});
const cTB=echarts.init(document.getElementById('st-chart-tb'),null,{renderer:'svg'});

document.getElementById('st-btn-f').addEventListener('click',function(){setSex('f');});
document.getElementById('st-btn-m').addEventListener('click',function(){setSex('m');});
document.getElementById('st-birth-yr').addEventListener('input',function(){
  birthYear=parseInt(this.value);
  document.getElementById('st-yr-disp').textContent=birthYear;
  update();
});

function setSex(s){
  sex=s;
  document.getElementById('st-btn-f').className='st-sex-btn'+(s==='f'?' active':'');
  document.getElementById('st-btn-m').className='st-sex-btn'+(s==='m'?' active':'');
  update();
}

function getVal(year,age){
  var y=DATA[String(year)];if(!y)return null;
  var a=y[String(age)];if(!a)return null;
  var v=sex==='f'?a[0]:a[1];
  return(v!==null&&v>0)?v:null;
}

function update(){
  var color=sex==='f'?CF:CM;
  var currentAge=CURRENT_YEAR-birthYear;
  var rem=null;
  if(currentAge>=0&&currentAge<=120)rem=getVal(CURRENT_YEAR,currentAge);
  var expectedDeath=rem!==null?Math.round(CURRENT_YEAR+rem):null;

  document.getElementById('st-c-birth').textContent=birthYear;
  document.getElementById('st-c-age').textContent=currentAge>=0?currentAge+' Jahre':'—';
  var remEl=document.getElementById('st-c-rem');
  remEl.textContent=rem!==null?rem.toFixed(1)+' Jahre':'—';
  remEl.style.color=color;
  document.getElementById('st-c-death').textContent=expectedDeath!==null?'~ '+expectedDeath:'—';

  drawTimeline(currentAge,rem,color);
  drawTrajectory(color);
  drawTable(currentAge);
}

function drawTimeline(currentAge,rem,color){
  if(rem===null||currentAge<0){cTL.clear();return;}
  cTL.setOption({
    animation:false,
    grid:{top:8,bottom:28,left:14,right:14,containLabel:true},
    tooltip:{trigger:'axis',axisPointer:{type:'shadow'},
      formatter:function(p){return p.map(function(s){return s.seriesName+': '+Number(s.value).toFixed(1)+' Jahre';}).join('<br>');}},
    xAxis:{type:'value',max:Math.ceil(currentAge+rem+2),
      axisLabel:{fontSize:10,formatter:function(v){return v+' J.';}},
      splitLine:{lineStyle:{color:'rgba(0,0,0,.06)'}}},
    yAxis:{type:'category',data:[sex==='f'?'Frau':'Mann'],axisLabel:{fontSize:10}},
    series:[
      {name:'Gelebte Jahre',type:'bar',stack:'s',data:[currentAge],
       itemStyle:{color:'#e0e0e0',borderRadius:[4,0,0,4]},
       label:{show:currentAge>8,position:'inside',fontSize:10,color:'#888',
              formatter:function(p){return p.value+' J.';}}},
      {name:'Verbleibende Jahre',type:'bar',stack:'s',data:[rem],
       itemStyle:{color:color,borderRadius:[0,4,4,0]},
       label:{show:true,position:'inside',fontSize:10,color:'#fff',
              formatter:function(p){return Number(p.value).toFixed(1)+' J.';}}}
    ]
  },{notMerge:true});
}

function drawTrajectory(color){
  var pts=[];
  for(var yr=birthYear;yr<=CURRENT_YEAR;yr++){
    var v=getVal(yr,yr-birthYear);
    if(v!==null)pts.push([yr,v]);
  }
  if(!pts.length){cTR.clear();return;}
  var BY=birthYear;
  cTR.setOption({
    animation:true,animationDuration:200,
    grid:{top:15,bottom:36,left:55,right:20},
    tooltip:{trigger:'axis',formatter:function(p){
      var yr=p[0].data[0],val=p[0].data[1];
      return yr+' · Alter '+(yr-BY)+': <b>'+val.toFixed(1)+' J.</b> verbleibend';
    }},
    xAxis:{type:'value',min:birthYear,max:CURRENT_YEAR,
      axisLabel:{fontSize:10},splitLine:{lineStyle:{color:'rgba(0,0,0,.04)'}}},
    yAxis:{type:'value',name:'Jahre',
      nameTextStyle:{fontSize:10,color:'#bbb',padding:[0,0,0,-20]},
      axisLabel:{fontSize:10},splitLine:{lineStyle:{color:'rgba(0,0,0,.04)'}}},
    series:[{
      type:'line',data:pts,smooth:0.3,
      lineStyle:{color:color,width:2.5},itemStyle:{color:color},symbol:'none',
      areaStyle:{color:{type:'linear',x:0,y:0,x2:0,y2:1,
        colorStops:[{offset:0,color:color+'38'},{offset:1,color:color+'04'}]}},
      markPoint:{data:[{coord:pts[pts.length-1],symbolSize:9}],itemStyle:{color:color}}
    }]
  },{notMerge:true});
}

function drawTable(currentAge){
  var yd=DATA[String(CURRENT_YEAR)]||{};
  var sF=[],sM=[];
  for(var age=0;age<=100;age++){
    var d=yd[String(age)];
    if(d){
      if(d[0]!==null&&d[0]>0)sF.push([age,d[0]]);
      if(d[1]!==null&&d[1]>0)sM.push([age,d[1]]);
    }
  }
  var mkl=(currentAge>=0&&currentAge<=100)
    ?[{xAxis:currentAge,
       label:{formatter:'Ihr Alter',fontSize:9,position:'end',color:'#aaa'},
       lineStyle:{color:'#aaa',type:'dashed',width:1}}]
    :[];
  cTB.setOption({
    animation:false,
    grid:{top:15,bottom:36,left:55,right:20},
    legend:{data:['Frau','Mann'],right:10,top:0,
      textStyle:{fontSize:10},itemWidth:12,itemHeight:6},
    tooltip:{trigger:'axis',formatter:function(params){
      var age=params[0].data[0];
      var map={};params.forEach(function(p){map[p.seriesName]=p.data[1];});
      return 'Alter '+age+'<br>Frau: '+(map['Frau']!=null?map['Frau'].toFixed(1):'—')+' J.<br>Mann: '+(map['Mann']!=null?map['Mann'].toFixed(1):'—')+' J.';
    }},
    xAxis:{type:'value',min:0,max:100,name:'Alter',nameLocation:'end',
      nameTextStyle:{fontSize:10,color:'#bbb'},
      axisLabel:{fontSize:10},splitLine:{lineStyle:{color:'rgba(0,0,0,.04)'}}},
    yAxis:{type:'value',name:'Jahre',
      nameTextStyle:{fontSize:10,color:'#bbb',padding:[0,0,0,-20]},
      axisLabel:{fontSize:10},splitLine:{lineStyle:{color:'rgba(0,0,0,.04)'}}},
    series:[
      {name:'Frau',type:'line',data:sF,
       lineStyle:{color:CF,width:2},itemStyle:{color:CF},symbol:'none',
       markLine:{symbol:'none',data:mkl}},
      {name:'Mann',type:'line',data:sM,
       lineStyle:{color:CM,width:2},itemStyle:{color:CM},symbol:'none'}
    ]
  },{notMerge:true});
}

update();
window.addEventListener('resize',function(){cTL.resize();cTR.resize();cTB.resize();});
})();
</script>"""


class Command(BaseCommand):
    help = "Create or refresh the BFS Sterbetafeln simulation template and generate HTML."

    def add_arguments(self, parser):
        parser.add_argument(
            "--dry-run",
            action="store_true",
            help="Show what would be created without writing to DB.",
        )
        parser.add_argument(
            "--create-story",
            action="store_true",
            help="Also create (or update) a StoryTemplate, StoryTemplateFocus, and StoryTemplateGraphic.",
        )

    def handle(self, *args, **options):
        dry_run = options["dry_run"]
        create_story = options["create_story"]

        self.stdout.write("Fetching life-table data from opendata.bfs_sterbetafeln …")
        data = self._fetch_data()
        data_json = json.dumps(data, separators=(",", ":"))
        self.stdout.write(f"  {len(data)} years · {len(data_json):,} bytes")

        js_template = JS_TEMPLATE.replace("__DATA__", data_json)

        if dry_run:
            self.stdout.write(self.style.WARNING("Dry-run: no DB changes written."))
            self.stdout.write(f"  js_template size: {len(js_template):,} chars")
            return

        # ── SimulationTemplate ────────────────────────────────────────────────
        sim_tmpl, created = SimulationTemplate.objects.update_or_create(
            title=TITLE,
            defaults={
                "description": (
                    "Interactive Swiss life-expectancy calculator based on BFS mortality tables "
                    "(Sterbetafeln 1876–2026). Embedded life-table JSON; single BASELINE param: current_year."
                ),
                "text": INTRO_TEXT,
                "js_template": js_template,
            },
        )
        self.stdout.write(
            f'  {"Created" if created else "Updated"} SimulationTemplate id={sim_tmpl.id} "{sim_tmpl.title}"'
        )

        # ── SimulationParameter: current_year ─────────────────────────────────
        param, p_created = SimulationParameter.objects.update_or_create(
            simulation=sim_tmpl,
            parameter_name="current_year",
            defaults={
                "parameter_type": SimulationParameter.CONSTANT,
                "value": CURRENT_YEAR,
                "description": "Reference year for life-table lookup and age calculations.",
                "sort_order": 0,
            },
        )
        self.stdout.write(
            f'  {"Created" if p_created else "Updated"} SimulationParameter: current_year = {CURRENT_YEAR}'
        )

        # ── Simulation HTML ───────────────────────────────────────────────────
        self.stdout.write("Generating Simulation HTML …")
        sim = generate_simulation(sim_tmpl.id)
        self.stdout.write(
            self.style.SUCCESS(f"  Simulation id={sim.id}  html={len(sim.html):,} chars")
        )

        if not create_story:
            self.stdout.write(
                f"\nRun with --create-story to also create the StoryTemplate, or add it manually:\n"
                f"  graphic_type = simulation\n"
                f"  settings     = {{\"simulation_template_slug\": \"{sim_tmpl.slug}\"}}"
            )
            return

        # ── StoryTemplate ─────────────────────────────────────────────────────
        self.stdout.write("\nCreating story …")
        period = Period.objects.get(value="year")
        direction = PeriodDirection.objects.get(id=73)  # 'current'
        graph_type = GraphType.objects.get(value="simulation")

        story_tmpl, st_created = StoryTemplate.objects.update_or_create(
            title=TITLE,
            defaults={
                "story_source": StoryTemplate.STORY_SOURCE_LLM,
                "generation_mode": StoryTemplate.GENERATION_MODE_TRANSLATE,
                "create_title": True,
                "create_lead": True,
                "reference_period": period,
                "period_direction": direction,
                "is_published": False,
                "active": True,
                "data_source": [{"text": "BFS Sterbetafeln", "url": "https://www.bfs.admin.ch"}],
            },
        )
        self.stdout.write(
            f'  {"Created" if st_created else "Updated"} StoryTemplate id={story_tmpl.id} "{story_tmpl.title}"'
        )

        # ── StoryTemplateFocus (default) ──────────────────────────────────────
        focus, f_created = StoryTemplateFocus.objects.get_or_create(
            story_template=story_tmpl,
            filter_value=None,
            defaults={"filter_expression": None, "focus_subject": None},
        )
        self.stdout.write(f'  {"Created" if f_created else "Exists"} StoryTemplateFocus (default)')

        # ── StoryTemplateGraphic ──────────────────────────────────────────────
        graphic, g_created = StoryTemplateGraphic.objects.update_or_create(
            story_template=story_tmpl,
            title="Lebenserwartung Rechner",
            defaults={
                "graphic_type": graph_type,
                "settings": {"simulation_template_slug": sim_tmpl.slug},
                "sql_command": "",
                "sort_order": 0,
            },
        )
        self.stdout.write(
            f'  {"Created" if g_created else "Updated"} StoryTemplateGraphic id={graphic.id}'
        )

        self.stdout.write(
            self.style.SUCCESS(
                f"\nDone! StoryTemplate id={story_tmpl.id} is ready.\n"
                f"  → Open /admin/reports/storytemplate/{story_tmpl.id}/change/ to review,\n"
                f"    add topics/region, then generate the story from admin."
            )
        )

    def _fetch_data(self) -> dict:
        with connection.cursor() as cur:
            cur.execute("""
                SELECT
                    jahr,
                    (regexp_match(alter_jahre, '^\\d+'))[1]::int AS age,
                    ROUND(SUM(CASE WHEN geschlecht = 'Frau' THEN value END)::numeric, 2),
                    ROUND(SUM(CASE WHEN geschlecht = 'Mann' THEN value END)::numeric, 2)
                FROM opendata.bfs_sterbetafeln
                WHERE jahr <= %s
                GROUP BY jahr, (regexp_match(alter_jahre, '^\\d+'))[1]::int
                ORDER BY jahr, age
            """, [CURRENT_YEAR])
            rows = cur.fetchall()

        data: dict = {}
        for jahr, age, frau, mann in rows:
            y = str(jahr)
            if y not in data:
                data[y] = {}
            data[y][str(age)] = [
                float(frau) if frau is not None else None,
                float(mann) if mann is not None else None,
            ]
        return data
