from fastapi import APIRouter, HTTPException, status, Depends, Query
from typing import Dict, Any, Optional, List
from app.api.deps import get_current_user
from app.schemas.auth import TokenData
from app.schemas.odoo import (
    OdooRecordRequest, 
    OdooRecordResponse, 
    OdooSearchResponse
)
from datetime import datetime
import pytz
from app.core.odoo_connector import OdooConnector
from app.odoo_models import MODEL_MAP
import json
import logging

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
    """
    Portal users authenticate → execution user runs ORM
    """

    connector = OdooConnector(
        url=current_user.odoo_url,
        database=current_user.database,
        username=current_user.exec_username,
        password=current_user.exec_password
    )

    # Preserve identity for filtering
    connector.identity = current_user

    if not await connector.authenticate():
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail="Failed to authenticate execution user with Odoo"
        )

    return connector

async def convert_attendance_datetimes(
    records: list,
    user_timezone: str = "UTC"
) -> list:
    """
    Convert check_in and check_out times from UTC to user's timezone.
    Specifically for hr.attendance records.
    
    Args:
        records: List of attendance records from Odoo
        user_timezone: User's timezone (e.g., 'Asia/Karachi')
    """
    try:
        tz = pytz.timezone(user_timezone)
    except pytz.exceptions.UnknownTimeZoneError:
        logger.warning(f"Invalid timezone '{user_timezone}', using UTC")
        tz = pytz.UTC
    
    for record in records:
        # Convert check_in
        if "check_in" in record and record["check_in"]:
            try:
                # Parse UTC datetime (format: "2026-01-09 21:00:00")
                utc_dt = datetime.strptime(record["check_in"], "%Y-%m-%d %H:%M:%S")
                utc_dt = pytz.UTC.localize(utc_dt)
                
                # Convert to user timezone
                local_dt = utc_dt.astimezone(tz)
                
                # Replace with local time
                record["check_in"] = local_dt.strftime("%Y-%m-%d %H:%M:%S")
            except Exception as e:
                logger.error(f"Failed to convert check_in '{record.get('check_in')}': {e}")
        
        # Convert check_out
        if "check_out" in record and record["check_out"]:
            try:
                # Parse UTC datetime
                utc_dt = datetime.strptime(record["check_out"], "%Y-%m-%d %H:%M:%S")
                utc_dt = pytz.UTC.localize(utc_dt)
                
                # Convert to user timezone
                local_dt = utc_dt.astimezone(tz)
                
                # Replace with local time
                record["check_out"] = local_dt.strftime("%Y-%m-%d %H:%M:%S")
            except Exception as e:
                logger.error(f"Failed to convert check_out '{record.get('check_out')}': {e}")
    
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

@router.put("/{model}/{record_id}", response_model=OdooRecordResponse)
async def update_record(
    model: str,
    record_id: int,
    request: OdooRecordRequest,
    current_user: TokenData = Depends(get_current_user)
):
    odoo_model = get_model_info(model, "update")
    connector = await get_odoo_connector(current_user)

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

