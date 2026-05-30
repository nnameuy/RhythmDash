# RhythmDash 技术规范

## 1. 技术栈

| 模块 | 语言 | 核心库 |
|------|------|--------|
| 音频分析 | Python 3.13+ | librosa, NumPy, SciPy |
| 游戏引擎 | C++17+ | Qt 6.x |
| 数据交换 | JSON | Python: `json`, C++: nlohmann/json 或 Qt JSON |

---

## 2. 项目目录结构

```
RhythmDash/
├── src/                # C++ 源代码
├── include/            # C++ 头文件
├── scripts/            # Python 脚本（analyzer.py 等）
├── assets/
│   ├── audio/          # 原始 MP3 音频
│   └── data/           # 生成的 data.json 关卡文件
├── build/              # 编译产物（gitignore）
├── docs/               # 项目文档
├── devlog/             # 开发日志
├── README.md           # 项目说明
└── .gitignore
```

---

## 3. 数据契约（Data Contract）

详见 `scripts/Data Contract.md`

### 3.1 JSON 顶层结构

```json
{
  "metadata": { "title": "...", "duration_sec": 0, "sample_rate": 0, "bpm_map": [...] },
  "entity_stream": [ { "id": 0, "type": "...", "time_ms": 0, "duration_ms": 0, "intensity": 0.0 } ],
  "macro_stream": [ { "id": 0, "type": "...", "time_ms": 0, "duration_ms": 0, "intensity": 0.0 } ]
}
```

### 3.2 难度文件命名

```
{曲名}_BASIC_data.json
{曲名}_ADVANCED_data.json
{曲名}_EXPERT_data.json
{曲名}_MASTER_data.json
{曲名}_REMASTER_data.json
```

---

## 4. 音频分析算法规范

### 4.1 预处理
- 采样率：保持原始，输出时记录到 metadata
- STFT 参数：n_fft=2048, hop_length=512
- 频率分辨率：约 10.7 Hz（@22050Hz 采样率）

### 4.2 频段定义

| 频段 | 范围 | 用途 |
|------|------|------|
| 低频 (Low) | 20 – 100 Hz | Kick detection |
| 中频 (Mid) | 200 – 2000 Hz | Snare detection |
| 高频 (High) | 5000+ Hz | Hi-hat detection |
| 全频段 (Full) | 20 – 20000 Hz | Crash / RMS energy |

### 4.3 Onset Detection 参数
- 使用 librosa.onset.onset_detect
- backtrack=True（回溯到更精确的位置）
- 按频段分别检测

### 4.4 Hold 检测
- 最短持续时间：200ms
- 检测方法：频段能量在阈值以上且持续

### 4.5 Macro Stream 检测
- energy_buildup：5-10秒滑动窗口，RMS 线性回归斜率为正
- energy_drop：buildup 后 RMS 急剧上升（导数突变）
- silence_gap：RMS < 静音阈值 且持续时间 > 500ms

---

## 5. 性能要求

| 指标 | 目标值 |
|------|--------|
| 音频分析耗时（3分钟 MP3） | < 30 秒 |
| JSON 文件大小 | < 1 MB |
| 游戏帧率 | 60 FPS |
| 输入延迟 | < 16ms（1 帧内响应） |
| 音画同步误差 | < 5ms |