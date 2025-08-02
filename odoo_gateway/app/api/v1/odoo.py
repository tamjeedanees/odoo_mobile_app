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
from app.odoo_models import MODEL_MAP
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

@router.get("/{model}", response_model=OdooSearchResponse)
async def get_records(
    model: str,
    domain: str = Query("[]", description="Optional search domain as JSON string"),
    fields: Optional[str] = Query(None, description="Optional fields to retrieve as JSON string; all if not specified"),
    limit: Optional[int] = Query(None, description="Maximum number of records to return"),
    offset: int = Query(0, description="Number of records to skip"),
    current_user: TokenData = Depends(get_current_user)
):
    """Fetch records from an Odoo model. If the model supports `employee_id`, restrict data to the current employee."""

    odoo_model = MODEL_MAP.get(model)
    if not odoo_model:
        raise HTTPException(status_code=404, detail=f"Model '{model}' not found.")

    try:
        connector = get_odoo_connector(current_user)

        # Parse domain
        try:
            domain_list = json.loads(domain)
            if not isinstance(domain_list, list):
                raise ValueError("Domain must be a list.")
        except (json.JSONDecodeError, ValueError) as e:
            logger.error(f"[{odoo_model}] Invalid domain format: {e}")
            raise HTTPException(status_code=400, detail=f"Invalid 'domain' parameter: {e}")

        # Fetch model field metadata
        try:
            fields_meta = connector.fields_get(model=odoo_model)
        except Exception as e:
            logger.error(f"[{odoo_model}] Error fetching model metadata: {e}")
            raise HTTPException(status_code=500, detail="Failed to retrieve model fields.")

        if odoo_model == "hr.employee":
            # Special case: filter by ID for the employee model
            domain_list.append(["id", "=", current_user.employee_id])
            logger.info(f"[{odoo_model}] Applied ID filter for hr.employee: {current_user.employee_id}")
        elif "employee_id" in fields_meta:
            # General case: filter by employee_id if the model supports it
            domain_list.append(["employee_id", "=", current_user.employee_id])
            logger.info(f"[{odoo_model}] Applied employee_id filter: {current_user.employee_id}")
        else:
            logger.warning(f"[{odoo_model}] Skipping employee_id filter — field not present")

        # Determine fields to fetch
        if fields:
            try:
                fields_list = json.loads(fields)
                if not isinstance(fields_list, list):
                    raise ValueError("Fields must be a list.")
            except (json.JSONDecodeError, ValueError) as e:
                logger.error(f"[{odoo_model}] Invalid fields parameter: {e}")
                raise HTTPException(status_code=400, detail=f"Invalid 'fields' parameter: {e}")
        else:
            fields_list = list(fields_meta.keys())
            logger.info(f"[{odoo_model}] No fields specified, fetching all fields.")

        # Fetch records
        records = connector.search_read(
            model=odoo_model,
            domain=domain_list,
            fields=fields_list,
            limit=limit,
            offset=offset
        )

        logger.info(f"[{odoo_model}] Retrieved {len(records)} records for employee_id={current_user.employee_id}")

        return OdooSearchResponse(
            success=True,
            data=records,
            count=len(records)
        )

    except HTTPException:
        raise
    except Exception as e:
        logger.exception(f"[{odoo_model}] Unexpected error: {e}")
        raise HTTPException(
            status_code=500,
            detail=f"Failed to retrieve records from model '{odoo_model}'."
        )

@router.post("/{model}", response_model=OdooRecordResponse)
async def create_record(
    model: str,
    request: OdooRecordRequest,
    current_user: TokenData = Depends(get_current_user)
):
    odoo_model = MODEL_MAP.get(model)
    if not odoo_model:
        raise HTTPException(status_code=404, detail=f"Model '{model}' not found.")
    
    if odoo_model == "hr.employee":
        raise HTTPException(status_code=403, detail="You are not allowed to create employee records.")

    try:
        connector = get_odoo_connector(current_user)
        fields_meta = connector.fields_get(model=odoo_model)
        required_fields = [name for name, meta in fields_meta.items() if meta.get('required')]

        if "employee_id" in fields_meta:
            request.values["employee_id"] = current_user.employee_id

        missing_fields = [
            f for f in required_fields
            if f not in request.values or request.values[f] in (None, "")
        ]
        if missing_fields:
            raise HTTPException(
                status_code=422,
                detail=f"Missing required fields: {', '.join(missing_fields)}"
            )

        record_id = connector.create_record(odoo_model, request.values)

        return OdooRecordResponse(
            success=True,
            data={"id": record_id},
            message=f"Record created in {odoo_model} (ID: {record_id})"
        )

    except Exception as e:
        logger.exception(f"[{odoo_model}] Error: {e}")
        raise HTTPException(status_code=500, detail=str(e))


@router.put("/{model}/{record_id}", response_model=OdooRecordResponse)
async def update_record(
    model: str,
    record_id: int,
    request: OdooRecordRequest,
    current_user: TokenData = Depends(get_current_user)
):
    odoo_model = MODEL_MAP.get(model)
    if not odoo_model:
        raise HTTPException(status_code=404, detail=f"Model '{model}' not found.")

    try:
        connector = get_odoo_connector(current_user)

        # Load record info
        record = connector.search_read(
            model=odoo_model,
            domain=[["id", "=", record_id]],
            fields=["employee_id"]
        )
        if not record:
            raise HTTPException(status_code=404, detail="Record not found.")

        # Restrict updates
        if odoo_model == "hr.employee":
            if record[0]["id"] != current_user.employee_id:
                raise HTTPException(status_code=403, detail="You are only allowed to update your own employee record.")
        elif "employee_id" in record[0]:
            if record[0]["employee_id"][0] != current_user.employee_id:
                raise HTTPException(status_code=403, detail="Not allowed to update this record.")

        if "employee_id" in request.values:
            del request.values["employee_id"]

        result = connector.write_record(odoo_model, record_id, request.values)

        return OdooRecordResponse(
            success=True,
            data={"updated": result},
            message=f"Record {record_id} updated in {odoo_model}"
        )

    except Exception as e:
        logger.exception(f"[{odoo_model}] Error: {e}")
        raise HTTPException(status_code=500, detail=str(e))


@router.delete("/{model}/{record_id}", response_model=OdooRecordResponse)
async def delete_record(
    model: str,
    record_id: int,
    current_user: TokenData = Depends(get_current_user)
):
    odoo_model = MODEL_MAP.get(model)
    if not odoo_model:
        raise HTTPException(status_code=404, detail=f"Model '{model}' not found.")

    if odoo_model == "hr.employee":
        raise HTTPException(status_code=403, detail="You are not allowed to delete employee records.")

    try:
        connector = get_odoo_connector(current_user)

        record = connector.search_read(
            model=odoo_model,
            domain=[["id", "=", record_id]],
            fields=["employee_id"]
        )
        if not record:
            raise HTTPException(status_code=404, detail="Record not found.")

        if "employee_id" in record[0]:
            if record[0]["employee_id"][0] != current_user.employee_id:
                raise HTTPException(status_code=403, detail="Not allowed to delete this record.")

        result = connector.delete_record(odoo_model, record_id)

        return OdooRecordResponse(
            success=True,
            data={"deleted": result},
            message=f"Record {record_id} deleted from {odoo_model}"
        )

    except Exception as e:
        logger.exception(f"[{odoo_model}] Error: {e}")
        raise HTTPException(status_code=500, detail=str(e))