# LNU-LibSeat 验证码模型训练

本目录保存了 **click1**（单字点选）和 **click3**（三字按序点选）验证码识别模型的完整训练管线：从数据采集 → 标注 → YOLO 检测 → Siamese 匹配 → 端到端评估 → ONNX 导出。

> 仓库根目录的 `core/checkpoints/` 是从这里产出的最终生产模型。运行项目本体（GUI / 抢座）**不需要** `train/` 里的任何文件，本目录只用于**复现训练**或**继续打标新增数据**。

---

## 0. 总体方案

每个点选验证码包含两张图：

| 图片 | 含义 | 尺寸 |
| --- | --- | --- |
| `target.png` | 顶部按顺序排列的目标字符（click1 = 1 字，click3 = 3 字） | 70 × 36 |
| `bg.png`     | 待点击的背景图（含 4 个候选字符 + 干扰） | 330 × 160 |

**两阶段推理**：

```
target + bg
   │
   ▼ 将 target 顶部的 plan 字符裁出来，与 bg 拼合
   │
   ▼ 阶段 1：YOLOv8 在合成图上检测 4 个候选字符框
   │
   ▼ 阶段 2：Siamese MobileNetV4 计算 plan 与每个候选的相似度
   │
   ▼ click1: argmax 选 1 个点 / click3: 3×4 相似矩阵最优匹配选 3 个有序点
```

最终产物 → `core/checkpoints/click{1,3}_yolo_plan_bg_char{40,60}_best.onnx`（YOLO）+ `core/checkpoints/click{1,3}_siamese_yolo4*_best.onnx`（Siamese）。

---

## 1. 模型架构

### YOLO 检测器

- **骨干**：YOLOv8s（Ultralytics，约 11M 参数；click1 用更小的 yolov8n）
- **输入**：640 × 640
- **类别**：单类 `char`（不区分顺序，顺序由后续 Siamese 决定）
- **训练**：200 epoch，mosaic=1.0，copy_paste=0.3，lr0=0.005，warmup=5
- **数据合成**：把 `target.png` 顶部 plan 字符块切成 3 份（click3）或整块（click1），放到合成图顶部 slot 区，bg 拼在下方
- **导出**：训练完用 `--export-onnx` 转 ONNX，opset 12，dynamic batch

### Siamese 匹配器

- **类名**：`SiameseMobileNetV4Embed`（`siamese_model_v8.py`）
- **骨干**：`timm.mobilenetv4_conv_medium`（pretrained）+ projection head `1280→256→128`
- **输出**：L2 归一化的 128 维 embedding；`forward` 返回两路 embedding 的 cosine 相似度
- **输入**：112 × 112
- **训练目标**：CE Loss on similarity matrix（`plan_i` 必须匹配 `char_i`）+ Triplet Loss 联合（v10 训练脚本）
- **正样本权重**：`posw3` = pos_weight=3，缓解样本不均衡
- **导出**：训练完导出双输入 ONNX，CPU 推理走 onnxruntime

---

## 2. Click3 训练全流程

`click3` 处理「按顺序点击 3 个目标字符」的验证码。

### 2.1 数据采集（一次性）

```powershell
.\.venv\Scripts\python.exe train\crawl_click3_dataset.py
```

- 用 Selenium 自动打开验证码弹窗
- 保存 `sample_xxxxx_target.png` / `sample_xxxxx_bg.png` / `sample_xxxxx_modal.png`
- 输出到 `dataset/click3/sample_xxxxx/`
- 一份样本约 50KB，建议采集 ≥1000 份

### 2.2 标注（按需）

**手动标注**（点击图上的 3 个目标）：

```powershell
.\.venv\Scripts\python.exe train\annotate_click3_dataset.py --dataset dataset/click3
```

- Tkinter GUI，按顺序点 3 下生成 `label.json`
- 写入 `{"target_count": 3, "points": [{x,y}, ...]}` 像素坐标相对 `bg.png`

**自动半监督标注**（已有训练好的 YOLO+Siamese 时）：

```powershell
.\.venv\Scripts\python.exe train\auto_label_unlabeled_click3.py
.\.venv\Scripts\python.exe train\review_click3_auto_labels_gui.py      # 人工 review 自动标注
.\.venv\Scripts\python.exe train\apply_click3_auto_labels.py            # 把审过的标签写入 label.json
```

### 2.3 准备 YOLO 数据集

```powershell
.\.venv\Scripts\python.exe train\prepare_click3_yolo_plan_bg_char.py
```

输出：`dataset/click3_yolo_plan_bg_char_60_900_100/`

- 把每张 `target.png` 顶部按固定坐标切出 3 个 plan 字符块（x ∈ {5,25,45,65}, y ∈ {5,27}）
- 顶部 slot（高 44px）摆 3 个 plan，下方拼 bg
- 单类 `char`、bounding box 60×60、按 90/10 切训练/验证集

### 2.4 训练 YOLO

