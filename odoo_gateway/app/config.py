from pydantic_settings import BaseSettings
from typing import List
import os

class Settings(BaseSettings):
    # Application
    APP_NAME: str = "Universal Odoo Gateway"
    APP_VERSION: str = "1.0.0"
    DEBUG: bool = False
    API_V1_STR: str = "/api/v1"
    
    # Security - NO DEFAULT VALUES for sensitive data
    SECRET_KEY: str
    ALGORITHM: str = "HS256"
    ACCESS_TOKEN_EXPIRE_HOURS: int = 24 * 30  # 30 days
    SESSION_TOKEN_EXPIRE_MINUTES: int = 24 * 30  # 30 days
    
    # Database - NO DEFAULT VALUES for sensitive data
    DATABASE_URL: str
    
    # Redis
    REDIS_URL: str = "redis://localhost:6379/0"
    
    # CORS
    BACKEND_CORS_ORIGINS: List[str] = []

    # Connection Pool
    ODOO_CONNECTION_POOL_SIZE: int = 20
    ODOO_CONNECTION_POOL_TIMEOUT: int = 30
    ODOO_CONNECTION_MAX_LIFETIME: int = 300
    ODOO_CONNECTION_IDLE_TIMEOUT: int = 60
    
    # Cache
    REDIS_MAX_CONNECTIONS: int = 50
    CACHE_FIELD_METADATA_TTL: int = 7200
    ENABLE_CACHE: bool = True
    
    # Rate Limiting
    RATE_LIMIT_ENABLED: bool = True
    RATE_LIMIT_PER_USER: int = 100
    RATE_LIMIT_BURST: int = 20
    
    # Workers
    WORKERS: int = 4
    WORKER_CONNECTIONS: int = 1000
    
    class Config:
        env_file = os.path.join(os.path.dirname(os.path.dirname(__file__)), ".env")
        case_sensitive = True

settings = Settings()