# 试卷题目打分器（智能作业批改系统）

基于多模态 AI 的中英文作业自动批改系统：上传学生作业图片与参考答案，自动完成 OCR 文字提取与语义评分。

## 拉取项目

```
git clone git@github.com:yeteye/Grade-your-homework.git
cd Grade-your-homework
```

## 环境配置

推荐 Python 3.9。使用 conda 创建独立环境并安装依赖：

```
conda create -n ggrade python=3.9 -y
conda activate ggrade
pip install -r requirements.txt
```

关键版本说明：paddlepaddle 2.6.2 针对 numpy 1.x 编译，requirements.txt 已锁定 numpy==1.26.4，请勿升级到 numpy 2.x，否则会出现 ABI 不兼容错误。

## 配置密钥

复制 `.env.example` 为 `.env` 并填入 DeepSeek API Key：

```
cp .env.example .env   # Windows: copy .env.example .env
```

`.env` 中可配置项：

| 变量 | 说明 |
| --- | --- |
| DEEPSEEK_API_KEY | DeepSeek API 密钥（在线评分必需） |
| FLASK_DEBUG | 调试模式开关，生产环境保持 0 |

## 运行

```
python run.py
```

或双击 `run.bat`。启动后浏览器访问 http://127.0.0.1:5000/ 。

## 测试

```
pytest
```

或 `python -m pytest`。测试不依赖网络与模型，DeepSeek 与 OCR 均已 mock，可离线运行。

## 架构

系统提供两条评分链路，由前端开关"在线模式（DeepSeek 精排）"控制：

| 模式 | 评分引擎 | 适用场景 |
| --- | --- | --- |
| 在线 | DeepSeek 大模型精排 | 高精度评分 |
| 离线 | 本地相似度（当前为 difflib 占位，后续替换为向量嵌入） | 大批量低成本 |

在线评分失败时自动降级为离线评分，并在结果中通过 degraded 字段标记。

## 训练数据来源

图像增强实验使用 DIV2K 数据集：https://data.vision.ee.ethz.ch/cvl/DIV2K/
