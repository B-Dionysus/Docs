#!/usr/bin/env python3
"""Generate a self-contained HTML report from mySugr and Samsung Health CSV exports.

Only rows present in the input CSVs are plotted. Line segments connect consecutive
recorded observations; they do not create extra readings on dates between records.
Uses only the Python standard library.
"""

from __future__ import annotations

import argparse
import csv
import html
import json
import re
import sys
from datetime import datetime, time, timezone
from pathlib import Path
from statistics import mean, median
from typing import Any

DEFAULT_GLUCOSE = "mySugr_Export_2026-11-09-16-08.csv"
DEFAULT_PRESSURE = "com.samsung.shealth.blood_pressure.20261109155644.csv"
DEFAULT_OUTPUT = "index.html"
DEFAULT_START = "2026-09-06"
DEFAULT_END = "2026-11-09"
DEFAULT_VISIT = "2026-10-06"

MONTHS = {name: number for number, name in enumerate(
    ("Jan", "Feb", "Mar", "Apr", "May", "Jun", "Jul", "Aug", "Sep", "Oct", "Nov", "Dec"), 1
)}


def parse_date(value: str) -> str | None:
    match = re.fullmatch(r"\s*([A-Z][a-z]{2})\s+(\d{1,2}),\s+(\d{4})\s*", value or "")
    if not match or match.group(1) not in MONTHS:
        return None
    month = MONTHS[match.group(1)]
    day = int(match.group(2))
    year = int(match.group(3))
    try:
        return datetime(year, month, day).strftime("%Y-%m-%d")
    except ValueError:
        return None


def parse_glucose(path: Path, start: str, end: str) -> tuple[list[dict[str, Any]], int]:
    with path.open(newline="", encoding="utf-8-sig") as stream:
        rows = list(csv.reader(stream))
    header_index = next((i for i, row in enumerate(rows)
                         if "Date" in row and "Time" in row
                         and "Blood Sugar Measurement (mg/dL)" in row), None)
    if header_index is None:
        raise ValueError(f"Could not find mySugr Date/Time/glucose header in {path}.")
    header = rows[header_index]
    date_col = header.index("Date")
    time_col = header.index("Time")
    value_col = header.index("Blood Sugar Measurement (mg/dL)")
    records: list[dict[str, Any]] = []
    excluded = 0
    for row in rows[header_index + 1:]:
        if max(date_col, time_col, value_col) >= len(row):
            continue
        date = parse_date(row[date_col])
        clock = row[time_col].strip()
        if not date or not (start <= date <= end) or not clock:
            continue
        try:
            glucose = float(row[value_col])
            parsed_time = datetime.strptime(clock, "%I:%M:%S %p").time()
        except (ValueError, TypeError):
            continue
        if not (glucose == glucose and abs(glucose) != float("inf")):
            continue
        # CSV time is a local wall-clock value. Encode its components as UTC solely
        # for stable chart ordering; show the original local date/time in tooltips.
        stamp = datetime.fromisoformat(f"{date}T{parsed_time.isoformat()}").replace(tzinfo=timezone.utc)
        records.append({
            "date": date,
            "clock": parsed_time.strftime("%-I:%M:%S %p") if sys.platform != "win32" else parsed_time.strftime("%I:%M:%S %p").lstrip("0"),
            "time": int(stamp.timestamp() * 1000),
            "value": glucose,
            "period": "AM" if parsed_time.hour < 12 else "PM",
        })
    records.sort(key=lambda item: item["time"])
    return records, excluded


