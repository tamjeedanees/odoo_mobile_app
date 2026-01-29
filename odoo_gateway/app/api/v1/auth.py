import asyncio
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
    3. Returns 24-hour access token with employee details
    
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

        # Step 2: Validate exec (internal/admin) credentials first
        exec_connector = OdooConnector(
            url=license_instance.odoo_url,
            database=license_instance.database_name,
            username=license_instance.exec_username,
            password=license_instance.exec_password
        )

        exec_auth_success = await exec_connector.authenticate()

        if not exec_auth_success:
            logger.error(
                f"Executive credentials authentication failed for license: {request.license_key}"
            )
            # Log failed exec auth attempt
            auth_attempt = AuthAttempt(
                license_key=request.license_key,
                username=f"EXEC:{license_instance.exec_username}",
                success="exec_failed"
            )
            db.add(auth_attempt)
            db.commit()
            
            return LoginResponse(
                success=False,
                error="Invalid internal user credentials. Please contact your system administrator."
            )

        logger.info(f"Executive credentials validated successfully for license: {request.license_key}")

        # Step 3: Authenticate user with Odoo
        user_connector = OdooConnector(
            url=license_instance.odoo_url,
            database=license_instance.database_name,
            username=request.username,
            password=request.password
        )

        user_auth_success = await user_connector.authenticate()

        # Log user authentication attempt
        auth_attempt = AuthAttempt(
            license_key=request.license_key,
            username=request.username,
            success="success" if user_auth_success else "failed"
        )
        db.add(auth_attempt)
        db.commit()

        if not user_auth_success:
            logger.warning(f"User authentication failed for user: {request.username}")
            return LoginResponse(
                success=False,
                error="Invalid credentials. Please check your username and password."
            )

        # Helper function to convert Odoo False to None
        def odoo_value(value):
            """Convert Odoo False values to None for proper validation"""
            return None if value is False else value

        # Step 4: Fetch user and employee information (PARALLEL)
        try:
            # Run both API calls concurrently
            user_info_task = user_connector.search_read(
                'res.users',
                domain=[['id', '=', user_connector.uid]],
                fields=['name', 'email']
            )
            
            employee_task = user_connector.search_read(
                'hr.employee',
                domain=[('user_id', '=', user_connector.uid)],
                fields=[
                    'id', 
                    'name',
                    'work_email',
                    'work_phone',
                    'mobile_phone',
                    'job_title',
                    'job_id',
                    'department_id',
                    'company_id',
                    'image_1920'
                ]
            )

            # Execute in parallel
            user_info_list, employee_data = await asyncio.gather(
                user_info_task,
                employee_task,
                return_exceptions=True
            )

            # Handle potential errors
            if isinstance(user_info_list, Exception):
                logger.error(f"Failed to get user info: {user_info_list}")
                user_info_list = []
            
            if isinstance(employee_data, Exception):
                logger.error(f"Failed to get employee data: {employee_data}")
                employee_data = []

            user_info = user_info_list[0] if user_info_list else {}

            # Fallback: match by email if user_id link not set
            if not employee_data and user_info.get('email'):
                employee_data = await user_connector.search_read(
                    'hr.employee',
                    domain=[('work_email', '=', user_info['email'])],
                    fields=[
                        'id', 
                        'name',
                        'work_email',
                        'work_phone',
                        'mobile_phone',
                        'job_title',
                        'job_id',
                        'department_id',
                        'company_id',
                        'image_1920'
                    ]
                )

            # Initialize employee data
            employee_object = None
            employee_id = None
            company_id = None
            currency_id = None

            if employee_data:
                emp = employee_data[0]
                employee_id = emp['id']
                
                # Build employee object with image
                employee_object = {
                    "id": emp['id'],
                    "name": odoo_value(emp.get('name')) or '',
                    "email": odoo_value(emp.get('work_email')),
                    "phone": odoo_value(emp.get('work_phone')),
                    "mobile": odoo_value(emp.get('mobile_phone')),
                    "job_title": odoo_value(emp.get('job_title')),
                    "job_id": emp['job_id'][0] if emp.get('job_id') and emp['job_id'] else None,
                    "job_name": emp['job_id'][1] if emp.get('job_id') and emp['job_id'] else None,
                    "department_id": emp['department_id'][0] if emp.get('department_id') and emp['department_id'] else None,
                    "department_name": emp['department_id'][1] if emp.get('department_id') and emp['department_id'] else None,
                    "image": odoo_value(emp.get('image_1920'))  # Employee image
                }

                # Extract company_id for token
                if emp.get('company_id') and emp['company_id']:
                    company_id = emp['company_id'][0]
                    
                    # Get currency_id for token (minimal company data fetch)
                    try:
                        company_data = await user_connector.search_read(
                            'res.company',
                            domain=[('id', '=', company_id)],
                            fields=['currency_id']
                        )
                        if company_data and company_data[0].get('currency_id'):
                            currency_id = company_data[0]['currency_id'][0] if company_data[0]['currency_id'] else None
                    except Exception as e:
                        logger.error(f"Failed to get currency_id: {e}")

        except Exception as e:
            logger.error(f"Failed to get user info: {e}")
            raise HTTPException(
                status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
                detail=f"Failed to retrieve user information: {str(e)}"
            )

        # Step 5: Create 24-hour access token with all necessary data
        token_data = {
            "license_key": request.license_key,
            "user_id": user_connector.uid,
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
                    "id": user_connector.uid,
                    "name": user_info.get('name', ''),
                    "email": user_info.get('email', '')
                },
                "employee": employee_object  # Only employee data with image
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