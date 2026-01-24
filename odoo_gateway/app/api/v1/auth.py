from fastapi import APIRouter, HTTPException, status, Depends
from sqlalchemy.orm import Session
from app.database import get_db
from app.models.license import LicenseInstance
from app.models.auth import AuthAttempt
from app.schemas.auth import (
    LicenseValidationRequest, 
    LicenseValidationResponse,
    LoginRequest, 
    LoginResponse,
    RefreshTokenRequest
)
from app.core.security import create_access_token, decode_access_token
from app.core.odoo_connector import OdooConnector
import json
import logging
from app.config import settings

logger = logging.getLogger(__name__)
router = APIRouter()


@router.post("/validate-license", response_model=LicenseValidationResponse)
async def validate_license(
    request: LicenseValidationRequest,
    db: Session = Depends(get_db)
):
    """
    ONE-TIME license validation endpoint.
    
    This is optional and only needed if you want to verify a license
    before attempting login. The /login endpoint will also validate
    the license, so this step is not mandatory.
    
    Use case: Initial setup or license verification without login.
    """
    try:
        license_instance = db.query(LicenseInstance).filter(
            LicenseInstance.license_key == request.license_key,
            LicenseInstance.is_active == True
        ).first()
        
        if not license_instance:
            logger.warning(f"Invalid license key attempted: {request.license_key}")
            return LicenseValidationResponse(
                success=False,
                error="Invalid or inactive license key"
            )

        logger.info(f"License validated successfully: {request.license_key}")
        return LicenseValidationResponse(
            success=True,
            data={
                "license_key": request.license_key,
                "company_info": {
                    "company_name": license_instance.company_name,
                    "odoo_url": license_instance.odoo_url,
                    "database": license_instance.database_name
                },
                "message": "License is valid. You can now proceed to login."
            }
        )
        
    except Exception as e:
        logger.error(f"License validation error: {e}")
        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail="Internal server error during license validation"
        )


@router.post("/login", response_model=LoginResponse)
async def login(
    request: LoginRequest,
    db: Session = Depends(get_db)
):
    """
    Direct login endpoint - NO session token required!
    
    Flow:
    1. Validates license key
    2. Authenticates user with Odoo
    3. Returns 24-hour access token
    
    The access token contains all necessary information for subsequent API calls.
    """
    try:
        # Step 1: Validate license key
        license_instance = db.query(LicenseInstance).filter(
            LicenseInstance.license_key == request.license_key,
            LicenseInstance.is_active == True
        ).first()
        
        if not license_instance:
            logger.warning(f"Invalid license key in login attempt: {request.license_key}")
            return LoginResponse(
                success=False,
                error="Invalid or inactive license key"
            )

        # Step 2: Authenticate with Odoo
        connector = OdooConnector(
            url=license_instance.odoo_url,
            database=license_instance.database_name,
            username=request.username,
            password=request.password
        )

        auth_success = await connector.authenticate()

        # Log authentication attempt
        auth_attempt = AuthAttempt(
            license_key=request.license_key,
            username=request.username,
            success="success" if auth_success else "failed"
        )
        db.add(auth_attempt)
        db.commit()

        if not auth_success:
            logger.warning(f"Authentication failed for user: {request.username}")
            return LoginResponse(
                success=False,
                error="Invalid credentials. Please check your username and password."
            )

        # Step 3: Fetch user information from Odoo
        try:
            # Get basic user info
            user_info_list = await connector.search_read(
                'res.users',
                domain=[['id', '=', connector.uid]],
                fields=['name', 'email']
            )
            user_info = user_info_list[0] if user_info_list else {}

            # Resolve employee_id and related data
            employee_id = None
            company_id = None
            currency_id = None

            # Try to find employee by user_id
            employee_data = await connector.search_read(
                'hr.employee',
                domain=[('user_id', '=', connector.uid)],
                fields=['id', 'company_id']
            )

            # Fallback: match by email if user_id link not set
            if not employee_data and user_info.get('email'):
                employee_data = await connector.search_read(
                    'hr.employee',
                    domain=[('work_email', '=', user_info['email'])],
                    fields=['id', 'company_id']
                )

            if employee_data:
                employee_id = employee_data[0]['id']
                if employee_data[0].get('company_id'):
                    company_id = employee_data[0]['company_id'][0]

                # Get currency from company
                if company_id:
                    company_data = await connector.search_read(
                        'res.company',
                        domain=[('id', '=', company_id)],
                        fields=['currency_id']
                    )
                    if company_data and company_data[0].get('currency_id'):
                        currency_id = company_data[0]['currency_id'][0]

        except Exception as e:
            logger.error(f"Failed to get user info: {e}")
            raise HTTPException(
                status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
                detail=f"Failed to retrieve user information: {str(e)}"
            )

        # Step 4: Create 24-hour access token with all necessary data
        token_data = {
            "license_key": request.license_key,
            "user_id": connector.uid,
            "username": request.username,
            "password": request.password,
            "odoo_url": license_instance.odoo_url,
            "database": license_instance.database_name,
            "exec_username": license_instance.exec_username,
            "exec_password": license_instance.exec_password,
            "employee_id": employee_id,
            "company_id": company_id,
            "currency_id": currency_id,
            "is_portal": True
        }

        # Create access token valid for 24 hours (1440 minutes)
        access_token = create_access_token(
            json.dumps(token_data),
            expires_minutes=1440
        )

        logger.info(f"User logged in successfully: {request.username} (License: {request.license_key})")
        
        return LoginResponse(
            success=True,
            data={
                "access_token": access_token,
                "token_type": "bearer",
                "expires_in": 86400,  # 24 hours in seconds
                "employee_id": employee_id,
                "company_id": company_id,
                "currency_id": currency_id,
                "user_info": {
                    "id": connector.uid,
                    "name": user_info.get('name', ''),
                    "email": user_info.get('email', '')
                }
            }
        )

    except HTTPException:
        raise
    except Exception as e:
        logger.error(f"Login error: {e}", exc_info=True)
        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail="Internal server error during login"
        )


