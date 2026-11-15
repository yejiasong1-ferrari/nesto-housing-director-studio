#!/usr/bin/env python3
"""Generate the repository's accessible, code-native system diagrams."""
from pathlib import Path
from html import escape

OUT = Path(__file__).resolve().parents[1] / 'docs/assets'
INK, MUTED, GOLD, GREEN = '#edf2f7', '#9aafc2', '#d6b16c', '#7ac6aa'

def start(title, desc, height=600):
    return [f'<svg xmlns="http://www.w3.org/2000/svg" viewBox="0 0 1160 {height}" role="img" aria-labelledby="title desc"><title id="title">{escape(title)}</title><desc id="desc">{escape(desc)}</desc><defs><marker id="arrow" markerWidth="8" markerHeight="8" refX="7" refY="4" orient="auto"><path d="M0 0L8 4L0 8" fill="{GOLD}"/></marker><style>text{{font-family:Arial,Helvetica,sans-serif}}.line{{fill:none;stroke:{GOLD};stroke-width:1.5;marker-end:url(#arrow)}}</style></defs><rect width="1160" height="{height}" rx="12" fill="#0d1825"/>',
            text(36, 39, title, 23, INK), text(36, 67, desc, 13)]

def text(x,y,value,size=14,color=MUTED):
    return f'<text x="{x}" y="{y}" font-size="{size}" fill="{color}">{escape(value)}</text>'

def box(x,y,w,h,title,lines,tag=None,color=GOLD):
    s=f'<rect x="{x}" y="{y}" width="{w}" height="{h}" rx="9" fill="#152333" stroke="#314457"/>'
    s+=f'<rect x="{x}" y="{y+13}" width="3" height="25" rx="1.5" fill="{color}"/>'
    s+=text(x+20,y+30,title,17,INK)
    for i,line in enumerate(lines):s+=text(x+20,y+57+i*23,line,13)
    if tag:s+=text(x+20,y+h-16,tag,11,color)
    return s

def arrow(x1,y1,x2,y2):return f'<path class="line" d="M{x1} {y1} L{x2} {y2}"/>'
def path(d):return f'<path class="line" d="{d}"/>'
def save(name,parts):OUT.joinpath(name).write_text('\n'.join(parts+['</svg>'])+'\n')

s=start('System overview','Three planes connect human intent, private computation and inspectable artifacts.',610)
s += [text(36,108,'01 / INTERACTION',11,GOLD),text(427,108,'02 / PRIVATE PROCESSING',11,GOLD),text(850,108,'03 / ARTIFACTS',11,GOLD),
      box(36,128,330,168,'Private Next.js Studio',['Footage, brief and property metadata','Authenticated job creation','Human review and script revisions'],'SEPARATE PRIVATE DEPLOYMENT'),
      box(36,352,330,160,'Public project page',['Recorded system walkthrough','Eight-agent workflow and diagrams','Source code and media provenance'],'VIDEO PLAYBACK ONLY · NO UPLOAD',GREEN),
      box(427,128,350,168,'FastAPI + worker',['API contracts and job orchestration','Vision, planning, script and voice','Timeline, editing, render and review'],'EIGHT AGENTS · SHARED PROJECT STATE'),
      box(427,352,350,160,'Execution services',['Model inference and speech synthesis','MoviePy / FFmpeg media processing','Measured audio and render timing'],'SERVER ENVIRONMENT CREDENTIALS',GREEN),
      box(850,128,274,168,'Structured project state',['Scene evidence and director plan','Narration and voice specifications','Timeline and evaluation reports'],'INSPECTABLE DECISIONS'),
      box(850,352,274,160,'Production artifacts',['Narrated video and subtitles','Render timing and output metadata','Local or configured object storage'],'RUNTIME DATA EXCLUDED FROM GIT',GREEN),
      arrow(366,210,427,210),arrow(777,210,850,210),arrow(777,432,850,432),arrow(602,296,602,352),
      path('M985 512 L985 539 L201 539 L201 512'),text(394,531,'Selected recording published for viewing',12),
      text(36,581,'PUBLIC PRESENTATION',11,GOLD),text(215,581,'Recorded playback and architecture only. Upload and processing remain in the private Studio.',13)]
