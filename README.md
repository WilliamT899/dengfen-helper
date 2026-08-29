# 登分助手

小学教师登分工具：拍摄（或批量导入）试卷照片，**离线 OCR** 自动识别学生姓名、学号、班级与分数，对照学生名单自动纠错，一键导出 Excel 成绩表（统计项全部用公式实现，改分自动重算）。

## 功能

- 📷 摄像头实时预览 + 拍摄（手机式快门动画），或批量导入照片
- 🖊 自动识别：姓名（学生手写）、学号、班级、分数（老师手写，支持小数如 88.5）
- 📋 学生名单导入（Excel/CSV，自动识别"姓名/学号/班级"列）
- 🔍 识别结果与名单模糊匹配（学号优先），不明确的行**黄色高亮"待确认"**，表格可直接人工修改
- 📊 一键导出 Excel：每个班一个 Sheet + 总览 Sheet；统计块（平均分/中位数/最高分/最低分/100分人数/95/90/80分以上/60分以下）全部用 `AVERAGE`/`MEDIAN`/`MAX`/`MIN`/`COUNTIF` 公式计算，**修改分数实时重算**
- 💾 照片存档：`姓名_分数.jpg`（同名自动加序号）；工作区自动保存，意外关闭不丢失
- 🔌 完全离线运行，学生数据不离开电脑

## 使用步骤

1. 点击 **导入学生名单**，选择名单文件（首行表头：姓名/学号/班级）
2. 用摄像头拍摄试卷（将试卷右上角分数对准画面），或点 **批量导入照片**
3. 核对表格：识别不明确的行会黄色高亮，双击单元格可直接修改
4. 点击 **导出 Excel**，选择保存位置
5. 完成后可用 Excel 或 WPS 打开，修改分数后统计自动更新

## 照片拍摄建议

- 光线充足，避免阴影和反光
- 试卷铺平，尽量正对摄像头，四角完整入画
- 分数写大字、数字清楚（如 98.5）

## 开发

```bash
# macOS 开发环境
uv venv --python 3.12 .venv && source .venv/bin/activate
uv pip install -r requirements.txt pytest
python tools/ocr_cli.py              # 样本验收
python tools/e2e_test.py             # 端到端测试
python main.py                       # 启动 GUI
```

### 打包 Windows exe

在 GitHub 仓库推送 tag（如 `v1.0.0`）后，Actions 自动构建并发布 exe（需 models 下载，见 `.github/workflows/build-windows.yml`）。也可以手动触发 workflow。

## 技术栈

- OCR：[RapidOCR](https://github.com/RapidAI/RapidOCR) 3.9.2 + PP-OCRv5 server 模型（中文手写识别，ONNX Runtime 本地推理）
- GUI：PySide6（Qt6，深色主题）
- 摄像头：OpenCV（Windows 上 DSHOW 后端优先）
- Excel：openpyxl（统计项以公式写入）
- 打包：PyInstaller + GitHub Actions

## 隐私说明

- 识别完全在本地进行（离线 OCR），试卷照片与名单数据不上传任何服务器
- GitHub 仓库仅包含程序源码与测试样本，不含真实学生数据
