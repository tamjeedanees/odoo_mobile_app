from pydantic import BaseModel
from typing import Optional, Dict, Any, List


class OdooRecordRequest(BaseModel):
    values: Dict[str, Any]


class OdooRecordResponse(BaseModel):
    success: bool
    data: Optional[Dict[str, Any]] = None
    message: Optional[str] = None
    error: Optional[str] = None


class OdooSearchRequest(BaseModel):
    domain: Optional[str] = "[]"
    fields: Optional[str] = "[]"
    limit: Optional[int] = None


class OdooSearchResponse(BaseModel):
    success: bool
    data: Optional[List[Dict[str, Any]]] = None
    count: Optional[int] = None
    error: Optional[str] = None