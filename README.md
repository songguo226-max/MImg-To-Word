# MathOCR Pro



将带有数学符号和公式的数学题目图片转换成可编辑的 Word 文档



**它能解决什么问题？**



要将带有数学符号和公式的数学题图片整理到 Word 文档，手动录入不仅耗时且容易出错，而普通 OCR 工具要么只能识别文字要么只能识别公式和符号，而 MathOCR Pro 就能很好解决这一难题。



**原理：**用 LLM 视觉模型（Qwen VL）或多模态模型（  kimi 2.6）识别图片，把公式转成 LaTeX，然后在排版不变的情况下，和文字内容一起写入 Markdown，最后通过 Pandoc 渲染处理成 Word

---



## 快速开始



### 第一步：配置



- **Python 3.12+**：[python.org](https://www.python.org/downloads/)
- **uv**（Python 包管理器）：
  
  ```bash
  # macOS / Linux
  curl -LsSf https://astral.sh/uv/install.sh | sh
  
  # Windows（PowerShell）
  powershell -ExecutionPolicy ByPass -c "irm https://astral.sh/uv/install.ps1 | iex"
  ```
- **Pandoc**（文档转换引擎）：[pandoc.org/installing.html](https://pandoc.org/installing.html)
  > 安装系统级 Pandoc 后项目自动找到它。也可以把 `pandoc.exe`（Windows）或 `pandoc`（macOS/Linux）直接放进项目根目录来代替系统安装



### 第二步：克隆并安装项目依赖



```bash
git clone <仓库地址>
cd MathOCR-Pro
uv sync
```



### 第三步：配置 .env 文件



详见 `.env.example` 文件

```
# 当前使用的模型（切换只需改这一行）
MODEL=qwen-vl-plus-latest

# Kimi (Moonshot AI) — kimi-k2.6 / kimi-k2.5
KIMI_API_KEY=your_kimi_api_key_here
KIMI_BASE_URL=https://api.moonshot.cn/v1

# Qwen VL (Alibaba DashScope) — qwen-vl-plus-latest / qwen-vl-max-latest
QWEN_API_KEY=your_qwen_api_key_here
QWEN_BASE_URL=https://dashscope.aliyuncs.com/compatible-mode/v1
```



> **推荐新手用 `qwen-vl-plus-latest`**：在阿里百炼平台注册后可免费试用 100 万 tokens，足够转换大量图片。获取 API Key：https://bailian.console.aliyun.com/cn-beijing?tab=model



### 第四步：启动



```bash
uv run main.py
```



打开浏览器访问 **http://127.0.0.1:8000**，拖入图片即可开始转换




## 使用方式



### Web 界面（推荐）



启动后在浏览器里操作：

- 拖拽或选择图片（PNG / JPG / JPEG / WEBP，可多选）
- 实时查看每张图片的处理进度和状态
- 转换完成后直接点击下载对应的 Word 文件，或一键「下载全部」
- 随时取消单个任务或停止全部

模型、API Key、并发数量等设置可在页面的「设置」页配置，保存到本地 `settings.local.json`，不会上传到 git



### CLI 批量处理



把图片放进项目根目录的 `img/` 文件夹，然后运行：

```bash
uv run main.py --cli
```

转换结果输出到 `output/` 目录。加 `--force` 参数可强制覆盖已有输出：

```bash
uv run main.py --cli --force
```



## 支持的模型



只要是 OpenAI 兼容接口的视觉模型都可以接入。**推荐使用 `qwen-vl-plus-latest`**，识别效果好，新用户在阿里百炼平台可免费试用 100 万 tokens。

| 服务商 | 模型 | MODEL 填写 | API Key 获取 |
|---|---|---|---|
| **阿里云百炼（推荐）** | qwen-vl-plus-latest | `qwen-vl-plus-latest` | [免费领取 100 万 tokens](https://bailian.console.aliyun.com/cn-beijing?tab=model) |
| 月之暗面（Kimi） | kimi-k2.6 | `kimi-k2.6` | [platform.moonshot.cn](https://platform.moonshot.cn) |

切换模型只需修改 `.env` 里的 `MODEL=` 一行，或在 Web 设置页直接填写模型名和 Base URL。



## 其他



**项目结构：**

```
core.py          核心逻辑：AI 识别 → Markdown → Word
config.py        配置加载（.env 与 settings.local.json）
main.py          CLI 入口
webapp/
  app.py         Web 服务（FastAPI）
  jobs.py        任务队列与并发管理
  static/        前端页面
pandoc.exe
```
