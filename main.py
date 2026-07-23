import os
import sys
import argparse
from concurrent.futures import ThreadPoolExecutor, as_completed

BASE_DIR = os.path.dirname(os.path.abspath(__file__))

from dotenv import load_dotenv
load_dotenv(override=True)

from core import convert_image
from config import load_config, default_output_dir
import pypandoc


def process_one(image_filename: str, force: bool = False):
    img_path = os.path.join(BASE_DIR, "img", image_filename)
    cfg = load_config()
    out_dir = cfg.get('output_dir') or default_output_dir()
    os.makedirs(out_dir, exist_ok=True)

    basename   = os.path.splitext(image_filename)[0]
    output_path = os.path.join(out_dir, f"{basename}.docx")

    if not force and os.path.exists(output_path):
        print(f"⏭ 跳过（已存在）: {image_filename}")
        return

    print(f"⏳ 处理: {image_filename}...")

    def cb(pct, label):
        print(f"  [{pct:3d}%] {label}")

    try:
        in_t, out_t = convert_image(img_path, output_path, cfg, cb)
        print(f"🎉 完成: {os.path.relpath(output_path, BASE_DIR)}  "
              f"(tokens in={in_t} out={out_t})")
    except Exception as exc:
        print(f"❌ 错误 [{image_filename}]: {exc}")


def run_web(host: str = "127.0.0.1", port: int = 8000):
    import uvicorn

    uvicorn.run("webapp.app:app", host=host, port=port)


def run_cli(force: bool = False):
    try:
        pypandoc.get_pandoc_path()
    except OSError:
        print("❌ 找不到 pandoc，请安装后重试：https://pandoc.org/installing.html")
        sys.exit(1)

    img_dir = os.path.join(BASE_DIR, "img")
    if not os.path.exists(img_dir):
        os.makedirs(img_dir, exist_ok=True)
        print("⚠️ 已创建 img/ 目录，请放入图片后重新运行。")
        return

    valid = {".png", ".jpg", ".jpeg", ".webp"}
    files = [
        f for f in os.listdir(img_dir)
        if os.path.isfile(os.path.join(img_dir, f))
        and os.path.splitext(f)[1].lower() in valid
    ]

    if not files:
        print("📁 img/ 目录为空，无可处理的图片。")
        return

    cfg = load_config()
    max_workers = cfg.get('max_workers', 3)

    print(f"📂 共 {len(files)} 张图片，并发数 {max_workers}\n" + "=" * 50)

    with ThreadPoolExecutor(max_workers=max_workers) as pool:
        futures = {pool.submit(process_one, f, force): f for f in files}
        for future in as_completed(futures):
            try:
                future.result()
            except Exception as exc:
                print(f"❌ 任务异常: {exc}")

    print("=" * 50 + "\n🚀 全部完成！")


def main():
    parser = argparse.ArgumentParser(description="数学图片转 Word")
    parser.add_argument("--cli", action="store_true", help="使用 img/ 目录批量转换，而不是启动 Web 界面")
    parser.add_argument("--force", action="store_true", help="CLI 模式下强制覆盖已有输出")
    parser.add_argument("--host", default="127.0.0.1", help="Web 服务监听地址")
    parser.add_argument("--port", type=int, default=8000, help="Web 服务监听端口")
    args = parser.parse_args()

    if args.cli:
        run_cli(args.force)
    else:
        run_web(args.host, args.port)


if __name__ == "__main__":
    main()
