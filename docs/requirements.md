# RhythmDash 开发需求文档

## 1. 项目定义

RhythmDash 是一款**节奏跑酷游戏**。核心机制：通过音频处理算法自动分析 MP3 文件，从音频中提取节奏特征，并根据这些特征自动生成与之匹配的游戏关卡。

灵感来源于 Geometry Dash，但核心区别在于**无需人工设计关卡**。

---

## 2. 功能需求

### 2.1 音频分析模块（Python）

| 编号 | 需求 | 优先级 |
|------|------|--------|
| A1 | 读取 MP3 音频文件，输出采样数据 | P0 |
| A2 | 检测 BPM（支持分段变速） | P0 |
| A3 | 提取 6 种实体流事件：onset_kick / onset_snare / onset_hihat / onset_crash / hold_bass / hold_melody | P0 |
| A4 | 提取 3 种宏观流事件：energy_buildup / energy_drop / silence_gap | P1 |
| A5 | 按 intensity 阈值生成 5 档难度（BASIC / ADVANCED / EXPERT / MASTER / Re:MASTER） | P0 |
| A6 | 输出 JSON 格式数据，遵循 Data Contract | P0 |

### 2.2 游戏主体（C++ with Qt）

| 编号 | 需求 | 优先级 |
|------|------|--------|
| G1 | 主菜单：Select（选关）/ Generate（上传音频生成关卡）/ Settings（设置） | P0 |
| G2 | 玩家以折线轨迹移动，2 键控制方向（左上 / 右下） | P0 |
| G3 | 1 键攻击敌对实体 | P1 |
| G4 | 障碍物出现时机与音频节奏同步（误差 < 5ms） | P0 |
| G5 | 碰撞检测：碰到障碍物即失败 | P0 |
| G6 | 按完成度评分 | P1 |
| G7 | 画面特效：闪光、震动、粒子 | P2 |
| G8 | Settings：按键自定义、音量调节 | P2 |

### 2.3 难度系统

| 难度 | intensity 阈值 | 目标玩家 |
|------|---------------|----------|
| BASIC | ≥ 0.70 | 新手 |
| ADVANCED | ≥ 0.50 | 进阶 |
| EXPERT | ≥ 0.35 | 高手 |
| MASTER | ≥ 0.20 | 大师 |
| Re:MASTER | 全部事件 | 挑战极限 |

---

## 3. 非功能需求

- **同步精度**：障碍物与音频节奏的偏差 < 5ms
- **平台**：Windows（优先）
- **性能**：60 FPS 稳定运行
- **延迟**：从按键到画面响应的输入延迟尽量低

---

## 4. 约束条件

- 音频分析使用 Python 3 + librosa + NumPy + SciPy
- 游戏引擎使用 C++ + Qt
- 中间数据格式为 JSON（遵循 `scripts/Data Contract.md`）
- 项目结构遵循 README 中定义的目录规范
