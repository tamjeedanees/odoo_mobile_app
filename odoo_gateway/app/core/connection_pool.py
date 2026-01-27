import asyncio
import time
import logging
from typing import Dict, Optional
from dataclasses import dataclass, field
from app.core.odoo_connector import OdooConnector
from app.config import settings

logger = logging.getLogger(__name__)

@dataclass
class PooledConnection:
    """Wrapper for a pooled Odoo connection"""
    connector: OdooConnector
    created_at: float = field(default_factory=time.time)
    last_used: float = field(default_factory=time.time)
    in_use: bool = False
    use_count: int = 0
    
    def is_expired(self) -> bool:
        """Check if connection has exceeded max lifetime"""
        lifetime = time.time() - self.created_at
        return lifetime > getattr(settings, 'ODOO_CONNECTION_MAX_LIFETIME', 300)
    
    def is_idle_expired(self) -> bool:
        """Check if connection has been idle too long"""
        idle_time = time.time() - self.last_used
        return idle_time > getattr(settings, 'ODOO_CONNECTION_IDLE_TIMEOUT', 60)
    
    def mark_used(self):
        """Mark connection as used"""
        self.last_used = time.time()
        self.use_count += 1

class OdooConnectionPool:
    """
    Connection pool for Odoo XML-RPC connections
    Manages a pool of authenticated connections to reduce authentication overhead
    """
    
    def __init__(self, max_size: int = None):
        self.max_size = max_size or getattr(settings, 'ODOO_CONNECTION_POOL_SIZE', 20)
        self.pool: Dict[str, list[PooledConnection]] = {}
        self.semaphore: Dict[str, asyncio.Semaphore] = {}
        self.lock = asyncio.Lock()
        self._cleanup_task = None
        
    async def start(self):
        """Start the connection pool cleanup task"""
        if self._cleanup_task is None:
            self._cleanup_task = asyncio.create_task(self._cleanup_loop())
            logger.info(f"Odoo connection pool started with max size: {self.max_size}")
    
    async def stop(self):
        """Stop the connection pool and cleanup"""
        if self._cleanup_task:
            self._cleanup_task.cancel()
            try:
                await self._cleanup_task
            except asyncio.CancelledError:
                pass
        
        # Close all connections
        async with self.lock:
            for pool_key, connections in self.pool.items():
                for conn in connections:
                    # Connections will be garbage collected
                    pass
            self.pool.clear()
            logger.info("Odoo connection pool stopped")
    
    def _get_pool_key(self, url: str, database: str, username: str) -> str:
        """Generate unique key for connection pool"""
        return f"{url}:{database}:{username}"
    
    async def get_connection(
        self,
        url: str,
        database: str,
        username: str,
        password: str,
        timeout: float = None
    ) -> OdooConnector:
        """
        Get a connection from the pool or create a new one
        
        Args:
            url: Odoo instance URL
            database: Database name
            username: Username for authentication
            password: Password for authentication
            timeout: Timeout to wait for available connection
            
        Returns:
            Authenticated OdooConnector instance
        """
        pool_key = self._get_pool_key(url, database, username)
        timeout = timeout or getattr(settings, 'ODOO_CONNECTION_POOL_TIMEOUT', 30)
        
        # Initialize semaphore for this pool key if not exists
        if pool_key not in self.semaphore:
            async with self.lock:
                if pool_key not in self.semaphore:
                    self.semaphore[pool_key] = asyncio.Semaphore(self.max_size)
        
        # Try to acquire semaphore with timeout
        try:
            await asyncio.wait_for(
                self.semaphore[pool_key].acquire(),
                timeout=timeout
            )
        except asyncio.TimeoutError:
            logger.error(f"Timeout waiting for connection from pool: {pool_key}")
            raise Exception("Connection pool timeout - all connections busy")
        
        try:
            # Try to get existing connection from pool
            connection = await self._get_from_pool(pool_key)
            
            if connection:
                # Validate and return existing connection
                if not connection.is_expired() and not connection.is_idle_expired():
                    connection.mark_used()
                    logger.debug(f"Reusing connection from pool: {pool_key} (use count: {connection.use_count})")
                    return connection.connector
                else:
                    # Connection expired, remove it
                    logger.debug(f"Connection expired, creating new one: {pool_key}")
                    await self._remove_from_pool(pool_key, connection)
            
            # Create new connection
            connector = OdooConnector(url, database, username, password)
            
            # Authenticate
            auth_success = await connector.authenticate()
            if not auth_success:
                self.semaphore[pool_key].release()
                raise Exception(f"Failed to authenticate Odoo connection: {pool_key}")
            
            # Wrap in pooled connection
            pooled_conn = PooledConnection(connector=connector)
            pooled_conn.in_use = True
            
            # Add to pool for future reuse
            await self._add_to_pool(pool_key, pooled_conn)
            
            logger.info(f"Created new connection for pool: {pool_key}")
            return connector
            
        except Exception as e:
            # Release semaphore on error
            self.semaphore[pool_key].release()
            logger.error(f"Error getting connection from pool: {e}")
            raise
    
    async def release_connection(
        self,
        url: str,
        database: str,
        username: str,
        connector: OdooConnector
    ):
        """
        Release a connection back to the pool
        
        Args:
            url: Odoo instance URL
            database: Database name
            username: Username
            connector: The connector to release
        """
        pool_key = self._get_pool_key(url, database, username)
        
        # Mark connection as not in use
        async with self.lock:
            if pool_key in self.pool:
                for conn in self.pool[pool_key]:
                    if conn.connector == connector:
                        conn.in_use = False
                        break
        
        # Release semaphore
        if pool_key in self.semaphore:
            self.semaphore[pool_key].release()
            logger.debug(f"Released connection back to pool: {pool_key}")
    
    async def _get_from_pool(self, pool_key: str) -> Optional[PooledConnection]:
        """Get an available connection from the pool"""
        async with self.lock:
            if pool_key not in self.pool:
                self.pool[pool_key] = []
                return None
            
            # Find first available connection
            for conn in self.pool[pool_key]:
                if not conn.in_use:
                    conn.in_use = True
                    return conn
            
            return None
    
    async def _add_to_pool(self, pool_key: str, connection: PooledConnection):
        """Add a connection to the pool"""
        async with self.lock:
            if pool_key not in self.pool:
                self.pool[pool_key] = []
            self.pool[pool_key].append(connection)
    
    async def _remove_from_pool(self, pool_key: str, connection: PooledConnection):
        """Remove a connection from the pool"""
        async with self.lock:
            if pool_key in self.pool:
                self.pool[pool_key] = [
                    conn for conn in self.pool[pool_key] 
                    if conn != connection
                ]
    
    async def _cleanup_loop(self):
        """Periodic cleanup of expired connections"""
        while True:
            try:
                await asyncio.sleep(30)  # Cleanup every 30 seconds
                await self._cleanup_expired_connections()
            except asyncio.CancelledError:
                break
            except Exception as e:
                logger.error(f"Error in connection pool cleanup: {e}")
    
    async def _cleanup_expired_connections(self):
        """Remove expired and idle connections from pool"""
        async with self.lock:
            total_removed = 0
            for pool_key, connections in list(self.pool.items()):
                expired = [
                    conn for conn in connections
                    if not conn.in_use and (conn.is_expired() or conn.is_idle_expired())
                ]
                
                if expired:
                    self.pool[pool_key] = [
                        conn for conn in connections
                        if conn not in expired
                    ]
                    total_removed += len(expired)
            
            if total_removed > 0:
                logger.info(f"Cleaned up {total_removed} expired connections from pool")
    
    async def get_pool_stats(self) -> Dict:
        """Get statistics about the connection pool"""
        async with self.lock:
            stats = {
                "total_pools": len(self.pool),
                "pools": {}
            }
            
            for pool_key, connections in self.pool.items():
                stats["pools"][pool_key] = {
                    "total_connections": len(connections),
                    "in_use": sum(1 for c in connections if c.in_use),
                    "available": sum(1 for c in connections if not c.in_use),
                    "avg_use_count": sum(c.use_count for c in connections) / len(connections) if connections else 0
                }
            
            return stats

# Global connection pool instance
_connection_pool: Optional[OdooConnectionPool] = None

def get_connection_pool() -> OdooConnectionPool:
    """Get the global connection pool instance"""
    global _connection_pool
    if _connection_pool is None:
        _connection_pool = OdooConnectionPool()
    return _connection_pool

async def init_connection_pool():
    """Initialize the connection pool on startup"""
    pool = get_connection_pool()
    await pool.start()
    logger.info("Odoo connection pool initialized")

async def shutdown_connection_pool():
    """Shutdown the connection pool on application shutdown"""
    pool = get_connection_pool()
    await pool.stop()
    logger.info("Odoo connection pool shutdown complete")