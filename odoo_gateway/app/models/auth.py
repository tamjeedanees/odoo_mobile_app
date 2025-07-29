from sqlalchemy import Column, Integer, String, DateTime, Text
from sqlalchemy.sql import func
from app.database import Base


class AuthAttempt(Base):
    __tablename__ = "auth_attempts"
    
    id = Column(Integer, primary_key=True, index=True)
    license_key = Column(String, index=True)
    username = Column(String)
    success = Column(String)  # 'success', 'failed', 'invalid_license'
    ip_address = Column(String)
    user_agent = Column(Text)
    attempted_at = Column(DateTime(timezone=True), server_default=func.now())