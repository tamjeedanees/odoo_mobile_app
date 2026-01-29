from fastapi import APIRouter, HTTPException, status, Depends, Query
from typing import Dict, Any, Optional, List
from app.api.deps import get_current_user
from app.schemas.auth import TokenData, CompanyDetailsResponse
from app.schemas.odoo import (
    OdooRecordRequest, 
    OdooRecordResponse, 
    OdooSearchResponse,
    LeaveCountResponse
)
from datetime import datetime
import pytz
from app.core.odoo_connector import OdooConnector
from app.odoo_models import MODEL_MAP
import json
import logging
from app.core.connection_pool import get_connection_pool

logger = logging.getLogger(__name__)
router = APIRouter()

def get_model_info(model_key: str, required_permission: str) -> str:
    model_config = MODEL_MAP.get(model_key)
    if not model_config:
        raise HTTPException(status_code=404, detail=f"Model '{model_key}' not found.")
    if required_permission not in model_config.get("permissions", []):
        raise HTTPException(
            status_code=403,
            detail=f"{required_permission.upper()} access denied for model '{model_key}'"
        )
    return model_config["model"]

async def inline_one2many_fields(
    records: List[Dict[str, Any]],
    fields_meta: Dict[str, Any],
    fields_list: List[str],
    connector: OdooConnector
) -> List[Dict[str, Any]]:
    """
    Replace One2many field ID lists in records with full related records.

    Args:
        records: List of Odoo records.
        fields_meta: Metadata for fields of the main model.
        fields_list: List of fields requested by the client.
        connector: Authenticated OdooConnector instance.

    Returns:
        Updated records with inlined One2many sub-records.
    """
    one2many_fields = [
        field for field, meta in fields_meta.items()
        if meta.get("type") == "one2many" and field in fields_list
    ]

    for record in records:
        for field in one2many_fields:
            line_ids = record.get(field, [])
            if line_ids:
                rel_model = fields_meta[field].get("relation")
                try:
                    line_data = await connector.read(model=rel_model, ids=line_ids)
                    record[field] = line_data
                except Exception as e:
                    logger.error(f"Failed to read One2many field '{field}': {e}")
                    record[field] = []

    return records

async def get_odoo_connector(current_user: TokenData) -> OdooConnector:
    """Get Odoo connector from connection pool - ALREADY AUTHENTICATED"""
    pool = get_connection_pool()
    
    try:
        # Get from pool (connection already authenticated - 0ms overhead)
        connector = await pool.get_connection(
            url=current_user.odoo_url,
            database=current_user.database,
            username=current_user.exec_username,
            password=current_user.exec_password
        )
        
        connector.identity = current_user
        connector._pool_info = {
            'url': current_user.odoo_url,
            'database': current_user.database,
            'username': current_user.exec_username
        }
        
        return connector
    except Exception as e:
        logger.error(f"Failed to get connector from pool: {e}")
        raise HTTPException(
            status_code=status.HTTP_503_SERVICE_UNAVAILABLE,
            detail="Service temporarily unavailable"
        )

async def release_odoo_connector(connector: OdooConnector, current_user: TokenData):
    """Return connector to pool for reuse"""
    if hasattr(connector, '_pool_info'):
        pool = get_connection_pool()
        try:
            await pool.release_connection(
                url=connector._pool_info['url'],
                database=connector._pool_info['database'],
                username=connector._pool_info['username'],
                connector=connector
            )
        except Exception as e:
            logger.error(f"Error releasing connector: {e}")

def float_hours_to_hhmm(hours: float) -> str:
    """
    Convert float hours to HH:MM format like Odoo frontend.
    Example: 128.2533 -> 128:15
    """
    if hours is None:
        return "0:00"

    total_minutes = int(round(hours * 60))
    hh = total_minutes // 60
    mm = total_minutes % 60

    return f"{hh}:{mm:02d}"

