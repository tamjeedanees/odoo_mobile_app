from fastapi import APIRouter, HTTPException, status, Depends, Query
from typing import Dict, Any, Optional
from app.api.deps import get_current_user
from app.schemas.auth import TokenData
from app.schemas.odoo import (
    OdooRecordRequest, 
    OdooRecordResponse, 
    OdooSearchResponse
)
from typing import List, Dict, Any
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
    connector = OdooConnector(
        url=current_user.odoo_url,
        database=current_user.database,
        username=current_user.username,
        password=current_user.password
    )
    if not await connector.authenticate():
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail="Failed to authenticate with Odoo instance"
        )
    return connector

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

    # Identify One2many fields
    one2many_fields = [
        field for field, meta in fields_meta.items()
        if meta.get("type") == "one2many" and field in fields_list
    ]

    records = await inline_one2many_fields(records, fields_meta, fields_list, connector)

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

    required_fields = [f for f, meta in fields_meta.items() if meta.get("required")]
    missing_fields = [
        f for f in required_fields
        if f not in request.values or request.values[f] in (None, "")
    ]
    if missing_fields:
        raise HTTPException(
            status_code=422,
            detail=f"Missing required fields: {', '.join(missing_fields)}"
        )

    if "employee_id" in fields_meta:
        request.values["employee_id"] = current_user.employee_id

    record_id = await connector.create_record(odoo_model, request.values)

    return OdooRecordResponse(
        success=True,
        data={"id": record_id},
        message=f"Record created in {odoo_model} (ID: {record_id})"
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