def parse_pressure(path: Path, start: str, end: str) -> list[dict[str, Any]]:
    with path.open(newline="", encoding="utf-8-sig") as stream:
        rows = list(csv.reader(stream))
    header_index = next((i for i, row in enumerate(rows)
                         if any(cell.endswith(".start_time") for cell in row)
                         and any(cell.endswith(".systolic") for cell in row)
                         and any(cell.endswith(".diastolic") for cell in row)), None)
    if header_index is None:
        raise ValueError(f"Could not find Samsung Health blood-pressure header in {path}.")
    header = rows[header_index]
    date_col = next(i for i, cell in enumerate(header) if cell.endswith(".start_time"))
    sys_col = next(i for i, cell in enumerate(header) if cell.endswith(".systolic"))
    dia_col = next(i for i, cell in enumerate(header) if cell.endswith(".diastolic"))
    records: list[dict[str, Any]] = []
    for row in rows[header_index + 1:]:
        if max(date_col, sys_col, dia_col) >= len(row):
            continue
        raw_datetime = row[date_col].strip()
        try:
            observed = datetime.strptime(raw_datetime[:19], "%Y-%m-%d %H:%M:%S")
            systolic = float(row[sys_col])
            diastolic = float(row[dia_col])
        except (ValueError, TypeError):
            continue
        date = observed.strftime("%Y-%m-%d")
        if not (start <= date <= end):
            continue
        stamp = observed.replace(tzinfo=timezone.utc)
        records.append({
            "date": date,
            "clock": observed.strftime("%H:%M:%S"),
            "time": int(stamp.timestamp() * 1000),
            "systolic": systolic,
            "diastolic": diastolic,
        })
    records.sort(key=lambda item: item["time"])
    return records


