from pydantic import BaseModel, field_validator
from typing import Optional, Dict, Any, List
from datetime import datetime


class EmployeeInfo(BaseModel):
    id: int
    name: str
    email: Optional[str] = None
    phone: Optional[str] = None
    mobile: Optional[str] = None
    job_title: Optional[str] = None
    job_id: Optional[int] = None
    job_name: Optional[str] = None
    department_id: Optional[int] = None
    department_name: Optional[str] = None
    image: Optional[str] = None  # Base64 encoded employee image
    
    @field_validator('email', 'phone', 'mobile', 'job_title', 'image', mode='before')
    @classmethod
    def convert_false_to_none(cls, v):
        """Convert Odoo False to None"""
        return None if v is False else v

# Login response - no company object
class LoginResponseData(BaseModel):
    access_token: str
    token_type: str
    expires_in: int
    employee_id: Optional[int] = None
    company_id: Optional[int] = None
    currency_id: Optional[int] = None
    user_info: Dict[str, Any]
    employee: Optional[EmployeeInfo] = None

# Company details response
class CompanyDetails(BaseModel):
    id: int
    name: str
    street: Optional[str] = None
    street2: Optional[str] = None
    city: Optional[str] = None
    state_id: Optional[int] = None
    state_name: Optional[str] = None
    zip: Optional[str] = None
    country_id: Optional[int] = None
    country_name: Optional[str] = None
    phone: Optional[str] = None
    mobile: Optional[str] = None
    email: Optional[str] = None
    website: Optional[str] = None
    currency_id: Optional[int] = None
    currency_name: Optional[str] = None
    logo: Optional[str] = None  # Base64 encoded logo
    vat: Optional[str] = None
    company_registry: Optional[str] = None
    
    @field_validator(
        'street', 'street2', 'city', 'zip', 'phone', 'mobile', 
        'email', 'website', 'logo', 'vat', 'company_registry', 
        mode='before'
    )
    @classmethod
    def convert_false_to_none(cls, v):
        """Convert Odoo False to None"""
        return None if v is False else v

class CompanyDetailsResponse(BaseModel):
    success: bool
    data: Optional[CompanyDetails] = None
    error: Optional[str] = None

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
    data: Optional[LoginResponseData] = None
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