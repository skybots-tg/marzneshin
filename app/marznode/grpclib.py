import asyncio
import atexit
import logging
import ssl
import tempfile

from grpclib import GRPCError
from grpclib.client import Channel
from grpclib.exceptions import StreamTerminatedError

from .base import MarzNodeBase
from .database import MarzNodeDB
from .marznode_grpc import MarzServiceStub
from .marznode_pb2 import (
    UserData,
    UsersData,
    Empty,
    User,
    Inbound,
    BackendConfig,
    BackendLogsRequest,
    Backend,
    RestartBackendRequest,
    BackendStats,
    UserDevicesRequest,
    UserDevicesHistory,
    AllUsersDevices,
)
from ..models.node import NodeStatus

logger = logging.getLogger(__name__)


def string_to_temp_file(content: str):
    file = tempfile.NamedTemporaryFile(mode="w+t")
    file.write(content)
    file.flush()
    return file


class MarzNodeGRPCLIB(MarzNodeBase, MarzNodeDB):
    def __init__(
        self,
        node_id: int,
        address: str,
        port: int,
        ssl_key: str,
        ssl_cert: str,
        usage_coefficient: int = 1,
    ):
        self.id = node_id
        self._address = address
        self._port = port

        self._key_file = string_to_temp_file(ssl_key)
        self._cert_file = string_to_temp_file(ssl_cert)

        ctx = ssl.create_default_context()
        ctx.load_cert_chain(self._cert_file.name, self._key_file.name)
        ctx.check_hostname = False
        ctx.verify_mode = ssl.CERT_NONE

        self._channel = Channel(self._address, self._port, ssl=ctx)
        self._stub = MarzServiceStub(self._channel)
        self._monitor_task = asyncio.create_task(self._monitor_channel())
        self._streaming_task = None

        self._updates_queue = asyncio.Queue(1)
        self.synced = False
        self.usage_coefficient = usage_coefficient
        atexit.register(self._channel.close)

    async def stop(self):
        self._channel.close()
        self._monitor_task.cancel()

    async def _monitor_channel(self):
        while state := self._channel._state:
            logger.debug("node %i channel state: %s", self.id, state.value)
            try:
                await asyncio.wait_for(self._channel.__connect__(), timeout=5)
            except asyncio.TimeoutError:
                error_msg = f"connection timeout (5s) to {self._address}:{self._port}"
                logger.warning("Node %i: %s", self.id, error_msg)
                self.set_status(NodeStatus.unhealthy, error_msg)
                self.synced = False
                if self._streaming_task:
                    self._streaming_task.cancel()
            except ssl.SSLError as e:
                error_msg = f"SSL error: {e}"
                logger.warning("Node %i: %s", self.id, error_msg)
                self.set_status(NodeStatus.unhealthy, error_msg)
                self.synced = False
                if self._streaming_task:
                    self._streaming_task.cancel()
            except ConnectionRefusedError:
                error_msg = f"connection refused by {self._address}:{self._port}"
                logger.warning("Node %i: %s", self.id, error_msg)
                self.set_status(NodeStatus.unhealthy, error_msg)
                self.synced = False
                if self._streaming_task:
                    self._streaming_task.cancel()
            except OSError as e:
                error_msg = f"network error: {e}"
                logger.warning("Node %i: %s", self.id, error_msg)
                self.set_status(NodeStatus.unhealthy, error_msg)
                self.synced = False
                if self._streaming_task:
                    self._streaming_task.cancel()
            except Exception as e:
                error_msg = f"{type(e).__name__}: {e}"
                logger.warning("Node %i connection failed: %s", self.id, error_msg)
                self.set_status(NodeStatus.unhealthy, error_msg)
                self.synced = False
                if self._streaming_task:
                    self._streaming_task.cancel()
            else:
                if not self.synced:
                    try:
                        await self._sync()
                    except Exception as e:
                        error_msg = f"sync failed: {type(e).__name__}: {e}"
                        logger.warning("Node %i: %s", self.id, error_msg)
                        self.set_status(NodeStatus.unhealthy, error_msg)
                    else:
                        self._streaming_task = asyncio.create_task(
                            self._stream_user_updates()
                        )
                        self.set_status(NodeStatus.healthy)
                        logger.info("Connected to node %i", self.id)
            await asyncio.sleep(10)

    async def _stream_user_updates(self):
        try:
            async with self._stub.SyncUsers.open() as stream:
                logger.debug("opened the stream")
                while True:
                    user_update = await self._updates_queue.get()
                    logger.debug("got something from queue")
                    user = user_update["user"]
                    
                    from app.config.env import ENFORCE_DEVICE_LIMITS_ON_PROXY
                    
                    user_proto = User(
                        id=user.id,
                        username=user.username,
                        key=user.key,
                        enforce_device_limit=ENFORCE_DEVICE_LIMITS_ON_PROXY
                    )
                    
                    # Add device_limit if set
                    if user_update.get("device_limit") is not None:
                        user_proto.device_limit = user_update["device_limit"]
                    
                    # Add allowed fingerprints
                    if user_update.get("allowed_fingerprints"):
                        user_proto.allowed_fingerprints.extend(
                            user_update["allowed_fingerprints"]
                        )
                    
                    await stream.send_message(
                        UserData(
                            user=user_proto,
                            inbounds=[
                                Inbound(tag=t) for t in user_update["inbounds"]
                            ],
                        )
                    )
        except (OSError, ConnectionError, GRPCError, StreamTerminatedError):
            logger.info("node %i detached", self.id)
            self.synced = False

    async def update_user(
        self, 
        user, 
        inbounds: set[str] | None = None,
        device_limit: int | None = None,
        allowed_fingerprints: list[str] | None = None
    ):
        if inbounds is None:
            inbounds = set()
        if allowed_fingerprints is None:
            allowed_fingerprints = []

        await self._updates_queue.put({
            "user": user, 
            "inbounds": inbounds,
            "device_limit": device_limit,
            "allowed_fingerprints": allowed_fingerprints
        })

    async def _repopulate_users(self, users_data: list[dict]) -> None:
        from app.config.env import ENFORCE_DEVICE_LIMITS_ON_PROXY
        
        updates = []
        for u in users_data:
            user_proto = User(
                id=u["id"], 
                username=u["username"], 
                key=u["key"],
                enforce_device_limit=ENFORCE_DEVICE_LIMITS_ON_PROXY
            )
            
            # Add device_limit if present
            if u.get("device_limit") is not None:
                user_proto.device_limit = u["device_limit"]
            
            # Add allowed fingerprints if present
            if u.get("allowed_fingerprints"):
                user_proto.allowed_fingerprints.extend(u["allowed_fingerprints"])
            
            updates.append(
                UserData(
                    user=user_proto,
                    inbounds=[Inbound(tag=t) for t in u["inbounds"]],
                )
            )
        
        await self._stub.RepopulateUsers(UsersData(users_data=updates))

    async def fetch_users_stats(self):
        response = await self._stub.FetchUsersStats(Empty())
        return response.users_stats

    async def _fetch_backends(self) -> list:
        response = await self._stub.FetchBackends(Empty())
        return response.backends

    async def _sync(self):
        backends = await self._fetch_backends()
        self.store_backends(backends)
        users = self.list_users()
        await self._repopulate_users(users)
        self.synced = True

    async def get_logs(self, name: str = "xray", include_buffer=True):
        async with self._stub.StreamBackendLogs.open() as stm:
            await stm.send_message(
                BackendLogsRequest(
                    backend_name=name, include_buffer=include_buffer
                )
            )
            while True:
                response = await stm.recv_message()
                yield response.line

    async def restart_backend(
        self, name: str, config: str, config_format: int
    ):
        try:
            await self._stub.RestartBackend(
                RestartBackendRequest(
                    backend_name=name,
                    config=BackendConfig(
                        configuration=config, config_format=config_format
                    ),
                )
            )
            await self._sync()
        except:
            self.synced = False
            self.set_status(NodeStatus.unhealthy)
            raise
        else:
            self.set_status(NodeStatus.healthy)

    async def get_backend_config(self, name: str):
        response: BackendConfig = await self._stub.FetchBackendConfig(
            Backend(name=name)
        )
        return response.configuration, response.config_format

    async def get_backend_stats(self, name: str):
        response: BackendStats = await self._stub.GetBackendStats(
            Backend(name=name)
        )
        return response

    async def fetch_user_devices(self, uid: int, active_only: bool = False):
        """Fetch device history for a specific user"""
        response: UserDevicesHistory = await self._stub.FetchUserDevices(
            UserDevicesRequest(uid=uid, active_only=active_only)
        )
        return response

    async def fetch_all_devices(self):
        """Fetch device history for all users"""
        response: AllUsersDevices = await self._stub.FetchAllDevices(Empty())
        return response

    async def resync_users(self) -> None:
        """Force resync all users with the node"""
        users = self.list_users()
        await self._repopulate_users(users)
        logger.info("Resynced %d users with node %d", len(users), self.id)