async def convert_attendance_datetimes(
    records: list,
    user_timezone: str = "UTC"
) -> list:
    try:
        tz = pytz.timezone(user_timezone)
    except pytz.exceptions.UnknownTimeZoneError:
        logger.warning(f"Invalid timezone '{user_timezone}', using UTC")
        tz = pytz.UTC

    for record in records:
        # check_in
        if record.get("check_in"):
            try:
                utc_dt = datetime.strptime(record["check_in"], "%Y-%m-%d %H:%M:%S")
                utc_dt = pytz.UTC.localize(utc_dt)
                record["check_in"] = utc_dt.astimezone(tz).strftime("%Y-%m-%d %H:%M:%S")
            except Exception as e:
                logger.error(f"Failed to convert check_in '{record.get('check_in')}': {e}")

        # check_out
        if record.get("check_out"):
            try:
                utc_dt = datetime.strptime(record["check_out"], "%Y-%m-%d %H:%M:%S")
                utc_dt = pytz.UTC.localize(utc_dt)
                record["check_out"] = utc_dt.astimezone(tz).strftime("%Y-%m-%d %H:%M:%S")
            except Exception as e:
                logger.error(f"Failed to convert check_out '{record.get('check_out')}': {e}")

        # worked_hours formatting like Odoo frontend
        if "worked_hours" in record and record["worked_hours"] is not None:
            try:
                record["worked_hours"] = float_hours_to_hhmm(
                    float(record["worked_hours"])
                )
            except Exception as e:
                logger.error(
                    f"Failed to convert worked_hours '{record.get('worked_hours')}': {e}"
                )

    return records

@router.get("/{model}", response_model=OdooSearchResponse)
async def get_records(
    model: str,
    domain: str = Query("[]"),
    fields: Optional[str] = Query(None),
    limit: Optional[int] = Query(None),
    offset: int = Query(0),
    current_user: TokenData = Depends(get_current_user)
):
    odoo_model = get_model_info(model, "read")
    connector = await get_odoo_connector(current_user)

    try:
        # Parse domain
        try:
            domain_list = json.loads(domain)
            if not isinstance(domain_list, list):
                raise ValueError("Domain must be a list.")
        except Exception as e:
            raise HTTPException(status_code=400, detail=f"Invalid 'domain': {e}")
        
        # Fetch fields metadata
        try:
            fields_meta = await connector.fields_get(odoo_model)
        except Exception as e:
            logger.error(f"[{odoo_model}] Metadata fetch failed: {e}")
            raise HTTPException(status_code=500, detail="Failed to fetch model metadata.")
        
        # Enforce employee filter
        if odoo_model == "hr.employee":
            domain_list.append(["id", "=", current_user.employee_id])
        elif "employee_id" in fields_meta:
            domain_list.append(["employee_id", "=", current_user.employee_id])
        
        # Parse fields
        if fields:
            try:
                fields_list = json.loads(fields)
                if not isinstance(fields_list, list):
                    raise ValueError("Fields must be a list.")
            except Exception as e:
                raise HTTPException(status_code=400, detail=f"Invalid 'fields': {e}")
        else:
            fields_list = list(fields_meta.keys())
        
        # Perform search_read
        records = await connector.search_read(
            model=odoo_model,
            domain=domain_list,
            fields=fields_list,
            limit=limit,
            offset=offset
        )
        
        # Handle One2many fields
        records = await inline_one2many_fields(records, fields_meta, fields_list, connector)
        
        # **ATTENDANCE-SPECIFIC: Convert UTC to user's local timezone**
        if odoo_model == "hr.attendance":
            try:
                # Fetch user timezone from Odoo
                user_info = await connector.search_read(
                    model="res.users",
                    domain=[["id", "=", current_user.user_id]],
                    fields=["tz"]
                )
                user_timezone = user_info[0].get("tz", "UTC") if user_info else "UTC"
                
                # Convert attendance datetimes
                records = await convert_attendance_datetimes(records, user_timezone)
                
                logger.info(f"Converted {len(records)} attendance records to timezone: {user_timezone}")
            except Exception as e:
                logger.error(f"Failed to convert attendance datetimes: {e}")
                # Continue without conversion rather than failing the request

        return OdooSearchResponse(
            success=True,
            data=records,
            count=len(records)
        )
    finally:
        await release_odoo_connector(connector, current_user)

