from fastapi import APIRouter, HTTPException, status, Depends, Query
from typing import Optional
from app.api.deps import get_current_user
from app.schemas.auth import TokenData
from app.schemas.odoo import (
    OdooRecordRequest, 
    OdooRecordResponse, 
    OdooSearchResponse
)
from app.core.odoo_connector import OdooConnector
import logging

logger = logging.getLogger(__name__)
router = APIRouter()

def get_odoo_connector(current_user: TokenData) -> OdooConnector:
    """Helper function to create Odoo connector from user token"""
    connector = OdooConnector(
        url=current_user.odoo_url,
        database=current_user.database,
        username=current_user.username,
        password=current_user.password
    )
    
    if not connector.authenticate():
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail="Failed to authenticate with Odoo instance"
        )
    
    return connector
    
def clean_phone_number(phone: str) -> str:
    """Clean and format phone number"""
    if not phone:
        return ""
    # Remove all non-digit characters except +
    cleaned = re.sub(r'[^\d+]', '', phone)
    return cleaned

def validate_email(email: str) -> bool:
    """Basic email validation"""
    import re
    pattern = r'^[a-zA-Z0-9._%+-]+@[a-zA-Z0-9.-]+\.[a-zA-Z]{2,}$'
    return re.match(pattern, email) is not None

@router.get("/{model}", response_model=OdooSearchResponse)
async def get_records(
    model: str,
    domain: str = Query("[]", description="Search domain as JSON string"),
    fields: str = Query("[]", description="Fields to retrieve as JSON string"),
    limit: Optional[int] = Query(None, description="Maximum number of records"),
    offset: int = Query(0, description="Number of records to skip"),
    current_user: TokenData = Depends(get_current_user)
):
    """Get records from any Odoo model"""
    
    try:
        connector = get_odoo_connector(current_user)
        
        # Parse domain and fields
        try:
            domain_list = json.loads(domain)
            fields_list = json.loads(fields)
        except json.JSONDecodeError as e:
            raise HTTPException(
                status_code=status.HTTP_400_BAD_REQUEST,
                detail=f"Invalid JSON in domain or fields: {e}"
            )
        
        records = connector.search_read(
            model=model,
            domain=domain_list,
            fields=fields_list,
            limit=limit,
            offset=offset
        )
        
        logger.info(f"Retrieved {len(records)} records from {model}")
        
        return OdooSearchResponse(
            success=True,
            data=records,
            count=len(records)
        )
        
    except HTTPException:
        raise
    except Exception as e:
        logger.error(f"Error retrieving records from {model}: {e}")
        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail=f"Failed to retrieve records: {str(e)}"
        )

@router.post("/{model}", response_model=OdooRecordResponse)
async def create_record(
    model: str,
    request: OdooRecordRequest,
    current_user: TokenData = Depends(get_current_user)
):
    """Create a record in any Odoo model"""
    
    try:
        connector = get_odoo_connector(current_user)
        
        record_id = connector.create_record(model, request.values)
        
        logger.info(f"Created record {record_id} in {model}")
        
        return OdooRecordResponse(
            success=True,
            data={"id": record_id},
            message=f"Record created successfully in {model}"
        )
        
    except HTTPException:
        raise
    except Exception as e:
        logger.error(f"Error creating record in {model}: {e}")
        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail=f"Failed to create record: {str(e)}"
        )

@router.put("/{model}/{record_id}", response_model=OdooRecordResponse)
async def update_record(
    model: str,
    record_id: int,
    request: OdooRecordRequest,
    current_user: TokenData = Depends(get_current_user)
):
    """Update a record in any Odoo model"""
    
    try:
        connector = get_odoo_connector(current_user)
        
        result = connector.write_record(model, record_id, request.values)
        
        logger.info(f"Updated record {record_id} in {model}")
        
        return OdooRecordResponse(
            success=True,
            data={"updated": result},
            message=f"Record {record_id} updated successfully in {model}"
        )
        
    except HTTPException:
        raise
    except Exception as e:
        logger.error(f"Error updating record {record_id} in {model}: {e}")
        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail=f"Failed to update record: {str(e)}"
        )

@router.delete("/{model}/{record_id}", response_model=OdooRecordResponse)
async def delete_record(
    model: str,
    record_id: int,
    current_user: TokenData = Depends(get_current_user)
):
    """Delete a record from any Odoo model"""
    
    try:
        connector = get_odoo_connector(current_user)
        
        result = connector.delete_record(model, record_id)
        
        logger.info(f"Deleted record {record_id} from {model}")
        
        return OdooRecordResponse(
            success=True,
            data={"deleted": result},
            message=f"Record {record_id} deleted successfully from {model}"
        )
        
    except HTTPException:
        raise
    except Exception as e:
        logger.error(f"Error deleting record {record_id} from {model}: {e}")
        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail=f"Failed to delete record: {str(e)}"
        )