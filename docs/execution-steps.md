# RhythmDash 执行步骤

## 阶段一：音频分析脚本（当前阶段 ⭐）

### 步骤 1.1：环境准备
- [x] 安装 librosa：`pip install librosa`
- [x] 验证依赖：Python 3, librosa, numpy, scipy

### 步骤 1.2：修复 analyzer.py
- [x] 删除第 7-8 行语法错误
- [x] 统一字段名：`meta_data` → `metadata`，`bpm_list` → `bpm_map`

### 步骤 1.3：实现 BPM 检测
- [x] 全局 BPM 检测（librosa.feature.tempo）
- [x] 分段 BPM 检测，生成 bpm_map

### 步骤 1.4：实现 entity_stream 提取
- [x] onset_kick：低频 onset detection
- [x] onset_snare：中频 onset detection
- [x] onset_hihat：高频 onset detection
- [x] onset_crash：全频段能量峰检测
- [x] hold_bass：低频持续能量检测
- [x] hold_melody：中高频基频持续检测

### 步骤 1.5：实现 macro_stream 提取
- [x] energy_buildup：RMS 上升趋势检测
- [x] energy_drop：能量急剧爆发检测
- [x] silence_gap：静音段落检测

### 步骤 1.6：五档难度输出
- [x] 按 intensity 阈值过滤 entity_stream
- [x] 输出 5 个独立 JSON 文件

### 步骤 1.7：验证
- [x] 用 Aorist.mp3 测试
- [x] 检查输出 JSON 格式正确性

---

## 阶段二：C++ 游戏框架（后续）

- [ ] Qt 项目搭建
- [ ] JSON 解析模块
- [ ] 基础渲染循环
- [ ] 玩家输入控制
- [ ] 碰撞检测
- [ ] 菜单系统

---

## 阶段三：打磨（后续）

- [ ] 画面特效
- [ ] 音画同步优化
- [ ] 性能优化
- [ ] 打包发布