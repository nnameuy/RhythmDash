#!/usr/bin/env python3
"""
RhythmDash 实时调试播放器
=======================
播放 MP3 音乐，同时在浏览器中实时滚动显示特征提取结果。
debug 工具，不修改项目中已有文件。

用法:
  python scripts/play_debug.py --song_name Aorist
  python scripts/play_debug.py --song_name Aorist --difficulty REMASTER
  python scripts/play_debug.py --json_path assets/data/Aorist_REMASTER_data.json --audio_path assets/audio/Aorist.mp3
"""

import argparse
import json
import mimetypes
import os
import re
import socket
import sys
import threading
import urllib.parse
import webbrowser
from http.server import HTTPServer, BaseHTTPRequestHandler
from socketserver import ThreadingMixIn
from pathlib import Path

# ============================================================
# 全局变量（由 main() 设置）
# ============================================================
BASE_DIR = Path(__file__).resolve().parent.parent
AUDIO_PATH = None
JSON_PATH = None
DIFFICULTY_FILES = {}   # {"BASIC": path, "ADVANCED": path, ...}
SONG_NAME = ""
SERVER_READY = threading.Event()


def find_free_port(start=8765, max_attempts=50):
    """找一个空闲端口"""
    for port in range(start, start + max_attempts):
        with socket.socket(socket.AF_INET, socket.SOCK_STREAM) as s:
            if s.connect_ex(("127.0.0.1", port)) != 0:
                return port
    raise RuntimeError(f"找不到空闲端口 (tried {start}-{start + max_attempts})")


# ============================================================
# 多线程 HTTP 服务器（支持浏览器并发请求）
# ============================================================
class ThreadingHTTPServer(ThreadingMixIn, HTTPServer):
    """支持多线程的 HTTP 服务器"""
    daemon_threads = True


# ============================================================
# HTTP 请求处理器
# ============================================================
class DebugHandler(BaseHTTPRequestHandler):
    """处理 HTTP 请求：HTML 页面、JSON 数据、MP3 音频"""

    # 类变量，由 main() 注入
    audio_path = None
    json_path = None
    difficulty_files = {}
    song_name = ""

    def do_GET(self):
        parsed = urllib.parse.urlparse(self.path)
        path = parsed.path

        try:
            if path == "/":
                self._serve_html()
            elif path == "/data.json" or path.startswith("/data/"):
                self._serve_json(path)
            elif path == "/audio.mp3":
                self._serve_audio()
            elif path == "/favicon.ico":
                self.send_response(204)
                self.end_headers()
            else:
                self.send_error(404, f"Not Found: {path}")
        except ConnectionResetError:
            pass
        except BrokenPipeError:
            pass
        except Exception:
            pass

    def do_HEAD(self):
        self.do_GET()

    def do_POST(self):
        parsed = urllib.parse.urlparse(self.path)
        if parsed.path == "/shutdown":
            self.send_response(200)
            self.end_headers()
            threading.Thread(target=self.server.shutdown, daemon=True).start()

    def _serve_html(self):
        self.send_response(200)
        self.send_header("Content-Type", "text/html; charset=utf-8")
        self.send_header("Cache-Control", "no-cache")
        self.end_headers()
        self.wfile.write(HTML_PAGE.encode("utf-8"))

    def _serve_json(self, path):
        """提供 JSON 数据文件"""
        if path == "/data.json":
            file_path = self.json_path
        elif path.startswith("/data/"):
            difficulty = path.split("/")[-1]
            file_path = self.difficulty_files.get(difficulty, "")
        else:
            file_path = self.json_path

        if not file_path or not os.path.isfile(file_path):
            self.send_error(404, f"JSON not found: {path}")
            return

        # 读取文件内容
        with open(file_path, "r", encoding="utf-8") as f:
            content = f.read()

        self.send_response(200)
        self.send_header("Content-Type", "application/json; charset=utf-8")
        self.send_header("Cache-Control", "no-cache")
        self.send_header("Access-Control-Allow-Origin", "*")
        self.send_header("Content-Length", str(len(content.encode("utf-8"))))
        self.end_headers()
        self.wfile.write(content.encode("utf-8"))

    def _serve_audio(self):
        """提供 MP3 音频，支持 Range 请求（浏览器拖进度条必需）"""
        if not os.path.isfile(self.audio_path):
            self.send_error(404, "Audio file not found")
            return

        file_size = os.path.getsize(self.audio_path)
        range_header = self.headers.get("Range")

        if range_header:
            m = re.match(r"bytes=(\d+)-(\d*)", range_header)
            if m:
                start = int(m.group(1))
                end_str = m.group(2)
                end = int(end_str) if end_str else file_size - 1
                end = min(end, file_size - 1)

                self.send_response(206)
                self.send_header("Content-Range", f"bytes {start}-{end}/{file_size}")
                content_length = end - start + 1
            else:
                self.send_response(200)
                content_length = file_size
                start = 0
        else:
            self.send_response(200)
            content_length = file_size
            start = 0

        self.send_header("Content-Type", "audio/mpeg")
        self.send_header("Accept-Ranges", "bytes")
        self.send_header("Content-Length", str(content_length))
        self.end_headers()

        with open(self.audio_path, "rb") as f:
            if start > 0:
                f.seek(start)
            remaining = content_length
            chunk_size = 64 * 1024
            while remaining > 0:
                chunk = f.read(min(chunk_size, remaining))
                if not chunk:
                    break
                self.wfile.write(chunk)
                remaining -= len(chunk)

    def log_message(self, format, *args):
        """抑制默认的访问日志（静默模式）"""
        pass


