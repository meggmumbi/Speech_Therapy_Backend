import uuid
from fastapi import APIRouter, WebSocket
from fastapi.websockets import WebSocketDisconnect
from ..ws.websocket import manager

router = APIRouter()


@router.websocket("/ws")
async def websocket_endpoint(websocket: WebSocket):
    connection_id = str(uuid.uuid4())
    await manager.connect(websocket, connection_id)

    try:
        while True:
            data = await websocket.receive_json()

            # First message should establish session
            if not manager.connection_sessions.get(connection_id):
                if data.get("type") == "initialize_session":
                    session_id = data.get("session_id", str(uuid.uuid4()))
                    await manager.join_session(connection_id, session_id)
                    await manager.send_personal_message(
                        connection_id,
                        {"type": "session_initialized", "session_id": session_id}
                    )
                continue

            # Handle other message types
            session_id = manager.connection_sessions[connection_id]

            if data["type"] == "child_response":
                await manager.broadcast_to_session(
                    session_id,
                    {
                        "type": "response_update",
                        "data": {
                            "item_id": data["item_id"],
                            "response": data["response"],
                            "score": data.get("score", 0)
                        }
                    }
                )
            elif data["type"] == "caregiver_command":
                await manager.broadcast_to_session(
                    session_id,
                    {
                        "type": "session_command",
                        "command": data["command"]
                    }
                )
            elif data["type"] == "ping":
                await manager.send_personal_message(
                    connection_id,
                    {"type": "pong"}
                )

    except WebSocketDisconnect:
        manager.disconnect(connection_id)
    except Exception as e:
        print(f"WebSocket error: {str(e)}")
        manager.disconnect(connection_id)