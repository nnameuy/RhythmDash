# Data Contract

本文档定义了Python 脚本`analyzer.py`与 C++ 游戏部分之间的数据交换格式。
通过 `data.json` 文件完成。

---

JSON格式示例：

```json
{
  "metadata": {
    "title": "RhythmDash_Demo_Track",
    "duration_sec": 125.5,
    "sample_rate": 22050,
    "bpm_map": [
      {
        "time_ms": 0,
        "bpm": 120.0
      },
      {
        "time_ms": 45000,
        "bpm": 145.0
      },
      {
        "time_ms": 80000,
        "bpm": 120.0
      }
    ]
  },

  "feature_stream": [
    {
      "id": 1,
      "type": "onset_kick",
      "time_ms": 500,
      "duration_ms": 50,
      "intensity": 0.85
    },
    {
      "id": 2,
      "type": "onset_high",
      "time_ms": 500,
      "duration_ms": 30,
      "intensity": 0.60,
    },
    {
      "id": 3,
      "type": "hold_melody",
      "time_ms": 1000,
      "duration_ms": 1500,
      "intensity": 0.75,
    },
    {
      "id": 4,
      "type": "onset_kick",
      "time_ms": 2500,
      "duration_ms": 50,
      "intensity": 0.95
    },
    {
      "id": 5,
      "type": "silence",
      "time_ms": 2550,
      "duration_ms": 2000,
      "intensity": 0.0
    }
  ]
}
```

---

1. **顶层结构**
   
   JSON 文件包含两个主要部分：`metadata`和 `feature_stream`。
   
   ```json
   {
     "metadata": { ... },
     "feature_stream": [ ... ]
   }
   ```

2. **Metadata (元数据)**
   
   提供关于当前音频的全局信息。
   
   | 字段名            | 说明        |
   | -------------- | --------- |
   | `title`        | 曲名        |
   | `duration_sec` | 音频总时长     |
   | `sample_rate`  | 采样率       |
   | `bpm_map`      | 分段 BPM 列表 |
   
   **`bpm_map` 数组结构：**
   
   - `time_ms`: 发生 BPM 变化的绝对时间，首个元素应该为0。
   - `bpm` : 浮点数。该时间点开始的新 BPM 值。



3. **Entity Stream (实体流)**
   
   这是一个音频事件的数组。
   
   **允许存在相同 `time_ms` 的不同事件**，将来引擎端会遍历此数组提取音频关键信息。
   
   | 字段名           | 说明             |
   | ------------- | -------------- |
   | `id`          | 特征唯一标识         |
   | `type`        | 特征类            |
   | `time_ms`     | 瞬时音效 / 长音的起始点。 |
   | `duration_ms` | 持续时间           |
   | `intensity`   | 能量强度           |

4. **Macro Stream（宏观流）**
   
   独立于实体流，捕捉整体氛围。
   
   | 字段名           | 说明          |
   |:------------- |:----------- |
   | `id`          | 宏观事件唯一标识    |
   | `type`        | 见下文的宏观特效枚举。 |
   | `time_ms`     | 起始点         |
   | `duration_ms` | 持续时间        |
   | `intensity`   | 特效的强度       |

---

# Audio Feature Type Dictionary

Entity Stream: type dict

| `type`            | duration | 提取判据（？）               | description             |
|:----------------- |:-------- |:--------------------- |:----------------------- |
| **`onset_kick`**  | 瞬发       | 20-100Hz 瞬时能量突变（低频）   | 底鼓 (Kick / Bass Drum)   |
| **`onset_snare`** | 瞬发       | 200-2000Hz 瞬时能量突变（中频） | 军鼓、拍手 (Snare / Clap)    |
| **`onset_hihat`** | 瞬发       | 5000Hz+ 瞬时能量突变（高频）    | 极短促的踩镲声 (Hi-hat / Tick) |
| **`onset_crash`** | 瞬发       | 极高的能量峰值               | 重击？（如果有这种噪音的话。。）        |
| **`hold_bass`**   | 持续       | 低频段能量持续 > 200ms       | 连续的重低音 (Bassline / 808) |
| **`hold_melody`** | 持续       | 中高频段、具有明显基频且持续        | 歌手长音、吉他、合成器长音           |

Macro Stream: type dict

| `type`               | 提取判据（？）              | description       |
|:-------------------- |:-------------------- |:----------------- |
| **`energy_buildup`** | 5-10秒内 RMS 能量呈稳定上升趋势 | 铺垫、鼓点加速（Build-up） |
| **`energy_drop`**    | 经历 buildup 后能量突然极速爆发 | 副歌 (Drop)         |


