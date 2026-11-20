"""读取客服配置，环境文件始终位于项目根目录。"""

from pathlib import Path

from pydantic_settings import BaseSettings, SettingsConfigDict

ROOT = Path(__file__).resolve().parents[2]


class Settings(BaseSettings):
    model_config = SettingsConfigDict(env_file=ROOT / ".env", extra="ignore", env_file_encoding="utf-8")
    chat_database_url: str = ""
    edu_data_base_url: str = "http://127.0.0.1:8000"
    order_items_base_url: str = "http://127.0.0.1:8002"
    chat_demo_auth_enabled: bool = False
    model_base_url: str = ""
    model_api_key: str = ""
    model_name: str = ""
    knowledge_version: str = "v1"
