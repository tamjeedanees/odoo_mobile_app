from fastapi import APIRouter, HTTPException, status, Depends, Query
from typing import Dict, Any, Optional
from app.api.deps import get_current_user
from app.schemas.auth import TokenData
from app.schemas.odoo import (
    OdooRecordRequest, 
    OdooRecordResponse, 
    OdooSearchResponse
)
from app.core.odoo_connector import OdooConnector
import json
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

@router.get("/employees", response_model=OdooSearchResponse)
async def get_employees(
    active_only: bool = Query(True, description="Get only active employees"),
    department_id: Optional[int] = Query(None, description="Filter by department ID"),
    limit: Optional[int] = Query(None, description="Maximum number of records"),
    current_user: TokenData = Depends(get_current_user)
):
    """Get HR employees with common filters"""
    
    try:
        connector = get_odoo_connector(current_user)
        
        # Build domain based on filters
        domain = []
        if active_only:
            domain.append(['active', '=', True])
        if department_id:
            domain.append(['department_id', '=', department_id])
        
        employees = connector.search_read(
            model='hr.employee',
            domain=domain,
            fields=[
                'name', 'job_title', 'department_id', 'work_email', 
                'work_phone', 'employee_id', 'user_id', 'active'
            ],
            limit=limit
        )
        
        logger.info(f"Retrieved {len(employees)} employees")
        
        return OdooSearchResponse(
            success=True,
            data=employees,
            count=len(employees)
        )
        
    except HTTPException:
        raise
    except Exception as e:
        logger.error(f"Error retrieving employees: {e}")
        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail=f"Failed to retrieve employees: {str(e)}"
        )

@router.get("/departments", response_model=OdooSearchResponse)
async def get_departments(
    current_user: TokenData = Depends(get_current_user)
):
    """Get HR departments"""
    
    try:
        connector = get_odoo_connector(current_user)
        
        departments = connector.search_read(
            model='hr.department',
            fields=['name', 'manager_id', 'parent_id', 'active']
        )
        
        logger.info(f"Retrieved {len(departments)} departments")
        
        return OdooSearchResponse(
            success=True,
            data=departments,
            count=len(departments)
        )
        
    except HTTPException:
        raise
    except Exception as e:
        logger.error(f"Error retrieving departments: {e}")
        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail=f"Failed to retrieve departments: {str(e)}"
        )

@router.get("/attendance", response_model=OdooSearchResponse)
async def get_attendance(
    employee_id: Optional[int] = Query(None, description="Filter by employee ID"),
    date_from: Optional[str] = Query(None, description="Start date (YYYY-MM-DD)"),
    date_to: Optional[str] = Query(None, description="End date (YYYY-MM-DD)"),
    limit: Optional[int] = Query(None, description="Maximum number of records"),
    current_user: TokenData = Depends(get_current_user)
):
    """Get HR attendance records"""
    
    try:
        connector = get_odoo_connector(current_user)
        
        # Build domain based on filters
        domain = []
        if employee_id:
            domain.append(['employee_id', '=', employee_id])
        if date_from:
            domain.append(['check_in', '>=', f"{date_from} 00:00:00"])
        if date_to:
            domain.append(['check_in', '<=', f"{date_to} 23:59:59"])
        
        attendance = connector.search_read(
            model='hr.attendance',
            domain=domain,
            fields=[
                'employee_id', 'check_in', 'check_out', 'worked_hours'
            ],
            limit=limit
        )
        
        logger.info(f"Retrieved {len(attendance)} attendance records")
        
        return OdooSearchResponse(
            success=True,
            data=attendance,
            count=len(attendance)
        )
        
    except HTTPException:
        raise
    except Exception as e:
        logger.error(f"Error retrieving attendance: {e}")
        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail=f"Failed to retrieve attendance: {str(e)}"
        )

@router.get("/leaves", response_model=OdooSearchResponse)
async def get_leaves(
    employee_id: Optional[int] = Query(None, description="Filter by employee ID"),
    state: Optional[str] = Query(None, description="Filter by state (draft, confirm, validate)"),
    limit: Optional[int] = Query(None, description="Maximum number of records"),
    current_user: TokenData = Depends(get_current_user)
):
    """Get HR leave requests"""
    
    try:
        connector = get_odoo_connector(current_user)
        
        # Build domain based on filters
        domain = []
        if employee_id:
            domain.append(['employee_id', '=', employee_id])
        if state:
            domain.append(['state', '=', state])
        
        leaves = connector.search_read(
            model='hr.leave',
            domain=domain,
            fields=[
                'employee_id', 'holiday_status_id', 'request_date_from', 
                'request_date_to', 'number_of_days', 'state', 'name'
            ],
            limit=limit
        )
        
        logger.info(f"Retrieved {len(leaves)} leave records")
        
        return OdooSearchResponse(
            success=True,
            data=leaves,
            count=len(leaves)
        )
        
    except HTTPException:
        raise
    except Exception as e:
        logger.error(f"Error retrieving leaves: {e}")
        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail=f"Failed to retrieve leaves: {str(e)}"
        )