```powershell
.\.venv\Scripts\python.exe train\train_click3_yolo_v2.py `
    --data dataset/click3_yolo_plan_bg_char_60_900_100/data.yaml `
    --model yolov8s.pt `
    --epochs 200 --imgsz 640 --batch 8 `
    --name plan_bg_char60_yolov8s_900_100 `
    --export-onnx
```

- GPU 推荐 RTX 3060 及以上，CUDA 12.1 PyTorch
- 输出：`runs/click3/plan_bg_char60_yolov8s_900_100/weights/best.pt` + `best.onnx`
- 自动跑测试集 mAP

### 2.5 准备 Siamese 数据集

利用上一步训出来的 YOLO，对每张验证码跑 top-4 候选，与 ground-truth 3 个点做距离匹配，构造 (plan, char) 配对：

```powershell
.\.venv\Scripts\python.exe train\prepare_click3_siamese_yolo4.py `
    --split-images dataset/click3_yolo_plan_bg_char_60_900_100/images/train `
    --split-name train --output dataset/click3_siamese_yolo4_train
.\.venv\Scripts\python.exe train\prepare_click3_siamese_yolo4.py `
    --split-images dataset/click3_yolo_plan_bg_char_60_900_100/images/val `
    --split-name val   --output dataset/click3_siamese_yolo4_val
```

每个 `sample_xxxxx/` 输出：

```
plan001.png  plan002.png  plan003.png        # 顶部 3 个 plan 字符
char001.png  char002.png  char003.png        # 与 plan_i 对应的 GT 候选
char004.png                                  # 干扰候选（distractor）
```

### 2.6 训练 Siamese

```powershell
.\.venv\Scripts\python.exe train\train_click3_siamese_v10.py `
    --data dataset/click3_siamese_yolo4_train `
    --epochs 60 --batch 16 `
    --ce-weight 1.0 --triplet-weight 0.5 `
    --export-onnx --exist-ok
```

- CE Loss（直接监督 3×4 相似度矩阵的对角线）+ Triplet Loss 联合
- 分层 lr：backbone 1e-5，head 2e-3
- 输出：`runs/click3_siamese_v10/ce_triplet/best.pth` + `best.onnx`

### 2.7 评估端到端

```powershell
.\.venv\Scripts\python.exe train\eval_plan_bg_author_siamese_e2e.py
.\.venv\Scripts\python.exe train\test_yolo4_siamese_e2e.py
.\.venv\Scripts\python.exe train\eval_plan_bg_char_yolo.py     # 仅 YOLO 召回评估
```

### 2.8 部署到生产

把 `best.onnx` 拷贝到 `core/checkpoints/` 并重命名：

```powershell
Copy-Item runs/click3/plan_bg_char60_yolov8s_900_100/weights/best.onnx `
          core/checkpoints/click3_yolo_plan_bg_char60_best.onnx
Copy-Item runs/click3_siamese_v10/ce_triplet/best.onnx `
          core/checkpoints/click3_siamese_yolo4_posw3_best.onnx
```

生产解算器在 `core/captcha_yolo4_siamese.py::Yolo4SiameseSolver`，开盘前用 `preload_click3_target_bg()` 热加载。

---

## 3. Click1 训练全流程

`click1` 与 click3 完全同构，差异只在「目标字符数 = 1」：

| 步骤 | click3 | click1 |
| --- | --- | --- |
| 目标个数 | 3 | 1 |
| YOLO 候选数 | 4 | 4 |
| Siamese 匹配 | 3×4 矩阵最优排列 | 1×4 argmax |
| 字符框尺寸 | 60×60 | 40×40 |
| Plan crop 坐标 | x ∈ {5,25,45,65}, y ∈ {5,27} | x ∈ {25,45}, y ∈ {5,27} |
| YOLO 骨干 | yolov8s | yolov8n |

### 3.1 数据集

样本目录 `dataset/click1/sample_xxxxx/`，结构与 click3 相同但 `label.json` 中 `target_count=1`、`points` 列表长度为 1。

### 3.2 标注

```powershell
.\.venv\Scripts\python.exe train\annotate_click1_dataset.py
.\.venv\Scripts\python.exe train\auto_label_unlabeled_click1.py
```

### 3.3 YOLO

```powershell
.\.venv\Scripts\python.exe train\prepare_click1_yolo_plan_bg_char.py
.\.venv\Scripts\python.exe train\train_click1_yolo.py
```

输出：`runs/click1/plan_bg_char40_yolov8n_900_100/weights/best.{pt,onnx}`

### 3.4 Siamese

```powershell
.\.venv\Scripts\python.exe train\prepare_click1_siamese_yolo4.py
.\.venv\Scripts\python.exe train\train_click1_siamese.py --export-onnx
```

### 3.5 端到端评估

```powershell
.\.venv\Scripts\python.exe train\eval_click1_e2e.py
```

当前生产端到端准确率约 **83.48%**，YOLO 召回率约 100%。

### 3.6 部署

```powershell
Copy-Item runs/click1/plan_bg_char40_yolov8n_900_100/weights/best.onnx `
          core/checkpoints/click1_yolo_plan_bg_char40_best.onnx
# Siamese best.onnx → core/checkpoints/click1_siamese_yolo4_best.onnx
```