# ============================================================
# HTML 页面（内嵌完整的前端应用）
# ============================================================
HTML_PAGE = """<!DOCTYPE html>
<html lang="zh-CN">
<head>
<meta charset="UTF-8">
<meta name="viewport" content="width=device-width, initial-scale=1.0">
<title>RhythmDash Debug Player</title>
<style>
  * { margin: 0; padding: 0; box-sizing: border-box; }
  body {
    background: #0f0f1a;
    color: #e0e0e0;
    font-family: 'Segoe UI', 'Microsoft YaHei', sans-serif;
    overflow: hidden;
    height: 100vh;
    display: flex;
    flex-direction: column;
    user-select: none;
    -webkit-user-select: none;
  }
  #header {
    background: #1a1a2e;
    padding: 8px 16px;
    display: flex;
    align-items: center;
    gap: 16px;
    flex-wrap: wrap;
    border-bottom: 1px solid #2a2a4e;
    min-height: 44px;
  }
  #header .title { font-size: 18px; font-weight: bold; color: #e94560; }
  #header .info { font-size: 13px; color: #aaa; }
  #header .info span { color: #FFD166; font-weight: 600; }
  #statusMsg { font-size: 12px; padding: 3px 10px; border-radius: 3px; display: none; }
  #statusMsg.error { background: #3a1010; color: #ff6b6b; display: inline-block; }
  #statusMsg.ok { background: #103a10; color: #6bff6b; display: inline-block; }

  #controls {
    background: #16213e;
    padding: 6px 16px;
    display: flex;
    align-items: center;
    gap: 10px;
    flex-wrap: wrap;
    border-bottom: 1px solid #2a2a4e;
    min-height: 40px;
  }
  button {
    background: #2a2a5e;
    color: #e0e0e0;
    border: 1px solid #3a3a7e;
    border-radius: 4px;
    padding: 6px 14px;
    cursor: pointer;
    font-size: 13px;
    transition: background 0.15s;
  }
  button:hover { background: #3a3a8e; }
  button:active { background: #4a4a9e; }
  button.active { background: #e94560; border-color: #e94560; }
  select {
    background: #2a2a5e;
    color: #e0e0e0;
    border: 1px solid #3a3a7e;
    border-radius: 4px;
    padding: 5px 8px;
    font-size: 13px;
    cursor: pointer;
  }
  select:hover { background: #3a3a8e; }
  label { font-size: 12px; color: #aaa; }
  .sep { width: 1px; height: 20px; background: #2a2a4e; margin: 0 4px; }

  #canvasWrap {
    flex: 1;
    position: relative;
    overflow: hidden;
    cursor: default;
    background: #0f0f1a;
  }
  canvas {
    display: block;
    width: 100%;
    height: 100%;
  }

  #timeline {
    background: #1a1a2e;
    padding: 8px 16px 10px 16px;
    border-top: 1px solid #2a2a4e;
  }
  #timeline input[type=range] {
    width: 100%;
    height: 6px;
    -webkit-appearance: none;
    appearance: none;
    background: #2a2a5e;
    border-radius: 3px;
    outline: none;
    cursor: pointer;
  }
  #timeline input[type=range]::-webkit-slider-thumb {
    -webkit-appearance: none;
    width: 16px;
    height: 16px;
    border-radius: 50%;
    background: #e94560;
    cursor: pointer;
    border: 2px solid #fff;
  }
  #timeLabels {
    display: flex;
    justify-content: space-between;
    font-size: 11px;
    color: #666;
    margin-top: 4px;
  }
</style>
</head>
<body>

<div id="header">
  <span class="title">RhythmDash Debug Player</span>
  <span id="statusMsg">...</span>
  <span class="info">歌曲: <span id="songTitle">加载中...</span></span>
  <span class="info">BPM: <span id="songBpm">--</span></span>
  <span class="info">时长: <span id="songDuration">--</span></span>
  <span class="info">实体数: <span id="entityCount">--</span></span>
</div>

<div id="controls">
  <button id="btnPlay" onclick="togglePlay()" title="空格键">▶ 播放</button>
  <button id="btnStop" onclick="stopPlay()">⏹ 停止</button>
  <span class="sep"></span>
  <label>难度:</label>
  <select id="selDifficulty" onchange="switchDifficulty(this.value)">
    <option value="BASIC">BASIC</option>
    <option value="ADVANCED">ADVANCED</option>
    <option value="EXPERT">EXPERT</option>
    <option value="MASTER">MASTER</option>
    <option value="REMASTER" selected>REMASTER</option>
  </select>
  <span class="sep"></span>
  <label>速度:</label>
  <select id="selSpeed" onchange="setSpeed(this.value)">
    <option value="0.5">0.5x</option>
    <option value="0.75">0.75x</option>
    <option value="1.0" selected>1.0x</option>
    <option value="1.25">1.25x</option>
    <option value="1.5">1.5x</option>
  </select>
  <span class="sep"></span>
  <label>缩放:</label>
  <button onclick="zoomIn()" title="↑ 键或滚轮">＋</button>
  <button onclick="zoomOut()" title="↓ 键或滚轮">－</button>
  <button onclick="resetZoom()">1:1</button>
  <span class="sep"></span>
  <span style="font-size:11px;color:#666;">空格=播放/暂停 ←→=跳5秒 ↑↓=缩放</span>
</div>

<div id="canvasWrap">
  <canvas id="mainCanvas"></canvas>
</div>

<div id="timeline">
  <input type="range" id="scrubber" min="0" max="1000" value="0" step="50"
         oninput="onScrub()" onchange="onScrubEnd()"
         onmousedown="scrubbing=true" onmouseup="onScrubEnd()">
  <div id="timeLabels"><span>0:00</span><span></span><span></span><span></span><span>0:00</span></div>
</div>

<script>
// ============================================================
// 状态
// ============================================================
const audio = new Audio();
audio.volume = 0.8;

let currentDifficulty = "REMASTER";
let songDuration = 0;
let songBpm = 0;
let entities = [];
let macroEvents = [];
let secondIndex = [];
let pixelsPerSec = 200;
let scrubbing = false;
let isPlaying = false;

// 平滑时间
let smoothTime = 0;
let lastAudioTime = 0;
let lastWallTime = 0;

// ============================================================
// DOM 引用
// ============================================================
const elTitle = document.getElementById("songTitle");
const elBpm = document.getElementById("songBpm");
const elDuration = document.getElementById("songDuration");
const elEntityCount = document.getElementById("entityCount");
const elStatus = document.getElementById("statusMsg");
const elBtnPlay = document.getElementById("btnPlay");
const elScrubber = document.getElementById("scrubber");
const elDifficulty = document.getElementById("selDifficulty");

function setStatus(msg, isError) {
    elStatus.textContent = msg;
    elStatus.className = isError ? "error" : "ok";
    elStatus.style.display = "inline-block";
    console.log("[DEBUG]", msg);
}

// ============================================================
// 配色
// ============================================================
const ENTITY_COLORS = {
    "onset_kick":     "#FF6B35",
    "onset_snare":    "#00B4D8",
    "onset_hihat":    "#FFD166",
    "onset_crash":    "#EF476F",
    "hold_bass":      "#06D6A0",
    "hold_melody":    "#8338EC",
};
const MACRO_COLORS = {
    "energy_buildup": "#FFD166",
    "energy_drop":    "#EF476F",
    "silence_gap":    "#4A4E69",
};
const LANE_TYPES = [
    "onset_kick", "onset_snare", "onset_hihat", "onset_crash",
    "hold_bass", "hold_melody",
];
const LANE_LABELS = ["KICK","SNARE","HIHAT","CRASH","BASS","MELODY"];

// ============================================================
// Canvas
// ============================================================
const canvas = document.getElementById("mainCanvas");
const ctx = canvas.getContext("2d");
const canvasWrap = document.getElementById("canvasWrap");

// roundRect polyfill
if (!ctx.roundRect) {
    ctx.roundRect = function(x, y, w, h, r) {
        if (typeof r === "number") r = { tl: r, tr: r, br: r, bl: r };
        this.beginPath();
        this.moveTo(x + r.tl, y);
        this.lineTo(x + w - r.tr, y);
        this.quadraticCurveTo(x + w, y, x + w, y + r.tr);
        this.lineTo(x + w, y + h - r.br);
        this.quadraticCurveTo(x + w, y + h, x + w - r.br, y + h);
        this.lineTo(x + r.bl, y + h);
        this.quadraticCurveTo(x, y + h, x, y + h - r.bl);
        this.lineTo(x, y + r.tl);
        this.quadraticCurveTo(x, y, x + r.tl, y);
        this.closePath();
    };
}

const LABEL_WIDTH = 70;
const LANE_HEIGHT = 36;
const LANE_GAP = 3;
const MACRO_LANE_HEIGHT = 24;
const TOP_PAD = 10;
const PLAYHEAD_FRAC = 0.25;

let lastCanvasW = 0, lastCanvasH = 0;

function resizeCanvas() {
    const rect = canvasWrap.getBoundingClientRect();
    const w = Math.floor(rect.width);
    const h = Math.floor(rect.height);
    if (w === lastCanvasW && h === lastCanvasH) return;
    lastCanvasW = w;
    lastCanvasH = h;
    const dpr = window.devicePixelRatio || 1;
    canvas.width = w * dpr;
    canvas.height = h * dpr;
    canvas.style.width = w + "px";
    canvas.style.height = h + "px";
    ctx.setTransform(1, 0, 0, 1, 0, 0);
    ctx.scale(dpr, dpr);
}

window.addEventListener("resize", resizeCanvas);

// ============================================================
// 数据加载
// ============================================================
async function loadData(difficulty) {
    setStatus("加载 " + difficulty + " 数据...", false);

    const resp = await fetch("/data/" + difficulty);
    if (!resp.ok) throw new Error("HTTP " + resp.status + " " + resp.statusText);

    const text = await resp.text();
    console.log("[DEBUG] loadData: got", text.length, "bytes for", difficulty);

    let data;
    try {
        data = JSON.parse(text);
    } catch (e) {
        throw new Error("JSON 解析失败: " + e.message);
    }

    // 元数据
    const meta = data.metadata;
    if (!meta) throw new Error("JSON 缺少 metadata 字段");

    songDuration = meta.duration_sec || 0;
    elTitle.textContent = meta.title || "???";
    elDuration.textContent = formatTime(songDuration);
    elScrubber.max = Math.floor(songDuration * 1000);
    updateTimeLabels();

    // BPM：取 bpm_map 第一项作为主 BPM
    if (meta.bpm_map && meta.bpm_map.length > 0) {
        songBpm = meta.bpm_map[0].bpm;
        elBpm.textContent = songBpm.toFixed(1);
        console.log("[DEBUG] BPM map:", meta.bpm_map.length, "entries, first BPM:", songBpm);
    } else {
        elBpm.textContent = "--";
    }

    // 实体流
    entities = data.entity_stream || [];
    elEntityCount.textContent = entities.length;
    console.log("[DEBUG] Entity count:", entities.length,
                "first:", entities.length > 0 ? entities[0] : "(empty)",
                "last:", entities.length > 0 ? entities[entities.length-1] : "(empty)");

    // 宏事件（只取一次）
    if (data.macro_stream && data.macro_stream.length > 0) {
        macroEvents = data.macro_stream;
        console.log("[DEBUG] Macro count:", macroEvents.length);
    }

    // 构建时间索引
    buildSecondIndex();
    currentDifficulty = difficulty;

    setStatus(difficulty + ": " + entities.length + " 实体, " + macroEvents.length + " 宏", false);
}

function buildSecondIndex() {
    secondIndex = [];
    if (entities.length === 0) return;
    const totalSec = Math.ceil(songDuration) + 1;
    let idx = 0;
    for (let sec = 0; sec <= totalSec; sec++) {
        const start = idx;
        const threshold = (sec + 1) * 1000;
        while (idx < entities.length && entities[idx].time_ms < threshold) {
            idx++;
        }
        secondIndex[sec] = [start, idx];
    }
    console.log("[DEBUG] secondIndex built:", secondIndex.length, "seconds covered");
}

async function switchDifficulty(diff) {
    try {
        await loadData(diff);
        elDifficulty.value = diff;
    } catch (err) {
        setStatus("切换失败: " + err.message, true);
        console.error(err);
    }
}

// ============================================================
// 可见实体查询
// ============================================================
function getVisibleEntities(currentTimeSec) {
    if (entities.length === 0 || secondIndex.length === 0) {
        return { entityList: [], macroList: macroEvents };
    }
    const dpr = window.devicePixelRatio || 1;
    const drawWidth = canvas.width / dpr - LABEL_WIDTH;
    const halfWinSec = Math.max(1, drawWidth / pixelsPerSec / 2);

    const startSec = Math.max(0, Math.floor(currentTimeSec - halfWinSec));
    const endSec = Math.min(secondIndex.length - 1, Math.ceil(currentTimeSec + halfWinSec));

    const startIdx = secondIndex[startSec] ? secondIndex[startSec][0] : 0;
    const endIdx = secondIndex[endSec] ? secondIndex[endSec][1] : entities.length;

    return {
        entityList: entities.slice(startIdx, endIdx),
        macroList: macroEvents,
    };
}

// ============================================================
// 时间 & 坐标
// ============================================================
function getCurrentTime() {
    if (isPlaying) {
        const rawTime = audio.currentTime;
        const now = performance.now() / 1000;
        const estimated = lastAudioTime + (now - lastWallTime) * audio.playbackRate;
        if (Math.abs(rawTime - estimated) > 0.1) {
            lastAudioTime = rawTime;
            lastWallTime = now;
            smoothTime = rawTime;
        } else {
            smoothTime = estimated;
        }
        return smoothTime;
    }
    return audio.currentTime;
}

function formatTime(sec) {
    if (!isFinite(sec) || sec < 0) sec = 0;
    const m = Math.floor(sec / 60);
    const s = Math.floor(sec % 60);
    return m + ":" + String(s).padStart(2, "0");
}

function entityX(timeMs, currentTimeSec) {
    const dpr = window.devicePixelRatio || 1;
    const drawWidth = canvas.width / dpr - LABEL_WIDTH;
    return LABEL_WIDTH + drawWidth * PLAYHEAD_FRAC + (timeMs / 1000 - currentTimeSec) * pixelsPerSec;
}

function laneY(laneIdx) {
    return TOP_PAD + laneIdx * (LANE_HEIGHT + LANE_GAP);
}

function macroLaneY() {
    return TOP_PAD + LANE_TYPES.length * (LANE_HEIGHT + LANE_GAP) + LANE_GAP;
}

// ============================================================
// 绘制
// ============================================================
function drawBackground(currentTimeSec) {
    const dpr = window.devicePixelRatio || 1;
    const w = canvas.width / dpr;
    const h = canvas.height / dpr;
    const drawWidth = w - LABEL_WIDTH;
    const playheadX = LABEL_WIDTH + drawWidth * PLAYHEAD_FRAC;

    ctx.fillStyle = "#0f0f1a";
    ctx.fillRect(0, 0, w, h);

    for (let i = 0; i < LANE_TYPES.length; i++) {
        const y = laneY(i);
        ctx.fillStyle = (i % 2 === 0) ? "#141428" : "#181830";
        ctx.fillRect(LABEL_WIDTH, y, drawWidth, LANE_HEIGHT);

        ctx.fillStyle = ENTITY_COLORS[LANE_TYPES[i]];
        ctx.font = "bold 12px 'Segoe UI', 'Microsoft YaHei', sans-serif";
        ctx.textAlign = "right";
        ctx.fillText(LANE_LABELS[i], LABEL_WIDTH - 8, y + LANE_HEIGHT / 2 + 4);

        ctx.strokeStyle = "#1a1a3e";
        ctx.lineWidth = 1;
        ctx.beginPath();
        ctx.moveTo(LABEL_WIDTH, y + LANE_HEIGHT + LANE_GAP / 2);
        ctx.lineTo(w, y + LANE_HEIGHT + LANE_GAP / 2);
        ctx.stroke();
    }

    const mY = macroLaneY();
    ctx.fillStyle = "#111125";
    ctx.fillRect(LABEL_WIDTH, mY, drawWidth, MACRO_LANE_HEIGHT);
    ctx.fillStyle = "#666";
    ctx.font = "bold 11px 'Segoe UI', 'Microsoft YaHei', sans-serif";
    ctx.textAlign = "right";
    ctx.fillText("MACRO", LABEL_WIDTH - 8, mY + MACRO_LANE_HEIGHT / 2 + 4);

    // 时间网格
    const visibleStartSec = currentTimeSec - (playheadX - LABEL_WIDTH) / pixelsPerSec;
    const visibleEndSec = currentTimeSec + (w - playheadX) / pixelsPerSec;
    const gridInterval = pixelsPerSec > 400 ? 0.5 : (pixelsPerSec > 150 ? 1 : (pixelsPerSec > 60 ? 2 : 5));

    ctx.strokeStyle = "#1a1a3e";
    ctx.lineWidth = 0.5;
    ctx.setLineDash([4, 8]);
    for (let t = Math.floor(visibleStartSec / gridInterval) * gridInterval; t <= visibleEndSec; t += gridInterval) {
        const x = entityX(t * 1000, currentTimeSec);
        if (x >= LABEL_WIDTH && x <= w) {
            ctx.beginPath();
            ctx.moveTo(x, TOP_PAD);
            ctx.lineTo(x, macroLaneY() + MACRO_LANE_HEIGHT);
            ctx.stroke();
            ctx.fillStyle = "#444";
            ctx.font = "10px monospace";
            ctx.textAlign = "center";
            ctx.fillText(formatTime(t), x, TOP_PAD - 2);
        }
    }
    ctx.setLineDash([]);

    // 播放头
    ctx.strokeStyle = "#ffffff";
    ctx.lineWidth = 2;
    ctx.shadowColor = "rgba(255,255,255,0.4)";
    ctx.shadowBlur = 8;
    ctx.beginPath();
    ctx.moveTo(playheadX, 0);
    ctx.lineTo(playheadX, h);
    ctx.stroke();
    ctx.shadowBlur = 0;

    ctx.fillStyle = "#e94560";
    ctx.beginPath();
    ctx.moveTo(playheadX, 0);
    ctx.lineTo(playheadX - 8, -12);
    ctx.lineTo(playheadX + 8, -12);
    ctx.closePath();
    ctx.fill();
}

function drawMacroEvents(currentTimeSec) {
    const dpr = window.devicePixelRatio || 1;
    const w = canvas.width / dpr;
    const mY = macroLaneY();

    for (const m of macroEvents) {
        const startX = entityX(m.time_ms, currentTimeSec);
        const endX = entityX(m.time_ms + Math.max(m.duration_ms, 500), currentTimeSec);
        const cx = Math.max(LABEL_WIDTH, startX);
        const cw = Math.min(w, endX) - cx;
        if (cw <= 0) continue;

        const color = MACRO_COLORS[m.type] || "#888";

        if (m.type === "energy_drop") {
            const dropX = entityX(m.time_ms, currentTimeSec);
            if (dropX >= LABEL_WIDTH && dropX <= w) {
                ctx.strokeStyle = color;
                ctx.lineWidth = 2;
                ctx.globalAlpha = 0.7;
                ctx.beginPath();
                ctx.moveTo(dropX, mY);
                ctx.lineTo(dropX, mY + MACRO_LANE_HEIGHT);
                ctx.stroke();
                ctx.globalAlpha = 1;
            }
        } else if (m.type === "silence_gap") {
            ctx.fillStyle = color;
            ctx.globalAlpha = 0.5;
            ctx.fillRect(cx, mY + 4, cw, MACRO_LANE_HEIGHT - 8);
            ctx.globalAlpha = 1;
        } else if (m.type === "energy_buildup") {
            const grad = ctx.createLinearGradient(cx, 0, cx + cw, 0);
            grad.addColorStop(0, "rgba(255,209,102,0.1)");
            grad.addColorStop(1, "rgba(255,209,102,0.5)");
            ctx.fillStyle = grad;
            ctx.fillRect(cx, mY + 4, cw, MACRO_LANE_HEIGHT - 8);
        }
    }
}

function drawEntities(currentTimeSec) {
    const dpr = window.devicePixelRatio || 1;
    const w = canvas.width / dpr;
    const { entityList } = getVisibleEntities(currentTimeSec);

    for (const e of entityList) {
        const laneIdx = LANE_TYPES.indexOf(e.type);
        if (laneIdx < 0) continue;

        const x = entityX(e.time_ms, currentTimeSec);
        if (x < LABEL_WIDTH - 20 || x > w + 20) continue;

        const ly = laneY(laneIdx);
        const cy = ly + LANE_HEIGHT / 2;
        const color = ENTITY_COLORS[e.type] || "#fff";
        const intensity = e.intensity || 0.5;

        if (e.type.startsWith("onset_")) {
            drawOnsetMarker(x, cy, e.type, color, intensity);
        } else {
            const endX = entityX(e.time_ms + Math.max(e.duration_ms, 30), currentTimeSec);
            const barX = Math.max(LABEL_WIDTH, x);
            const barW = Math.max(4, Math.min(w, endX) - barX);
            if (barW > 0) {
                ctx.fillStyle = color;
                ctx.globalAlpha = 0.25 + intensity * 0.55;
                const barH = LANE_HEIGHT * 0.55;
                const barY = ly + (LANE_HEIGHT - barH) / 2;
                ctx.beginPath();
                ctx.roundRect(barX, barY, barW, barH, 3);
                ctx.fill();
                ctx.globalAlpha = 1;
            }
        }
    }
}

function drawOnsetMarker(x, y, etype, color, intensity) {
    const size = 3 + intensity * 8;
    ctx.fillStyle = color;
    ctx.globalAlpha = 0.5 + intensity * 0.5;

    switch (etype) {
        case "onset_kick":
            ctx.beginPath();
            ctx.moveTo(x, y - size);
            ctx.lineTo(x + size * 0.7, y);
            ctx.lineTo(x, y + size);
            ctx.lineTo(x - size * 0.7, y);
            ctx.closePath();
            ctx.fill();
            break;
        case "onset_snare":
            ctx.beginPath();
            ctx.arc(x, y, size * 0.75, 0, Math.PI * 2);
            ctx.fill();
            break;
        case "onset_hihat":
            ctx.beginPath();
            ctx.moveTo(x, y - size);
            ctx.lineTo(x + size * 0.8, y + size * 0.6);
            ctx.lineTo(x - size * 0.8, y + size * 0.6);
            ctx.closePath();
            ctx.fill();
            break;
        case "onset_crash":
            drawStar(x, y, size * 0.7, 5);
            ctx.fill();
            break;
        default:
            ctx.beginPath();
            ctx.arc(x, y, size * 0.5, 0, Math.PI * 2);
            ctx.fill();
    }
    ctx.globalAlpha = 1;
}

function drawStar(cx, cy, r, points) {
    const outerR = r;
    const innerR = r * 0.45;
    ctx.beginPath();
    for (let i = 0; i < points * 2; i++) {
        const radius = i % 2 === 0 ? outerR : innerR;
        const angle = (i * Math.PI) / points - Math.PI / 2;
        const x = cx + Math.cos(angle) * radius;
        const y = cy + Math.sin(angle) * radius;
        if (i === 0) ctx.moveTo(x, y);
        else ctx.lineTo(x, y);
    }
    ctx.closePath();
}

// ============================================================
// 动画循环
// ============================================================
function animate() {
    resizeCanvas();

    const dpr = window.devicePixelRatio || 1;
    const w = canvas.width / dpr;
    const h = canvas.height / dpr;
    const currentTimeSec = getCurrentTime();

    ctx.save();
    drawBackground(currentTimeSec);
    drawMacroEvents(currentTimeSec);
    drawEntities(currentTimeSec);

    // 播放头左侧轻微变暗
    const playheadX = LABEL_WIDTH + (w - LABEL_WIDTH) * PLAYHEAD_FRAC;
    ctx.fillStyle = "rgba(15,15,26,0.25)";
    ctx.fillRect(LABEL_WIDTH, 0, playheadX - LABEL_WIDTH, h);
    ctx.restore();

    // 更新时间线（不干扰用户拖动）
    if (!scrubbing) {
        elScrubber.value = Math.floor(currentTimeSec * 1000);
    }

    requestAnimationFrame(animate);
}

// ============================================================
// 音频控制
// ============================================================
function togglePlay() {
    if (audio.paused) {
        const promise = audio.play();
        if (promise !== undefined) {
            promise.then(() => {
                isPlaying = true;
                lastAudioTime = audio.currentTime;
                lastWallTime = performance.now() / 1000;
                smoothTime = lastAudioTime;
                elBtnPlay.textContent = "⏸ 暂停";
                elBtnPlay.classList.add("active");
                setStatus("正在播放", false);
            }).catch(err => {
                setStatus("播放失败: " + err.message + "（请检查音频文件是否正常）", true);
                console.error("Play error:", err);
            });
        }
    } else {
        audio.pause();
        isPlaying = false;
        elBtnPlay.textContent = "▶ 播放";
        elBtnPlay.classList.remove("active");
    }
}

function stopPlay() {
    audio.pause();
    audio.currentTime = 0;
    isPlaying = false;
    smoothTime = 0;
    lastAudioTime = 0;
    lastWallTime = performance.now() / 1000;
    elBtnPlay.textContent = "▶ 播放";
    elBtnPlay.classList.remove("active");
}

function onScrub() {
    const val = parseFloat(elScrubber.value) / 1000;
    audio.currentTime = val;
    smoothTime = val;
    lastAudioTime = val;
    lastWallTime = performance.now() / 1000;
}

function onScrubEnd() {
    scrubbing = false;
    onScrub();
}

function setSpeed(val) {
    audio.playbackRate = parseFloat(val);
}

function zoomIn()  { pixelsPerSec = Math.min(800, pixelsPerSec * 1.3); }
function zoomOut() { pixelsPerSec = Math.max(30, pixelsPerSec / 1.3); }
function resetZoom() { pixelsPerSec = 200; }

// ============================================================
// 键盘快捷键
// ============================================================
document.addEventListener("keydown", (e) => {
    if (e.target.tagName === "INPUT" || e.target.tagName === "SELECT") return;
    switch (e.code) {
        case "Space": e.preventDefault(); togglePlay(); break;
        case "ArrowLeft":
            e.preventDefault();
            audio.currentTime = Math.max(0, audio.currentTime - 5);
            smoothTime = lastAudioTime = audio.currentTime;
            lastWallTime = performance.now() / 1000;
            break;
        case "ArrowRight":
            e.preventDefault();
            audio.currentTime = Math.min(songDuration, audio.currentTime + 5);
            smoothTime = lastAudioTime = audio.currentTime;
            lastWallTime = performance.now() / 1000;
            break;
        case "ArrowUp":    e.preventDefault(); zoomIn(); break;
        case "ArrowDown":  e.preventDefault(); zoomOut(); break;
        case "Home":
            e.preventDefault();
            audio.currentTime = 0;
            smoothTime = lastAudioTime = 0;
            lastWallTime = performance.now() / 1000;
            break;
        case "End":
            e.preventDefault();
            audio.currentTime = songDuration;
            smoothTime = lastAudioTime = songDuration;
            lastWallTime = performance.now() / 1000;
            break;
    }
});

// 滚轮缩放
canvas.addEventListener("wheel", (e) => {
    e.preventDefault();
    if (e.deltaY < 0) zoomIn(); else zoomOut();
}, { passive: false });

// ============================================================
// 时间标签
// ============================================================
function updateTimeLabels() {
    const dur = songDuration || 1;
    const labels = document.getElementById("timeLabels").children;
    labels[0].textContent = "0:00";
    labels[1].textContent = formatTime(dur * 0.25);
    labels[2].textContent = formatTime(dur * 0.5);
    labels[3].textContent = formatTime(dur * 0.75);
    labels[4].textContent = formatTime(dur) || "0:00";
}

// ============================================================
// 音频事件
// ============================================================
audio.addEventListener("loadedmetadata", () => {
    console.log("[DEBUG] Audio metadata loaded, duration:", audio.duration);
    setStatus("音频已就绪", false);
});

audio.addEventListener("error", (e) => {
    setStatus("音频加载失败！请检查 MP3 文件是否存在", true);
    console.error("Audio error:", audio.error);
});

audio.addEventListener("ended", () => {
    isPlaying = false;
    elBtnPlay.textContent = "▶ 播放";
    elBtnPlay.classList.remove("active");
    setStatus("播放完毕", false);
});

// ============================================================
// 启动
// ============================================================
async function init() {
    setStatus("正在连接服务器...", false);

    // 先加载数据
    try {
        await loadData(currentDifficulty);
    } catch (err) {
        setStatus("数据加载失败: " + err.message, true);
        elTitle.textContent = "⚠ 加载失败";
        console.error("Init loadData error:", err);
        // 仍然启动画布（空数据）
    }

    // 再设置音频源（等数据加载完，确保有充分时间让服务器就绪）
    audio.src = "/audio.mp3";
    audio.preload = "auto";
    console.log("[DEBUG] Audio src set to:", audio.src);

    elDifficulty.value = currentDifficulty;

    // 启动动画
    resizeCanvas();
    requestAnimationFrame(animate);
    console.log("[DEBUG] Animation started");
}

// 启动！
init();
</script>
</body>
</html>"""


