from pydantic_settings import BaseSettings
from typing import List
import os

# Debug: Print current working directory and .env file location
print(f"Current working directory: {os.getcwd()}")
env_path = os.path.join(os.path.dirname(os.path.dirname(__file__)), ".env")
print(f"Looking for .env file at: {env_path}")
print(f".env file exists: {os.path.exists(env_path)}")

# If .env exists, let's see what's in the directory
if os.path.exists(os.path.dirname(env_path)):
    print(f"Contents of parent directory: {os.listdir(os.path.dirname(env_path))}")

class Settings(BaseSettings):
    # Application
    APP_NAME: str = "Universal Odoo Gateway"
    APP_VERSION: str = "1.0.0"
    DEBUG: bool = False
    API_V1_STR: str = "/api/v1"
    
    # Security - NO DEFAULT VALUES for sensitive data
    SECRET_KEY: str
    ALGORITHM: str = "HS256"
    ACCESS_TOKEN_EXPIRE_HOURS: int = 24
    SESSION_TOKEN_EXPIRE_MINUTES: int = 5
    
    # Database - NO DEFAULT VALUES for sensitive data
    DATABASE_URL: str
    
    # Redis
    REDIS_URL: str = "redis://localhost:6379/0"
    
    # CORS
    BACKEND_CORS_ORIGINS: List[str] = []
    
    class Config:
        env_file = os.path.join(os.path.dirname(os.path.dirname(__file__)), ".env")
        case_sensitive = True

settings = Settings()