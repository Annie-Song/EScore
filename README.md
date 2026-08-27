# 智能作业批改系统（Grade-your-homework）

基于多模态 AI 的中英文作业自动批改系统。教师上传学生作业图片与参考答案，系统自动完成 OCR 文字提取、语义评分与批改报告生成。核心工作流有两条：单份快速批改（上传两图，即时识别、评分、下载报告）与大批量离线批改（一次上传一份参考图与多份作业图，异步逐份识别评分，产出每题得分明细与统计报告），并内置按科目/题型/难度检索的高考题题库作为数据底座。全部模型在单机 CPU（Windows）推理，无 GPU 依赖。

## 核心能力

| 能力 | 说明 |
| --- | --- |
| 单图批改 | 上传作业图与参考答案图，OCR 提取文本，级联评分引擎打分，下载 HTML/Word 批改报告 |
| 批量批改 | 一份参考图 + 多份作业图，异步后台线程逐份识别评分，前端轮询进度，长耗时批改不阻塞请求 |
| 作业智能分区 | 一张图含多道题时按水平投影自动切分为独立区域，逐区域 OCR 与评分，一图多题分别打分 |
| 错因归类 | 按分数规则分档（未作答/概念错误/要点遗漏/部分正确/掌握良好），可开启 AI 结构化归类并给出一句话原因 |
| 分类题库 | 2811 道高考题（10 科目、14 题型）按确定性标签入库，支持科目/题型/难度/年份/关键词过滤检索；校本题库按校隔离增删，检索范围=全局题库+本校题目 |
| 持久化与统计 | 批改记录落 SQLite，可按题查看人数/平均分/最高/最低/及格率/未作答数，按错因查看分布，下载 HTML/Word 报告 |
| 用户体系 | 注册/登录（Flask 签名会话，零新依赖）、个人主页（资料/批改记录/会员状态/个人卷库）、free/pro 会员门控、题库收藏，游客免登录使用 |

## 系统架构

评分链路采用级联两阶段：先由离线向量嵌入（sentence-transformers 多语言 MiniLM）粗筛，离线分低于阈值或落入边界带时自动路由 DeepSeek 精排，在精度与成本之间做平衡；在线评分失败时自动降级为离线，并在结果中通过 degraded 字段标记。

系统按微服务拆分，模型全部收敛到独立进程，主应用进程不持有任何模型：

```
┌────────────────────┐   HTTP    ┌─────────────────────────────┐
│   Flask 主应用       │ ────────▶ │  Embedding 微服务 :8765      │
│   路由 / 业务编排      │           │  MiniLM 语义粗筛 / 参考缓存    │
│   批量任务调度         │   HTTP    ├─────────────────────────────┤
│   上传/落库/报告生成    │ ────────▶ │  OCR 微服务 :8766            │
└────────────────────┘           │  PaddleOCR / ESRGAN / 分区    │
                                 └─────────────────────────────┘
```

Embedding 服务负责句向量编码与语义相似度，OCR 服务负责 PaddleOCR 文字识别、Real-ESRGAN 低置信增强重识别与水平投影分区。两者均为独立 FastAPI 进程，主应用经 HTTP 客户端调用，接口契约不变、业务调用方零改动即可在进程内实现与远程调用间切换。模型加载错误、内存尖峰都被隔离在服务进程内，不拖垮 Web 主进程。单题图合并评分接口 `/api/grade_image` 把上传、OCR、评分收拢为一次请求，省去浏览器两次往返与文件二次落盘（单题实测中位 ~247ms）；OCR 推理线程数 `OCR_CPU_THREADS` 默认 4（整页/单题折中，环境变量可覆盖），推理设备 `OCR_DEVICE` 默认 `cpu`、设为 `gpu` 即启用 PaddleOCR GPU 推理（需另装 paddlepaddle-gpu），CPU 单题小图稳态 ~90ms，毫秒级出分需 GPU 加速。

## 用户体系

面向学校/教师客户的身份与商业化能力。左侧 sidebar 导航含 5 入口（首页/批量批改/分类题库/使用教程/个人主页），管理员（admin 与 school_admin）额外显示"学校管理"入口；登录态显示头像昵称与退出入口，游客显示"登录/注册"。角色取值为 teacher / school_admin（学校管理员）/ admin（全局管理员）：school_admin 管理范围限定本校（成员、批改统计、校本题库），admin 拥有全部能力（建校、跨校数据、角色分配），角色由全局管理员在 `/admin` 成员表中分配。注册登录基于 Flask 签名 session 加 werkzeug pbkdf2 口令哈希，零新依赖，密钥来自环境变量 `SECRET_KEY`。

