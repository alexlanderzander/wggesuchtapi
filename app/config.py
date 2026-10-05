from functools import lru_cache
from pydantic_settings import BaseSettings, SettingsConfigDict


class Settings(BaseSettings):
    model_config = SettingsConfigDict(env_file='.env', env_file_encoding='utf-8', extra='ignore')

    app_secret_key: str = 'change-me'
    app_base_url: str = 'http://127.0.0.1:8000'
    database_path: str = '.data/wg_review.sqlite3'

    wg_gesucht_email: str = ''
    wg_gesucht_password: str = ''
    wg_session_file: str = '.data/wg_session.json'

    google_client_id: str = ''
    google_client_secret: str = ''
    google_redirect_uri: str = 'http://127.0.0.1:8000/api/calendar/google/callback'

    microsoft_client_id: str = ''
    microsoft_client_secret: str = ''
    microsoft_redirect_uri: str = 'http://127.0.0.1:8000/api/calendar/microsoft/callback'


@lru_cache
def get_settings() -> Settings:
    return Settings()
