from pydantic import BaseModel
from typing import Optional, Dict, Any, List
from datetime import datetime


class LicenseValidationRequest(BaseModel):
    license_key: str


class LicenseValidationResponse(BaseModel):
    success: bool
    data: Optional[Dict[str, Any]] = None
    error: Optional[str] = None


class LoginRequest(BaseModel):
    session_token: str
    username: str
    password: str


class UserInfo(BaseModel):
    id: int
    name: str
    email: str
    permissions: List[str]


class LoginResponse(BaseModel):
    success: bool
    data: Optional[Dict[str, Any]] = None
    error: Optional[str] = None


class TokenData(BaseModel):
    license_key: str
    user_id: int
    username: str
    password: str  # Store encrypted in production
    odoo_url: str
    database: str