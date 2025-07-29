from fastapi import APIRouter, HTTPException, status, Depends, Query
from typing import Optional
from app.api.deps import get_current_user
from app.schemas.auth import TokenData
from app.schemas.odoo import OdooSearchResponse, OdooRecordResponse
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

@router.get("/payslips", response_model=OdooSearchResponse)
async def get_payslips(
    employee_id: Optional[int] = Query(None, description="Filter by employee ID"),
    date_from: Optional[str] = Query(None, description="Start date (YYYY-MM-DD)"),
    date_to: Optional[str] = Query(None, description="End date (YYYY-MM-DD)"),
    state: Optional[str] = Query(None, description="Filter by state (draft, verify, done)"),
    limit: Optional[int] = Query(None, description="Maximum number of records"),
    current_user: TokenData = Depends(get_current_user)
):
    """Get payroll payslips"""
    
    try:
        connector = get_odoo_connector(current_user)
        
        # Build domain based on filters
        domain = []
        if employee_id:
            domain.append(['employee_id', '=', employee_id])
        if date_from:
            domain.append(['date_from', '>=', date_from])
        if date_to:
            domain.append(['date_to', '<=', date_to])
        if state:
            domain.append(['state', '=', state])
        
        payslips = connector.search_read(
            model='hr.payslip',
            domain=domain,
            fields=[
                'name', 'employee_id', 'date_from', 'date_to', 
                'state', 'basic_wage', 'net_wage', 'struct_id'
            ],
            limit=limit
        )
        
        logger.info(f"Retrieved {len(payslips)} payslips")
        
        return OdooSearchResponse(
            success=True,
            data=payslips,
            count=len(payslips)
        )
        
    except HTTPException:
        raise
    except Exception as e:
        logger.error(f"Error retrieving payslips: {e}")
        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail=f"Failed to retrieve payslips: {str(e)}"
        )

@router.get("/salary-rules", response_model=OdooSearchResponse)
async def get_salary_rules(
    struct_id: Optional[int] = Query(None, description="Filter by salary structure ID"),
    current_user: TokenData = Depends(get_current_user)
):
    """Get salary rules"""
    
    try:
        connector = get_odoo_connector(current_user)
        
        domain = []
        if struct_id:
            domain.append(['struct_id', '=', struct_id])
        
        rules = connector.search_read(
            model='hr.salary.rule',
            domain=domain,
            fields=[
                'name', 'code', 'category_id', 'sequence', 
                'condition_select', 'amount_select', 'struct_id'
            ]
        )
        
        logger.info(f"Retrieved {len(rules)} salary rules")
        
        return OdooSearchResponse(
            success=True,
            data=rules,
            count=len(rules)
        )
        
    except HTTPException:
        raise
    except Exception as e:
        logger.error(f"Error retrieving salary rules: {e}")
        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail=f"Failed to retrieve salary rules: {str(e)}"
        )

@router.get("/structures", response_model=OdooSearchResponse)
async def get_salary_structures(
    current_user: TokenData = Depends(get_current_user)
):
    """Get salary structures"""
    
    try:
        connector = get_odoo_connector(current_user)
        
        structures = connector.search_read(
            model='hr.payroll.structure',
            fields=['name', 'code', 'rule_ids', 'active']
        )
        
        logger.info(f"Retrieved {len(structures)} salary structures")
        
        return OdooSearchResponse(
            success=True,
            data=structures,
            count=len(structures)
        )
        
    except HTTPException:
        raise
    except Exception as e:
        logger.error(f"Error retrieving salary structures: {e}")
        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail=f"Failed to retrieve salary structures: {str(e)}"
        )

@router.post("/generate-payslip", response_model=OdooRecordResponse)
async def generate_payslip(
    employee_id: int,
    date_from: str,
    date_to: str,
    struct_id: int,
    current_user: TokenData = Depends(get_current_user)
):
    """Generate a new payslip"""
    
    try:
        connector = get_odoo_connector(current_user)
        
        # Create payslip record
        payslip_values = {
            'employee_id': employee_id,
            'date_from': date_from,
            'date_to': date_to,
            'struct_id': struct_id,
            'state': 'draft'
        }
        
        payslip_id = connector.create_record('hr.payslip', payslip_values)
        
        # Compute payslip (call Odoo method)
        try:
            connector.call_method('hr.payslip', 'compute_sheet', [payslip_id])
        except Exception as e:
            logger.warning(f"Could not compute payslip automatically: {e}")
        
        logger.info(f"Generated payslip {payslip_id} for employee {employee_id}")
        
        return OdooRecordResponse(
            success=True,
            data={"payslip_id": payslip_id},
            message=f"Payslip generated successfully"
        )
        
    except HTTPException:
        raise
    except Exception as e:
        logger.error(f"Error generating payslip: {e}")
        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail=f"Failed to generate payslip: {str(e)}"
        )