会员按 free/pro 两档功能门控，游客视为 free：批量批改需 pro（不足返 402 并提示升级），在线精排 free 自动降级为离线评分（状态码仍 200，核心评分始终可用）。演示账号运行 `python scripts/seed_demo_user.py` 后可用：demo/demo1234（教师 pro）与 admin/admin123（管理员 pro），免费用户可在注册页自助注册。

个人主页 `/me` 四卡片区：会员状态（计划徽章与升级入口）、我的资料、我的批改记录（个人批量任务与每题均分）、我的卷库（从分类题库收藏的题目，作为后续组卷的数据底座）。批改记录按映射表归属，grades.db 原表不变。

升级走可插拔支付网关闭环：`/upgrade` 套餐页创建订单，支付宝沙箱配置齐全时用沙箱网关（`python-alipay-sdk`，懒导入），否则回退本地演示网关（`/api/pay/demo/confirm` 直接完成支付），回调经 `mark_paid` 幂等升级，重放不重复扣权益。学校维度数据隔离：注册可填 `school_code` 加入学校，`POST /api/me/school` 换绑学校；管理端 `/admin` 提供学校列表、建校、成员与跨校批改统计（按 `school_id` 过滤批次）；school_admin 进入该页仅见本校数据且不可建校，全局 admin 见全部。校本题库：本校教师可向校本题库添加题目（需已入校），删除限题主本人、本校 school_admin 与全局 admin；跨校成员检索、按 qid 直拉、删除均被拒绝（404/403），实现租户级题库隔离。演示学校 code=`DEMO`（id=`school-demo`）由种子脚本幂等创建。

## 技术栈

| 层 | 技术 |
| --- | --- |
| 主应用 | Flask + Jinja2（app 工厂 + Blueprint 分层） |
| 微服务 | FastAPI + Uvicorn（Embedding、OCR 两个独立进程） |
| OCR | PaddleOCR；Real-ESRGAN x4plus 低置信增强重识别 |
| 语义匹配 | sentence-transformers 多语言 MiniLM-L12（384 维） |
| 精排 | DeepSeek API（级联路由，双档预设） |
| 存储 | SQLite（WAL，批改记录/统计/题库/用户体系） |
| 认证 | Flask 签名 session + werkzeug pbkdf2（零新依赖） |
| 前端 | 原生 HTML/CSS/JS，响应式侧边导航 + 明暗主题切换 |

## 关键设计与量化成果

OCR 识别做了按语言单例缓存加双重检查锁的懒加载，PaddleOCR 实例化从每个请求重建改为复用，稳态识别延迟从 1.71s 降到 0.57s。单例缓存随后暴露了共享实例不线程安全的问题，对推理加模块级锁串行化后，并发 /ocr 成功率从 50% 修复到 12/12，同时用吞吐换回了正确性。

批量批改先解决性能再解决交互。逐对评分在 N=20 时耗 466ms，改为参考答案嵌入预计算缓存（同一参考对 N 份作业只编码一次，满 256 条整体清空保证内存有界）加答案批量编码后降到 98ms，收益随作业数放大。大批量上传从同步阻塞改为提交即返回任务 ID、后台线程执行、前端轮询进度，单份批改约 2.0s，使十万级规模在"不阻塞请求 + 记录落库"层面成立。

| 优化项 | 量化结果 |
| --- | --- |
| OCR 单例缓存 | 识别延迟 1.71s → 0.57s（约 3 倍） |
| OCR 并发竞态修复 | 成功率 50% → 12/12 |
| 向量嵌入服务化 | 批量相似度 N=20 98ms → 72.5ms（参考缓存随模型迁服务端），主应用进程内存释放 |
| 向量预计算 | 逐对 466ms → 批处理 98ms（4.7x，N=20） |
| 单份批改 | 约 2.0s/份（真实作业，不触发增强） |
| 分区整图增强去重 | Real-ESRGAN 增强次数 N 次 → 1 次，9 区域作业约 542s → 约 90-120s（约 4.5x） |

