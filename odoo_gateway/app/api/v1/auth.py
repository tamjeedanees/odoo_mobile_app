from fastapi import APIRouter, HTTPException, status, Depends
from sqlalchemy.orm import Session
from app.database import get_db
from app.models.license import LicenseInstance
from app.models.auth import AuthAttempt
from app.schemas.auth import (
    LicenseValidationRequest, 
    LicenseValidationResponse,
    LoginRequest, 
    LoginResponse
)
from app.core.security import create_session_token, create_access_token
from app.core.odoo_connector import OdooConnector
from app.core.cache import cache
import json
import logging

logger = logging.getLogger(__name__)
router = APIRouter()

@router.post("/validate-license", response_model=LicenseValidationResponse)
async def validate_license(
    request: LicenseValidationRequest,
    db: Session = Depends(get_db)
):
    """Step 1: Validate license key and return session token"""
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

        session_data = {
            'license_key': request.license_key,
            'odoo_url': license_instance.odoo_url,
            'database': license_instance.database_name
        }

        session_token = create_session_token(session_data)

        cache.set(
            f"session:{session_token}",
            session_data,
            expire=300  # 5 minutes
        )

        logger.info(f"License validated successfully: {request.license_key}")
        return LicenseValidationResponse(
            success=True,
            data={
                "session_token": session_token,
                "company_info": {
                    "company_name": license_instance.company_name
                }
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
    """Step 2: Authenticate user with Odoo instance"""
    try:
        session_data = cache.get(f"session:{request.session_token}")
        if not session_data:
            logger.warning("Invalid or expired session token")
            return LoginResponse(
                success=False,
                error="Invalid or expired session token"
            )

        connector = OdooConnector(
            url=session_data['odoo_url'],
            database=session_data['database'],
            username=request.username,
            password=request.password
        )

        auth_success = await connector.authenticate()

        auth_attempt = AuthAttempt(
            license_key=session_data['license_key'],
            username=request.username,
            success="success" if auth_success else "failed"
        )
        db.add(auth_attempt)
        db.commit()

        if not auth_success:
            logger.warning(f"Authentication failed for user: {request.username}")
            return LoginResponse(
                success=False,
                error="Invalid credentials"
            )

        try:
            # Step 1: get basic user info (no employee_id to avoid access error)
            user_info_list = await connector.search_read(
                'res.users',
                domain=[['id', '=', connector.uid]],
                fields=['name', 'email']
            )
            user_info = user_info_list[0] if user_info_list else {}

            # Step 2: try to resolve employee_id
            employee_id = None
            company_id = None
            currency_id = None

            # preferred: match by user_id
            employee_data = await connector.search_read(
                'hr.employee',
                domain=[('user_id', '=', connector.uid)],
                fields=['id', 'company_id']
            )

            # fallback: match by email if user_id link not set
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

                # Step 3: get currency from company
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

        # Include company_id & currency_id in token
        token_data = {
            'license_key': session_data['license_key'],
            'user_id': connector.uid,
            'username': request.username,
            'password': request.password,
            'odoo_url': session_data['odoo_url'],
            'database': session_data['database'],
            'employee_id': employee_id,
            'company_id': company_id,
            'currency_id': currency_id
        }

        access_token = create_access_token(json.dumps(token_data))

        # Cleanup session from cache
        cache.delete(f"session:{request.session_token}")

        logger.info(f"User logged in successfully: {request.username}")
        return LoginResponse(
            success=True,
            data={
                "access_token": access_token,
                "token_type": "bearer",
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
        logger.error(f"Login error: {e}")
        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail="Internal server error during login"
        )