from datetime import datetime, timedelta
from typing import Any, Union, Optional
from jose import jwt, JWTError
from passlib.context import CryptContext
from app.config import settings
import logging

logger = logging.getLogger(__name__)

pwd_context = CryptContext(schemes=["bcrypt"], deprecated="auto")


def create_access_token(
    subject: Union[str, Any], 
    expires_minutes: Optional[int] = None
) -> str:
    """
    Create an access token with configurable expiration.
    
    Args:
        subject: The data to encode in the token (usually JSON string)
        expires_minutes: Token expiration in minutes. Defaults to 24 hours (1440 minutes)
    
    Returns:
        Encoded JWT token
    """
    if expires_minutes:
        expire = datetime.utcnow() + timedelta(minutes=expires_minutes)
    else:
        # Default to 24 hours if not specified
        expire = datetime.utcnow() + timedelta(minutes=1440)
    
    to_encode = {
        "exp": expire,
        "iat": datetime.utcnow(),
        "sub": str(subject),
        "type": "access"
    }
    
    encoded_jwt = jwt.encode(
        to_encode, 
        settings.SECRET_KEY, 
        algorithm=settings.ALGORITHM
    )
    return encoded_jwt


def decode_access_token(token: str) -> Optional[dict]:
    """
    Decode and validate an access token.
    
    Args:
        token: The JWT token to decode
    
    Returns:
        Decoded token data as dict, or None if invalid/expired
    """
    try:
        payload = jwt.decode(
            token, 
            settings.SECRET_KEY, 
            algorithms=[settings.ALGORITHM]
        )
        
        # Verify it's an access token
        if payload.get("type") != "access":
            logger.warning("Token type mismatch")
            return None
        
        # Parse the subject (which contains our JSON data)
        import json
        token_data = json.loads(payload.get("sub"))
        return token_data
        
    except JWTError as e:
        logger.error(f"JWT decode error: {e}")
        return None
    except json.JSONDecodeError as e:
        logger.error(f"JSON decode error in token: {e}")
        return None


def decode_token(token: str) -> Optional[dict]:
    """
    Generic token decoder (backwards compatible).
    
    Args:
        token: The JWT token to decode
    
    Returns:
        Decoded payload as dict, or None if invalid
    """
    try:
        payload = jwt.decode(
            token, 
            settings.SECRET_KEY, 
            algorithms=[settings.ALGORITHM]
        )
        return payload
    except JWTError as e:
        logger.error(f"Token decode error: {e}")
        return None


def verify_password(plain_password: str, hashed_password: str) -> bool:
    """Verify a plain password against a hashed password."""
    return pwd_context.verify(plain_password, hashed_password)


def get_password_hash(password: str) -> str:
    """Hash a password for storage."""
    return pwd_context.hash(password)


def create_session_token(data: dict) -> str:
    """
    DEPRECATED: Session tokens are no longer needed in the new flow.
    Keeping for backwards compatibility during migration.
    
    Use create_access_token() instead.
    """
    logger.warning("create_session_token is deprecated. Use create_access_token instead.")
    to_encode = {**data, "type": "session"}
    encoded_jwt = jwt.encode(
        to_encode, 
        settings.SECRET_KEY, 
        algorithm=settings.ALGORITHM
    )
    return encoded_jwt