HTML_TEMPLATE = r'''<!doctype html>
<html lang="en">
<head>
<meta charset="utf-8"><meta name="viewport" content="width=device-width,initial-scale=1">
<title>Blood pressure &amp; blood glucose · __START_LABEL__–__END_LABEL__</title>
<style>
:root{color-scheme:light;--bg:#f4f6fb;--card:#fff;--ink:#172033;--muted:#667085;--grid:#e4e9f2;--orange:#f97316;--blue:#2563eb;--cyan:#0891b2;--visit:#be123c;--border:#d9e1ec;--accent:#0f766e}
*{box-sizing:border-box}body{margin:0;background:var(--bg);color:var(--ink);font:16px/1.5 system-ui,-apple-system,Segoe UI,Roboto,Arial,sans-serif}
main{max-width:1600px;margin:auto;padding:28px clamp(12px,2.4vw,36px) 56px}h1{margin:0;font-size:clamp(1.7rem,3vw,2.5rem);letter-spacing:-.03em}.intro,.muted{color:var(--muted)}.intro{margin:4px 0 0}.status{margin:16px 0 0;padding:10px 12px;border-radius:9px;background:#ecfdf3;color:#166534}
.section{margin-top:30px;background:var(--card);border-radius:16px;padding:clamp(14px,2vw,26px);box-shadow:0 8px 26px #18264012}.section h2{margin:0;font-size:1.35rem}.section-lede{margin:2px 0 12px;color:var(--muted);font-size:.94rem}.plot-wrap{position:relative;width:100%;overflow:visible}svg{display:block;width:100%;height:auto}.legend{display:flex;flex-wrap:wrap;gap:14px 22px;margin-top:8px;color:var(--muted);font-size:.9rem}.legend span{display:inline-flex;align-items:center;gap:7px}.key{width:11px;height:11px;border-radius:50%;display:inline-block}.vline{width:20px;height:0;border-top:2px dashed var(--visit);display:inline-block}.tooltip{display:none;position:absolute;z-index:3;pointer-events:none;max-width:270px;padding:9px 11px;border-radius:9px;background:#172033;color:#fff;font-size:.88rem;line-height:1.45;box-shadow:0 4px 16px #11182735;white-space:pre-line}
.analysis{margin-top:18px;padding:18px;border:2px solid #cbd5e1;border-left:7px solid var(--accent);border-radius:13px;background:linear-gradient(110deg,#f0fdfa 0%,#f8fafc 58%,#fff 100%);box-shadow:0 5px 16px #0f172a10}.analysis h3{margin:0 0 4px;font-size:1.15rem;color:#134e4a}.analysis .summary{font-size:.98rem;color:#334155;margin:4px 0 12px}.metrics{display:grid;grid-template-columns:repeat(auto-fit,minmax(150px,1fr));gap:10px;margin:10px 0}.metric{background:white;border:1px solid var(--border);border-radius:10px;padding:11px 12px;color:var(--muted);font-size:.86rem;min-height:72px}.metric strong{display:block;color:var(--ink);font-size:1.12rem;line-height:1.25;margin-bottom:3px}.analysis .interpretation{margin:10px 0 0;padding-top:10px;border-top:1px solid var(--border);font-size:.92rem;color:#475569}.subsection{margin-top:42px;padding-top:28px;border-top:2px solid var(--border)}.subsection:first-of-type{margin-top:8px;padding-top:0;border-top:0}.subsection h3{margin:0;font-size:1.12rem}.subsection .section-lede{margin-bottom:10px}.note{margin:18px 2px 0;color:var(--muted);font-size:.88rem}
@media(max-width:600px){main{padding-top:20px}.section{padding:12px}.subsection{margin-top:34px;padding-top:24px}.analysis{padding:13px}.metric{min-height:64px}}
</style>
</head>
<body><main>
<h1>Blood pressure &amp; blood glucose</h1>
<p class="intro">__START_LABEL__–__END_LABEL__ · Doctor visit: __VISIT_LABEL__</p>
<p id="status" class="status" role="status">Loading the source CSV exports…</p>
<section class="section" aria-labelledby="bpTitle">
<h2 id="bpTitle">Blood pressure</h2><p class="section-lede">Recorded systolic and diastolic measurements (mmHg)</p>
<div class="plot-wrap"><svg id="pressureChart" viewBox="0 0 1400 520" role="img" aria-label="Blood pressure line graph using recorded CSV measurements"></svg><div id="pressureTooltip" class="tooltip" role="tooltip"></div></div>
<div class="legend"><span><i class="key" style="background:var(--blue)"></i>Systolic</span><span><i class="key" style="background:var(--cyan)"></i>Diastolic</span><span><i class="vline"></i>Doctor visit · __VISIT_SHORT__</span></div><div id="pressureAnalysis" class="analysis"></div>
</section>
<section class="section" aria-labelledby="glucoseTitle">
<h2 id="glucoseTitle">Blood glucose</h2><p class="section-lede">AM and PM readings are separated into their own graphs; the export records time of day, not fasting or meal status.</p>
<div class="subsection" aria-labelledby="amTitle"><h3 id="amTitle">AM readings</h3><p class="section-lede">Morning (AM) readings</p>
<div class="plot-wrap"><svg id="glucoseAMChart" viewBox="0 0 1400 500" role="img" aria-label="Line graph of recorded morning blood glucose readings"></svg><div id="glucoseAMTooltip" class="tooltip" role="tooltip"></div></div>
<div class="legend"><span><i class="key" style="background:var(--orange)"></i>Blood glucose (mg/dL)</span><span><i class="vline"></i>Doctor visit · __VISIT_SHORT__</span></div><div id="glucoseAMAnalysis" class="analysis"></div></div>
<div class="subsection" aria-labelledby="pmTitle"><h3 id="pmTitle">PM readings</h3><p class="section-lede">Evening (PM) readings</p>
<div class="plot-wrap"><svg id="glucosePMChart" viewBox="0 0 1400 500" role="img" aria-label="Line graph of recorded evening blood glucose readings"></svg><div id="glucosePMTooltip" class="tooltip" role="tooltip"></div></div>
<div class="legend"><span><i class="key" style="background:var(--orange)"></i>Blood glucose (mg/dL)</span><span><i class="vline"></i>Doctor visit · __VISIT_SHORT__</span></div><div id="glucosePMAnalysis" class="analysis"></div></div>
</section>
<p class="note">Analysis summarizes the exported readings and is descriptive, not a diagnosis or treatment recommendation.</p>
</main>
<script>
(()=>{'use strict';
const START='__START__',END='__END__',VISIT='__VISIT__',DATA=__DATA__,NS='http://www.w3.org/2000/svg';
const css=n=>getComputedStyle(document.documentElement).getPropertyValue(n).trim();
const parseCSV=text=>{text=text.replace(/^\uFEFF/,'');let rows=[],row=[],field='',q=false;for(let i=0;i<text.length;i++){const c=text[i];if(q){if(c==='"'&&text[i+1]==='"'){field+='"';i++}else if(c==='"')q=false;else field+=c}else if(c==='"')q=true;else if(c===','){row.push(field);field=''}else if(c==='\n'||c==='\r'){if(c==='\r'&&text[i+1]==='\n')i++;row.push(field);field='';if(row.some(v=>v!==''))rows.push(row);row=[]}else field+=c}if(field!==''||row.length){row.push(field);if(row.some(v=>v!==''))rows.push(row)}return rows};
const el=(tag,attrs={},text=null)=>{const n=document.createElementNS(NS,tag);for(const[k,v]of Object.entries(attrs))n.setAttribute(k,v);if(text!==null)n.textContent=text;return n};
const num=v=>v!==undefined&&String(v).trim()!==''&&Number.isFinite(Number(v))?Number(v):null;
const months={Jan:'01',Feb:'02',Mar:'03',Apr:'04',May:'05',Jun:'06',Jul:'07',Aug:'08',Sep:'09',Oct:'10',Nov:'11',Dec:'12'};
const parseMySugrDate=v=>{const m=String(v||'').trim().match(/^([A-Z][a-z]{2})\s+(\d{1,2}),\s+(\d{4})$/);return m&&months[m[1]]?`${m[3]}-${months[m[1]]}-${m[2].padStart(2,'0')}`:null};
const wallClockMs=(date,clock)=>{const d=String(date||'').match(/^(\d{4})-(\d{2})-(\d{2})$/);if(!d)return null;let hh=0,mm=0,ss=0;if(clock){const t=String(clock).match(/^(\d{1,2}):(\d{2})(?::(\d{2})(?:\.\d+)?)?(?:\s*(AM|PM))?$/i);if(!t)return null;hh=Number(t[1]);mm=Number(t[2]);ss=Number(t[3]||0);if(t[4]){hh%=12;if(t[4].toUpperCase()==='PM')hh+=12}}return Date.UTC(Number(d[1]),Number(d[2])-1,Number(d[3]),hh,mm,ss)};
function parseGlucose(rows){const hi=rows.findIndex(r=>r.includes('Date')&&r.includes('Time')&&r.includes('Blood Sugar Measurement (mg/dL)'));if(hi<0)throw Error('mySugr CSV header not found.');const h=rows[hi],di=h.indexOf('Date'),ti=h.indexOf('Time'),vi=h.indexOf('Blood Sugar Measurement (mg/dL)');return rows.slice(hi+1).flatMap(r=>{const date=parseMySugrDate(r[di]),value=num(r[vi]),clock=r[ti]||'',time=date?wallClockMs(date,clock):null;if(!date||date<START||date>END||value===null||time===null)return[];const m=clock.match(/\b(AM|PM)\b/i);if(!m)return[];return[{date,time,clock,value,period:m[1].toUpperCase()}]}).sort((a,b)=>a.time-b.time)}
function parsePressure(rows){const hi=rows.findIndex(r=>r.some(c=>c.endsWith('.start_time'))&&r.some(c=>c.endsWith('.systolic'))&&r.some(c=>c.endsWith('.diastolic')));if(hi<0)throw Error('Blood-pressure CSV header not found.');const h=rows[hi],di=h.findIndex(c=>c.endsWith('.start_time')),si=h.findIndex(c=>c.endsWith('.systolic')),ai=h.findIndex(c=>c.endsWith('.diastolic'));return rows.slice(hi+1).flatMap(r=>{const raw=r[di]||'',date=raw.slice(0,10),clock=raw.slice(11,19),systolic=num(r[si]),diastolic=num(r[ai]),time=wallClockMs(date,clock);if(date<START||date>END||systolic===null||diastolic===null||time===null)return[];return[{date,time,clock,systolic,diastolic}]}).sort((a,b)=>a.time-b.time)}
function niceDomain(values){if(!values.length)return[0,1];let lo=Math.min(...values),hi=Math.max(...values);if(lo===hi){const p=Math.max(Math.abs(lo)*.08,1);return[lo-p,hi+p]}const pad=(hi-lo)*.08;return[lo-pad,hi+pad]}
function showTooltip(box,event,lines){box.textContent=lines.join('\n');box.style.display='block';const parent=box.parentElement.getBoundingClientRect(),w=box.offsetWidth,h=box.offsetHeight;let left=event.clientX-parent.left+12,top=event.clientY-parent.top+12;if(left+w>parent.width)left=Math.max(0,event.clientX-parent.left-w-12);if(top+h>parent.height)top=Math.max(0,event.clientY-parent.top-h-12);box.style.left=`${left}px`;box.style.top=`${top}px`}
function draw({svgId,tooltipId,records,series,yLabel}){const svg=document.getElementById(svgId),tip=document.getElementById(tooltipId),W=1400,H=500,m={l:70,r:28,t:34,b:62},iw=W-m.l-m.r,ih=H-m.t-m.b;while(svg.firstChild)svg.removeChild(svg.firstChild);tip.style.display='none';if(!records.length){svg.append(el('text',{x:W/2,y:H/2,'text-anchor':'middle',fill:css('--muted')},'No qualifying readings in this range.'));return}
const first=records[0],last=records[records.length-1];let x0=first.time,x1=last.time;if(x0===x1){x0-=12*3600000;x1+=12*3600000}const visitTime=wallClockMs(VISIT,'12:00:00');if(visitTime>=x0&&visitTime<=x1){x0=Math.min(x0,visitTime);x1=Math.max(x1,visitTime)}const values=records.flatMap(r=>series.map(s=>r[s.key]));let[y0,y1]=niceDomain(values);const x=t=>m.l+(t-x0)/(x1-x0)*iw,y=v=>m.t+ih-(v-y0)/(y1-y0)*ih;
for(let i=0;i<=5;i++){const val=y1-(y1-y0)*i/5,yy=m.t+ih*i/5;svg.append(el('line',{x1:m.l,x2:W-m.r,y1:yy,y2:yy,stroke:css('--grid')}));svg.append(el('text',{x:m.l-10,y:yy+4,'text-anchor':'end','font-size':12,fill:css('--muted')},String(Math.round(val))))}
const firstDay=new Date(first.date+'T00:00:00Z'),lastDay=new Date(last.date+'T00:00:00Z'),days=Math.max(1,Math.round((lastDay-firstDay)/86400000)),ticks=Math.min(9,Math.max(2,Math.ceil(days/7)));for(let i=0;i<=ticks;i++){const t=x0+(x1-x0)*i/ticks,xx=x(t);svg.append(el('line',{x1:xx,x2:xx,y1:m.t,y2:m.t+ih,stroke:css('--grid'),'stroke-dasharray':'2 5'}));const label=new Date(t).toLocaleDateString('en-US',{month:'short',day:'numeric',timeZone:'UTC'});svg.append(el('text',{x:xx,y:H-20,'text-anchor':i===0?'start':i===ticks?'end':'middle','font-size':11,fill:css('--muted')},label))}
svg.append(el('line',{x1:m.l,x2:W-m.r,y1:m.t+ih,y2:m.t+ih,stroke:'#94a3b8'}));svg.append(el('line',{x1:m.l,x2:m.l,y1:m.t,y2:m.t+ih,stroke:'#94a3b8'}));svg.append(el('text',{x:15,y:19,'font-size':12,fill:css('--muted')},yLabel));if(visitTime>=x0&&visitTime<=x1){const vx=x(visitTime);svg.append(el('line',{x1:vx,x2:vx,y1:m.t,y2:m.t+ih,stroke:css('--visit'),'stroke-width':2,'stroke-dasharray':'7 5'}));svg.append(el('text',{x:Math.min(vx+5,W-m.r-120),y:m.t+14,'font-size':11,fill:css('--visit')},'Doctor visit · Oct 6'))}
for(const s of series){const path=records.map((r,i)=>`${i?'L':'M'}${x(r.time).toFixed(2)},${y(r[s.key]).toFixed(2)}`).join(' ');if(records.length>1)svg.append(el('path',{d:path,fill:'none',stroke:s.color,'stroke-width':2.4,'stroke-linecap':'round','stroke-linejoin':'round'}))}
for(const r of records)for(const s of series){const p=el('circle',{cx:x(r.time),cy:y(r[s.key]),r:4.2,fill:s.color,stroke:'#fff','stroke-width':1.2,tabindex:'0','aria-label':`${r.date} ${r.clock}: ${s.name} ${r[s.key]} ${s.unit}`});p.append(el('title',{},`${r.date} ${r.clock}: ${s.name} ${r[s.key]} ${s.unit}`));const lines=series.length>1?[`${r.date} ${r.clock}`,`Systolic: ${r.systolic} mmHg`,`Diastolic: ${r.diastolic} mmHg`]:[`${r.date} ${r.clock}`,`${s.name}: ${r[s.key]} ${s.unit}`];p.addEventListener('mouseenter',e=>showTooltip(tip,e,lines));p.addEventListener('mousemove',e=>showTooltip(tip,e,lines));p.addEventListener('mouseleave',()=>tip.style.display='none');p.addEventListener('focus',e=>showTooltip(tip,e,lines));p.addEventListener('blur',()=>tip.style.display='none');svg.append(p)}}
const mean=(a,k)=>a.length?(a.reduce((s,r)=>s+r[k],0)/a.length).toFixed(1):'—';const median=(a,k)=>{if(!a.length)return'—';const v=a.map(r=>r[k]).sort((x,y)=>x-y),n=v.length;return(n%2?v[(n-1)/2]:(v[n/2-1]+v[n/2])/2).toFixed(1)};const range=(a,k)=>a.length?`${Math.min(...a.map(r=>r[k]))}–${Math.max(...a.map(r=>r[k]))}`:'—';
function analysisBox(id,title,records,keys,units,groupName){const box=document.getElementById(id);box.replaceChildren();const h=document.createElement('h3');h.textContent=title;box.append(h);const pre=records.filter(r=>r.date<VISIT),post=records.filter(r=>r.date>=VISIT),metrics=document.createElement('div');metrics.className='metrics';const add=(label,value)=>{const d=document.createElement('div');d.className='metric';const b=document.createElement('strong');b.textContent=value;d.append(b,document.createTextNode(label));metrics.append(d)};add(`${groupName} recorded readings`,String(records.length));add('Before Oct 6',String(pre.length));add('On/after Oct 6',String(post.length));for(let i=0;i<keys.length;i++){const k=keys[i],u=units[i];add(`Mean · ${k}`,records.length?`${mean(records,k)} ${u}`:'—');add(`Median · ${k}`,records.length?`${median(records,k)} ${u}`:'—');add(`Range · ${k}`,records.length?`${range(records,k)} ${u}`:'—');add(`Pre-visit mean · ${k}`,pre.length?`${mean(pre,k)} ${u}`:'—');add(`Post-visit mean · ${k}`,post.length?`${mean(post,k)} ${u}`:'—')}box.append(metrics);const p=document.createElement('p');p.className='interpretation';if(!records.length)p.textContent='No readings in this period.';else p.textContent=`${records.length} ${groupName.toLowerCase()} readings, from ${records[0].date} through ${records[records.length-1].date}. Pre-/post-visit means compare readings before October 6 with readings on or after October 6; they are descriptive summaries, not evidence that the visit caused a change.`;box.append(p)}
function main(){const glucose=DATA.glucose,pressure=DATA.pressure,am=glucose.filter(r=>r.period==='AM'),pm=glucose.filter(r=>r.period==='PM');draw({svgId:'pressureChart',tooltipId:'pressureTooltip',records:pressure,series:[{key:'systolic',name:'Systolic',unit:'mmHg',color:css('--blue')},{key:'diastolic',name:'Diastolic',unit:'mmHg',color:css('--cyan')}],yLabel:'mmHg'});draw({svgId:'glucoseAMChart',tooltipId:'glucoseAMTooltip',records:am,series:[{key:'value',name:'Glucose',unit:'mg/dL',color:css('--orange')}],yLabel:'mg/dL'});draw({svgId:'glucosePMChart',tooltipId:'glucosePMTooltip',records:pm,series:[{key:'value',name:'Glucose',unit:'mg/dL',color:css('--orange')}],yLabel:'mg/dL'});analysisBox('pressureAnalysis','Blood pressure analysis',pressure,['systolic','diastolic'],['mmHg','mmHg'],'Blood pressure');analysisBox('glucoseAMAnalysis','AM glucose analysis',am,['value'],['mg/dL'],'AM');analysisBox('glucosePMAnalysis','PM glucose analysis',pm,['value'],['mg/dL'],'PM');const s=document.getElementById('status');s.textContent=`Loaded ${pressure.length} blood-pressure records and ${am.length} AM / ${pm.length} PM glucose records. Hover or focus a point to see its date, time, and value.`;s.style.background='#ecfdf3';s.style.color='#166534'}
try{main()}catch(e){document.getElementById('status').textContent=`Could not render data: ${e.message}`}
})();
</script></body></html>
'''


