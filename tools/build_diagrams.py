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
      box(36,352,330,160,'Public project page',['Recorded system walkthrough','Video chapters and download','GitHub source and media provenance'],'VIDEO PLAYBACK ONLY · NO UPLOAD',GREEN),
      box(427,128,350,168,'FastAPI + worker',['API contracts and job orchestration','Vision, planning, script and voice','Timeline, editing, render and review'],'EIGHT AGENTS · SHARED PROJECT STATE'),
      box(427,352,350,160,'Execution services',['Model inference and speech synthesis','MoviePy / FFmpeg media processing','Measured audio and render timing'],'SERVER ENVIRONMENT CREDENTIALS',GREEN),
      box(850,128,274,168,'Structured project state',['Scene evidence and director plan','Narration and voice specifications','Timeline and evaluation reports'],'INSPECTABLE DECISIONS'),
      box(850,352,274,160,'Production artifacts',['Narrated video and subtitles','Render timing and output metadata','Local or configured object storage'],'RUNTIME DATA EXCLUDED FROM GIT',GREEN),
      arrow(366,210,427,210),arrow(777,210,850,210),arrow(777,432,850,432),arrow(602,296,602,352),
      path('M985 512 L985 539 L201 539 L201 512'),text(394,531,'Selected recording published for viewing',12),
      text(36,581,'PUBLIC PRESENTATION',11,GOLD),text(215,581,'Recorded playback only. Architecture is documented in GitHub; processing remains in the private Studio.',13)]
save('system-overview.svg',s)


# Editorial swimlanes: a light palette and a serpentine process show the two
# passes of the Timeline agent explicitly, instead of duplicating a box grid.
def label(x, y, value, size=14, color='#526271'):
    return text(x, y, value, size, color)

s = [
    '<svg xmlns="http://www.w3.org/2000/svg" viewBox="0 0 1160 820" role="img" aria-labelledby="title desc">',
    '<title id="title">Eight agents, three production phases</title><desc id="desc">A swimlane workflow. Vision, Planner and Script build the story. Timeline validates the speech budget before Voice and reconciles measured audio afterward. Editing, Rendering and Evaluation produce and review the output.</desc>',
    '<defs><marker id="flow" markerWidth="8" markerHeight="8" refX="7" refY="4" orient="auto"><path d="M0 0L8 4L0 8" fill="#64809a"/></marker><style>text{font-family:Arial,Helvetica,sans-serif}.flow{fill:none;stroke:#64809a;stroke-width:2;marker-end:url(#flow)}</style></defs>',
    '<rect width="1160" height="820" rx="14" fill="#f6f4ef"/>',
    label(40, 45, 'The production loop', 27, '#20354a'),
    label(40, 75, 'Eight agents, three phases. Timing is checked before and after speech synthesis.', 14),
]
lanes = [
    (118, '#e8eef4', '01 / UNDERSTAND & COMPOSE'),
    (323, '#f0e7d7', '02 / CONSTRAIN & ALIGN'),
    (528, '#e6eee7', '03 / EXECUTE & REVIEW'),
]
for y, color, name in lanes:
    s += [f'<rect x="40" y="{y}" width="1080" height="181" rx="12" fill="{color}"/>', label(61, y+24, name, 11, '#526271')]

def step(x, y, title, lines, badge, color):
    return ''.join([
        f'<rect x="{x}" y="{y}" width="280" height="128" rx="8" fill="#fff" stroke="#d5dde3"/>',
        f'<circle cx="{x+23}" cy="{y+25}" r="5" fill="{color}"/>',
        label(x+38, y+31, title, 18, '#20354a'),
        *[label(x+18, y+59+i*20, line, 12) for i, line in enumerate(lines)],
        label(x+18, y+111, badge, 10, color),
    ])

for x, title, lines, badge in [
    (90, 'Vision', ['Room segments and visible features', 'Reusable scene evidence'], '01 / PERCEPTION'),
    (440, 'Planner', ['Highlights, audience and narrative arc', 'Attention allocation across rooms'], '02 / STORY PLANNING'),
    (790, 'Script', ['Scene-grounded narration', 'Style, coverage and speech estimates'], '03 / WRITING'),
]: s.append(step(x, 158, title, lines, badge, '#426b91'))
for x, title, lines, badge in [
    (90, 'Timeline · reconcile', ['Measured TTS duration and offsets', 'Final scene windows'], '05 / POST-TTS ALIGNMENT'),
    (440, 'Voice + TTS', ['Delivery, rhythm and pronunciation', 'Synthesize speech and measure audio'], '04 / SPEECH DIRECTION'),
    (790, 'Timeline · budget', ['Available scene duration', 'Validate the narration budget'], '05 / PRE-TTS GUARD'),
]: s.append(step(x, 363, title, lines, badge, '#9b7338'))
for x, title, lines, badge in [
    (90, 'Editing', ['Pacing, visual treatment and subtitles', 'Structured editing decisions'], '06 / EDIT DIRECTION'),
    (440, 'Rendering', ['MoviePy / FFmpeg media operations', 'Video and timing manifest'], '07 / DETERMINISTIC EXECUTION'),
    (790, 'Evaluation', ['Alignment and technical checks', 'Categorized correction feedback'], '08 / REVIEW'),
]: s.append(step(x, 568, title, lines, badge, '#4e7b60'))
for d in ['M370 222H440', 'M720 222H790', 'M930 286V363', 'M790 427H720', 'M440 427H370', 'M230 491V568', 'M370 632H440', 'M720 632H790']:
    s.append(f'<path class="flow" d="{d}"/>')