save('system-overview.svg',s)

s=start('Agent collaboration','Eight specialized responsibilities share one project state; execution stays separate from reasoning.',640)
xs=[36,324,612,900];w=224;h=140
data=[('01 / Vision',['Rooms and visual evidence','Reusable scene inventory'],'PERCEIVE'),('02 / Planner',['Brief, highlights and scene roles','Narrative attention budget'],'PLAN'),('03 / Script',['Scene-grounded narration','Style and coverage constraints'],'WRITE'),('04 / Voice',['Delivery and pronunciation','TTS execution + measurement'],'SPEAK')]
for x,(title,lines,tag) in zip(xs,data):s.append(box(x,125,w,h,title,lines,tag))
for i in range(3):s.append(arrow(xs[i]+w,195,xs[i+1],195))
bottom=[('08 / Evaluation',['Alignment and technical checks','Bounded correction routing'],'REVIEW'),('07 / Rendering',['Deterministic media operations','MoviePy / FFmpeg video output'],'EXECUTE'),('06 / Editing',['Pacing and visual treatment','Subtitle and audio strategy'],'DIRECT'),('05 / Timeline',['Pre-TTS budget validation','Post-TTS window alignment'],'ALIGN')]
for x,(title,lines,tag) in zip(xs,bottom):s.append(box(x,350,w,h,title,lines,tag,GREEN))
for i in range(3,0,-1):s.append(arrow(xs[i],420,xs[i-1]+w,420))
s += [arrow(1012,265,1012,350),
      '<rect x="324" y="286" width="512" height="43" rx="7" fill="#d6b16c12" stroke="#7a6745"/>',text(345,313,'SHARED PROJECT STATE  /  versioned, structured stage artifacts',13,GOLD),
      path('M148 490 L148 530 L724 530 L724 490'),text(281,521,'Bounded correction pass when constraints fail',13),
      text(36,586,'HYBRID CONTROL',11,GREEN),text(207,586,'LLMs support perception and language decisions. Validators, routing and rendering enforce explicit constraints.',12)]
save('agent-workflow.svg',s)

s=start('Data and credential boundaries','Public code can be inspected. Private media and provider credentials remain in their own execution boundary.',620)
for x,label,color in [(36,'PUBLIC REPOSITORY',GOLD),(427,'YOUR BROWSER / DEVICE',GREEN),(818,'PRIVATE SERVER',GOLD)]:
 s += [f'<rect x="{x}" y="110" width="306" height="390" rx="12" fill="none" stroke="#314457" stroke-dasharray="5 5"/>',text(x+20,141,label,12,color)]
s += [box(56,164,266,130,'Curated source',['Application and agent code','Generic configuration templates'],'NO RUNTIME WORKSPACES'),
      box(56,326,266,130,'Publication checks',['Working tree + Git history scan','Secret-value comparison locally'],'NO SECRETS IN SCAN OUTPUT'),
      box(447,164,266,130,'Recorded presentation',['Previously rendered video','Project and architecture diagrams'],'VIEWING ONLY · NO FILE INPUT',GREEN),
      box(447,326,266,130,'Video playback',['Play, seek and download recording','No generation or editing controls'],'NO PROJECT OR CREDENTIAL STORAGE',GREEN),
      box(838,164,266,130,'Environment + access',['Provider API keys on the server','Authenticated private Studio'],'NEVER BUNDLED INTO FRONTEND'),
      box(838,326,266,130,'Processing and storage',['Model / TTS calls from the worker','Private runtime media and artifacts'],'CONFIGURED BY THE OPERATOR'),
      arrow(342,220,427,220),arrow(580,294,580,326),arrow(971,294,971,326),
      text(36,554,'PUBLIC VIEWING',11,GREEN),text(191,554,'The public page does not accept uploads or call the private processing service.',13),
      text(36,583,'BEFORE PUBLISHING',11,GOLD),text(191,583,'Scan source and history. Review your media, metadata and permissions before sharing your own output.',13)]
save('data-boundaries.svg',s)
print('Built 3 system diagrams.')
