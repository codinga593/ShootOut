import asyncio
import json
import math
from pathlib import Path

from aiohttp import WSMsgType, web


HOST, PORT = "0.0.0.0", 8000
MAX_PLAYERS = 8
MAP_W, MAP_H = 7000, 4000
PLAYER_MAX_HP = 100
SPAWN_RING_RADIUS = 190
WEB_ROOT = Path(__file__).resolve().parent / "build" / "web"


class Player:
    def __init__(self, player_id, name, websocket, x, y):
        self.id = player_id
        self.name = name
        self.websocket = websocket
        self.x = x
        self.y = y
        self.angle = 0.0
        self.vx = self.vy = 0.0
        self.hp = PLAYER_MAX_HP
        self.dead = False
        self.kills = 0

    def to_roster_dict(self):
        return {
            "id": self.id,
            "name": self.name,
            "x": self.x,
            "y": self.y,
            "angle": self.angle,
            "vx": self.vx,
            "vy": self.vy,
            "hp": self.hp,
            "dead": self.dead,
        }


class GameServer:
    def __init__(self):
        self.players = {}
        self.host_id = None
        self.game_started = False
        self.cleanup_task = None

    def next_spawn_point(self):
        """Return a separated spawn around the clear centre of the map."""
        radius = SPAWN_RING_RADIUS
        candidates = []
        for slot in range(MAX_PLAYERS):
            angle = slot * (2 * math.pi / MAX_PLAYERS)
            candidates.append((
                MAP_W // 2 + round(math.cos(angle) * radius),
                MAP_H // 2 + round(math.sin(angle) * radius),
            ))
        if not self.players:
            return candidates[0]
        return max(
            candidates,
            key=lambda point: min(
                math.hypot(point[0] - p.x, point[1] - p.y)
                for p in self.players.values()
            ),
        )

    async def start_background_tasks(self, _app):
        self.cleanup_task = asyncio.create_task(self.cleanup_loop())

    async def stop_background_tasks(self, _app):
        if self.cleanup_task:
            self.cleanup_task.cancel()
            try:
                await self.cleanup_task
            except asyncio.CancelledError:
                pass
        await asyncio.gather(
            *(player.websocket.close() for player in list(self.players.values())),
            return_exceptions=True,
        )

    async def websocket_handler(self, request):
        websocket = web.WebSocketResponse(heartbeat=20)
        await websocket.prepare(request)
        player = None

        try:
            async for incoming in websocket:
                if incoming.type == WSMsgType.TEXT:
                    try:
                        message = json.loads(incoming.data)
                    except (TypeError, json.JSONDecodeError):
                        await self.send(websocket, {"type": "error", "message": "Invalid message"})
                        continue
                    player = await self.process_message(message, websocket, player)
                elif incoming.type == WSMsgType.ERROR:
                    break
        finally:
            if player:
                await self.remove_player(player.id)

        return websocket

    async def process_message(self, message, websocket, player):
        message_type = message.get("type")

        if message_type == "ping":
            await self.send(websocket, {"type": "pong"})
            print("WebSocket browser probe passed")
            return player

        if message_type == "join":
            player_id = str(message.get("id", ""))[:64]
            name = str(message.get("name", "Player"))[:24]
            if not player_id:
                await self.send(websocket, {"type": "error", "message": "Missing player id"})
                return None
            if len(self.players) >= MAX_PLAYERS and player_id not in self.players:
                await self.send(websocket, {"type": "error", "message": "Server full"})
                await websocket.close()
                return None
            if player_id in self.players:
                await self.remove_player(player_id)

            spawn_x, spawn_y = self.next_spawn_point()
            player = Player(player_id, name, websocket, spawn_x, spawn_y)
            self.players[player_id] = player
            if not self.host_id:
                self.host_id = player_id
            self.game_started = True

            # Send the complete authoritative roster to everyone. This makes
            # existing and newly-opened browser tabs converge to the same view.
            await self.broadcast(
                {
                    "type": "roster",
                    "players": [p.to_roster_dict() for p in self.players.values()],
                    "host_id": self.host_id,
                }
            )
            await self.broadcast({"type": "start", "players": len(self.players)})
            print(f"Player {name} ({player_id}) joined via WebSocket")
            return player

        if not player:
            await self.send(websocket, {"type": "error", "message": "Join first"})
            return None

        if message_type == "leave":
            await self.remove_player(player.id)
            return None

        if message_type == "state":
            player.x = message.get("x", player.x)
            player.y = message.get("y", player.y)
            player.angle = message.get("angle", player.angle)
            player.vx = message.get("vx", player.vx)
            player.vy = message.get("vy", player.vy)
            player.hp = message.get("hp", player.hp)
            await self.broadcast_except(
                {
                    "type": "state",
                    "id": player.id,
                    "x": player.x,
                    "y": player.y,
                    "angle": player.angle,
                    "vx": player.vx,
                    "vy": player.vy,
                    "hp": player.hp,
                },
                player.id,
            )

        elif message_type == "shoot":
            await self.broadcast_except(
                {
                    "type": "shoot",
                    "id": player.id,
                    "x": message.get("x", 0),
                    "y": message.get("y", 0),
                    "vx": message.get("vx", 0),
                    "vy": message.get("vy", 0),
                    "dmg": message.get("dmg", 15),
                },
                player.id,
            )

        elif message_type in {"chest_open", "powerup_collect", "medkit_use"}:
            await self.broadcast_except({**message, "id": player.id}, player.id)

        elif message_type == "dead":
            player.dead = True
            await self.broadcast({"type": "dead", "id": player.id})

        elif message_type == "respawn":
            player.x = message.get("x", MAP_W // 2)
            player.y = message.get("y", MAP_H // 2)
            player.hp = PLAYER_MAX_HP
            player.dead = False
            await self.broadcast(
                {
                    "type": "respawn",
                    "id": player.id,
                    "x": player.x,
                    "y": player.y,
                    "hp": player.hp,
                }
            )

        elif message_type == "hit":
            target = self.players.get(message.get("target_id"))
            if target and not target.dead:
                damage = max(0, min(500, int(message.get("dmg", 15))))
                target.hp = max(0, target.hp - damage)
                if target.hp == 0:
                    target.dead = True
                    player.kills += 1
                    await self.broadcast({"type": "dead", "id": target.id})
                else:
                    await self.broadcast({"type": "hp", "id": target.id, "hp": target.hp})

        return player

    async def remove_player(self, player_id):
        player = self.players.pop(player_id, None)
        if not player:
            return
        if self.host_id == player_id:
            self.host_id = next(iter(self.players), None)
        if not self.players:
            self.game_started = False
        await self.broadcast({"type": "leave", "id": player_id, "host_id": self.host_id})
        print(f"Player {player.name} ({player_id}) left")

    async def send(self, websocket, message):
        if not websocket.closed:
            try:
                await websocket.send_str(json.dumps(message))
            except (ConnectionError, RuntimeError):
                pass

    async def broadcast(self, message):
        await asyncio.gather(
            *(self.send(player.websocket, message) for player in list(self.players.values())),
            return_exceptions=True,
        )

    async def broadcast_except(self, message, excluded_id):
        await asyncio.gather(
            *(
                self.send(player.websocket, message)
                for player in list(self.players.values())
                if player.id != excluded_id
            ),
            return_exceptions=True,
        )

    async def cleanup_loop(self):
        while True:
            await asyncio.sleep(15)
            stale_ids = [
                player.id
                for player in self.players.values()
                if player.websocket.closed
            ]
            for player_id in stale_ids:
                await self.remove_player(player_id)

    async def status_handler(self, _request):
        return web.json_response(
            {
                "players": len(self.players),
                "max_players": MAX_PLAYERS,
                "game_started": self.game_started,
                "host": self.host_id,
            }
        )


async def index_handler(_request):
    index = WEB_ROOT / "index.html"
    if not index.exists():
        raise web.HTTPServiceUnavailable(text="Run ./build_web.sh first")
    return web.FileResponse(index)


def create_app():
    server = GameServer()
    app = web.Application()
    app["game_server"] = server
    app.on_startup.append(server.start_background_tasks)
    app.on_cleanup.append(server.stop_background_tasks)
    app.router.add_get("/ws", server.websocket_handler)
    app.router.add_get("/api/status", server.status_handler)
    app.router.add_get("/", index_handler)
    if WEB_ROOT.exists():
        app.router.add_static("/", WEB_ROOT, show_index=False)
    return app


def main():
    print(f"ShootOut web server: http://localhost:{PORT}")
    print(f"WebSocket multiplayer: ws://localhost:{PORT}/ws")
    web.run_app(create_app(), host=HOST, port=PORT)


if __name__ == "__main__":
    main()
