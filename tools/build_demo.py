#!/usr/bin/env python3
"""Build a narrated public demo from an existing local Nesto workspace.

Requires FFmpeg. Provider calls are not made. Original footage credits remain
visible; only the background music is replaced with the saved TTS-only track.
"""
from __future__ import annotations

import argparse
import base64
from html import escape
import json
from pathlib import Path
import shutil
import subprocess
import tempfile


def run(args: list[str]) -> None:
    result = subprocess.run(args, stdout=subprocess.DEVNULL, stderr=subprocess.PIPE)
    if result.returncode:
        raise RuntimeError(result.stderr.decode(errors="replace")[-3000:])


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--workspace", required=True, type=Path)
    parser.add_argument("--out", type=Path, default=Path("docs/assets"))
    parser.add_argument("--font", type=Path,
                        default=Path("/System/Library/Fonts/Supplemental/Arial.ttf"))
    args = parser.parse_args()
    if not shutil.which("ffmpeg"):
        raise SystemExit("FFmpeg is required on PATH.")
    if not args.font.is_file():
        raise SystemExit("Pass --font with a valid TrueType font path.")
    args.out.mkdir(parents=True, exist_ok=True)
    render = json.loads((args.workspace / "output/render_result_v2.json").read_text())
    source = args.workspace / "output/final_video_v2.mp4"
    duration = float(render["duration"])
    voices = json.loads((args.workspace / "voice/voice_execution.json").read_text())["segments"]
    timing = render["studio_timing"]
    if len(voices) != len(timing):
        raise SystemExit("Saved voice and render timing counts differ.")
    logo = args.out / "nesto-logo.png"
    output = args.out / "generated-output.mp4"
    base = ["ffmpeg", "-hide_banner", "-loglevel", "error", "-y"]
    cmd = base + ["-i", str(source)]
    filters: list[str] = []
    for i, (voice, cue) in enumerate(zip(voices, timing), 1):
        path = args.workspace / "audio" / Path(voice["audio_path"]).name
        if not path.is_file():
            raise SystemExit(f"Missing saved TTS audio: {path.name}")
        cmd += ["-i", str(path)]
        delay = round(float(cue["narration_at"]) * 1000)
        filters.append(f"[{i}:a]aresample=48000,adelay={delay}:all=1[a{i}]")
    labels = "".join(f"[a{i}]" for i in range(1, len(voices) + 1))
    filters.append(labels + f"amix=inputs={len(voices)}:normalize=0,"
                   f"alimiter=limit=0.95,apad,atrim=duration={duration}[narration]")
    cmd += ["-filter_complex", ";".join(filters), "-map", "0:v:0", "-map", "[narration]",
            "-vf", "scale=1280:720,setsar=1", "-c:v", "libx264", "-preset", "fast",
            "-crf", "24", "-pix_fmt", "yuv420p", "-r", "30", "-c:a", "aac",
            "-ar", "48000", "-ac", "2", "-b:a", "128k", "-t", str(duration),
            "-movflags", "+faststart", str(output)]
    run(cmd)
    with tempfile.TemporaryDirectory(prefix="nesto-demo-") as temp:
        temp = Path(temp)

        def card(name: str, seconds: int, lines: list[tuple[str, int, int, int, str]],
                 *, dark: bool = False, brand: bool = False) -> Path:
            dest = temp / f"{name}.mp4"
            color = "#071626" if dark else "#f9f7f2"
            svg = [f'<svg xmlns="http://www.w3.org/2000/svg" width="1280" height="720" viewBox="0 0 1280 720"><rect width="1280" height="720" fill="{color}"/>']
            if brand:
                data = base64.b64encode(logo.read_bytes()).decode()
                svg.append(f'<image href="data:image/png;base64,{data}" x="480" y="45" width="320" height="320"/>')
            for text, x, y, size, ink in lines:
                anchor = "middle" if x == -1 else "start"
                x = 640 if x == -1 else x
                svg.append(f'<text x="{x}" y="{y + size}" text-anchor="{anchor}" font-family="Arial" font-size="{size}" fill="{ink.replace("0x", "#")}">{escape(text)}</text>')
            svg.append('</svg>')
            svg_path, png_path = temp / f"{name}.svg", temp / f"{name}.png"
            svg_path.write_text(''.join(svg))
            run(["node", str(Path(__file__).with_name("render_svg.cjs")), str(svg_path), str(png_path), str(args.font)])
            c = base + ["-loop", "1", "-framerate", "30", "-i", str(png_path), "-f", "lavfi", "-i", "anullsrc=r=48000:cl=stereo", "-map", "0:v", "-map", "1:a", "-t", str(seconds), "-c:v", "libx264", "-preset", "fast", "-crf", "24", "-pix_fmt", "yuv420p", "-c:a", "aac", "-ar", "48000", "-ac", "2", "-b:a", "128k", str(dest)]
            run(c)
            return dest

        intro = card("intro", 5, [
            ("Nesto Housing Director", -1, 390, 52, "0x0b2947"),
            ("Eight agents. One production workflow.", -1, 472, 29, "0x826329"),
            ("An independent AI engineering project by Jiasong Ye", -1, 552, 22, "0x4b5f70"),
        ], brand=True)
        flow_lines = [
            ("From perception to production", 72, 65, 43, "0xf5f2e9"),
            ("Eight specialized agents share a structured Project State", 72, 130, 24, "0xd7ad60"),
        ]
        agents = [
            ("01  VISION", "Rooms and visual facts"),
            ("02  PLANNER", "Highlights and narrative flow"),
            ("03  SCRIPT", "Scene-grounded narration"),
            ("04  VOICE", "Delivery and pronunciation"),
            ("05  TIMELINE", "Measured speech-to-scene timing"),
            ("06  EDITING", "Pacing and subtitle strategy"),
            ("07  RENDERING", "Deterministic media execution"),
            ("08  EVALUATION", "Quality checks and bounded feedback"),
        ]
        for i, (name, role) in enumerate(agents):
            x = 72 + (i % 2) * 600
            y = 220 + (i // 2) * 100
            flow_lines += [(name, x, y, 23, "0xd7ad60"), (role, x, y + 36, 20, "0xc2cfda")]
        flow = card("workflow", 8, flow_lines, dark=True)
        end = card("end", 4, [
            ("Explore the source. Inspect the workflow.", -1, 225, 40, "0x0b2947"),
            ("github.com/yejiasong1-ferrari/nesto-housing-director-demo", -1, 325, 26, "0x826329"),
            ("Recorded output from saved local project artifacts", -1, 405, 22, "0x4b5f70"),
        ])
        concat = temp / "concat.txt"
        concat.write_text("\n".join(f"file '{p.resolve()}'" for p in [intro, flow, output, end]))
        run(base + ["-f", "concat", "-safe", "0", "-i", str(concat), "-c", "copy",
                    "-movflags", "+faststart", str(args.out / "nesto-demo.mp4")])
    run(base + ["-ss", "18", "-i", str(args.out / "nesto-demo.mp4"), "-frames:v", "1",
                "-q:v", "2", str(args.out / "demo-poster.jpg")])
    output.unlink()
    print(f"Built public demo: {args.out / 'nesto-demo.mp4'}")


if __name__ == "__main__":
    main()
