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
    """
    Updated LoginRequest - now requires license_key instead of session_token
    This enables direct login without prior license validation
    """
    license_key: str
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
    password: str
    exec_username: str
    exec_password: str
    odoo_url: str
    database: str
    employee_id: Optional[int] = None
    company_id: Optional[int] = None
    currency_id: Optional[int] = None
    is_portal: Optional[bool] = True


class RefreshTokenRequest(BaseModel):
    """New schema for token refresh endpoint"""
    refresh_token: str