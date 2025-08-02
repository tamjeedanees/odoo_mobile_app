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
from app.core.security import create_session_token, create_access_token, decode_token
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
        # Query license from database
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
        
        # Generate session token
        session_data = {
            'license_key': request.license_key,
            'odoo_url': license_instance.odoo_url,
            'database': license_instance.database_name
        }
        
        session_token = create_session_token(session_data)
        
        # Cache session data
        cache.set(
            f"session:{session_token}",
            session_data,
            expire=300
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
        # Get session data
        session_data = cache.get(f"session:{request.session_token}")
        if not session_data:
            logger.warning("Invalid or expired session token")
            return LoginResponse(
                success=False,
                error="Invalid or expired session token"
            )
        
        # Create Odoo connector
        connector = OdooConnector(
            url=session_data['odoo_url'],
            database=session_data['database'],
            username=request.username,
            password=request.password
        )
        
        # Authenticate with Odoo
        auth_success = connector.authenticate()
        
        # Log authentication attempt
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
        
        # Get user info from Odoo
        try:
            user_info = connector.search_read(
                'res.users',
                domain=[['id', '=', connector.uid]],
                fields=['name', 'email', 'groups_id', 'employee_id']
            )[0]

            # Get user permissions (groups)
            groups = connector.search_read(
                'res.groups',
                domain=[['id', 'in', user_info['groups_id']]],
                fields=['name', 'category_id']
            )
            
            permissions = [group['name'] for group in groups]

            employee_id = user_info.get('employee_id')
            if isinstance(employee_id, list):
                employee_id = employee_id[0]

            if not employee_id:
                logger.warning(f"No employee_id linked to user {connector.uid}")
                raise HTTPException(
                    status_code=status.HTTP_403_FORBIDDEN,
                    detail="This user is not linked to any employee record."
                )
            
        except Exception as e:
            logger.error(f"Failed to get user info: {e}")
            raise HTTPException(
                status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
                detail="Failed to retrieve user information"
            )

        # Generate access token
        token_data = {
            'license_key': session_data['license_key'],
            'user_id': connector.uid,
            'username': request.username,
            'password': request.password,
            'odoo_url': session_data['odoo_url'],
            'database': session_data['database'],
            'employee_id': employee_id
        }

        access_token = create_access_token(json.dumps(token_data))
        
        # Clean up session
        cache.delete(f"session:{request.session_token}")
        
        logger.info(f"User logged in successfully: {request.username}")
        
        return LoginResponse(
            success=True,
            data={
                "access_token": access_token,
                "token_type": "bearer",
                "employee_id": employee_id,
                "user_info": {
                    "id": connector.uid,
                    "name": user_info['name'],
                    "email": user_info.get('email', ''),
                    "permissions": permissions
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