# ============================================================
# 主入口
# ============================================================
def main():
    global AUDIO_PATH, JSON_PATH, DIFFICULTY_FILES, SONG_NAME

    parser = argparse.ArgumentParser(
        description="RhythmDash 实时调试播放器 — 边听音乐边看特征提取",
        formatter_class=argparse.RawDescriptionHelpFormatter,
        epilog="""
示例:
  python scripts/play_debug.py --song_name Aorist
  python scripts/play_debug.py --song_name Aorist --difficulty REMASTER
""",
    )
    parser.add_argument("--song_name", default=None, help="歌曲名称（不含扩展名），如 Aorist")
    parser.add_argument("--difficulty", default="REMASTER",
                        choices=["BASIC", "ADVANCED", "EXPERT", "MASTER", "REMASTER"],
                        help="初始难度（默认 REMASTER）")
    parser.add_argument("--json_path", default=None, help="直接指定 JSON 数据文件路径")
    parser.add_argument("--audio_path", default=None, help="直接指定 MP3 音频文件路径")
    parser.add_argument("--port", type=int, default=0, help="指定端口（0=自动分配）")
    parser.add_argument("--no-browser", action="store_true", help="不自动打开浏览器")
    args = parser.parse_args()

    # ---- 解析路径 ----
    if args.json_path:
        JSON_PATH = str(Path(args.json_path).resolve())
    elif args.song_name:
        JSON_PATH = str(BASE_DIR / "assets" / "data" / f"{args.song_name}_{args.difficulty}_data.json")
    else:
        print("错误: 请指定 --song_name 或 --json_path")
        sys.exit(1)

    if args.audio_path:
        AUDIO_PATH = str(Path(args.audio_path).resolve())
    elif args.song_name:
        AUDIO_PATH = str(BASE_DIR / "assets" / "audio" / f"{args.song_name}.mp3")
    else:
        guess = Path(JSON_PATH).with_suffix(".mp3")
        if guess.exists():
            AUDIO_PATH = str(guess)
        else:
            print("错误: 请指定 --audio_path（无法自动推断 MP3 路径）")
            sys.exit(1)

    SONG_NAME = args.song_name or Path(JSON_PATH).stem.replace(f"_{args.difficulty}", "")

    # 验证文件
    if not os.path.isfile(JSON_PATH):
        print(f"错误: JSON 文件不存在: {JSON_PATH}")
        sys.exit(1)
    if not os.path.isfile(AUDIO_PATH):
        print(f"错误: MP3 文件不存在: {AUDIO_PATH}")
        sys.exit(1)

    # ---- 构建所有难度文件映射 ----
    json_dir = os.path.dirname(JSON_PATH)
    for diff in ["BASIC", "ADVANCED", "EXPERT", "MASTER", "REMASTER"]:
        candidate = os.path.join(json_dir, f"{SONG_NAME}_{diff}_data.json")
        if os.path.isfile(candidate):
            DIFFICULTY_FILES[diff] = candidate

    if args.difficulty not in DIFFICULTY_FILES:
        DIFFICULTY_FILES[args.difficulty] = JSON_PATH

    # ---- 注入 Handler 类变量 ----
    DebugHandler.audio_path = AUDIO_PATH
    DebugHandler.json_path = JSON_PATH
    DebugHandler.difficulty_files = DIFFICULTY_FILES
    DebugHandler.song_name = SONG_NAME

    # ---- 启动多线程服务器 ----
    port = args.port if args.port > 0 else find_free_port()
    server = ThreadingHTTPServer(("127.0.0.1", port), DebugHandler)
    url = f"http://127.0.0.1:{port}"

    print("=" * 60)
    print("  RhythmDash Debug Player")
    print("=" * 60)
    print(f"  歌曲: {SONG_NAME}")
    print(f"  JSON: {os.path.basename(JSON_PATH)}")
    print(f"  音频: {os.path.basename(AUDIO_PATH)}")
    print(f"  难度: {args.difficulty}")
    print(f"  地址: {url}")
    print()
    print("  操作说明:")
    print("    空格 = 播放/暂停")
    print("    <- -> = 跳 5 秒")
    print("    上下箭头 = 缩放")
    print("    滚轮 = 缩放")
    print("    底部拖动条 = 跳转")
    print("    Ctrl+C = 退出")
    print("=" * 60)

    if not args.no_browser:
        threading.Thread(target=lambda: (
            SERVER_READY.wait(),
            webbrowser.open(url),
        ), daemon=True).start()

    SERVER_READY.set()

    try:
        server.serve_forever()
    except KeyboardInterrupt:
        print("\n已退出。")
        server.shutdown()


if __name__ == "__main__":
    main()