生产解算器：`core/captcha_click1_yolo4_siamese.py::Click1SiameseSolver`。

---

## 4. 文件清单

### 数据采集 / 标注
| 文件 | 用途 |
| --- | --- |
| `crawl_click3_dataset.py` | Selenium 自动采集验证码原图（target+bg+modal） |
| `annotate_click3_dataset.py` / `annotate_click1_dataset.py` | Tkinter GUI 手动点标 |
| `auto_label_unlabeled_click3.py` / `auto_label_unlabeled_click1.py` | 用已有模型对未标样本生成伪标签 |
| `gpu_infer_click3_unlabeled_from_1001.py` | GPU 批量推理未标数据 |
| `apply_click3_auto_labels.py` | 把审过的伪标签提交为正式 label.json |
| `review_click3_auto_labels_gui.py` / `infer_click3_review_gui.py` | 人工 review 自动标注 |
| `manual_plan_split.py` / `manual_plan_split_click1.py` | 手动微调 plan 切分坐标 |

### YOLO 训练
| 文件 | 用途 |
| --- | --- |
| `prepare_click3_yolo_plan_bg_char.py` | 生成 click3 YOLO 数据（plan + bg 合成） |
| `train_click3_yolo_v2.py` | YOLOv8s 训练 + 自动测试 + ONNX 导出 |
| `prepare_click1_yolo_plan_bg_char.py` / `train_click1_yolo.py` | click1 同上 |
| `eval_plan_bg_char_yolo.py` | 仅 YOLO 召回/mAP 评估 |

### Siamese 训练
| 文件 | 用途 |
| --- | --- |
| `prepare_click3_siamese_yolo4.py` | 用 YOLO 输出构造 (plan, char) 配对数据 |
| `train_click3_siamese_v10.py` | **当前生产** Siamese 训练（CE+Triplet） |
| `train_click3_siamese_author.py` | 原作者方案（仅 BCE+focal），保留对照 |
| `siamese_model_v8.py` | MobileNetV4 + projection head 模型定义 |
| `siamese_dataloader_v8.py` | Triplet 数据加载器（in-sample + cross-sample neg） |
| `prepare_click1_siamese_yolo4.py` / `train_click1_siamese.py` | click1 同上 |
| `hard_negative_mine.py` | 难负样本挖掘工具 |

### 端到端评估 / 可视化
| 文件 | 用途 |
| --- | --- |
| `test_yolo4_siamese_e2e.py` | click3 端到端测试（YOLO+Siamese） |
| `eval_plan_bg_author_siamese_e2e.py` | click3 端到端评估（生成报告） |
| `eval_click1_e2e.py` | click1 端到端评估 |
| `vis_click1_*.py` × 5 | click1 YOLO 可视化分析（置信度、box 数、topk 等） |

---

## 5. 已知问题

下列脚本引用了**已在历史清理中被删除**的基础模块 `siamese_dataloader.py` / `siamese_model.py`，目前**无法直接运行**：

- `train_click3_siamese_author.py`
- `train_click1_siamese.py`
- `eval_click1_e2e.py`
- `hard_negative_mine.py`

若要复现生产 click1 Siamese 训练，需要从 git 历史里 `git show <commit>:siamese_dataloader.py > train/siamese_dataloader.py` 恢复，或参考 `siamese_dataloader_v8.py` 改造（`v8` 是带后缀的版本，没有依赖问题）。

**推荐路径**：直接基于 `train_click3_siamese_v10.py` 改 1-plan × 4-char 的 click1 训练，避免恢复旧模块。

---

## 6. 环境依赖

```powershell
.\.venv\Scripts\python.exe -m pip install -r train\requirements-train.txt
# GPU PyTorch (CUDA 12.1)
.\.venv\Scripts\python.exe -m pip install --force-reinstall `
    torch==2.5.1 torchvision==0.20.1 --index-url https://download.pytorch.org/whl/cu121
```

`requirements-train.txt`：`ultralytics>=8.4.0`、`onnx>=1.16.0`、`timm`（Siamese 用，按需手动加）、`sklearn`、`tqdm`、`Pillow`、`opencv-python`。

---

## 7. 输出位置约定

```
dataset/
  click3/                                       # 原始采集
  click1/
  click3_yolo_plan_bg_char_60_900_100/          # YOLO 训练数据
  click1_yolo_plan_bg_char_40_900_100/
  click3_siamese_yolo4_train/                   # Siamese 训练数据
  click3_siamese_yolo4_val/

runs/
  click3/plan_bg_char60_yolov8s_900_100/        # click3 YOLO 输出
  click1/plan_bg_char40_yolov8n_900_100/        # click1 YOLO 输出（生产用）
  click1/plan_bg_char40_yolov8s_900_100/        # click1 YOLO（备份对照）
  click3_siamese_v10/ce_triplet/                # click3 Siamese 输出

core/checkpoints/                               # 部署上线后的 ONNX 模型（生产）
```
