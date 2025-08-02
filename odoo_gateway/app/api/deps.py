import json
import logging
from fastapi import Depends, HTTPException, status, Header
from app.core.security import decode_token
from app.schemas.auth import TokenData

logger = logging.getLogger(__name__)

def get_current_user(authorization: str = Header(None)) -> TokenData:
    """Dependency to get current authenticated user"""

    if not authorization or not authorization.startswith('Bearer '):
        logger.warning("Missing or malformed Authorization header")
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail="Missing or invalid authorization header",
            headers={"WWW-Authenticate": "Bearer"},
        )
    
    try:
        token = authorization.split(' ')[1]
        payload = decode_token(token)
        
        if not payload:
            logger.warning("Decoded token is empty or invalid")
            raise HTTPException(
                status_code=status.HTTP_401_UNAUTHORIZED,
                detail="Could not validate credentials",
                headers={"WWW-Authenticate": "Bearer"},
            )
        
        if payload.get('type') != 'access':
            logger.warning(f"Invalid token type: {payload.get('type')}")
            raise HTTPException(
                status_code=status.HTTP_401_UNAUTHORIZED,
                detail="Invalid token type",
                headers={"WWW-Authenticate": "Bearer"},
            )
        
        user_data = json.loads(payload['sub'])

        return TokenData(**user_data)
        
    except Exception as e:
        logger.exception(f"Token decoding or user extraction failed: {e}")
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail="Could not validate credentials",
            headers={"WWW-Authenticate": "Bearer"},
        )