"""
RhythmDash 音频分析脚本
输入: MP3 音频文件
输出: 符合 Data Contract 的 JSON 关卡数据（5 个难度级别）
"""

import librosa
import numpy as np
import json
import argparse
import os

# ============================================================
# 常量定义（遵循 docs/tech-spec.md 规范）
# ============================================================

N_FFT = 2048
HOP_LENGTH = 512

# 频段定义 (Hz) — 消除 100-200Hz 和 2000-4000Hz 盲区
BAND_LOW = (20, 200)        # 低频：Kick（含次低频 40-80Hz + 主体 80-200Hz）
BAND_MID = (200, 4000)      # 中频：Snare（含鼓腔 200-400Hz + 脆响 1-4kHz）
BAND_HIGH = (4000, None)    # 高频：Hi-hat（4kHz+ 镲片主体）

# Hold 检测：最短持续时间 (秒)
HOLD_MIN_DURATION = 0.2

# Macro 检测参数
BUILDUP_WINDOW_SEC = 8.0     # buildup 检测窗口
SILENCE_RMS_THRESHOLD = 0.02 # 静音 RMS 阈值（相对于最大 RMS）
SILENCE_MIN_DURATION = 0.5   # 最短静音时长 (秒)

# 难度阈值
DIFFICULTY_THRESHOLDS = {
    "BASIC":    0.70,
    "ADVANCED": 0.50,
    "EXPERT":   0.35,
    "MASTER":   0.20,
    "REMASTER": 0.00,
}

# ============================================================
# 工具函数
# ============================================================

def hz_to_bin(freq_hz, sr):
    """将频率 (Hz) 转换为 FFT bin 索引"""
    return int(np.floor(freq_hz * (N_FFT / sr)))

def get_band_energy(S_mag, sr, band):
    """获取指定频段的能量时间序列"""
    low_hz, high_hz = band
    lo = hz_to_bin(low_hz, sr)
    hi = hz_to_bin(high_hz, sr) if high_hz is not None else S_mag.shape[0]
    lo = max(0, lo)
    hi = min(S_mag.shape[0], hi)
    return np.sum(S_mag[lo:hi, :], axis=0)

def ms_to_frame(time_ms, sr):
    """将毫秒时间转换为 STFT 帧索引"""
    return int(time_ms / 1000.0 * sr / HOP_LENGTH)

def frame_to_ms(frame_idx, sr):
    """将 STFT 帧索引转换为毫秒时间"""
    return int(frame_idx * HOP_LENGTH / sr * 1000)

# ============================================================
# BPM 检测
# ============================================================