评分精度用自建评测集量化。用 GAOKAO-Bench 60 道中文主观题（含标准答案）加 DeepSeek 构造优/中/差三档作答共 180 条建立评测集，实测 MiniLM 对中文主观题优/差二分类 AUC 0.731，证明"语义相似"不等于"答案质量"，MiniLM 只适合粗筛，中文主观题的高质量评判仍需 DeepSeek 精排兜底。修复三档构造的词汇重叠混淆后，档位单调性恢复、Spearman 0.381 → 0.505、优/差 AUC 0.807，综合多指标判别 AUC 达 0.947。基于评测集把路由策略做成双档预设由使用者运行时自选：fast 档差档作答捕获率 23.3%、总路由率 11.7%（低成本），quality 档捕获率 78.3%、总路由率 50.6%（高质但调用成本约 4.3 倍），运营点权衡量化写进界面与可复用扫描工具。

低质量作业图片的增强也做了结构性优化。一图多题分区后每个低置信区域各自触发一次 Real-ESRGAN 超分，成本随区域数线性放大，改为整图增强一次、各区域从增强图按放大比例裁剪识别，增强从 N 次并为 1 次，任何异常降级回原路径保证任务不失败。

## 快速上手

推荐 Python 3.9，用 conda 创建独立环境安装依赖：

```
conda create -n ggrade python=3.9 -y
conda activate ggrade
pip install -r requirements.txt
```

关键版本说明：paddlepaddle 2.6.2 针对 numpy 1.x 编译，requirements.txt 已锁定 numpy==1.26.4，请勿升级到 numpy 2.x。复制 `.env.example` 为 `.env` 并填入 DeepSeek API Key；`.env` 可配置 `DEEPSEEK_API_KEY`、`FLASK_DEBUG`、`EMBEDDING_SERVICE_URL`、`OCR_SERVICE_URL`、`SECRET_KEY`（会话签名密钥，生产环境务必设置）、`OCR_CPU_THREADS`（OCR 推理线程数，默认 4）、`OCR_DEVICE`（OCR 推理设备，默认 cpu，设 gpu 启用 GPU）、`OCR_CACHE_MAX`（OCR 文本缓存上限，默认 256，满则整体清空）、`GRADE_CACHE_MAX`（单图评分结果缓存上限，默认 256）。启动前可选运行 `python scripts/seed_demo_user.py` 播种演示账号（demo/demo1234、admin/admin123）。

启动三个进程（同一 conda 环境，或双击 `run.bat`）：

```
# 终端 1：向量嵌入微服务（默认 127.0.0.1:8765）
python -m servers.embedding.server

# 终端 2：OCR 微服务（默认 127.0.0.1:8766）
python -m servers.ocr.server

# 终端 3：主应用
python run.py
```

浏览器访问 http://127.0.0.1:5000/ 即可使用。微服务未启动时离线评分与 OCR 会明确报错并提示启动命令（fail-fast，不静默降级），服务地址可用环境变量指向其他主机。启动后可运行 `python scripts/healthcheck.py` 检查三服务是否就绪（缺省只测一轮，`--wait 30` 表示每 1 秒重试直到全部就绪或 30 秒超时）。`run.bat` 已内置该健康检查：启动三个进程后等待最多 30 秒，全部就绪才打开浏览器，失败会提示"服务启动失败，请查看对应终端日志"并以非零码退出。

## Docker 容器化部署

项目可用 Docker 一键拉起三进程（主应用 :5000、向量嵌入 :8765、OCR :8766），免去 conda 环境与三终端手动启动。前置要求是装有 Docker Desktop（Windows/macOS）或 Docker Engine（Linux）的机器，并先把 `.env` 从 `.env.example` 复制并填入 `DEEPSEEK_API_KEY` 与 `SECRET_KEY`（缺 `.env` 也能启动，仅影响在线精排与会话签名安全）。

模型权重在构建期从宿主机缓存打包进镜像，镜像构建完成后自包含离线，运行时零外网下载。本机实测 huggingface.co 与 hf-mirror.com 均被阻断，故构建期不联网拉模型，改为脚本把已下载完整的模型拷贝进构建上下文。首次构建前先运行 `python scripts/prepare_docker_models.py`：它把宿主机 `~/.cache/huggingface/hub` 中的 MiniLM 模型、`~/.paddleocr` 中的 PaddleOCR 模型（ch/en）拷贝到 `docker/models/` 舞台目录（跟随符号链接展开真实文件并跳过 blobs 缓存，合计约 488MB），并校验仓库内 ESRGAN 权重存在。然后执行 `docker compose build` 构建 app/embedding/ocr 三个镜像，`docker compose up -d` 启动全部服务。容器健康检查打各服务的 `/ready` 端点（会真实加载模型，而非 `/health` 的仅端口存活），embedding 与 ocr 就绪后主应用才启动，访问 http://localhost:5000 即进入系统。

