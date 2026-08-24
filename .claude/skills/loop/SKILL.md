---
name: loop
description: 执行一次完整迭代闭环（确定版本号→开版本分支→读取上轮结果→规划→实现 agent 编码与测试 agent 独立验证→联合测试与压测→合并回 main→生成版本报告、模块单测报告、增量提炼优化量化与工作流优化建议）。当用户说"开始迭代"、"跑一轮 loop"、"/loop"、"进入下一版本"时使用。
---

# 迭代闭环

你是本项目的迭代执行者。收到 /loop 后严格按五阶段推进，每阶段完成再进入下一阶段。关键实现方案（影响架构、用户体验、核心功能性能、总成本）用 AskUserQuestion 让用户拍板，不要擅自决定。工作原则是 fail fast：小步提交、频繁测试、错误尽早暴露、不吞异常、不塞默认值。实现与测试必须分离：业务代码由实现 agent（子代理）撰写，单元测试由独立的测试 agent 撰写并运行，避免同一上下文自查自测。

## 产物文件

| 文件 | 用途 |
| --- | --- |
| memory/问题与优化反馈/迭代反馈表.md | 活跃问题状态，持续更新 |
| memory/问题与优化反馈/已完成迭代反馈表.md | 已完成归档，持续更新 |
| memory/问题与优化反馈/bugLOG.md | bug 日志，持续更新 |
| memory/版本迭代报告集/版本迭代报告_vX.Y.Z.md | 每版本一份，文件名带版本号 |
| memory/测试报告集/模块单测报告集/模块单测报告_vX.Y.Z.md | 每版本一份，文件名带版本号 |
| memory/测试报告集/压力测试报告集/压力测试报告_vX.Y.Z.md | 每版本一份，文件名带版本号 |
| memory/优化量化.md | 量化优化记录（文字+表格+选择思路，面试叙事用），增量追加，持续更新 |

命名规则：持续更新的文件（迭代反馈表、已完成迭代反馈表、bugLOG、优化量化）原地更新不带版本号；每版本一份的文件（版本迭代报告、模块单测报告、压力测试报告）新版本写新文件，文件名带版本号 vX.Y.Z。

## Phase 0 启动

1. 确定版本号（语义化三段：主.次.修订）
2. 从 main 开版本分支 version/x.y.z
3. 冒烟检查（ggrade 环境）：python -c "from backend.app import create_app"
4. 读取上轮产物：迭代反馈表、bugLOG、上一版版本迭代报告
5. 预检固定项（避免重复踩坑）：memory/ 已被 .gitignore 忽略，git add/commit 永不收录 memory/；交付前约束门禁脚本位于 scripts/check_constraints.py，Phase 2 步骤 12 必须通过；压测可复用脚本位于 scripts/bench_embedding.py，Phase 3 步骤 18 优先使用、不临时手写；外网可达性要逐端点实测（如 curl api.deepseek.com 探测）而非按历史推断，用于正确判断哪些步骤需用户 `!` 执行、哪些本会话可直接执行（v2.6.0 教训：github/huggingface 被阻断但 api.deepseek.com 可达，曾错误地把 DeepSeek 作答生成委托给用户）；涉及在线评分（force_online/DeepSeek）的任务，Phase 0 用最小 chat 请求探测密钥有效性（401 即密钥失效需换 key，勿等到 Phase 3 联调才暴露，v2.11.0 教训）

## Phase 1 规划

5. 筛"待处理"且 P0/P1 的问题，加用户新需求，按优先级排序
6. 为每个任务写 plan：目标、方案、涉及文件、验收标准（DoD）、依赖关系
7. 关键方案用 AskUserQuestion 给多选让用户拍板；架构/取舍类问题把推荐项放第一选项并标注"（推荐）"，减少澄清往返
8. 涉及性能的任务先记录优化前基线，并写明收益预测及依据假设（如"参考重编码=独立全成本"）；实测后若与预测偏差大，按假设归因，预测失效本身也是量化产出

## Phase 2 执行（内循环，逐任务）

9. 任务较多（≥3 个）时为该任务开分支 task/<编号>
10. 实现 agent（子代理）编写业务代码，只做实现不写测试。新增 scripts/ 下的脚本若 import services/utils，必须自带项目根 sys.path 引导（`sys.path.insert(0, str(Path(__file__).resolve().parent.parent))`，置于项目 import 之前），保证 `python scripts/xxx.py` 可直接运行——`python scripts/xxx.py` 时 sys.path[0] 是脚本目录而非项目根（v2.6.0 bugLOG 记录）
11. 测试 agent（独立子代理）编写单元测试并运行（ggrade 环境 python -m pytest），独立验证实现 agent 的产出；失败回到 10 由实现 agent 修复。patch 约定：`from x import y` 会把 y 绑定到调用方模块命名空间，mock 目标必须是调用方模块（如 backend.scoring.batch_scoring.should_route），不是被导入的 backend.scoring.engine
12. 约束门禁（交付前，避免事后返工）：ggrade 环境跑 python scripts/check_constraints.py，硬约束（业务目录 .py ≤200 行、模块级公开函数 ≤5）不通过 → 回到 10 拆分重构，通过后再往下走
13. 有 bug：可修 → 修复并记入 bugLOG.md；跨版本无法解决 → 记入迭代反馈表标"待处理/已延后"
14. 单测与门禁均通过后 merge --no-ff 回版本分支
15. 更新迭代反馈表（任务状态 → 已完成）
16. 按 git 规范提交
17. 进入下一子任务

## Phase 3 联合测试

17. 端到端联调（首页、OCR、评分全链路）+ 回归测试
18. 涉及核心功能（OCR、评分、批改链路）→ 压测记入 memory/测试报告集/压力测试报告集/压力测试报告_vX.Y.Z.md；压测优先复用 scripts/bench_embedding.py，不临时手写；跑前先小规模校准（--calibrate：校验端点方法——/health 是 GET、其余 POST；httpx.Client 连接复用；同会话 before/after A/B 对照），校准通过再正式测量
19. 联调失败且短时间修不好 → 回退上一版本 commit，保持 main 可运行
20. 有 bug 回 Phase 2

## Phase 4 总结

21. 版本分支联调通过后 merge --no-ff 回 main
22. 生成模块单测报告（精简：测试模块、用例数、通过情况），写入 memory/测试报告集/模块单测报告集/模块单测报告_vX.Y.Z.md
23. 生成版本迭代报告：目标、完成项、遗留问题、度量数据、经验教训
24. 增量提炼优化量化：本轮涉及性能优化或模型选型且有实测对比时，把新量化数据（前后对比数字、选择思路）追加到 memory/优化量化.md，沿用其文字+表格结构，避免项目收尾时集中回溯全部报告浪费 token；无新增量化数据则跳过
25. 同步 requirements.txt（若依赖有变更）
26. 更新迭代反馈表：把"已完成"条目移入 已完成迭代反馈表.md，活跃表只留待处理/进行中/已延后
27. loop 自省：哪里卡、哪里冗余，输出工作流优化建议；若性能任务实测与 Phase 1 步骤 8 记录的预测偏差大，把偏差归因写入当轮版本报告经验教训（预测失效也是量化产出），可再次沉淀为流程规则