s += ['<path class="flow" d="M930 696V740H230V696" stroke-dasharray="5 5"/>', '<rect x="352" y="722" width="454" height="32" fill="#f6f4ef"/>', label(374,743,'Bounded correction pass when constraints fail',13,'#9b654d'), label(40,790,'Shared Project State links evidence, decisions, measured speech and the final artifact.',13)]
save('agent-workflow.svg', s)

# A trust-boundary map uses circles, a screen and a credential lock rather than
# another rectangular flowchart. Only curated recorded media crosses the gate.
s = [
    '<svg xmlns="http://www.w3.org/2000/svg" viewBox="0 0 1160 690" role="img" aria-labelledby="title desc">',
    '<title id="title">Publication and private processing boundaries</title><desc id="desc">Public source and the recorded video are visible to visitors. Provider credentials, private footage and runtime workspaces remain inside a separate private processing boundary. Only a selected recording is published.</desc>',
    '<defs><marker id="publish" markerWidth="8" markerHeight="8" refX="7" refY="4" orient="auto"><path d="M0 0L8 4L0 8" fill="#c68568"/></marker><style>text{font-family:Arial,Helvetica,sans-serif}</style></defs>',
    '<rect width="1160" height="690" rx="14" fill="#faf7f1"/>',
    label(40,45,'A clear publication boundary',27,'#273b3a'), label(40,75,'The public recording is separate from private media, runtime data and provider credentials.',14),
    '<circle cx="267" cy="342" r="213" fill="#e8f1ec" stroke="#7a9b8a" stroke-width="1.5"/>',
    '<circle cx="889" cy="342" r="227" fill="#f4e9e1" stroke="#bd947e" stroke-width="1.5" stroke-dasharray="6 6"/>',
    label(143,182,'PUBLIC / VIEWING',12,'#507e67'), label(777,170,'PRIVATE / PROCESSING',12,'#9b654d'),
    '<rect x="147" y="218" width="240" height="143" rx="9" fill="#fff" stroke="#7a9b8a" stroke-width="2"/><rect x="159" y="230" width="216" height="119" rx="3" fill="#d4e5dc"/><path d="M252 263L252 316L298 289Z" fill="#507e67"/><path d="M267 362V384M222 385H312" fill="none" stroke="#7a9b8a" stroke-width="2"/>',
    label(175,422,'Recorded video',19,'#273b3a'), label(141,453,'Playback, chapters and download',13), label(148,478,'Source code and architecture',13),
    label(169,518,'NO UPLOAD CONTROLS',11,'#507e67'),
    '<circle cx="889" cy="303" r="90" fill="#fff8f2" stroke="#bd947e" stroke-width="1.5"/>',
    '<path d="M865 286V269A24 24 0 0 1 913 269V286" fill="none" stroke="#a36f56" stroke-width="3"/><rect x="854" y="284" width="70" height="53" rx="7" fill="#c68568"/><circle cx="889" cy="306" r="5" fill="#fff"/><path d="M889 310V320" stroke="#fff" stroke-width="3"/>',
    label(811,366,'Server environment',15,'#9b654d'),
    label(755,420,'API keys and access controls',16,'#493d36'), label(755,450,'Private footage and project files',14), label(755,478,'Model / TTS calls and runtime logs',14), label(792,519,'NEVER IN PUBLIC GIT',11,'#9b654d'),
    '<path d="M670 590H485" fill="none" stroke="#c68568" stroke-width="2" marker-end="url(#publish)"/>',
    '<path d="M582 160V545" fill="none" stroke="#bd947e" stroke-dasharray="3 7"/>',
    '<rect x="515" y="306" width="134" height="58" rx="29" fill="#faf7f1" stroke="#c68568"/>', label(536,330,'REVIEW',12,'#9b654d'), label(535,348,'BEFORE SHARING',9,'#9b654d'),
    label(422,623,'Only the curated recording is published',13,'#9b654d'),
    label(40,665,'Scan source and reachable Git history before publishing. Keep provider credentials on the private server.',12),
]
save('data-boundaries.svg', s)
print('Built three diagrams: blueprint architecture, editorial swimlanes and a trust-boundary map.')
