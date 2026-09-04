#!/usr/bin/env python3
"""Generate the repository's SVG brand and user-story assets.

SVG generation uses only the Python standard library. Passing --png-dir
optionally renders 2x PNG previews when CairoSVG and Pillow are available.
"""

from __future__ import annotations

import argparse
import json
from html import escape
from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]
ASSETS = ROOT / "assets"
BENCHMARK_RESULT = ROOT / "evals" / "public" / "sce-1.2.json"

NAVY = "#0B1020"
NAVY_2 = "#141B31"
PAPER = "#F7F5EF"
WHITE = "#FFFFFF"
INK = "#171C2C"
MUTED = "#687086"
CORAL = "#FF6B4A"
CORAL_LIGHT = "#FFF0EC"
SOFT_BLUE = "#5B8DEF"
GREEN = "#19A974"
GREEN_LIGHT = "#EAF8F2"
LINE = "#DDE1EA"
FONT = "Inter,-apple-system,BlinkMacSystemFont,'Segoe UI','PingFang SC','Microsoft YaHei',sans-serif"


def text(
    x: int,
    y: int,
    content: str,
    *,
    size: int = 24,
    color: str = INK,
    weight: int = 400,
    anchor: str = "start",
    opacity: float = 1,
    spacing: float = 0,
) -> str:
    return (
        f'<text x="{x}" y="{y}" fill="{color}" font-family="{FONT}" '
        f'font-size="{size}" font-weight="{weight}" text-anchor="{anchor}" '
        f'dominant-baseline="middle" opacity="{opacity}" '
        f'letter-spacing="{spacing}">{escape(content)}</text>'
    )


def rect(
    x: int,
    y: int,
    width: int,
    height: int,
    *,
    fill: str,
    radius: int = 16,
    stroke: str | None = None,
    stroke_width: int = 1,
    opacity: float = 1,
    shadow: bool = False,
) -> str:
    stroke_attrs = (
        f' stroke="{stroke}" stroke-width="{stroke_width}"' if stroke else ""
    )
    filter_attr = ' filter="url(#shadow)"' if shadow else ""
    return (
        f'<rect x="{x}" y="{y}" width="{width}" height="{height}" rx="{radius}" '
        f'fill="{fill}" opacity="{opacity}"{stroke_attrs}{filter_attr}/>'
    )


def base_svg(width: int, height: int, background: str, body: str) -> str:
    raw = f"""<?xml version="1.0" encoding="UTF-8"?>
<svg xmlns="http://www.w3.org/2000/svg" viewBox="0 0 {width} {height}" width="{width}" height="{height}" role="img">
  <defs>
    <linearGradient id="hero-bg" x1="0" y1="0" x2="1" y2="1">
      <stop offset="0" stop-color="{NAVY}"/>
      <stop offset="1" stop-color="#1B2340"/>
    </linearGradient>
    <filter id="shadow" x="-8%" y="-8%" width="116%" height="116%">
      <feDropShadow dx="0" dy="4" stdDeviation="8" flood-color="{NAVY}" flood-opacity="0.10"/>
    </filter>
    <marker id="arrow-coral" markerWidth="10" markerHeight="8" refX="9" refY="4" orient="auto">
      <polygon points="0 0, 10 4, 0 8" fill="{CORAL}"/>
    </marker>
    <marker id="arrow-green" markerWidth="10" markerHeight="8" refX="9" refY="4" orient="auto">
      <polygon points="0 0, 10 4, 0 8" fill="{GREEN}"/>
    </marker>
  </defs>
  <rect width="{width}" height="{height}" fill="{background}"/>
  {body}
</svg>
"""
    return "\n".join(line.rstrip() for line in raw.splitlines()) + "\n"