@router.post("/refresh-token", response_model=LoginResponse)
async def refresh_token(
    request: RefreshTokenRequest,
    db: Session = Depends(get_db)
):
    """
    Refresh an existing access token without requiring re-authentication.
    
    Use this endpoint before your token expires (within 24 hours) to get
    a new token without asking the user to log in again.
    
    Best practice: Refresh when token has <1 hour remaining.
    """
    try:
        # Decode and validate current token
        token_data = decode_access_token(request.refresh_token)
        
        if not token_data:
            logger.warning("Invalid or expired token in refresh attempt")
            raise HTTPException(
                status_code=status.HTTP_401_UNAUTHORIZED,
                detail="Invalid or expired token. Please log in again."
            )
        
        # Verify license is still active
        license_instance = db.query(LicenseInstance).filter(
            LicenseInstance.license_key == token_data.get('license_key'),
            LicenseInstance.is_active == True
        ).first()
        
        if not license_instance:
            logger.warning(f"License no longer active: {token_data.get('license_key')}")
            raise HTTPException(
                status_code=status.HTTP_401_UNAUTHORIZED,
                detail="License is no longer active. Please contact support."
            )
        
        # Create new token with same data but extended expiry
        new_access_token = create_access_token(
            json.dumps(token_data),
            expires_minutes=1440  # 24 hours
        )
        
        logger.info(f"Token refreshed for user: {token_data.get('username')}")
        
        return LoginResponse(
            success=True,
            data={
                "access_token": new_access_token,
                "token_type": "bearer",
                "expires_in": 86400,  # 24 hours in seconds
                "employee_id": token_data.get('employee_id'),
                "company_id": token_data.get('company_id'),
                "currency_id": token_data.get('currency_id'),
                "user_info": {
                    "id": token_data.get('user_id'),
                    "name": token_data.get('name', ''),
                    "email": token_data.get('email', '')
                }
            }
        )
        
    except HTTPException:
        raise
    except Exception as e:
        logger.error(f"Token refresh error: {e}", exc_info=True)
        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail="Internal server error during token refresh"
        )


@router.post("/logout")
async def logout():
    """
    Logout endpoint (optional).
    
    Since we're using stateless JWT tokens, logout is handled client-side
    by deleting the stored token. This endpoint exists for consistency
    and can be used to log the logout event if needed.
    """
    return {
        "success": True,
        "message": "Logged out successfully. Please delete your access token."
    }