from pathlib import Path
from typing import Annotated, Callable

from dotenv import load_dotenv
from fastapi import FastAPI, File, HTTPException, UploadFile
from fastapi.responses import FileResponse, HTMLResponse, Response
from fastapi.staticfiles import StaticFiles
from pydantic import BaseModel

from config import MASKED_API_KEY, load_config, load_web_settings, save_web_settings
from core import convert_image, test_model_connection
from webapp.jobs import JobManager, JobStatus

BASE_DIR = Path(__file__).resolve().parents[1]
STATIC_DIR = Path(__file__).resolve().parent / "static"
VALID_IMAGE_EXTS = {".png", ".jpg", ".jpeg", ".webp"}


class SettingsPayload(BaseModel):
    model: str
    base_url: str = ""
    api_key: str = ""
    max_workers: int = 3
    input_token_price_per_million: float = 0
    output_token_price_per_million: float = 0


def friendly_connection_error(exc: Exception, cfg: dict) -> str:
    raw = str(exc).strip() or exc.__class__.__name__
    api_key = str(cfg.get("api_key") or "")
    if api_key:
        raw = raw.replace(api_key, "API Key")

    model = str(cfg.get("model") or "").strip()
    model_name = f"“{model}”" if model else "当前填写的模型"
    status_code = str(getattr(exc, "status_code", "") or "")
    provider_code = str(getattr(exc, "code", "") or "")
    body = str(getattr(exc, "body", "") or "")
    text = " ".join([raw, status_code, provider_code, body]).lower()

    if any(marker in text for marker in ("model_not_found", "does not exist", "model not found")):
        return f"不可用：模型名称{model_name}不可用。请检查模型名是否拼写正确，或确认当前 API Key 已开通这个模型。"
    if "do not have access" in text or "permission" in text or status_code == "403":
        return "不可用：当前 API Key 没有权限访问这个模型。请在服务商后台开通模型权限，或换一个已授权的 API Key。"
    if "401" in text or "unauthorized" in text or "invalid api key" in text or "incorrect api key" in text:
        return "不可用：API Key 无效或已过期。请重新复制服务商后台的 API Key，保存后再测试。"
    if "insufficient_quota" in text or "quota" in text or "balance" in text or "余额" in text:
        return "不可用：账号额度不足。请检查服务商后台的余额、套餐或免费额度是否还能使用。"
    if "rate limit" in text or "too many requests" in text or status_code == "429":
        return "不可用：请求太频繁。请稍等一会儿再测试，或降低并发数量。"
    if "timed out" in text or "timeout" in text:
        return "不可用：连接超时。请检查网络是否正常，或确认 Base URL 是否填写正确。"
    if any(marker in text for marker in ("connection error", "connection refused", "getaddrinfo", "name resolution", "nodename", "dns")):
        return "不可用：无法连接到模型服务。请检查 Base URL 是否正确，以及当前网络是否能访问服务商接口。"
    if "ssl" in text or "certificate" in text:
        return "不可用：HTTPS 证书验证失败。请确认 Base URL 是服务商提供的正式 HTTPS 地址。"
    if "method not allowed" in text or status_code == "405":
        return "不可用：Base URL 不是可用的模型接口地址。请填写服务商的 OpenAI 兼容地址，通常需要以 /v1 结尾。"
    if "404" in text or "not found" in text:
        return "不可用：接口地址没有找到。请检查 Base URL 是否填成服务商的 OpenAI 兼容地址。"

    return "不可用：连接失败。请检查模型名称、Base URL 和 API Key 是否与服务商后台一致。"


def frontend_version() -> str:
    assets = [
        STATIC_DIR / "index.html",
        STATIC_DIR / "styles.css",
        STATIC_DIR / "app.js",
    ]
    stamps = [path.stat().st_mtime_ns for path in assets if path.exists()]
    return str(max(stamps, default=0))


