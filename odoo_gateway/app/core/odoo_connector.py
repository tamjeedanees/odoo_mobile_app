import xmlrpc.client
import logging
from typing import List, Dict, Any, Optional
import anyio

logger = logging.getLogger(__name__)

class OdooConnector:
    """Async-compatible Odoo XML-RPC connector using anyio.to_thread.run_sync"""
    
    def __init__(self, url: str, database: str, username: str, password: str):
        self.url = url.rstrip('/')
        self.database = database
        self.username = username
        self.password = password
        self.uid = None
        self.common = None
        self.models = None

    async def authenticate(self) -> bool:
        def _auth():
            self.common = xmlrpc.client.ServerProxy(f'{self.url}/xmlrpc/2/common')
            version_info = self.common.version()
            logger.info(f"Connected to Odoo {version_info.get('server_version', 'Unknown')}")
            self.uid = self.common.authenticate(
                self.database, self.username, self.password, {}
            )
            if self.uid:
                self.models = xmlrpc.client.ServerProxy(f'{self.url}/xmlrpc/2/object')
                logger.info(f"Authenticated user {self.username} (UID: {self.uid})")
                return True
            else:
                logger.error("Authentication failed: Invalid credentials")
                return False
        return await anyio.to_thread.run_sync(_auth)

    async def search_read(
        self, 
        model: str, 
        domain: List = None, 
        fields: List = None, 
        limit: int = None,
        offset: int = 0
    ) -> List[Dict[str, Any]]:
        if not self.uid or not self.models:
            raise Exception("Not authenticated")

        def _search_read():
            domain_inner = domain or []
            fields_inner = fields or []
            kwargs = {'offset': offset}
            if limit:
                kwargs['limit'] = limit

            result = self.models.execute_kw(
                self.database, self.uid, self.password,
                model, 'search_read',
                [domain_inner], {'fields': fields_inner, **kwargs}
            )
            logger.info(f"Retrieved {len(result)} records from {model}")
            return result

        return await anyio.to_thread.run_sync(_search_read)

    async def create_record(self, model: str, values: Dict[str, Any]) -> int:
        """
        Create a record in Odoo and attach any files included in 'attachments' key of values.
        Expected format for attachments:
        [
          {
            "filename": "file.pdf",
            "content": "<base64_string>",
            "mimetype": "application/pdf"
          }
        ]
        """
        if not self.uid or not self.models:
            raise Exception("Not authenticated")

        # Extract attachments if present
        attachments = values.pop("attachments", [])

        # Step 1: Create main record
        def _create():
            record_id = self.models.execute_kw(
                self.database, self.uid, self.password,
                model, 'create', [values]
            )
            logger.info(f"Created record {record_id} in {model}")
            return record_id

        record_id = await anyio.to_thread.run_sync(_create)

        # Step 2: Create attachment records
        for att in attachments:
            filename = att.get("filename")
            content = att.get("content")
            mimetype = att.get("mimetype", "application/octet-stream")

            if not filename or not content:
                logger.warning(f"Skipping attachment due to missing filename or content: {att}")
                continue

            attachment_vals = {
                "name": filename,
                "res_model": model,
                "res_id": record_id,
                "type": "binary",
                "datas": content,
                "mimetype": mimetype
            }

            def _attach():
                attach_id = self.models.execute_kw(
                    self.database, self.uid, self.password,
                    'ir.attachment', 'create', [attachment_vals]
                )
                logger.info(f"Attached file {filename} to record {record_id} in {model}")
                return attach_id

            await anyio.to_thread.run_sync(_attach)

        return record_id

    async def write_record(self, model: str, record_id: int, values: Dict[str, Any]) -> bool:
        if not self.uid or not self.models:
            raise Exception("Not authenticated")

        def _write():
            result = self.models.execute_kw(
                self.database, self.uid, self.password,
                model, 'write', [[record_id], values]
            )
            logger.info(f"Updated record {record_id} in {model}")
            return result

        return await anyio.to_thread.run_sync(_write)

    async def delete_record(self, model: str, record_id: int) -> bool:
        if not self.uid or not self.models:
            raise Exception("Not authenticated")

        def _delete():
            result = self.models.execute_kw(
                self.database, self.uid, self.password,
                model, 'unlink', [[record_id]]
            )
            logger.info(f"Deleted record {record_id} from {model}")
            return result

        return await anyio.to_thread.run_sync(_delete)

    async def call_method(
        self,
        model: str,
        method: str,
        record_ids: Optional[List[int]] = None,
        *args,
        **kwargs
    ):
        if not self.uid or not self.models:
            raise Exception("Not authenticated")

        def _call():
            if record_ids:
                result = self.models.execute_kw(
                    self.database, self.uid, self.password,
                    model, method, [record_ids] + list(args), kwargs
                )
            else:
                result = self.models.execute_kw(
                    self.database, self.uid, self.password,
                    model, method, list(args), kwargs
                )
            logger.info(f"Called method {method} on {model}")
            return result

        return await anyio.to_thread.run_sync(_call)

    async def fields_get(self, model: str):
        if not self.uid or not self.models:
            raise Exception("Not authenticated")

        def _fields_get():
            return self.models.execute_kw(
                self.database,
                self.uid,
                self.password,
                model,
                'fields_get',
                []
            )

        return await anyio.to_thread.run_sync(_fields_get)

    async def read(self, model: str, ids: list[int], fields: list[str] = None):
        if not self.uid or not self.models:
            raise Exception("Not authenticated")

        def _read():
            return self.models.execute_kw(
                self.database,
                self.uid,
                self.password,
                model,
                'read',
                [ids],
                {"fields": fields} if fields else {}
            )

        return await anyio.to_thread.run_sync(_read)