def detect_bpm(y, sr):
    """
    检测全局 BPM，使用自相关法 + 多起点验证。
    仅在大窗口检测到显著变化时才记录多条 bpm_map。
    返回: (global_bpm, bpm_map)
    """
    onset_env = librosa.onset.onset_strength(y=y, sr=sr)

    # 方法1：自相关法（不依赖起始猜测）
    ac = np.correlate(onset_env, onset_env, mode="full")
    ac = ac[len(ac) // 2:]
    lag_times = np.arange(1, len(ac)) * HOP_LENGTH / sr
    with np.errstate(divide="ignore"):
        bpm_candidates = 60.0 / lag_times
    valid_mask = (bpm_candidates >= 50) & (bpm_candidates <= 250)
    valid_bpm = bpm_candidates[valid_mask]
    valid_ac = ac[1:][valid_mask]
    if len(valid_ac) > 0:
        peak_idx = np.argmax(valid_ac)
        bpm_ac = float(valid_bpm[peak_idx])
    else:
        bpm_ac = 120.0

    # 方法2：多起点 tempo() 交叉验证
    starts = [80, 100, 120, 140, 160, 180, 200]
    tempo_results = []
    for s in starts:
        t = float(librosa.feature.tempo(onset_envelope=onset_env, sr=sr,
                                         start_bpm=s, std_bpm=4)[0])
        tempo_results.append(t)
    closest = min(tempo_results, key=lambda t: abs(t - bpm_ac))
    global_bpm = round((bpm_ac + closest) / 2.0, 1)

    # -- bpm_map：默认只有一条 （恒速歌曲）--
    bpm_map = [{"time_ms": 0, "bpm": float(global_bpm)}]

    # 仅在歌曲 > 60 秒时，用 30 秒重叠窗口检查是否真有变速
    # 要求连续两个窗口都偏离全局 BPM 才记录（防止单窗口假变奏）
    duration_sec = len(y) / sr
    if duration_sec > 60:
        window_sec = 30
        step_sec = 15
        window_bpms = []  # (start_sec, bpm)
        for start_sec in np.arange(0, duration_sec - window_sec, step_sec):
            start_sample = int(start_sec * sr)
            end_sample = start_sample + int(window_sec * sr)
            segment = y[start_sample:end_sample]
            seg_onset = librosa.onset.onset_strength(y=segment, sr=sr)
            seg_ac = np.correlate(seg_onset, seg_onset, mode="full")
            seg_ac = seg_ac[len(seg_ac) // 2:]
            seg_lag = np.arange(1, len(seg_ac)) * HOP_LENGTH / sr
            with np.errstate(divide="ignore"):
                seg_bpm_vals = 60.0 / seg_lag
            seg_v = (seg_bpm_vals >= 50) & (seg_bpm_vals <= 250)
            if seg_v.sum() > 0:
                seg_bpm = float(seg_bpm_vals[seg_v][np.argmax(seg_ac[1:][seg_v])])
                window_bpms.append((start_sec, seg_bpm))

        # 需要两个连续窗口 BPM 接近（相差 < 10）且都偏离全局 BPM > 15
        for i in range(len(window_bpms) - 1):
            t1, b1 = window_bpms[i]
            _, b2 = window_bpms[i + 1]
            if abs(b1 - global_bpm) > 15 and abs(b2 - global_bpm) > 15:
                if abs(b1 - b2) < 10:
                    # 检查与已有最后一条 bpm_map 的差异 > 20
                    last_bpm = bpm_map[-1]["bpm"]
                    if abs(b1 - last_bpm) > 20:
                        bpm_map.append({"time_ms": int(t1 * 1000), "bpm": round(b1, 1)})

    return float(global_bpm), bpm_map


# ============================================================
# Entity Stream 提取（节拍网格法）
# ============================================================

def compute_band_energies_at_frames(S_mag, sr, frames):
    """
    在给定的帧位置，分别计算 LOW/MID/HIGH 三个频段的能量。
    每个位置取前后各 1 帧的窗口平均，抗噪声。
    返回: (low_vals, mid_vals, high_vals) 三个数组
    """
    low_energy = get_band_energy(S_mag, sr, BAND_LOW)
    mid_energy = get_band_energy(S_mag, sr, BAND_MID)
    high_energy = get_band_energy(S_mag, sr, BAND_HIGH)

    n_frames = S_mag.shape[1]
    lows, mids, highs = [], [], []

    for f in frames:
        # 取 f-1 到 f+1 的窗口平均
        win_start = max(0, f - 1)
        win_end = min(n_frames, f + 2)
        lows.append(float(np.mean(low_energy[win_start:win_end])))
        mids.append(float(np.mean(mid_energy[win_start:win_end])))
        highs.append(float(np.mean(high_energy[win_start:win_end])))

    return np.array(lows), np.array(mids), np.array(highs)


def classify_beat_competitive(low, mid, high, low_th, mid_th, high_th):
    """
    竞争分类：三频段不是各自独立判定，而是互相比拼。
    返回: [(type, intensity), ...] 最多 3 个 onset 类型

    规则：
      - 最强频段：超过绝对阈值就发射（保证每拍至少一种）
      - 次强频段：需 > 绝对阈值 且 > 最强的 60% 才发射
      - 最弱频段：需 > 绝对阈值 且 > 最强的 80% 才发射
      - Crash：三频段都超过各自的 2 倍中位数阈值时发射
    """
    bands = [
        ("onset_kick",  low),
        ("onset_snare", mid),
        ("onset_hihat", high),
    ]
    # 按强度降序排列
    bands.sort(key=lambda x: x[1], reverse=True)

    types = []
    e1_name, e1_val = bands[0]
    e2_name, e2_val = bands[1]
    e3_name, e3_val = bands[2]

    ABS_FLOOR = 0.10  # 绝对最低阈值
    REL_SECOND = 0.65  # 次强需达到最强的 65%
    REL_THIRD  = 0.85  # 最弱需达到最强的 85%

    # 最强一定发射（如果超过绝对地板）
    if e1_val > ABS_FLOOR:
        types.append((e1_name, e1_val))

    # 次强：需在绝对地板之上，且相对强度够
    if e2_val > ABS_FLOOR and e2_val > e1_val * REL_SECOND:
        types.append((e2_name, e2_val))

    # 最弱：更严格的条件
    if e3_val > ABS_FLOOR and e3_val > e1_val * REL_THIRD:
        types.append((e3_name, e3_val))

    # Crash：三频段都远超各自中位数
    if low > low_th * 2 and mid > mid_th * 2 and high > high_th * 2:
        types.append(("onset_crash", max(low, mid, high)))

    return types


def detect_melody_holds(y_harmonic, sr, beat_frames, entity_id_start):
    """
    用 pyin 在和声分量上追踪音高，检测持续旋律段落。
    返回: [(hold_melody_dict), ...] 和最终的 entity_id
    """
    fmin = librosa.note_to_hz('C3')   # ~131 Hz
    fmax = librosa.note_to_hz('C7')   # ~2093 Hz

    try:
        f0, voiced_flag, voiced_prob = librosa.pyin(
            y_harmonic,
            fmin=fmin, fmax=fmax,
            sr=sr,
            frame_length=N_FFT,
            hop_length=HOP_LENGTH,
        )
    except Exception:
        return [], entity_id_start  # pyin 可能在某些音频上失败

    if f0 is None or voiced_flag is None:
        return [], entity_id_start

    # 找到 voiced 的连续段落
    holds = []
    entity_id = entity_id_start
    in_phrase = False
    phrase_start = 0
    MIN_PHRASE_FRAMES = int(0.15 * sr / HOP_LENGTH)  # 最短 150ms

    for i in range(len(voiced_flag)):
        if voiced_flag[i] and voiced_prob[i] > 0.6:
            if not in_phrase:
                in_phrase = True
                phrase_start = i
        else:
            if in_phrase:
                duration_frames = i - phrase_start
                if duration_frames >= MIN_PHRASE_FRAMES:
                    # 检查音高稳定性（半音标准差 < 1.0）
                    f0_segment = f0[phrase_start:i]
                    f0_valid = f0_segment[~np.isnan(f0_segment)]
                    if len(f0_valid) > 0:
                        semitones = 12 * np.log2(f0_valid / 440.0) + 69  # MIDI 音符号
                        if np.std(semitones) < 1.0:
                            start_ms = frame_to_ms(phrase_start, sr)
                            end_ms = frame_to_ms(i - 1, sr)
                            # 对齐到最近的节拍
                            beat_times = [frame_to_ms(bf, sr) for bf in beat_frames]
                            start_ms = min(beat_times, key=lambda t: abs(t - start_ms))
                            end_ms = min(beat_times, key=lambda t: abs(t - end_ms))

                            avg_intensity = float(np.mean(voiced_prob[phrase_start:i]))
                            holds.append({
                                "id": entity_id,
                                "type": "hold_melody",
                                "time_ms": start_ms,
                                "duration_ms": max(end_ms - start_ms, 200),
                                "intensity": round(avg_intensity, 3),
                            })
                            entity_id += 1
                in_phrase = False

    # 末尾仍在乐句中
    if in_phrase:
        duration_frames = len(voiced_flag) - phrase_start
        if duration_frames >= MIN_PHRASE_FRAMES:
            f0_segment = f0[phrase_start:]
            f0_valid = f0_segment[~np.isnan(f0_segment)]
            if len(f0_valid) > 0:
                semitones = 12 * np.log2(f0_valid / 440.0) + 69
                if np.std(semitones) < 1.0:
                    start_ms = frame_to_ms(phrase_start, sr)
                    end_ms = frame_to_ms(len(voiced_flag) - 1, sr)
                    beat_times = [frame_to_ms(bf, sr) for bf in beat_frames]
                    start_ms = min(beat_times, key=lambda t: abs(t - start_ms))
                    end_ms = min(beat_times, key=lambda t: abs(t - end_ms))
                    avg_intensity = float(np.mean(voiced_prob[phrase_start:]))
                    holds.append({
                        "id": entity_id,
                        "type": "hold_melody",
                        "time_ms": start_ms,
                        "duration_ms": max(end_ms - start_ms, 200),
                        "intensity": round(avg_intensity, 3),
                    })
                    entity_id += 1

    return holds, entity_id


def extract_entity_stream(y, sr):
    """
    v3: HPSS 分离 + 竞争分类 + pyin 旋律追踪

    步骤:
      0. HPSS 分离打击乐/和声分量
      A. 节拍网格（全音频）
      B. 打击乐分量上计算三频段能量
      C. 竞争分类（每拍 1-2 种，不再全开）
      D. 自适应细分（同上）
      E. 和声分量上用 pyin 追踪旋律
      F. 打击乐分量上检测 hold_bass
    """
    # -- 0. HPSS 分离 --
    y_harmonic, y_percussive = librosa.effects.hpss(y, margin=(1.0, 1.0))

    # 打击乐分量 STFT
    S_perc = librosa.stft(y_percussive, n_fft=N_FFT, hop_length=HOP_LENGTH)
    S_perc_mag = np.abs(S_perc)

    # 原始音频 STFT（用于 beat tracking 的 onset envelope）
    _ = librosa.stft(y, n_fft=N_FFT, hop_length=HOP_LENGTH)

    # -- A. 节拍网格 --
    onset_env = librosa.onset.onset_strength(y=y, sr=sr)
    guide_bpm = float(librosa.feature.tempo(onset_envelope=onset_env, sr=sr,
                                              start_bpm=150, std_bpm=4)[0])

    _, beat_frames = librosa.beat.beat_track(
        y=y, sr=sr, start_bpm=guide_bpm, tightness=200
    )
    beat_frames = np.unique(beat_frames)
    beat_frames = beat_frames[beat_frames < S_perc_mag.shape[1]]

    if len(beat_frames) < 4:
        beat_interval_frames = int(60.0 / guide_bpm * sr / HOP_LENGTH)
        beat_frames = np.arange(0, S_perc_mag.shape[1], beat_interval_frames)

    # -- B. 打击乐分量上计算三频段能量 --
    beat_low, beat_mid, beat_high = compute_band_energies_at_frames(S_perc_mag, sr, beat_frames)

    def safe_norm(arr):
        m = arr.max()
        return arr / m if m > 0 else arr

    beat_low_n = safe_norm(beat_low)
    beat_mid_n = safe_norm(beat_mid)
    beat_high_n = safe_norm(beat_high)

    # 自适应阈值
    low_th  = max(np.median(beat_low_n)  * 0.5, 0.10)
    mid_th  = max(np.median(beat_mid_n)  * 0.5, 0.10)
    high_th = max(np.median(beat_high_n) * 0.5, 0.08)

    # -- C. 竞争分类 --
    entities = []
    entity_id = 0

    for i, bf in enumerate(beat_frames):
        time_ms = frame_to_ms(bf, sr)
        etypes = classify_beat_competitive(
            beat_low_n[i], beat_mid_n[i], beat_high_n[i],
            low_th, mid_th, high_th
        )
        for etype, intensity in etypes:
            dur = {"onset_kick": 80, "onset_snare": 60, "onset_hihat": 30, "onset_crash": 100}
            entities.append({
                "id": entity_id,
                "type": etype,
                "time_ms": time_ms,
                "duration_ms": dur.get(etype, 50),
                "intensity": round(float(intensity), 3),
            })
            entity_id += 1

    # -- D. 自适应细分 --
    rms = librosa.feature.rms(y=y, frame_length=N_FFT, hop_length=HOP_LENGTH)[0]
    rms_mean = float(np.mean(rms))

    for i in range(len(beat_frames) - 1):
        f0, f1 = int(beat_frames[i]), int(beat_frames[i+1])
        if f1 <= f0 + 2:
            continue
        local_rms = float(np.mean(rms[f0:f1]))
        ratio = local_rms / rms_mean if rms_mean > 0 else 1.0

        # 8 分音符
        if ratio >= 1.0:
            mid_frame = (f0 + f1) // 2
            m_low, m_mid, m_high = compute_band_energies_at_frames(S_perc_mag, sr, [mid_frame])
            m_low_n = m_low[0] / (beat_low.max() or 1)
            m_mid_n = m_mid[0] / (beat_mid.max() or 1)
            m_high_n = m_high[0] / (beat_high.max() or 1)
            etypes = classify_beat_competitive(m_low_n, m_mid_n, m_high_n, low_th, mid_th, high_th)
            for etype, intensity in etypes:
                dur = {"onset_kick": 80, "onset_snare": 60, "onset_hihat": 30, "onset_crash": 100}
                entities.append({
                    "id": entity_id,
                    "type": etype,
                    "time_ms": frame_to_ms(mid_frame, sr),
                    "duration_ms": dur.get(etype, 50),
                    "intensity": round(float(intensity), 3),
                })
                entity_id += 1

        # 16 分音符
        if ratio >= 2.0:
            for frac in [0.25, 0.75]:
                sub_frame = int(f0 + (f1 - f0) * frac)
                s_low, s_mid, s_high = compute_band_energies_at_frames(S_perc_mag, sr, [sub_frame])
                s_low_n = s_low[0] / (beat_low.max() or 1)
                s_mid_n = s_mid[0] / (beat_mid.max() or 1)
                s_high_n = s_high[0] / (beat_high.max() or 1)
                etypes = classify_beat_competitive(s_low_n, s_mid_n, s_high_n, low_th, mid_th, high_th)
                for etype, intensity in etypes:
                    dur = {"onset_kick": 80, "onset_snare": 60, "onset_hihat": 30, "onset_crash": 100}
                    entities.append({
                        "id": entity_id,
                        "type": etype,
                        "time_ms": frame_to_ms(sub_frame, sr),
                        "duration_ms": dur.get(etype, 50),
                        "intensity": round(float(intensity), 3),
                    })
                    entity_id += 1

    # -- E. Hold 检测（在和声分量上做，避开军鼓污染）--
    S_harm = librosa.stft(y_harmonic, n_fft=N_FFT, hop_length=HOP_LENGTH)
    S_harm_mag = np.abs(S_harm)

    # hold_melody: 和声分量中频段持续能量
    melody_energy = get_band_energy(S_harm_mag, sr, BAND_MID)
    melody_norm = melody_energy / melody_energy.max() if melody_energy.max() > 0 else melody_energy
    melody_th = max(np.median(melody_norm) * 0.8, 0.15)

    in_melody = False
    melody_start_beat = None
    for i, bf in enumerate(beat_frames):
        val = float(np.mean(melody_norm[max(0, bf-1):min(len(melody_norm), bf+2)]))
        if val > melody_th:
            if not in_melody:
                in_melody = True
                melody_start_beat = i
        else:
            if in_melody and melody_start_beat is not None:
                duration_beats = i - melody_start_beat
                if duration_beats >= 2:
                    start_ms = frame_to_ms(beat_frames[melody_start_beat], sr)
                    end_ms = frame_to_ms(beat_frames[i-1], sr)
                    avg_intensity = float(np.mean(
                        melody_norm[beat_frames[melody_start_beat]:beat_frames[i-1]+1]
                    ))
                    entities.append({
                        "id": entity_id,
                        "type": "hold_melody",
                        "time_ms": start_ms,
                        "duration_ms": max(end_ms - start_ms, 200),
                        "intensity": round(avg_intensity, 3),
                    })
                    entity_id += 1
                in_melody = False
                melody_start_beat = None

    if in_melody and melody_start_beat is not None and len(beat_frames) - melody_start_beat >= 2:
        start_ms = frame_to_ms(beat_frames[melody_start_beat], sr)
        end_ms = frame_to_ms(beat_frames[-1], sr)
        avg_intensity = float(np.mean(
            melody_norm[beat_frames[melody_start_beat]:beat_frames[-1]+1]
        ))
        entities.append({
            "id": entity_id,
            "type": "hold_melody",
            "time_ms": start_ms,
            "duration_ms": max(end_ms - start_ms, 200),
            "intensity": round(avg_intensity, 3),
        })
        entity_id += 1

    # hold_bass: 和声分量低频段持续能量
    bass_energy = get_band_energy(S_harm_mag, sr, BAND_LOW)
    bass_norm = bass_energy / bass_energy.max() if bass_energy.max() > 0 else bass_energy
    bass_th = max(np.median(bass_norm) * 1.0, 0.15)

    in_bass = False
    bass_start_beat = None
    for i, bf in enumerate(beat_frames):
        val = float(np.mean(bass_norm[max(0, bf-1):min(len(bass_norm), bf+2)]))
        if val > bass_th:
            if not in_bass:
                in_bass = True
                bass_start_beat = i
        else:
            if in_bass and bass_start_beat is not None:
                duration_beats = i - bass_start_beat
                if duration_beats >= 2:
                    start_ms = frame_to_ms(beat_frames[bass_start_beat], sr)
                    end_ms = frame_to_ms(beat_frames[i-1], sr)
                    avg_intensity = float(np.mean(
                        bass_norm[beat_frames[bass_start_beat]:beat_frames[i-1]+1]
                    ))
                    entities.append({
                        "id": entity_id,
                        "type": "hold_bass",
                        "time_ms": start_ms,
                        "duration_ms": max(end_ms - start_ms, 200),
                        "intensity": round(avg_intensity, 3),
                    })
                    entity_id += 1
                in_bass = False
                bass_start_beat = None

    if in_bass and bass_start_beat is not None and len(beat_frames) - bass_start_beat >= 2:
        start_ms = frame_to_ms(beat_frames[bass_start_beat], sr)
        end_ms = frame_to_ms(beat_frames[-1], sr)
        avg_intensity = float(np.mean(
            bass_norm[beat_frames[bass_start_beat]:beat_frames[-1]+1]
        ))
        entities.append({
            "id": entity_id,
            "type": "hold_bass",
            "time_ms": start_ms,
            "duration_ms": max(end_ms - start_ms, 200),
            "intensity": round(avg_intensity, 3),
        })
        entity_id += 1

    # 按时间排序
    entities.sort(key=lambda e: (e["time_ms"], e["id"]))
    return entities


# ============================================================
# Macro Stream 提取
# ============================================================

def extract_macro_stream(y, sr):
    """
    提取宏观流事件：energy_buildup / energy_drop / silence_gap。
    返回: macro_stream 列表
    """
    # 计算 RMS 能量
    rms = librosa.feature.rms(y=y, frame_length=N_FFT, hop_length=HOP_LENGTH)[0]

    if rms.max() > 0:
        rms_norm = rms / rms.max()
    else:
        return []

    macro_id = 1000  # 从 1000 开始，与 entity 区分
    macros = []

    # -- silence_gap --
    in_silence = False
    silence_start = 0
    for i in range(len(rms_norm)):
        if rms_norm[i] < SILENCE_RMS_THRESHOLD:
            if not in_silence:
                in_silence = True
                silence_start = i
        else:
            if in_silence:
                duration_frames = i - silence_start
                duration_sec = duration_frames * HOP_LENGTH / sr
                if duration_sec >= SILENCE_MIN_DURATION:
                    macros.append({
                        "id": macro_id,
                        "type": "silence_gap",
                        "time_ms": frame_to_ms(silence_start, sr),
                        "duration_ms": int(duration_sec * 1000),
                        "intensity": 0.0,
                    })
                    macro_id += 1
                in_silence = False

    # -- energy_buildup & energy_drop --
    window_frames = int(BUILDUP_WINDOW_SEC * sr / HOP_LENGTH)
    step_frames = window_frames // 4  # 75% 重叠

    for start in range(0, len(rms_norm) - window_frames, step_frames):
        segment = rms_norm[start:start + window_frames]

        # 用线性回归判断能量是否持续上升
        x = np.arange(len(segment))
        slope, _ = np.polyfit(x, segment, 1)

        # 斜率足够大、且整体能量不是特别低（排除静音段）
        if slope > 1e-5 and segment.mean() > SILENCE_RMS_THRESHOLD * 2:
            # 检查 buildup 之后是否有 drop
            drop_start = start + window_frames
            if drop_start < len(rms_norm) - 10:
                # 在 buildup 结束后的短时间内检查能量是否急剧上升
                post_segment = rms_norm[drop_start:drop_start + int(2 * sr / HOP_LENGTH)]
                if len(post_segment) > 0 and post_segment.max() - segment[-1] > 0.15:
                    # 找到了 buildup → drop 的组合
                    buildup_intensity = round(float(slope * 100000), 3)  # 缩放便于阅读
                    macros.append({
                        "id": macro_id,
                        "type": "energy_buildup",
                        "time_ms": frame_to_ms(start, sr),
                        "duration_ms": int(BUILDUP_WINDOW_SEC * 1000),
                        "intensity": min(buildup_intensity, 1.0),
                    })
                    macro_id += 1

                    macros.append({
                        "id": macro_id,
                        "type": "energy_drop",
                        "time_ms": frame_to_ms(drop_start, sr),
                        "duration_ms": 0,
                        "intensity": round(float(post_segment.max()), 3),
                    })
                    macro_id += 1

    macros.sort(key=lambda m: (m["time_ms"], m["id"]))
    return macros


# ============================================================
# 难度过滤 & 主流程
# ============================================================

def filter_by_difficulty(entity_stream, macro_stream, threshold):
    """
    按 intensity 阈值过滤 entity_stream。
    macro_stream 不受过滤影响（氛围效果全难度一致）。
    """
    if threshold == 0.0:
        filtered_entities = entity_stream
    else:
        filtered_entities = [e for e in entity_stream if e["intensity"] >= threshold]

    # 重新分配 ID
    for i, e in enumerate(filtered_entities):
        e["id"] = i

    return filtered_entities, macro_stream


def audio_analyzer(audio_path, output_dir):
    """
    主函数：加载音频 → 提取特征 → 输出 5 个难度的 JSON 文件。
    """
    print(f"[analyzer] 加载音频: {audio_path}")
    y, sr = librosa.load(audio_path, sr=None)
    duration_sec = float(librosa.get_duration(y=y, sr=sr))
    print(f"[analyzer] 时长: {duration_sec:.1f}s, 采样率: {sr}Hz")

    # 推导文件名
    base_name = os.path.basename(audio_path)
    song_name = os.path.splitext(base_name)[0]

    # BPM 检测
    print("[analyzer] 检测 BPM...")
    global_bpm, bpm_map = detect_bpm(y, sr)
    print(f"[analyzer] 全局 BPM: {global_bpm:.1f}")

    # 实体流提取
    print("[analyzer] 提取实体流 (entity_stream)...")
    entity_stream = extract_entity_stream(y, sr)
    print(f"[analyzer] 检测到 {len(entity_stream)} 个实体事件")

    # 宏观流提取
    print("[analyzer] 提取宏观流 (macro_stream)...")
    macro_stream = extract_macro_stream(y, sr)
    print(f"[analyzer] 检测到 {len(macro_stream)} 个宏观事件")

    # 按难度输出
    os.makedirs(output_dir, exist_ok=True)

    for diff_name, threshold in DIFFICULTY_THRESHOLDS.items():
        filtered_entities, _ = filter_by_difficulty(entity_stream, macro_stream, threshold)

        contract_data = {
            "metadata": {
                "title": song_name,
                "duration_sec": duration_sec,
                "sample_rate": sr,
                "bpm_map": bpm_map,
            },
            "entity_stream": filtered_entities,
            "macro_stream": macro_stream,
        }

        output_filename = f"{song_name}_{diff_name}_data.json"
        output_path = os.path.join(output_dir, output_filename)
        with open(output_path, "w", encoding="utf-8") as f:
            json.dump(contract_data, f, ensure_ascii=False, indent=2)

        print(f"[analyzer] OK {output_filename} ({len(filtered_entities)} entities)")

    print("[analyzer] 完成！")


# ============================================================
# 入口
# ============================================================

if __name__ == "__main__":
    parser = argparse.ArgumentParser(description="RhythmDash 音频分析器")
    parser.add_argument("--audio_name", default="Aorist.mp3", help="音频文件名（位于 assets/audio/）")
    parser.add_argument("--audio_path", default=None, help="或直接指定音频的绝对路径")
    args = parser.parse_args()

    BASE_DIR = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))

    if args.audio_path:
        audio_path = args.audio_path
    else:
        audio_path = os.path.join(BASE_DIR, "assets", "audio", args.audio_name)

    output_dir = os.path.join(BASE_DIR, "assets", "data")

    audio_analyzer(audio_path, output_dir)