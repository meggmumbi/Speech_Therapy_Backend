from typing import Dict, List
from fastapi import WebSocket, WebSocketDisconnect

class ConnectionManager:
    def __init__(self):
        self.active_connections: Dict[str, WebSocket] = {}
        self.connection_sessions: Dict[str, str] = {}  # {connection_id: session_id}
        self.session_rooms: Dict[str, List[str]] = {}  # {session_id: [connection_ids]}

    async def connect(self, websocket: WebSocket, connection_id: str):
        await websocket.accept()
        self.active_connections[connection_id] = websocket

    def disconnect(self, connection_id: str):
        if connection_id in self.active_connections:
            del self.active_connections[connection_id]
        # Remove from any rooms
        if connection_id in self.connection_sessions:
            session_id = self.connection_sessions[connection_id]
            if session_id in self.session_rooms:
                self.session_rooms[session_id].remove(connection_id)
            del self.connection_sessions[connection_id]

    async def join_session(self, connection_id: str, session_id: str):
        self.connection_sessions[connection_id] = session_id
        if session_id not in self.session_rooms:
            self.session_rooms[session_id] = []
        self.session_rooms[session_id].append(connection_id)

    async def broadcast_to_session(self, session_id: str, message: dict):
        if session_id in self.session_rooms:
            for connection_id in self.session_rooms[session_id]:
                if connection_id in self.active_connections:
                    try:
                        await self.active_connections[connection_id].send_json(message)
                    except WebSocketDisconnect:
                        self.disconnect(connection_id)

    async def send_personal_message(self, connection_id: str, message: dict):
        if connection_id in self.active_connections:
            await self.active_connections[connection_id].send_json(message)

manager = ConnectionManager()