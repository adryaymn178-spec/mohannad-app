import asyncio
import json
import logging
from typing import Dict, Set, Any
import auth
import database

logger = logging.getLogger("ws_server")
logging.basicConfig(level=logging.INFO)

class WebSocketManager:
    def __init__(self):
        # user_id -> set of active websocket connections
        self.active_connections: Dict[str, Set[Any]] = {}
        # ws -> user_id
        self.connection_users: Dict[Any, str] = {}
        self.owner_user_ids: Set[str] = set()

    async def register(self, websocket, user_id: str, role: str):
        if user_id not in self.active_connections:
            self.active_connections[user_id] = set()
        self.active_connections[user_id].add(websocket)
        self.connection_users[websocket] = user_id

        if role == 'owner':
            self.owner_user_ids.add(user_id)

        # Update last_seen in DB
        now = database.now_iso()
        conn = database.get_db()
        conn.execute("UPDATE users SET last_seen = ? WHERE user_id = ?", (now, user_id))
        conn.commit()
        conn.close()

        # Broadcast online presence
        await self.broadcast_presence(user_id, is_online=True)
        logger.info(f"User {user_id} connected via WebSocket.")

    async def unregister(self, websocket):
        user_id = self.connection_users.pop(websocket, None)
        if user_id and user_id in self.active_connections:
            self.active_connections[user_id].discard(websocket)
            if not self.active_connections[user_id]:
                del self.active_connections[user_id]
                self.owner_user_ids.discard(user_id)
                
                # Update last seen
                now = database.now_iso()
                conn = database.get_db()
                conn.execute("UPDATE users SET last_seen = ? WHERE user_id = ?", (now, user_id))
                conn.commit()
                conn.close()

                # Broadcast offline presence
                await self.broadcast_presence(user_id, is_online=False)
        logger.info(f"WebSocket connection closed for user {user_id}.")

    async def send_to_user(self, user_id: str, message: dict):
        if user_id in self.active_connections:
            data = json.dumps(message, ensure_ascii=False)
            dead_connections = set()
            for ws in self.active_connections[user_id]:
                try:
                    await ws.send(data)
                except Exception:
                    dead_connections.add(ws)
            for ws in dead_connections:
                await self.unregister(ws)

    async def broadcast_to_owners(self, message: dict):
        """Sends notification to all online owners."""
        data = json.dumps(message, ensure_ascii=False)
        for owner_id in list(self.owner_user_ids):
            await self.send_to_user(owner_id, message)

    async def broadcast_presence(self, user_id: str, is_online: bool):
        msg = {
            "type": "presence_update",
            "payload": {
                "user_id": user_id,
                "is_online": is_online,
                "last_seen": database.now_iso()
            }
        }
        data = json.dumps(msg, ensure_ascii=False)
        for uid, conns in self.active_connections.items():
            if uid != user_id:
                for ws in conns:
                    try:
                        await ws.send(data)
                    except Exception:
                        pass

    def is_user_online(self, user_id: str) -> bool:
        return bool(self.active_connections.get(user_id))

ws_manager = WebSocketManager()

async def handle_ws_client(websocket):
    current_user_id = None
    try:
        # First message must be authentication
        auth_msg = await websocket.recv()
        data = json.loads(auth_msg)
        token = data.get("token")
        payload = auth.verify_session_token(token) if token else None

        if not payload:
            await websocket.send(json.dumps({"type": "error", "message": "Authentication failed"}))
            await websocket.close()
            return

        current_user_id = payload["user_id"]
        role = payload.get("role", "user")
        await ws_manager.register(websocket, current_user_id, role)

        await websocket.send(json.dumps({
            "type": "auth_success",
            "user_id": current_user_id,
            "role": role
        }))

        # Message loop
        async for raw_message in websocket:
            try:
                msg = json.loads(raw_message)
                mtype = msg.get("type")
                mpayload = msg.get("payload", {})

                if mtype == "typing":
                    # Broadcast typing to chat recipient/members
                    recipient_id = mpayload.get("recipient_id")
                    chat_id = mpayload.get("chat_id")
                    is_typing = mpayload.get("is_typing", True)
                    if recipient_id:
                        await ws_manager.send_to_user(recipient_id, {
                            "type": "user_typing",
                            "payload": {
                                "chat_id": chat_id,
                                "sender_id": current_user_id,
                                "is_typing": is_typing
                            }
                        })

                elif mtype == "call_signal":
                    # WebRTC signaling: offer, answer, ice-candidate, end
                    target_user_id = mpayload.get("target_user_id")
                    if target_user_id:
                        mpayload["caller_id"] = current_user_id
                        await ws_manager.send_to_user(target_user_id, {
                            "type": "call_signal",
                            "payload": mpayload
                        })

                elif mtype == "message_read":
                    chat_id = mpayload.get("chat_id")
                    sender_id = mpayload.get("sender_id")
                    now = database.now_iso()
                    conn = database.get_db()
                    conn.execute("""
                        UPDATE messages SET read_at = ?
                        WHERE chat_id = ? AND sender_id != ? AND read_at IS NULL
                    """, (now, chat_id, current_user_id))
                    conn.commit()
                    conn.close()
                    if sender_id:
                        await ws_manager.send_to_user(sender_id, {
                            "type": "messages_read_receipt",
                            "payload": {"chat_id": chat_id, "read_by": current_user_id, "read_at": now}
                        })

                elif mtype == "ping":
                    await websocket.send(json.dumps({"type": "pong"}))

            except Exception as e:
                logger.error(f"Error processing WS message: {e}")

    except Exception as e:
        logger.info(f"WS client disconnected: {e}")
    finally:
        await ws_manager.unregister(websocket)