@router.get("/leaves/count/summary", response_model=LeaveCountResponse)
async def get_leave_count_summary(
    current_user: TokenData = Depends(get_current_user)
):
    """
    Get leave allocation summary for the current employee.
    Returns total allocated and remaining leaves per leave type.
    """
    connector = await get_odoo_connector(current_user)
    
    try:
        # Fetch all leave allocations for the employee
        allocations = await connector.search_read(
            model="hr.leave.allocation",
            domain=[
                ["employee_id", "=", current_user.employee_id],
                ["state", "=", "validate"]  # Only validated allocations
            ],
            fields=[
                "holiday_status_id",  # Leave type
                "number_of_days",     # Total allocated
                "number_of_days_display",  # Displayed days (if different)
            ]
        )
        
        # Fetch approved/confirmed leaves to calculate remaining
        leaves = await connector.search_read(
            model="hr.leave",
            domain=[
                ["employee_id", "=", current_user.employee_id],
                ["state", "in", ["confirm", "validate", "validate1"]]  # Approved states
            ],
            fields=[
                "holiday_status_id",
                "number_of_days"
            ]
        )
        
        # Group by leave type and calculate
        leave_summary = {}
        
        # Process allocations
        for allocation in allocations:
            leave_type_id = allocation["holiday_status_id"][0]
            leave_type_name = allocation["holiday_status_id"][1]
            
            if leave_type_id not in leave_summary:
                leave_summary[leave_type_id] = {
                    "leave_type_id": leave_type_id,
                    "leave_type_name": leave_type_name,
                    "total_allocated": 0.0,
                    "total_consumed": 0.0,
                    "remaining": 0.0
                }
            
            leave_summary[leave_type_id]["total_allocated"] += allocation.get("number_of_days", 0.0)
        
        # Process consumed leaves
        for leave in leaves:
            leave_type_id = leave["holiday_status_id"][0]
            
            if leave_type_id in leave_summary:
                leave_summary[leave_type_id]["total_consumed"] += leave.get("number_of_days", 0.0)
        
        # Calculate remaining
        for leave_type_id in leave_summary:
            summary = leave_summary[leave_type_id]
            summary["remaining"] = summary["total_allocated"] - summary["total_consumed"]
        
        return LeaveCountResponse(
            success=True,
            data=list(leave_summary.values()),
            count=len(leave_summary)
        )
        
    except Exception as e:
        logger.error(f"Failed to fetch leave count summary: {e}")
        raise HTTPException(status_code=500, detail=f"Failed to fetch leave summary: {str(e)}")
    finally:
        await release_odoo_connector(connector, current_user)

@router.post("/{model}", response_model=OdooRecordResponse)
async def create_record(
    model: str,
    request: OdooRecordRequest,
    current_user: TokenData = Depends(get_current_user)
):
    odoo_model = get_model_info(model, "create")
    if odoo_model == "hr.employee":
        raise HTTPException(status_code=403, detail="Cannot create employee records.")

    connector = await get_odoo_connector(current_user)

    try:
        fields_meta = await connector.fields_get(odoo_model)

        if "employee_id" in fields_meta:
            request.values["employee_id"] = current_user.employee_id

        required_fields = [f for f, meta in fields_meta.items() if meta.get("required")]
        missing_fields = [f for f in required_fields if f not in request.values or request.values[f] in (None, "")]

        # Auto-fill company_id if required and missing
        if "company_id" in missing_fields and "company_id" in fields_meta:
            request.values["company_id"] = current_user.company_id
            missing_fields.remove("company_id")

        # Auto-fill currency_id if required and missing
        if "currency_id" in missing_fields and "currency_id" in fields_meta:
            if getattr(current_user, "currency_id", None):
                request.values["currency_id"] = current_user.currency_id
            else:
                # Fallback: fetch from Odoo
                company_currency = await connector.search_read(
                    "res.company",
                    [("id", "=", current_user.company_id)],
                    ["currency_id"]
                )
                if company_currency and company_currency[0].get("currency_id"):
                    request.values["currency_id"] = company_currency[0]["currency_id"][0]
            missing_fields.remove("currency_id")

        # If after autofill we still have missing required fields → raise error
        if missing_fields:
            raise HTTPException(
                status_code=422,
                detail=f"Missing required fields: {', '.join(missing_fields)}"
            )

        record_id = await connector.create_record(odoo_model, request.values)

        return OdooRecordResponse(
            success=True,
            data={"id": record_id},
            message=f"Record created in {odoo_model} (ID: {record_id}) with {len(request.values.get('attachments', []))} attachments"
        )
    finally:
        await release_odoo_connector(connector, current_user)

@router.put("/{model}/{record_id}", response_model=OdooRecordResponse)
async def update_record(
    model: str,
    record_id: int,
    request: OdooRecordRequest,
    current_user: TokenData = Depends(get_current_user)
):
    odoo_model = get_model_info(model, "update")
    connector = await get_odoo_connector(current_user)

    try:
        records = await connector.search_read(
            model=odoo_model,
            domain=[["id", "=", record_id]],
            fields=["employee_id"]
        )

        if not records:
            raise HTTPException(status_code=404, detail="Record not found.")

        if odoo_model == "hr.employee":
            if records[0]["id"] != current_user.employee_id:
                raise HTTPException(status_code=403, detail="Can only update own record.")
        elif "employee_id" in records[0]:
            if records[0]["employee_id"][0] != current_user.employee_id:
                raise HTTPException(status_code=403, detail="Not allowed to update this record.")

        request.values.pop("employee_id", None)

        result = await connector.write_record(odoo_model, record_id, request.values)

        return OdooRecordResponse(
            success=True,
            data={"updated": result},
            message=f"Record {record_id} updated in {odoo_model}"
        )
    finally:
        await release_odoo_connector(connector, current_user)

