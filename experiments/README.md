# 遗留实验目录说明

本目录收纳项目开发过程中被替代或弃用的实验资产，仅作历史存档，不参与运行。除 experiments/image/chinese/homework.jpeg 被 scripts/bench_ocr_chain.py 引用为压测样本图外，其余文件均不再被主应用、微服务或测试引用。各子目录按来源与结论归档如下。

## enhance/

本目录记录图像超分增强的早期探索。ESRGAN.ipynb 是从零实现并训练的 RRDB 生成器加判别器加 VGG 感知损失的对抗超分尝试，SRCNN.ipynb 是经典卷积超分基线。两条路线均未投入生产：生产链路最终采用 Real-ESRGAN x4plus 预训练权重（servers/ocr/enhance.py），因为该模型针对真实世界退化训练，实测 OCR 置信度提升 0.163、识别行数从 2 增到 10，效果显著优于自研训练。笔记本保留作为选型过程的证据。

## image/

本目录存放 OCR 与评分联调的样本图。chinese/ 下为中文作业样例，homework.jpeg 是整页作业图，被 scripts/bench_ocr_chain.py 用作压测样本；en/ 下为英文样例。这些图片是手工构造的测试素材，保留用于压测与人工联调。

## others/

本目录是 PaddleNLP 模型清单的参考文档。model_list.txt 是一次加载 PaddleNLP 模型失败的报错输出，列出了该库全部可用模型名；model_sorted.md 是对该清单按任务分类的整理。此批材料对应"弃 PaddleNLP"的决策背景：PaddleNLP 在本机缺十余个依赖维护不齐，评分语义匹配最终改用 sentence-transformers 多语言 MiniLM。保留作为模型选型叙事的量化依据。

## txt_compare/

本目录是 HanLP 语义相似度实验。texts_comparer.py 是基于 HanLP STS_ELECTRA_BASE_ZH 的批量相似度计算器，含阈值判定与准确率统计；text_comparer.py 是被其取代的单句命令行脚本，整理时合并删除，仅保留功能完整的 texts_comparer.py。该路线与 HanLP 一并弃用，原因与 others/ 同源：自研与 HanLP 语义模型被 MiniLM 语义粗筛加 DeepSeek 精排的级联架构取代。

## transferIntoBlack.py（已删除）

Otsu 二值化转黑白的单次工具脚本，引用不存在的 test.jpg 且无任何代码引用，整理时删除。