def logo_mark(x: int, y: int, size: int, *, background: str = CORAL) -> str:
    scale = size / 96
    return f"""
    <g transform="translate({x} {y}) scale({scale})">
      <rect width="96" height="96" rx="24" fill="{background}"/>
      <path d="M22 24h52a8 8 0 0 1 8 8v27a8 8 0 0 1-8 8H48L34 79V67H22a8 8 0 0 1-8-8V32a8 8 0 0 1 8-8Z" fill="{WHITE}"/>
      <circle cx="34" cy="46" r="5" fill="{CORAL}"/>
      <circle cx="48" cy="46" r="5" fill="{CORAL}" opacity="0.55"/>
      <path d="M60 46h10" stroke="{GREEN}" stroke-width="7" stroke-linecap="round"/>
    </g>
    """


def make_logo() -> str:
    body = f"""
    <rect x="0" y="0" width="512" height="512" rx="112" fill="{NAVY}"/>
    <circle cx="420" cy="92" r="56" fill="{CORAL}" opacity="0.14"/>
    {logo_mark(112, 112, 288)}
    """
    return base_svg(512, 512, NAVY, body)


def make_hero() -> str:
    parts: list[str] = []
    parts.append('<rect width="1280" height="720" fill="url(#hero-bg)"/>')
    parts.append('<circle cx="1160" cy="90" r="170" fill="#FFFFFF" opacity="0.025"/>')
    parts.append('<circle cx="70" cy="680" r="210" fill="#FF6B4A" opacity="0.055"/>')
    parts.append(logo_mark(68, 58, 72))
    parts.append(text(164, 96, "STOP CHATTER", size=24, color=WHITE, weight=800, spacing=3))
    parts.append(text(72, 198, "让 LLM 只输出你要的最终结果", size=22, color="#CBD2E4", weight=600))
    parts.append(text(72, 268, "避免多余解释", size=52, color=CORAL, weight=850))
    parts.append(text(72, 338, "和过程留痕！", size=56, color=CORAL, weight=850))

    pills = [("CURSOR", 72, 126), ("CODEX", 214, 118), ("CLAUDE CODE", 348, 174)]
    for label, x, width in pills:
        parts.append(rect(x, 402, width, 42, fill="#FFFFFF", radius=21, opacity=0.08, stroke="#FFFFFF", stroke_width=1))
        parts.append(text(x + width // 2, 424, label, size=13, color=WHITE, weight=700, anchor="middle", spacing=1))

    parts.append(text(72, 520, "轻量 Skill", size=17, color=WHITE, weight=700))
    parts.append(text(172, 520, "+", size=17, color=CORAL, weight=800))
    parts.append(text(196, 520, "可选确定性门禁", size=17, color=WHITE, weight=700))
    parts.append(text(72, 558, "纠正需求后，删除旧想法，而不是继续解释它。", size=17, color="#AAB3CB"))

    parts.append(rect(748, 48, 472, 624, fill="#FFFFFF", radius=28, opacity=0.055, stroke="#FFFFFF", stroke_width=1))
    parts.append(text(786, 86, "对话噪音", size=14, color="#AAB3CB", weight=700, spacing=1))

    parts.append(rect(786, 108, 394, 50, fill=WHITE, radius=12, opacity=0.96))
    parts.append(text(806, 124, "需求", size=11, color=MUTED, weight=800, spacing=1))
    parts.append(text(806, 144, "番茄炒蛋", size=18, color="#1B2340", weight=700))

    parts.append(rect(786, 166, 394, 50, fill="#FFD8CF", radius=12))
    parts.append(text(806, 182, "擅自扩展", size=11, color=CORAL, weight=800, spacing=1))
    parts.append(text(806, 202, "+ 东坡肉", size=18, color="#5D2B24", weight=700))

    parts.append(text(786, 238, "纠正之后还留下", size=12, color="#E7A193", weight=700, spacing=0.6))
    residue = [
        (252, "解释：", "PR 写成「番茄炒蛋（无东坡肉）」"),
        (308, "标签：", "方案被叫成「简洁高效不啰嗦版」"),
        (364, "测试：", "用例还在测「为什么没有东坡肉」"),
        (420, "记忆：", "记下「用户不喜欢东坡肉」"),
    ]
    for y, label, detail in residue:
        parts.append(rect(786, y, 394, 50, fill="#FFD8CF", radius=12))
        parts.append(text(806, y + 16, label, size=11, color=CORAL, weight=800, spacing=1))
        parts.append(text(806, y + 36, detail, size=15, color="#5D2B24", weight=650))

    parts.append('<line x1="983" y1="478" x2="983" y2="508" stroke="#FF6B4A" stroke-width="3" marker-end="url(#arrow-coral)"/>')
    parts.append(rect(914, 484, 138, 26, fill=NAVY_2, radius=13, stroke=CORAL))
    parts.append(text(983, 498, "RECOMPILE", size=10, color=CORAL, weight=800, anchor="middle", spacing=1.2))

    parts.append(rect(786, 518, 394, 122, fill=GREEN_LIGHT, radius=18, stroke=GREEN, stroke_width=2, shadow=True))
    parts.append(text(812, 544, "当前目标", size=12, color=GREEN, weight=800, spacing=1))
    parts.append(text(812, 586, "番茄炒蛋", size=30, color=INK, weight=800))
    parts.append(text(812, 616, "只输出你要的最终结果", size=14, color=MUTED))
    parts.append('<circle cx="1140" cy="568" r="20" fill="#19A974"/>')
    parts.append('<path d="M1130 568l7 7 14-16" fill="none" stroke="#FFFFFF" stroke-width="4" stroke-linecap="round" stroke-linejoin="round"/>')

    parts.append(text(72, 664, "CURRENT TARGET IN · CORRECTION HISTORY OUT", size=12, color="#78839F", weight=700, spacing=1.4))
    return base_svg(1280, 720, NAVY, "".join(parts))


def make_hero_en() -> str:
    parts: list[str] = []
    parts.append('<rect width="1280" height="720" fill="url(#hero-bg)"/>')
    parts.append('<circle cx="1160" cy="90" r="170" fill="#FFFFFF" opacity="0.025"/>')
    parts.append('<circle cx="70" cy="680" r="210" fill="#FF6B4A" opacity="0.055"/>')
    parts.append(logo_mark(68, 58, 72))
    parts.append(text(164, 96, "STOP CHATTER", size=24, color=WHITE, weight=800, spacing=3))
    parts.append(text(72, 198, "Make LLMs output only the result you asked for", size=20, color="#CBD2E4", weight=600))
    parts.append(text(72, 268, "No extra explanation.", size=40, color=CORAL, weight=850))
    parts.append(text(72, 338, "No process residue.", size=44, color=CORAL, weight=850))

    pills = [("CURSOR", 72, 126), ("CODEX", 214, 118), ("CLAUDE CODE", 348, 174)]
    for label, x, width in pills:
        parts.append(rect(x, 402, width, 42, fill="#FFFFFF", radius=21, opacity=0.08, stroke="#FFFFFF", stroke_width=1))
        parts.append(text(x + width // 2, 424, label, size=13, color=WHITE, weight=700, anchor="middle", spacing=1))

    parts.append(text(72, 520, "Lightweight skill", size=17, color=WHITE, weight=700))
    parts.append(text(202, 520, "+", size=17, color=CORAL, weight=800))
    parts.append(text(226, 520, "optional deterministic gate", size=17, color=WHITE, weight=700))
    parts.append(text(72, 558, "After a correction, delete the old idea—do not keep explaining it.", size=16, color="#AAB3CB"))

    parts.append(rect(748, 48, 472, 624, fill="#FFFFFF", radius=28, opacity=0.055, stroke="#FFFFFF", stroke_width=1))
    parts.append(text(786, 86, "CONVERSATION NOISE", size=14, color="#AAB3CB", weight=700, spacing=1))

    parts.append(rect(786, 108, 394, 50, fill=WHITE, radius=12, opacity=0.96))
    parts.append(text(806, 124, "REQUEST", size=11, color=MUTED, weight=800, spacing=0.8))
    parts.append(text(806, 144, "Tomato and egg stir-fry", size=16, color="#1B2340", weight=700))

    parts.append(rect(786, 166, 394, 50, fill="#FFD8CF", radius=12))
    parts.append(text(806, 182, "UNASKED ADDITION", size=11, color=CORAL, weight=800, spacing=0.8))
    parts.append(text(806, 202, "+ Dongpo pork", size=16, color="#5D2B24", weight=700))

    parts.append(text(786, 238, "STILL LEFT AFTER THE CORRECTION", size=11, color="#E7A193", weight=700, spacing=0.6))
    residue = [
        (252, "EXPLAIN:", 'PR titled "stir-fry (no pork)"'),
        (308, "LABEL:", 'shipped as "no-fluff edition"'),
        (364, "TEST:", "tests still prove the pork is gone"),
        (420, "MEMORY:", '"user dislikes Dongpo pork"'),
    ]
    for y, label, detail in residue:
        parts.append(rect(786, y, 394, 50, fill="#FFD8CF", radius=12))
        parts.append(text(806, y + 16, label, size=11, color=CORAL, weight=800, spacing=0.8))
        parts.append(text(806, y + 36, detail, size=14, color="#5D2B24", weight=650))

    parts.append('<line x1="983" y1="478" x2="983" y2="508" stroke="#FF6B4A" stroke-width="3" marker-end="url(#arrow-coral)"/>')
    parts.append(rect(914, 484, 138, 26, fill=NAVY_2, radius=13, stroke=CORAL))
    parts.append(text(983, 498, "RECOMPILE", size=10, color=CORAL, weight=800, anchor="middle", spacing=1.2))

    parts.append(rect(786, 518, 394, 122, fill=GREEN_LIGHT, radius=18, stroke=GREEN, stroke_width=2, shadow=True))
    parts.append(text(812, 544, "CURRENT TARGET", size=11, color=GREEN, weight=800, spacing=1))
    parts.append(text(812, 586, "Tomato and egg stir-fry", size=22, color=INK, weight=800))
    parts.append(text(812, 616, "Only the result you asked for", size=14, color=MUTED))
    parts.append('<circle cx="1140" cy="568" r="20" fill="#19A974"/>')
    parts.append('<path d="M1130 568l7 7 14-16" fill="none" stroke="#FFFFFF" stroke-width="4" stroke-linecap="round" stroke-linejoin="round"/>')

    parts.append(text(72, 664, "CURRENT TARGET IN · CORRECTION HISTORY OUT", size=12, color="#78839F", weight=700, spacing=1.4))
    return base_svg(1280, 720, NAVY, "".join(parts))


def step_card(
    x: int,
    y: int,
    width: int,
    number: str,
    title: str,
    detail: str,
    *,
    accent: str,
    fill: str,
) -> str:
    return "".join(
        [
            rect(x, y, width, 64, fill=fill, radius=12, stroke=accent, stroke_width=1),
            f'<circle cx="{x + 28}" cy="{y + 32}" r="15" fill="{accent}"/>',
            text(x + 28, y + 33, number, size=12, color=WHITE, weight=800, anchor="middle"),
            text(x + 56, y + 22, title, size=15, color=INK, weight=750),
            text(x + 56, y + 44, detail, size=12, color=MUTED),
        ]
    )


def make_user_story() -> str:
    parts: list[str] = []
    parts.append(text(64, 54, "你要一道菜，Agent 却交付一段纠错史", size=30, color=INK, weight=800))
    parts.append(text(64, 90, "同一次纠正，在 artifact 里会走向两种完全不同的结果", size=16, color=MUTED))

    parts.append(rect(40, 122, 560, 548, fill=WHITE, radius=24, stroke="#F1BEB3", shadow=True))
    parts.append(rect(680, 122, 560, 548, fill=WHITE, radius=24, stroke="#A9DFC9", shadow=True))
    parts.append(rect(64, 144, 142, 34, fill=CORAL_LIGHT, radius=17))
    parts.append(text(135, 162, "普通 Agent", size=14, color=CORAL, weight=800, anchor="middle"))
    parts.append(rect(704, 144, 156, 34, fill=GREEN_LIGHT, radius=17))
    parts.append(text(782, 162, "STOP CHATTER", size=14, color=GREEN, weight=800, anchor="middle", spacing=0.8))

    left_steps = [
        ("1", "用户要：番茄炒蛋", "目标本来很清楚"),
        ("2", "Agent 擅自加：东坡肉", "“顺便完善一下”开始扩张"),
        ("3", "用户纠正：去掉", "旧想法没有从内部目标中删除"),
        ("4", "PR：番茄炒蛋（无东坡肉）", "标题、注释、测试继续复述纠错史"),
        ("5", "长任务：东坡肘子复活", "被否定概念换个近义变体重新出现"),
    ]
    for index, (number, title_, detail) in enumerate(left_steps):
        parts.append(step_card(64, 194 + index * 72, 512, number, title_, detail, accent=CORAL, fill=CORAL_LIGHT))

    parts.append(rect(64, 568, 512, 74, fill=NAVY, radius=14))
    parts.append(text(88, 592, "结果", size=11, color="#AAB3CB", weight=800, spacing=1))
    parts.append(text(88, 618, "多余功能 + 交付物解释 + 过程留痕", size=18, color=WHITE, weight=750))

    right_steps = [
        ("1", "重编译当前正向目标", "现在只需要：番茄炒蛋"),
        ("2", "剪掉旧想法的依赖链", "实现、配置、测试、注释、UI、PR、记忆"),
        ("3", "逐项追溯到有效需求", "没有独立理由的改动直接删除"),
        ("4", "交付当前状态", "不展示纠错史，不制造“无 X 版”"),
    ]
    for index, (number, title_, detail) in enumerate(right_steps):
        parts.append(step_card(704, 194 + index * 78, 512, number, title_, detail, accent=GREEN, fill=GREEN_LIGHT))

    parts.append(rect(704, 520, 512, 122, fill=NAVY, radius=16))
    parts.append(text(730, 548, "最终 artifact", size=11, color="#AAB3CB", weight=800, spacing=1))
    parts.append(text(730, 590, "番茄炒蛋", size=30, color=WHITE, weight=850))
    parts.append(text(730, 620, "只描述现在要什么", size=14, color="#A9DFC9", weight=650))
    parts.append('<circle cx="1170" cy="581" r="22" fill="#19A974"/>')
    parts.append('<path d="M1159 581l8 8 15-18" fill="none" stroke="#FFFFFF" stroke-width="4" stroke-linecap="round" stroke-linejoin="round"/>')

    parts.append('<circle cx="640" cy="386" r="30" fill="#FFFFFF" stroke="#DDE1EA" filter="url(#shadow)"/>')
    parts.append('<path d="M628 386h23m-8-9 9 9-9 9" fill="none" stroke="#19A974" stroke-width="3" stroke-linecap="round" stroke-linejoin="round"/>')
    return base_svg(1280, 720, PAPER, "".join(parts))


def make_user_story_en() -> str:
    parts: list[str] = []
    parts.append(text(64, 54, "You asked for a dish. The agent shipped its correction history.", size=29, color=INK, weight=800))
    parts.append(text(64, 90, "One correction can produce two very different artifacts", size=16, color=MUTED))

    parts.append(rect(40, 122, 560, 548, fill=WHITE, radius=24, stroke="#F1BEB3", shadow=True))
    parts.append(rect(680, 122, 560, 548, fill=WHITE, radius=24, stroke="#A9DFC9", shadow=True))
    parts.append(rect(64, 144, 156, 34, fill=CORAL_LIGHT, radius=17))
    parts.append(text(142, 162, "TYPICAL AGENT", size=13, color=CORAL, weight=800, anchor="middle"))
    parts.append(rect(704, 144, 156, 34, fill=GREEN_LIGHT, radius=17))
    parts.append(text(782, 162, "STOP CHATTER", size=14, color=GREEN, weight=800, anchor="middle", spacing=0.8))

    left_steps = [
        ("1", "User asks: tomato & egg", "The target starts clear"),
        ("2", "Agent adds: Dongpo pork", "“Helpful” scope expansion begins"),
        ("3", "User says: remove it", "The old idea stays inside the working target"),
        ("4", 'PR: “Tomato & egg (no pork)”', "Titles, comments, and tests repeat the mistake"),
        ("5", "Long task: pork elbow returns", "The rejected idea comes back under a nearby name"),
    ]
    for index, (number, title_, detail) in enumerate(left_steps):
        parts.append(step_card(64, 194 + index * 72, 512, number, title_, detail, accent=CORAL, fill=CORAL_LIGHT))

    parts.append(rect(64, 568, 512, 74, fill=NAVY, radius=14))
    parts.append(text(88, 592, "RESULT", size=11, color="#AAB3CB", weight=800, spacing=1))
    parts.append(text(88, 618, "Extra scope + artifact commentary + process residue", size=16, color=WHITE, weight=750))

    right_steps = [
        ("1", "Recompile the positive target", "What is wanted now: tomato & egg"),
        ("2", "Prune the old dependency cone", "Code, config, tests, comments, UI, PR, memory"),
        ("3", "Trace changes to active needs", "Delete anything without independent support"),
        ("4", "Ship the current state", "No correction history. No “without X” edition"),
    ]
    for index, (number, title_, detail) in enumerate(right_steps):
        parts.append(step_card(704, 194 + index * 78, 512, number, title_, detail, accent=GREEN, fill=GREEN_LIGHT))

    parts.append(rect(704, 520, 512, 122, fill=NAVY, radius=16))
    parts.append(text(730, 548, "FINAL ARTIFACT", size=11, color="#AAB3CB", weight=800, spacing=1))
    parts.append(text(730, 590, "Tomato & egg stir-fry", size=27, color=WHITE, weight=850))
    parts.append(text(730, 620, "Only the current requested result", size=14, color="#A9DFC9", weight=650))
    parts.append('<circle cx="1170" cy="581" r="22" fill="#19A974"/>')
    parts.append('<path d="M1159 581l8 8 15-18" fill="none" stroke="#FFFFFF" stroke-width="4" stroke-linecap="round" stroke-linejoin="round"/>')

    parts.append('<circle cx="640" cy="386" r="30" fill="#FFFFFF" stroke="#DDE1EA" filter="url(#shadow)"/>')
    parts.append('<path d="M628 386h23m-8-9 9 9-9 9" fill="none" stroke="#19A974" stroke-width="3" stroke-linecap="round" stroke-linejoin="round"/>')
    return base_svg(1280, 720, PAPER, "".join(parts))


def benchmark_metric_row(
    parts: list[str],
    x: int,
    y: int,
    label: str,
    value: float,
    accent: str,
) -> None:
    parts.append(text(x, y, label, size=12, color=MUTED, weight=650))
    parts.append(text(x + 332, y, f"{value:.1f}%", size=12, color=INK, weight=750, anchor="end"))
    parts.append(rect(x, y + 14, 332, 8, fill="#E8EAF0", radius=4))
    if value > 0:
        parts.append(rect(x, y + 14, round(332 * value / 100), 8, fill=accent, radius=4))


def make_benchmark_chart(*, english: bool) -> str:
    summary = json.loads(BENCHMARK_RESULT.read_text(encoding="utf-8"))
    tasks = int(summary["tasks_per_condition"])
    total = int(summary["total_tasks"])
    light_rate = summary["conditions"]["light"]["rate"]
    guarded_rate = summary["conditions"]["guarded"]["rate"]
    copy = {
        "title": "ChatterBench — deliverable success" if english else "ChatterBench — 交付物成功率",
        "subtitle": (
            f"{summary['cases']} correction scenarios × {summary['repeats']} repeats × 3 modes · grok-4.6 + GLM-5.3"
            if english
            else f"{summary['cases']} 个纠错场景 × {summary['repeats']} 次重复 × 3 种模式 · grok-4.6 + GLM-5.3"
        ),
        "badge": f"{total} TASKS · 2 HOSTS" if english else f"{total} 次任务 · 两套宿主",
        "success": "successful" if english else "次成功",
        "requirements": "Current requirements kept" if english else "当前需求仍在",
        "artifact": "Rejected content absent" if english else "仍在文件无撤回词",
        "surface": "Retired files removed" if english else "撤回功能面已删除",
        "footer": (
            f"Light {light_rate:.1f}%. Guarded {guarded_rate:.1f}%."
            if english
            else f"Light {light_rate:.1f}% · Guarded {guarded_rate:.1f}%"
        ),
        "limit": (
            "Synthetic correction tasks · two hosts · reply wording is not scored"
            if english
            else "合成纠错场景 · 两套宿主 · 回复措辞不计分"
        ),
        "mode_notes": {
            "baseline": "No Stop Chatter" if english else "未使用 Stop Chatter",
            "light": "Skill only" if english else "只使用 Skill",
            "guarded": "Skill + checker" if english else "Skill + 确定性门禁",
        },
    }

    parts: list[str] = []
    parts.append(text(48, 52, copy["title"], size=30, color=INK, weight=850))
    parts.append(text(48, 88, copy["subtitle"], size=15, color=MUTED, weight=500))
    parts.append(rect(948, 34, 284, 40, fill=NAVY, radius=20))
    parts.append(text(1090, 55, copy["badge"], size=12, color=WHITE, weight=800, anchor="middle", spacing=0.5))

    cards = [
        ("baseline", "Baseline", "#7B8499", 40),
        ("light", "Light", SOFT_BLUE, 450),
        ("guarded", "Guarded", GREEN, 860),
    ]
    for key, label, accent, x in cards:
        values = summary["conditions"][key]
        parts.append(rect(x, 122, 380, 410, fill=WHITE, radius=22, stroke=accent, stroke_width=2, shadow=True))
        parts.append(rect(x, 122, 380, 58, fill=accent, radius=21))
        parts.append(f'<rect x="{x}" y="158" width="380" height="22" fill="{accent}"/>')
        parts.append(text(x + 190, 151, label, size=19, color=WHITE, weight=850, anchor="middle", spacing=0.6))
        parts.append(text(x + 28, 228, f"{values['rate']:.1f}%", size=46, color=accent, weight=900))
        parts.append(
            text(
                x + 352,
                228,
                f"{values['successes']} / {tasks} {copy['success']}",
                size=13,
                color=INK,
                weight=700,
                anchor="end",
            )
        )
        benchmark_metric_row(parts, x + 24, 286, copy["requirements"], values["active_requirements_preserved"], accent)
        benchmark_metric_row(parts, x + 24, 346, copy["artifact"], values["artifact_residue_free"], accent)
        benchmark_metric_row(parts, x + 24, 406, copy["surface"], values["retired_surface_removed"], accent)
        parts.append(rect(x + 24, 472, 332, 36, fill="#F4F5F8", radius=10))
        parts.append(
            text(
                x + 190,
                491,
                copy["mode_notes"][key],
                size=12,
                color=INK,
                weight=700,
                anchor="middle",
            )
        )

    parts.append(rect(40, 558, 1200, 132, fill=NAVY, radius=16))
    parts.append(text(64, 604, copy["footer"], size=22, color=WHITE, weight=750))
    parts.append(text(64, 650, copy["limit"], size=14, color="#AAB3CB", weight=500))
    return base_svg(1280, 720, PAPER, "".join(parts))


def make_results_table(*, english: bool) -> str:
    summary = json.loads(BENCHMARK_RESULT.read_text(encoding="utf-8"))
    tasks = int(summary["tasks_per_condition"])
    headers = (
        ["Mode", "Deliverable success", "Requirements kept", "Rejected content gone", "Retired files removed"]
        if english
        else ["模式", "交付物成功", "当前需求仍在", "仍在文件无撤回词", "撤回功能面已删除"]
    )
    col_x = [40, 248, 496, 744, 992]
    parts: list[str] = []
    parts.append(rect(24, 16, 1232, 268, fill=WHITE, radius=20, stroke=LINE, shadow=True))
    for x, label in zip(col_x, headers):
        parts.append(text(x + 16, 52, label, size=14, color=MUTED, weight=700))
    parts.append(f'<line x1="48" y1="76" x2="1232" y2="76" stroke="{LINE}" stroke-width="1"/>')
    rows = [
        ("baseline", "Baseline", "#7B8499"),
        ("light", "Light", SOFT_BLUE),
        ("guarded", "Guarded", GREEN),
    ]
    for index, (key, label, accent) in enumerate(rows):
        y = 110 + index * 54
        values = summary["conditions"][key]
        parts.append(rect(40, y - 22, 1200, 48, fill="#F7F8FB" if index % 2 else WHITE, radius=10))
        parts.append(text(col_x[0] + 16, y, label, size=18, color=accent, weight=800))
        success = f"{values['successes']} / {tasks}   {values['rate']:.1f}%"
        parts.append(text(col_x[1] + 16, y, success, size=16, color=INK, weight=700))
        parts.append(text(col_x[2] + 16, y, f"{values['active_requirements_preserved']:.1f}%", size=16, color=INK, weight=650))
        parts.append(text(col_x[3] + 16, y, f"{values['artifact_residue_free']:.1f}%", size=16, color=INK, weight=650))
        parts.append(text(col_x[4] + 16, y, f"{values['retired_surface_removed']:.1f}%", size=16, color=INK, weight=650))
    return base_svg(1280, 300, PAPER, "".join(parts))


def make_spacer() -> str:
    return (
        '<?xml version="1.0" encoding="UTF-8"?>\n'
        '<svg xmlns="http://www.w3.org/2000/svg" width="1280" height="1" '
        'viewBox="0 0 1280 1" role="presentation"></svg>\n'
    )


def write_assets() -> list[Path]:
    ASSETS.mkdir(parents=True, exist_ok=True)
    outputs = {
        ASSETS / "logo.svg": make_logo(),
        ASSETS / "hero.svg": make_hero(),
        ASSETS / "hero-en.svg": make_hero_en(),
        ASSETS / "cover.svg": make_hero(),
        ASSETS / "cover-en.svg": make_hero_en(),
        ASSETS / "user-story.svg": make_user_story(),
        ASSETS / "user-story-en.svg": make_user_story_en(),
        ASSETS / "chatterbench.svg": make_benchmark_chart(english=False),
        ASSETS / "chatterbench-en.svg": make_benchmark_chart(english=True),
        ASSETS / "results-table.svg": make_results_table(english=False),
        ASSETS / "results-table-en.svg": make_results_table(english=True),
        ASSETS / "spacer.svg": make_spacer(),
        ASSETS / "benchmark-v2.svg": make_benchmark_chart(english=False),
        ASSETS / "benchmark-v2-en.svg": make_benchmark_chart(english=True),
    }
    for path, content in outputs.items():
        path.write_text(content, encoding="utf-8")
        print(f"Generated {path.relative_to(ROOT)}")
    return list(outputs)


def render_previews(paths: list[Path], output_dir: Path) -> None:
    try:
        import cairosvg
        from PIL import Image
    except ImportError as exc:
        raise SystemExit(
            "--png-dir requires the optional development packages cairosvg and Pillow"
        ) from exc

    output_dir.mkdir(parents=True, exist_ok=True)
    for source in paths:
        output = output_dir / f"{source.stem}.png"
        cairosvg.svg2png(url=str(source), write_to=str(output), scale=2)
        with Image.open(output) as image:
            print(f"Rendered {output} ({image.width}x{image.height})")


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument(
        "--png-dir",
        type=Path,
        help="optionally render 2x PNG previews into this directory",
    )
    args = parser.parse_args()
    outputs = write_assets()
    if args.png_dir:
        render_previews(outputs, args.png_dir.expanduser().resolve())
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