@router.delete("/{model}/{record_id}", response_model=OdooRecordResponse)
async def delete_record(
    model: str,
    record_id: int,
    current_user: TokenData = Depends(get_current_user)
):
    odoo_model = get_model_info(model, "delete")
    if odoo_model == "hr.employee":
        raise HTTPException(status_code=403, detail="Cannot delete employee records.")

    connector = await get_odoo_connector(current_user)

    try:
        records = await connector.search_read(
            model=odoo_model,
            domain=[["id", "=", record_id]],
            fields=["employee_id"]
        )

        if not records:
            raise HTTPException(status_code=404, detail="Record not found.")

        if "employee_id" in records[0]:
            if records[0]["employee_id"][0] != current_user.employee_id:
                raise HTTPException(status_code=403, detail="Not allowed to delete this record.")

        result = await connector.delete_record(odoo_model, record_id)

        return OdooRecordResponse(
            success=True,
            data={"deleted": result},
            message=f"Record {record_id} deleted from {odoo_model}"
        )
    finally:
        await release_odoo_connector(connector, current_user)


@router.get("/company/details", response_model=CompanyDetailsResponse)
async def get_company_details(
    current_user: TokenData = Depends(get_current_user)
):
    """
    Get complete company details including logo and contact information.
    
    Returns:
    - Company name, logo
    - Full address (street, city, state, zip, country)
    - Contact info (phone, email, website)
    - Currency information
    """
    connector = await get_odoo_connector(current_user)
    
    try:
        # Check if company_id exists
        if not current_user.company_id:
            logger.warning(f"No company_id found for user: {current_user.username}")
            return CompanyDetailsResponse(
                success=False,
                error="No company associated with this user"
            )
        
        # Helper function to convert Odoo False to None
        def odoo_value(value):
            """Convert Odoo False values to None for proper validation"""
            return None if value is False else value
        
        # Fetch company details
        company_data = await connector.search_read(
            model='res.company',
            domain=[('id', '=', current_user.company_id)],
            fields=[
                'name',
                'street',
                'street2',
                'city',
                'state_id',
                'zip',
                'country_id',
                'phone',
                'mobile',
                'email',
                'website',
                'currency_id',
                'logo',
                'vat',  # Tax ID
                'company_registry'  # Company registration number
            ]
        )
        
        if not company_data:
            logger.error(f"Company not found for company_id: {current_user.company_id}")
            return CompanyDetailsResponse(
                success=False,
                error="Company details not found"
            )
        
        comp = company_data[0]
        
        # Build company object
        company_object = {
            "id": current_user.company_id,
            "name": odoo_value(comp.get('name')) or '',
            "street": odoo_value(comp.get('street')),
            "street2": odoo_value(comp.get('street2')),
            "city": odoo_value(comp.get('city')),
            "state_id": comp['state_id'][0] if comp.get('state_id') and comp['state_id'] else None,
            "state_name": comp['state_id'][1] if comp.get('state_id') and comp['state_id'] else None,
            "zip": odoo_value(comp.get('zip')),
            "country_id": comp['country_id'][0] if comp.get('country_id') and comp['country_id'] else None,
            "country_name": comp['country_id'][1] if comp.get('country_id') and comp['country_id'] else None,
            "phone": odoo_value(comp.get('phone')),
            "mobile": odoo_value(comp.get('mobile')),
            "email": odoo_value(comp.get('email')),
            "website": odoo_value(comp.get('website')),
            "currency_id": comp['currency_id'][0] if comp.get('currency_id') and comp['currency_id'] else None,
            "currency_name": comp['currency_id'][1] if comp.get('currency_id') and comp['currency_id'] else None,
            "logo": odoo_value(comp.get('logo')),  # Base64 encoded logo
            "vat": odoo_value(comp.get('vat')),
            "company_registry": odoo_value(comp.get('company_registry'))
        }
        
        logger.info(f"Company details retrieved for company_id: {current_user.company_id}")
        
        return CompanyDetailsResponse(
            success=True,
            data=company_object
        )
        
    except Exception as e:
        logger.error(f"Failed to fetch company details: {e}")
        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail=f"Failed to retrieve company details: {str(e)}"
        )
    finally:
        await release_odoo_connector(connector, current_user)
