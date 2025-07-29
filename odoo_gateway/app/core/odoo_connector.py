import xmlrpc.client
from typing import List, Dict, Any, Optional
import logging

logger = logging.getLogger(__name__)

class OdooConnector:
    """Universal Odoo connector using XML-RPC"""
    
    def __init__(self, url: str, database: str, username: str, password: str):
        self.url = url.rstrip('/')
        self.database = database
        self.username = username
        self.password = password
        self.uid = None
        self.common = None
        self.models = None
        
    def authenticate(self) -> bool:
        """Authenticate with Odoo instance"""
        try:
            # Connect to common endpoint
            self.common = xmlrpc.client.ServerProxy(f'{self.url}/xmlrpc/2/common')
            
            # Get version info (optional check)
            version_info = self.common.version()
            logger.info(f"Connected to Odoo {version_info.get('server_version', 'Unknown')}")
            
            # Authenticate and get user ID
            self.uid = self.common.authenticate(
                self.database, self.username, self.password, {}
            )
            
            if self.uid:
                # Connect to object endpoint
                self.models = xmlrpc.client.ServerProxy(f'{self.url}/xmlrpc/2/object')
                logger.info(f"Successfully authenticated user {self.username} with UID {self.uid}")
                return True
            else:
                logger.error("Authentication failed: Invalid credentials")
                return False
                
        except Exception as e:
            logger.error(f"Authentication failed: {e}")
            return False
    
    def search_read(
        self, 
        model: str, 
        domain: List = None, 
        fields: List = None, 
        limit: int = None,
        offset: int = 0
    ) -> List[Dict[str, Any]]:
        """Generic search_read method"""
        if not self.uid or not self.models:
            raise Exception("Not authenticated")
            
        try:
            domain = domain or []
            fields = fields or []
            kwargs = {'offset': offset}
            if limit:
                kwargs['limit'] = limit
                
            result = self.models.execute_kw(
                self.database, self.uid, self.password,
                model, 'search_read',
                [domain], {'fields': fields, **kwargs}
            )
            
            logger.info(f"Retrieved {len(result)} records from {model}")
            return result
            
        except Exception as e:
            logger.error(f"Search failed for model {model}: {e}")
            raise Exception(f"Search failed: {e}")
    
    def create_record(self, model: str, values: Dict[str, Any]) -> int:
        """Create a record"""
        if not self.uid or not self.models:
            raise Exception("Not authenticated")
            
        try:
            record_id = self.models.execute_kw(
                self.database, self.uid, self.password,
                model, 'create', [values]
            )
            
            logger.info(f"Created record {record_id} in {model}")
            return record_id
            
        except Exception as e:
            logger.error(f"Create failed for model {model}: {e}")
            raise Exception(f"Create failed: {e}")
    
    def write_record(self, model: str, record_id: int, values: Dict[str, Any]) -> bool:
        """Update a record"""
        if not self.uid or not self.models:
            raise Exception("Not authenticated")
            
        try:
            result = self.models.execute_kw(
                self.database, self.uid, self.password,
                model, 'write', [[record_id], values]
            )
            
            logger.info(f"Updated record {record_id} in {model}")
            return result
            
        except Exception as e:
            logger.error(f"Update failed for model {model}, record {record_id}: {e}")
            raise Exception(f"Update failed: {e}")
    
    def delete_record(self, model: str, record_id: int) -> bool:
        """Delete a record"""
        if not self.uid or not self.models:
            raise Exception("Not authenticated")
            
        try:
            result = self.models.execute_kw(
                self.database, self.uid, self.password,
                model, 'unlink', [[record_id]]
            )
            
            logger.info(f"Deleted record {record_id} from {model}")
            return result
            
        except Exception as e:
            logger.error(f"Delete failed for model {model}, record {record_id}: {e}")
            raise Exception(f"Delete failed: {e}")
    
    def call_method(self, model: str, method: str, record_ids: List[int] = None, *args, **kwargs):
        """Call any Odoo method"""
        if not self.uid or not self.models:
            raise Exception("Not authenticated")
            
        try:
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
            
        except Exception as e:
            logger.error(f"Method call failed: {method} on {model}: {e}")
            raise Exception(f"Method call failed: {e}")