def create_app(
    job_manager: JobManager | None = None,
    settings_path: str | Path | None = None,
    settings_tester: Callable[[dict], None] | None = None,
) -> FastAPI:
    load_dotenv(override=True)
    app = FastAPI(title="MathImgToWord Web")
    settings_file = Path(settings_path) if settings_path is not None else None
    manager = job_manager or JobManager(
        storage_dir=BASE_DIR / "runtime",
        converter=convert_image,
        config_loader=lambda: load_config(settings_file),
    )
    tester = settings_tester or test_model_connection

    @app.middleware("http")
    async def prevent_frontend_cache(request, call_next):
        response = await call_next(request)
        if request.url.path == "/" or request.url.path.startswith("/static/"):
            response.headers["Cache-Control"] = "no-store"
        return response

    if STATIC_DIR.exists():
        app.mount("/static", StaticFiles(directory=STATIC_DIR), name="static")

    @app.get("/")
    def index():
        index_path = STATIC_DIR / "index.html"
        if not index_path.exists():
            raise HTTPException(status_code=404, detail="Frontend is not built")
        version = frontend_version()
        html = index_path.read_text(encoding="utf-8")
        html = html.replace('/static/styles.css"', f'/static/styles.css?v={version}"')
        html = html.replace(
            '<script src="/static/app.js"></script>',
            f'<script>window.__MATHIMG_APP_VERSION__ = "{version}";</script>\n  '
            f'<script src="/static/app.js?v={version}"></script>',
        )
        return HTMLResponse(html)

    @app.get("/favicon.ico", include_in_schema=False)
    def favicon():
        return Response(status_code=204)

    @app.get("/api/frontend-version")
    def get_frontend_version():
        return {"version": frontend_version()}

    @app.get("/api/settings")
    def get_settings():
        return load_web_settings(settings_file, mask_api_key=True)

    @app.put("/api/settings")
    def put_settings(payload: SettingsPayload):
        try:
            saved = save_web_settings(payload.model_dump(), settings_file)
            manager.configure(saved["max_workers"])
            return saved
        except ValueError as exc:
            raise HTTPException(status_code=400, detail=str(exc)) from exc

    @app.post("/api/settings/test")
    def test_settings(payload: SettingsPayload):
        if not payload.model.strip():
            raise HTTPException(status_code=400, detail="模型名称不能为空")
        existing = load_config(settings_file)
        data = payload.model_dump()
        api_key = data.get("api_key") or ""
        if api_key == MASKED_API_KEY:
            api_key = existing.get("api_key") or ""
        cfg = {
            **existing,
            "model": payload.model.strip(),
            "base_url": payload.base_url.strip(),
            "api_key": api_key.strip(),
            "max_workers": payload.max_workers,
            "input_token_price_per_million": payload.input_token_price_per_million,
            "output_token_price_per_million": payload.output_token_price_per_million,
        }
        if not cfg["api_key"]:
            raise HTTPException(status_code=400, detail="API Key 不能为空")
        try:
            tester(cfg)
        except Exception as exc:
            raise HTTPException(status_code=400, detail=friendly_connection_error(exc, cfg)) from exc
        return {"ok": True, "message": "可用：已成功连接模型"}

    @app.post("/api/jobs")
    async def create_jobs(files: Annotated[list[UploadFile], File(...)]):
        if not files:
            raise HTTPException(status_code=400, detail="请至少上传一张图片")
        jobs = []
        for upload in files:
            ext = Path(upload.filename or "").suffix.lower()
            if ext not in VALID_IMAGE_EXTS:
                raise HTTPException(status_code=400, detail=f"不支持的图片格式: {upload.filename}")
            content = await upload.read()
            if not content:
                raise HTTPException(status_code=400, detail=f"图片为空: {upload.filename}")
            jobs.append(manager.create_job(upload.filename or "image", content).to_dict())
        return {"jobs": jobs}

    @app.get("/api/jobs")
    def list_jobs():
        return {"jobs": [job.to_dict() for job in manager.list_jobs()]}

    def clear_jobs_response():
        try:
            return {"jobs": [job.to_dict() for job in manager.clear_jobs()]}
        except RuntimeError as exc:
            raise HTTPException(status_code=409, detail=str(exc)) from exc

    @app.post("/api/jobs/clear")
    def clear_jobs_post():
        return clear_jobs_response()

    @app.get("/api/jobs/{job_id}")
    def get_job(job_id: str):
        try:
            return manager.get_job(job_id).to_dict()
        except KeyError as exc:
            raise HTTPException(status_code=404, detail="任务不存在") from exc

    @app.post("/api/jobs/{job_id}/cancel")
    def cancel_job(job_id: str):
        try:
            return manager.cancel_job(job_id).to_dict()
        except KeyError as exc:
            raise HTTPException(status_code=404, detail="任务不存在") from exc

    @app.post("/api/jobs/cancel")
    def cancel_all():
        return {"jobs": [job.to_dict() for job in manager.cancel_all()]}

    @app.delete("/api/jobs")
    def clear_jobs():
        return clear_jobs_response()

    @app.get("/api/jobs/{job_id}/download")
    def download_job(job_id: str):
        try:
            job = manager.get_job(job_id)
        except KeyError as exc:
            raise HTTPException(status_code=404, detail="任务不存在") from exc
        if job.status != JobStatus.COMPLETED:
            raise HTTPException(status_code=409, detail="任务尚未完成")
        output_path = Path(job.output_path)
        if not output_path.exists():
            raise HTTPException(status_code=404, detail="输出文件不存在")
        return FileResponse(
            output_path,
            filename=f"{Path(job.filename).stem}.docx",
            media_type="application/vnd.openxmlformats-officedocument.wordprocessingml.document",
        )

    return app


app = create_app()