本机 Docker Hub（auth.docker.io/registry-1.docker.io）也被阻断，基础镜像 `python:3.9-slim-bullseye` 需先从可达镜像源拉取再本地打标，之后 `docker compose build` 直接命中本地镜像：`docker pull docker.m.daocloud.io/library/python:3.9-slim-bullseye && docker tag docker.m.daocloud.io/library/python:3.9-slim-bullseye python:3.9-slim-bullseye`。同理 `docker/Dockerfile` 已移除 `# syntax=docker/dockerfile:1` 指令（该指令会触发构建期从被墙的 docker.io 拉取 dockerfile 前端镜像），改用 BuildKit 内置前端，行为等价。apt（deb.debian.org）与 pip（清华 tuna）在本机可达，无需镜像。

数据落宿主而非容器：`./output`（SQLite 库、批改报告、增强与分区中间产物）与 `./uploads`（上传图片）通过 bind mount 与宿主机共享，OCR 容器按主应用 HTTP 传入的文件路径读取同一份 `uploads`（只读），因此三容器共享同一套数据，零迁移即可接管现有 `output/` 与 `uploads/` 目录。关闭用 `docker compose down`（bind mount 保留数据）；联调通过后可给 app 服务加 `restart: unless-stopped` 实现重启自愈。

GPU 预留了通路：`docker-compose.gpu.yml` 把 `OCR_DEVICE` 置为 `gpu` 并预留 nvidia 资源声明，但当前镜像内置 CPU 版 paddlepaddle，直接叠加启动会在 PaddleOCR 处失败，需先把 `docker/Dockerfile` 中的 paddlepaddle 换成 paddlepaddle-gpu 再重构建 ocr 目标。容器内主应用保持单进程（Werkzeug 开发服务器），因为批改任务注册表与内存缓存是进程内状态，多 worker 会破坏任务可见性；生产化换 gunicorn 单 worker 留作后续项。

CPU 兼容性做了自动适配：paddlepaddle 2.6.x 的 Linux wheel 在 IR 图优化 pass 里编译进了 AVX-512 指令，在熔断 AVX-512 的 CPU（如 Raptor Lake 消费级）上会因非法指令崩溃，同时该 wheel 捆绑的 zlib 会插桩系统库导致 charset_normalizer 导入崩溃。镜像内已内置两层兜底：ocr 阶段预加载系统 libz 抢先绑定符号，`servers/ocr/paddle_compat.py` 在 Linux 且 CPU 无 AVX-512 时自动关闭 paddle 的 IR 图优化（Windows 宿主不受影响）。无 AVX-512 的机器可直接部署，代价仅是 OCR 推理少了图融合加速。

## 工程化

单测 747 条，外部依赖（DeepSeek、OCR、向量嵌入）全部 mock、可离线独立运行，命名遵循 `test_功能_场景`。代码按 backend/servers/frontend 三层组织：backend/ 按功能域拆包（core/auth/bank/school/scoring/ocr/batch/stats/grading/pay/infra，routes+services+store 同置），servers/ 收纳独立微服务进程（embedding/、ocr/），frontend/ 收拢模板与静态资源实现目录级前后端分离，tests/ 按功能域分子目录。单个文件不超过约 200 行、模块级公开函数不超过 5 个，约束门禁脚本强制校验。部署已容器化：`docker compose up -d` 一键拉起三服务，模型构建期打包进镜像自包含离线，数据经 bind mount 落宿主（见 Docker 容器化部署一节）。迭代采用两层 Git 分支（版本分支 + 任务分支）与独立实现/测试 agent 分离的开发流程，业务代码由实现 agent 撰写、测试由独立 agent 撰写运行，避免自查自测。

## 训练数据来源

图像增强实验使用 DIV2K 数据集：https://data.vision.ee.ethz.ch/cvl/DIV2K/ 。分类题库数据来自 GAOKAO-Bench：https://github.com/OpenLMLab/GAOKAO-Bench ，构建脚本为 `python scripts/build_question_bank.py`。
