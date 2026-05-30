"""
RhythmDash 可视化测试脚本（仅本地调试用，非游戏一部分）
输入: MP3 音频文件
输出: PNG 综合可视化图表，用于目视检查特征提取是否靠谱
"""

import librosa
import librosa.display
import numpy as np
import matplotlib
matplotlib.use("Agg")  # 非交互模式，输出到文件
import matplotlib.pyplot as plt
import matplotlib.patches as mpatches
import argparse
import os
import sys

# 添加同目录的 analyzer 模块
sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
from analyzer import (
    N_FFT, HOP_LENGTH,
    BAND_LOW, BAND_MID, BAND_HIGH,
    detect_bpm, extract_entity_stream, extract_macro_stream,
    frame_to_ms, ms_to_frame,
)

# ============================================================
# 配色方案
# ============================================================

ENTITY_COLORS = {
    "onset_kick":     "#FF6B35",  # 橙红
    "onset_snare":    "#00B4D8",  # 亮蓝
    "onset_hihat":    "#FFD166",  # 金黄
    "onset_crash":    "#EF476F",  # 粉红
    "hold_bass":      "#06D6A0",  # 青绿
    "hold_melody":    "#8338EC",  # 紫色
}

MACRO_COLORS = {
    "energy_buildup": "#FFD166",
    "energy_drop":    "#EF476F",
    "silence_gap":    "#4A4E69",
}