def label(date: str, with_year: bool = True) -> str:
    parsed = datetime.strptime(date, "%Y-%m-%d")
    return f"{parsed.strftime('%b')} {parsed.day}" + (f", {parsed.year}" if with_year else "")


def render(glucose: list[dict[str, Any]], pressure: list[dict[str, Any]],
           start: str, end: str, visit: str) -> str:
    data = json.dumps({"glucose": glucose, "pressure": pressure}).replace("</", "<\\/")
    replacements = {
        "__START_LABEL__": label(start), "__END_LABEL__": label(end),
        "__VISIT_LABEL__": label(visit), "__VISIT_SHORT__": label(visit, False),
        "__START__": start, "__END__": end, "__VISIT__": visit, "__DATA__": data,
    }
    page = HTML_TEMPLATE
    for key, value in replacements.items():
        page = page.replace(key, value)
    return page


def main() -> None:
    here = Path(__file__).resolve().parent
    parser = argparse.ArgumentParser(description="Generate the health report page from CSV exports.")
    parser.add_argument("--glucose", type=Path, default=here / DEFAULT_GLUCOSE)
    parser.add_argument("--pressure", type=Path, default=here / DEFAULT_PRESSURE)
    parser.add_argument("--output", type=Path, default=here / DEFAULT_OUTPUT)
    parser.add_argument("--start", default=DEFAULT_START, help="YYYY-MM-DD")
    parser.add_argument("--end", default=DEFAULT_END, help="YYYY-MM-DD")
    parser.add_argument("--visit", default=DEFAULT_VISIT, help="Doctor visit date, YYYY-MM-DD")
    args = parser.parse_args()
    glucose, _ = parse_glucose(args.glucose, args.start, args.end)
    pressure = parse_pressure(args.pressure, args.start, args.end)
    args.output.write_text(render(glucose, pressure, args.start, args.end, args.visit), encoding="utf-8")
    print(f"Wrote {args.output}: {len(glucose)} glucose and {len(pressure)} blood-pressure readings.")


if __name__ == "__main__":
    main()
