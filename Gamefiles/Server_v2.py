#Server Code

import socket, threading, json, time, random

HOST, PORT = "0.0.0.0", 50007
MAX_PLAYERS = 8
TICK_RATE = 20  # Server updates per second
MAP_W, MAP_H = 7000, 4000
PLAYER_MAX_HP = 100

class Player:
    def __init__(self, player_id, name, conn):
        self.id = player_id
        self.name = name
        self.conn = conn
        self.x = MAP_W // 2 + random.randint(-100, 100)
        self.y = MAP_H // 2 + random.randint(-100, 100)
        self.angle = 0.0
        self.vx = self.vy = 0.0
        self.hp = PLAYER_MAX_HP
        self.dead = False
        self.last_update = time.time()
        self.kills = 0

    def to_dict(self):
        return {
            'id': self.id, 'name': self.name, 'x': self.x, 'y': self.y,
            'angle': self.angle, 'vx': self.vx, 'vy': self.vy,
            'hp': self.hp, 'dead': self.dead, 'kills': self.kills
        }

class GameServer:
    def __init__(self):
        self.players = {}
        self.game_started = False
        self.host_id = None
        self.running = True
        self.sock = None

    def start(self):
        self.sock = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
        self.sock.setsockopt(socket.SOL_SOCKET, socket.SO_REUSEADDR, 1)
        self.sock.bind((HOST, PORT))
        self.sock.listen(MAX_PLAYERS)

        print(f"Zombs server started on {HOST}:{PORT}")
        print(f"Max players: {MAX_PLAYERS}")

        # Start game loop thread
        threading.Thread(target=self.game_loop, daemon=True).start()

        try:
            while self.running:
                try:
                    conn, addr = self.sock.accept()
                    print(f"Connection from {addr}")
                    threading.Thread(target=self.handle_client, args=(conn, addr), daemon=True).start()
                except OSError:
                    break
        except KeyboardInterrupt:
            print("\nServer shutting down...")
        finally:
            self.cleanup()

    def cleanup(self):
        self.running = False
        if self.sock:
            self.sock.close()
        for player in list(self.players.values()):
            try:
                player.conn.close()
            except:
                pass

    def handle_client(self, conn, addr):
        buffer = ""
        player = None

        try:
            while self.running:
                data = conn.recv(1024).decode('utf-8')
                if not data:
                    break

                buffer += data
                while '\n' in buffer:
                    line, buffer = buffer.split('\n', 1)
                    if line.strip():
                        try:
                            msg = json.loads(line)
                            player = self.process_message(msg, conn, player)
                        except json.JSONDecodeError:
                            continue
                        except Exception as e:
                            print(f"Error processing message: {e}")
                            continue

        except Exception as e:
            print(f"Client {addr} error: {e}")
        finally:
            if player:
                self.remove_player(player.id)
            try:
                conn.close()
            except:
                pass

    def process_message(self, msg, conn, player):
        msg_type = msg.get('type')

        if msg_type == 'join':
            player_id = msg.get('id')
            name = msg.get('name', 'Player')

            if len(self.players) >= MAX_PLAYERS:
                self.send_to_client(conn, {'type': 'error', 'message': 'Server full'})
                return None

            player = Player(player_id, name, conn)
            self.players[player_id] = player

            # Set first player as host
            if not self.host_id:
                self.host_id = player_id
                print(f"Player {name} ({player_id}) is now host")

            print(f"Player {name} ({player_id}) joined. Players: {len(self.players)}")

            # Send roster to new player
            roster = [{'id': p.id, 'name': p.name} for p in self.players.values()]
            self.send_to_client(conn, {'type': 'roster', 'players': roster})

            # Notify others of new player
            join_msg = {'type': 'join', 'id': player_id, 'name': name}
            self.broadcast_except(join_msg, player_id)

            return player

        elif msg_type == 'leave':
            if player:
                self.remove_player(player.id)
            return None

        elif msg_type == 'state' and player:
            # Update player state
            player.x = msg.get('x', player.x)
            player.y = msg.get('y', player.y)
            player.angle = msg.get('angle', player.angle)
            player.vx = msg.get('vx', player.vx)
            player.vy = msg.get('vy', player.vy)
            player.hp = msg.get('hp', player.hp)
            player.last_update = time.time()

            # Broadcast state to others
            state_msg = {
                'type': 'state', 'id': player.id,
                'x': player.x, 'y': player.y, 'angle': player.angle,
                'vx': player.vx, 'vy': player.vy, 'hp': player.hp
            }
            self.broadcast_except(state_msg, player.id)

        elif msg_type == 'start' and player and player.id == self.host_id:
            if not self.game_started and len(self.players) > 0:
                self.start_game()

        elif msg_type == 'shoot' and player:
            # Relay bullet to all players (render-only on clients)
            bullet_msg = {
                'type': 'shoot', 'id': player.id,
                'x': msg.get('x', 0), 'y': msg.get('y', 0),
                'vx': msg.get('vx', 0), 'vy': msg.get('vy', 0),
                'dmg': msg.get('dmg', 15)
            }
            self.broadcast_except(bullet_msg, player.id)

        elif msg_type == 'chest_open' and player and self.game_started:
            # Relay chest opening to all players
            chest_msg = {
                'type': 'chest_open', 'id': player.id,
                'cx': msg.get('cx'), 'cy': msg.get('cy'),
                'contents': msg.get('contents')
            }
            self.broadcast_except(chest_msg, player.id)

        elif msg_type == 'powerup_collect' and player and self.game_started:
            # Relay powerup collection to all players
            powerup_msg = {
                'type': 'powerup_collect', 'id': player.id,
                'px': msg.get('px'), 'py': msg.get('py'),
                'ptype': msg.get('ptype')
            }
            self.broadcast_except(powerup_msg, player.id)

        elif msg_type == 'medkit_use' and player and self.game_started:
            # Relay medkit use to all players
            medkit_msg = {'type': 'medkit_use', 'id': player.id}
            self.broadcast_except(medkit_msg, player.id)

        elif msg_type == 'dead' and player and self.game_started:
            player.dead = True
            dead_msg = {'type': 'dead', 'id': player.id}
            self.broadcast_except(dead_msg, player.id)

        elif msg_type == 'respawn' and player:
            player.x = msg.get('x', MAP_W // 2)
            player.y = msg.get('y', MAP_H // 2)
            player.hp = msg.get('hp', PLAYER_MAX_HP)
            player.dead = False

            respawn_msg = {
                'type': 'respawn', 'id': player.id,
                'x': player.x, 'y': player.y, 'hp': player.hp
            }
            # Inform everyone else, and also echo back to the requester in case client-side suppressed local spawn UI
            self.broadcast_except(respawn_msg, player.id)
            self.send_to_client(player.conn, respawn_msg)

        elif msg_type == 'hit' and player:
            target_id = msg.get('target_id')
            dmg = int(msg.get('dmg', 15))
            if target_id and target_id in self.players:
                target = self.players[target_id]
                if not target.dead:
                    target.hp = max(0, target.hp - dmg)
                    if target.hp <= 0:
                        target.dead = True
                        # announce death
                        dead_msg = {'type': 'dead', 'id': target.id}
                        self.broadcast(dead_msg)
                    else:
                        # hp update for target
                        hp_msg = {'type': 'hp', 'id': target.id, 'hp': target.hp}
                        self.broadcast(hp_msg)

        return player

    def start_game(self):
        self.game_started = True
        print(f"Game started with {len(self.players)} players")

        # Reset all players
        for player in self.players.values():
            player.hp = PLAYER_MAX_HP
            player.dead = False
            player.kills = 0
            player.x = MAP_W // 2 + random.randint(-200, 200)
            player.y = MAP_H // 2 + random.randint(-200, 200)

        start_msg = {'type': 'start', 'players': len(self.players)}
        self.broadcast(start_msg)

    def remove_player(self, player_id):
        if player_id in self.players:
            player = self.players[player_id]
            del self.players[player_id]

            print(f"Player {player.name} ({player_id}) left. Players: {len(self.players)}")

            # If host left, assign new host
            if self.host_id == player_id:
                if self.players:
                    self.host_id = next(iter(self.players))
                    print(f"New host: {self.players[self.host_id].name}")
                else:
                    self.host_id = None
                    self.game_started = False

            # Notify others
            leave_msg = {'type': 'leave', 'id': player_id}
            self.broadcast(leave_msg)

    def send_to_client(self, conn, msg):
        try:
            data = json.dumps(msg) + '\n'
            conn.sendall(data.encode('utf-8'))
        except:
            pass

    def broadcast(self, msg):
        for player in list(self.players.values()):
            self.send_to_client(player.conn, msg)

    def broadcast_except(self, msg, except_id):
        for player in list(self.players.values()):
            if player.id != except_id:
                self.send_to_client(player.conn, msg)

    def game_loop(self):
        last_time = time.time()

        while self.running:
            current_time = time.time()
            dt = current_time - last_time

            if dt >= 1.0 / TICK_RATE:
                self.update_game(dt)
                last_time = current_time

            time.sleep(0.01)  # Prevent busy waiting

    def update_game(self, dt):
        if not self.game_started:
            return

        # Remove disconnected players (no updates for 10 seconds)
        current_time = time.time()
        disconnected = []

        for player_id, player in self.players.items():
            if current_time - player.last_update > 10.0:
                disconnected.append(player_id)

        for player_id in disconnected:
            print(f"Player {player_id} timed out")
            self.remove_player(player_id)

        # Check win conditions (if needed)
        alive_players = [p for p in self.players.values() if not p.dead]
        if len(alive_players) <= 1 and len(self.players) > 1:
            # Game over logic could go here
            pass

    def get_status(self):
        return {
            'players': len(self.players),
            'max_players': MAX_PLAYERS,
            'game_started': self.game_started,
            'host': self.host_id
        }

def main():
    print("Zombs Game Server v1.0")
    print("Press Ctrl+C to stop")

    server = GameServer()
    try:
        server.start()
    except KeyboardInterrupt:
        print("\nShutting down server...")
    finally:
        server.cleanup()

if __name__ == "__main__":
    main()