def plot_visualization(y, sr, entity_stream, macro_stream, bpm_map, output_path):
    """
    生成综合可视化图表。
    包含 4 个子图：
      1. 波形概览 + 实体事件标注
      2. 频谱图 + onset 标注
      3. 各实体类型时间线
      4. RMS 能量 + 宏观事件标注
    """
    duration = len(y) / sr
    times = np.linspace(0, duration, len(y))

    fig, axes = plt.subplots(4, 1, figsize=(22, 16), sharex=True)
    fig.suptitle("RhythmDash — Feature Detection Visualization", fontsize=18, fontweight="bold", y=0.98)
    fig.subplots_adjust(hspace=0.35, top=0.94)

    # ==========================================
    # Subplot 1: 波形 + 实体事件散点
    # ==========================================
    ax1 = axes[0]
    ax1.set_title("1. Waveform with Entity Events", fontsize=13, loc="left")
    # 降采样波形（44100 个点太多，降到 ~2000 个点）
    ds_factor = max(1, len(y) // 4000)
    ax1.plot(times[::ds_factor], y[::ds_factor], color="#CCCCCC", linewidth=0.4, alpha=0.6)
    ax1.set_ylabel("Amplitude")

    # 在波形上标注每个实体事件
    for e in entity_stream:
        t = e["time_ms"] / 1000.0
        color = ENTITY_COLORS.get(e["type"], "#888888")
        marker = "|" if "onset" in e["type"] else "o"
        ax1.axvline(x=t, color=color, alpha=0.35, linewidth=0.6 if marker == "|" else 1.0)
        if "onset" in e["type"]:
            ax1.plot(t, 0.85 + e["intensity"] * 0.15, marker=".", color=color,
                     markersize=3, alpha=0.5)

    # 图例
    legend_patches = [mpatches.Patch(color=c, label=t) for t, c in ENTITY_COLORS.items()]
    ax1.legend(handles=legend_patches, loc="upper right", fontsize=7, ncol=3)

    # ==========================================
    # Subplot 2: 频谱图 + onset 叠加
    # ==========================================
    ax2 = axes[1]
    ax2.set_title("2. Spectrogram (Mel-scaled) with Onset Markers", fontsize=13, loc="left")

    S = librosa.feature.melspectrogram(y=y, sr=sr, n_fft=N_FFT, hop_length=HOP_LENGTH, n_mels=128)
    S_db = librosa.power_to_db(S, ref=np.max)
    img = librosa.display.specshow(S_db, sr=sr, hop_length=HOP_LENGTH, x_axis="s",
                                    y_axis="mel", ax=ax2, cmap="magma")
    plt.colorbar(img, ax=ax2, format="%+2.0f dB", shrink=0.8)

    # 在频谱图上标注 onset 事件
    for e in entity_stream:
        if "onset" in e["type"]:
            t = e["time_ms"] / 1000.0
            color = ENTITY_COLORS.get(e["type"], "#ffffff")
            ax2.axvline(x=t, color=color, alpha=0.4, linewidth=0.6)

    # 标注频段范围
    for label, band, ls in [("20-100Hz", BAND_LOW, "--"), ("200-2000Hz", BAND_MID, "--")]:
        y_pos = librosa.hz_to_mel(band[0])
        ax2.axhline(y=y_pos, color="white", linestyle=ls, linewidth=0.5, alpha=0.5)
        ax2.text(1, y_pos + 5, label, color="white", fontsize=7, alpha=0.7, va="bottom")

    # ==========================================
    # Subplot 3: 实体类型时间线
    # ==========================================
    ax3 = axes[2]
    ax3.set_title("3. Entity Stream Timeline by Type", fontsize=13, loc="left")

    entity_types = list(ENTITY_COLORS.keys())
    for row_idx, etype in enumerate(entity_types):
        events = [e for e in entity_stream if e["type"] == etype]
        if not events:
            continue
        color = ENTITY_COLORS[etype]
        for e in events:
            t_start = e["time_ms"] / 1000.0
            t_end = (e["time_ms"] + max(e["duration_ms"], 30)) / 1000.0
            width = t_end - t_start
            alpha = min(1.0, 0.3 + e["intensity"] * 0.7)  # intensity 影响透明度，钳制到 [0,1]
            ax3.barh(row_idx, width, left=t_start, height=0.7, color=color, alpha=alpha, edgecolor="none")

    ax3.set_yticks(range(len(entity_types)))
    ax3.set_yticklabels([t.replace("_", " ") for t in entity_types], fontsize=8)
    ax3.set_ylabel("Entity Type")
    ax3.invert_yaxis()

    # 实体数量标签
    for row_idx, etype in enumerate(entity_types):
        count = sum(1 for e in entity_stream if e["type"] == etype)
        ax3.text(duration + 2, row_idx, f"n={count}", fontsize=7, va="center", color="#666666")

    # ==========================================
    # Subplot 4: RMS 能量 + 宏观事件
    # ==========================================
    ax4 = axes[3]
    ax4.set_title("4. RMS Energy with Macro Events", fontsize=13, loc="left")

    rms = librosa.feature.rms(y=y, frame_length=N_FFT, hop_length=HOP_LENGTH)[0]
    rms_times = librosa.frames_to_time(np.arange(len(rms)), sr=sr, hop_length=HOP_LENGTH)

    if rms.max() > 0:
        rms_norm = rms / rms.max()
    else:
        rms_norm = rms

    ax4.fill_between(rms_times, rms_norm, alpha=0.4, color="#4361EE")
    ax4.plot(rms_times, rms_norm, color="#4361EE", linewidth=0.6)

    # 标注宏观事件
    for m in macro_stream:
        t_start = m["time_ms"] / 1000.0
        t_end = (m["time_ms"] + max(m["duration_ms"], 1000)) / 1000.0
        color = MACRO_COLORS.get(m["type"], "#888888")
        label = m["type"].replace("_", " ")
        # 半透明色块
        ax4.axvspan(t_start, t_end, alpha=0.15, color=color)
        ax4.text(t_start, 0.95, label, fontsize=6, rotation=90, va="top", color=color, alpha=0.7)

    ax4.set_ylabel("RMS Energy (normalized)")
    ax4.set_xlabel(f"Time (seconds) | Total: {duration:.1f}s")
    ax4.set_ylim(0, 1.05)

    # ==========================================
    # BPM 信息文本框
    # ==========================================
    bpm_text = "BPM Map:\n"
    for b in bpm_map:
        time_sec = b["time_ms"] / 1000.0
        bpm_text += f"  @{time_sec:.1f}s → {b['bpm']:.1f} BPM\n"

    fig.text(0.01, 0.01, bpm_text, fontsize=8, family="monospace",
             bbox=dict(boxstyle="round", facecolor="#F8F9FA", alpha=0.9))

    # ==========================================
    # 保存
    # ==========================================
    os.makedirs(os.path.dirname(output_path), exist_ok=True)
    fig.savefig(output_path, dpi=150, bbox_inches="tight", facecolor="white")
    plt.close(fig)
    print(f"[visualize] Saved: {output_path}")


def main():
    parser = argparse.ArgumentParser(description="RhythmDash 特征可视化工具（本地测试用）")
    parser.add_argument("--audio_name", default="Aorist.mp3", help="音频文件名")
    parser.add_argument("--audio_path", default=None, help="或直接指定音频路径")
    parser.add_argument("--difficulty", default="REMASTER", help="要可视化的难度（默认 REMASTER 显示全部）")
    args = parser.parse_args()

    BASE_DIR = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))

    if args.audio_path:
        audio_path = args.audio_path
    else:
        audio_path = os.path.join(BASE_DIR, "assets", "audio", args.audio_name)

    base_name = os.path.splitext(os.path.basename(audio_path))[0]
    output_dir = os.path.join(BASE_DIR, "assets", "debug")

    print(f"[visualize] Loading: {audio_path}")
    y, sr = librosa.load(audio_path, sr=None)

    print("[visualize] Detecting BPM...")
    _, bpm_map = detect_bpm(y, sr)
    print(f"  BPM map: {bpm_map}")

    print("[visualize] Extracting entity stream...")
    entity_stream = extract_entity_stream(y, sr)
    print(f"  Total entities: {len(entity_stream)}")

    print("[visualize] Extracting macro stream...")
    macro_stream = extract_macro_stream(y, sr)
    print(f"  Total macro events: {len(macro_stream)}")

    # 统计
    type_counts = {}
    for e in entity_stream:
        type_counts[e["type"]] = type_counts.get(e["type"], 0) + 1
    print("  Entity breakdown:")
    for t, c in sorted(type_counts.items()):
        print(f"    {t}: {c}")

    output_path = os.path.join(output_dir, f"{base_name}_viz.png")
    plot_visualization(y, sr, entity_stream, macro_stream, bpm_map, output_path)


if __name__ == "__main__":
    main()