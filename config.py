import json
import os
from pathlib import Path
from typing import Any

# 按模型名前缀路由到对应 provider 的 env 变量
_PROVIDERS: dict[str, tuple[str, str, str]] = {
    'kimi': ('KIMI_API_KEY', 'KIMI_BASE_URL', 'https://api.moonshot.cn/v1'),
    'qwen': ('QWEN_API_KEY', 'QWEN_BASE_URL', 'https://dashscope.aliyuncs.com/compatible-mode/v1'),
}

BASE_DIR = Path(__file__).resolve().parent
SETTINGS_FILE = BASE_DIR / 'settings.local.json'
MASKED_API_KEY = '••••••••••••'


def _provider_for(model: str) -> tuple[str, str, str]:
    for prefix, cfg in _PROVIDERS.items():
        if model.lower().startswith(prefix):
            return cfg
    # 兜底：读通用变量
    return ('OPENAI_API_KEY', 'OPENAI_BASE_URL', '')


def _settings_path(settings_path: str | os.PathLike[str] | None = None) -> Path:
    return Path(settings_path) if settings_path is not None else SETTINGS_FILE


def _read_local_settings(settings_path: str | os.PathLike[str] | None = None) -> dict[str, Any]:
    path = _settings_path(settings_path)
    if not path.exists():
        return {}
    with path.open('r', encoding='utf-8') as f:
        data = json.load(f)
    return data if isinstance(data, dict) else {}


def _env_config() -> dict:
    model = os.getenv('MODEL', 'kimi-k2.6')
    key_var, url_var, default_url = _provider_for(model)
    return {
        'api_key':    os.getenv(key_var),
        'base_url':   os.getenv(url_var, default_url),
        'model':      model,
        'output_dir': os.getenv('OUTPUT_DIR'),
        'max_workers': int(os.getenv('MAX_WORKERS', '3')),
    }


def _coerce_max_workers(value: Any) -> int:
    try:
        max_workers = int(value)
    except (TypeError, ValueError) as exc:
        raise ValueError('max_workers must be a positive integer') from exc
    if max_workers < 1:
        raise ValueError('max_workers must be a positive integer')
    return max_workers


def _coerce_token_price(value: Any) -> float:
    if value in (None, ''):
        return 0.0
    try:
        price = float(value)
    except (TypeError, ValueError) as exc:
        raise ValueError('token price must be a non-negative number') from exc
    if price < 0:
        raise ValueError('token price must be a non-negative number')
    return price


def load_config(settings_path: str | os.PathLike[str] | None = None) -> dict:
    cfg = _env_config()
    cfg['input_token_price_per_million'] = _coerce_token_price(os.getenv('INPUT_TOKEN_PRICE_PER_MILLION', 0))
    cfg['output_token_price_per_million'] = _coerce_token_price(os.getenv('OUTPUT_TOKEN_PRICE_PER_MILLION', 0))
    local = _read_local_settings(settings_path)
    if not local:
        return cfg

    if local.get('model'):
        cfg['model'] = str(local['model'])
    if local.get('base_url') is not None:
        cfg['base_url'] = str(local['base_url'])
    if local.get('api_key'):
        cfg['api_key'] = str(local['api_key'])
    if local.get('max_workers') is not None:
        cfg['max_workers'] = _coerce_max_workers(local['max_workers'])
    if local.get('input_token_price_per_million') is not None:
        cfg['input_token_price_per_million'] = _coerce_token_price(local['input_token_price_per_million'])
    if local.get('output_token_price_per_million') is not None:
        cfg['output_token_price_per_million'] = _coerce_token_price(local['output_token_price_per_million'])
    return cfg


def load_web_settings(
    settings_path: str | os.PathLike[str] | None = None,
    mask_api_key: bool = True,
) -> dict:
    cfg = load_config(settings_path)
    api_key = cfg.get('api_key') or ''
    return {
        'model': cfg.get('model') or '',
        'base_url': cfg.get('base_url') or '',
        'api_key': MASKED_API_KEY if mask_api_key and api_key else api_key,
        'max_workers': cfg.get('max_workers', 3),
        'input_token_price_per_million': cfg.get('input_token_price_per_million', 0),
        'output_token_price_per_million': cfg.get('output_token_price_per_million', 0),
    }


def save_web_settings(
    data: dict[str, Any],
    settings_path: str | os.PathLike[str] | None = None,
) -> dict:
    path = _settings_path(settings_path)
    existing = load_config(path)
    api_key = data.get('api_key', existing.get('api_key') or '')
    if api_key == MASKED_API_KEY:
        api_key = existing.get('api_key') or ''

    settings = {
        'model': str(data.get('model') or existing.get('model') or 'kimi-k2.6').strip(),
        'base_url': str(data.get('base_url') if data.get('base_url') is not None else existing.get('base_url') or '').strip(),
        'api_key': str(api_key or '').strip(),
        'max_workers': _coerce_max_workers(data.get('max_workers', existing.get('max_workers', 3))),
        'input_token_price_per_million': _coerce_token_price(
            data.get('input_token_price_per_million', existing.get('input_token_price_per_million', 0))
        ),
        'output_token_price_per_million': _coerce_token_price(
            data.get('output_token_price_per_million', existing.get('output_token_price_per_million', 0))
        ),
    }
    if not settings['model']:
        raise ValueError('model is required')

    path.parent.mkdir(parents=True, exist_ok=True)
    with path.open('w', encoding='utf-8') as f:
        json.dump(settings, f, ensure_ascii=False, indent=2)
    return load_web_settings(path, mask_api_key=True)


def default_output_dir() -> str:
    return str(BASE_DIR / 'output')
