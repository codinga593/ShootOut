import pygame, random, math, os, sys, time, threading, socket, json, uuid
from dataclasses import dataclass

# Server and Game Config
SERVER_HOST, SERVER_PORT = "0.0.0.0", 50007
MAP_W, MAP_H = 7000, 4000
SCREEN_W, SCREEN_H = 1280, 800
FPS = 60

# Game constants
PLAYER_SPEED, PLAYER_RADIUS, PLAYER_MAX_HP = 320.0, 18, 100
BULLET_LIFE, BOT_COUNT = 2.2, 16
BOT_RADIUS, BOT_SPEED, BOT_HP = 16, 150.0, 70
BOT_SHOOT_COOLDOWN, BOT_VIEW_RANGE = 1.1, 700
OBSTACLE_COUNT, CHEST_COUNT, POWERUP_COUNT = 120, 46, 30
MAX_WEAPON_SLOTS, MAX_MEDKITS = 2, 3
MEDKIT_HEAL, MEDKIT_USE_TIME = 50, 1.8


# Colors definitions
WHITE, BLACK, RED, GREEN = (240,240,240), (10,10,10), (220,40,40), (40,200,40)
YELLOW, BLUE, GRAY, PURPLE = (220,200,40), (60,140,220), (120,120,120), (180,40,180)
ORANGE, CYAN, PINK = (255,165,0), (0, 0, 139), (255,20,147)

# Assets and Music intialization for background sounds
ASSET_DIR = os.path.join(os.path.dirname(__file__), "zombs_assets_v3")
SOUND_DIR = os.path.join(ASSET_DIR, "sounds")
pygame.mixer.init()
pygame.mixer.music.load("background.mp3")
pygame.mixer.music.set_volume(0.7)
pygame.mixer.music.play(-1)

#Functions required
def clamp(v,a,b): 
    return max(a,min(b,v))

def length(x,y): 
    return math.hypot(x,y)

def normalize(x,y):
    d = math.hypot(x,y)
    return (x/d, y/d) if d else (0,0)

#Predictable random function for seed gen
class DeterministicRandom:
    def __init__(self, seed): 
        self.seed = seed

    def random(self):
        self.seed = (self.seed * 1103515245 + 12345) & 0x7fffffff
        return self.seed / 0x7fffffff
    
    def randint(self, a, b): 
        return int(self.random() * (b - a + 1)) + a
    
    def choice(self, seq): 
        return seq[int(self.random() * len(seq))]


#Gun Class
@dataclass
class Gun:
    name: str
    mag: int
    damage: int
    fire_rate: float
    reload_time: float
    bullets_per_shot: int
    spread: float
    bullet_speed: float

GUN_TYPES = {
    "Pistol": Gun("Pistol", 12, 28, 0.22, 1.0, 1, 4, 1000),
    "SMG": Gun("SMG", 30, 12, 0.08, 1.6, 1, 6, 980),
    "Shotgun": Gun("Shotgun", 6, 10, 0.9, 2.1, 7, 32, 720),
    "Sniper": Gun("Sniper", 5, 120, 1.6, 2.6, 1, 0.8, 1800),
}

#Powerup Types
POWERUP_TYPES = {
    "speed": {"name": "Speed Boost", "color": CYAN, "duration": 12.0},
    "damage": {"name": "Damage Boost", "color": RED, "duration": 15.0},
    "shield": {"name": "Shield", "color": PURPLE, "duration": 18.0},
    "rapid": {"name": "Rapid Fire", "color": ORANGE, "duration": 10.0},
    "heal": {"name": "Regeneration", "color": GREEN, "duration": 5.0},
    "ghost": {"name": "Phase Walk", "color": PINK, "duration": 10.0},
}

class Entity:
    def __init__(self, x, y, r):
        self.x, self.y, self.r = x, y, r
        self.vx = self.vy = 0
        self.hp, self.dead = 100, False
            
#Multiplayer
class RemotePlayer(Entity):
    def __init__(self, pid, name, x=MAP_W/2, y=MAP_H/2):
        super().__init__(x, y, PLAYER_RADIUS)
        self.id = pid
        self.name = name
        self.angle = 0.0
        self.color = (200, 200, 0)  # yellowish to stand out

#Player Class
class Player(Entity):
    def __init__(self, x, y):
        super().__init__(x, y, PLAYER_RADIUS)
        self.hp, self.angle, self.kills = PLAYER_MAX_HP, 0.0, 0
        self.inventory = [GUN_TYPES["Pistol"], None]
        self.equipped, self.mag = 0, [self.inventory[0].mag, 0]
        self.is_reloading = self.is_using_medkit = False
        self.reload_timer = self.medkit_timer = self.last_shot = 0.0
        self.medkits = 0
        self.reset_powerup_effects()
        self.active_powerups = []
#ALL required functions (update, reset, etc)
    def reset_powerup_effects(self):
        self.base_speed = PLAYER_SPEED
        self.damage_multiplier = 1.0
        self.shield_active = self.regen_active = self.ghost_mode = False
        self.fire_rate_multiplier = 1.0

    def add_powerup(self, ptype):
        # Remove existing of same type
        self.active_powerups = [p for p in self.active_powerups if p['type'] != ptype]
        # Add new
        duration = POWERUP_TYPES[ptype]['duration']
        self.active_powerups.append({'type': ptype, 'time_left': duration})
        self.update_powerup_effects()

    def update_powerups(self, dt):
        for p in self.active_powerups[:]:
            p['time_left'] -= dt
            if p['time_left'] <= 0:
                self.active_powerups.remove(p)
        self.update_powerup_effects()
        if self.regen_active and self.hp < PLAYER_MAX_HP:
            self.hp = min(PLAYER_MAX_HP, self.hp + 10 * dt)

    def update_powerup_effects(self):
        self.reset_powerup_effects()
        for p in self.active_powerups:
            if p['type'] == 'speed':
                self.base_speed = PLAYER_SPEED * 1.8
            elif p['type'] == 'damage':
                self.damage_multiplier = 2.5
            elif p['type'] == 'shield':
                self.shield_active = True
            elif p['type'] == 'rapid':
                self.fire_rate_multiplier = 0.3
            elif p['type'] == 'heal':
                self.regen_active = True
            elif p['type'] == 'ghost':
                self.ghost_mode = True

    @property
    def gun(self): 
        return self.inventory[self.equipped]

    def shoot(self, tx, ty):
        if not self.gun or self.is_reloading or self.is_using_medkit or self.mag[self.equipped] <= 0:
            return []
        
        effective_fire_rate = self.gun.fire_rate * self.fire_rate_multiplier
        if self.last_shot < effective_fire_rate:
            return []

        dx, dy = tx - self.x, ty - self.y
        nx, ny = normalize(dx, dy)
        bullets = []
        
        for _ in range(self.gun.bullets_per_shot):
            angle = math.atan2(ny, nx)
            spread = (random.random()-0.5) * math.radians(self.gun.spread)
            a = angle + spread
            vx, vy = math.cos(a) * self.gun.bullet_speed, math.sin(a) * self.gun.bullet_speed
            bx = self.x + math.cos(a) * (self.r + 8)
            by = self.y + math.sin(a) * (self.r + 8)
            damage = int(self.gun.damage * self.damage_multiplier)
            bullets.append(Bullet(bx, by, vx, vy, 'player', damage))
        
        self.mag[self.equipped] -= 1
        self.last_shot = 0.0
        return bullets

#Bot States (Chase & Wander)
class Bot(Entity):
    def __init__(self, x, y, i):
        super().__init__(x, y, BOT_RADIUS)
        self.id, self.hp = i, BOT_HP
        self.state = 'wander'
        self.wander_dir = normalize(random.uniform(-1,1), random.uniform(-1,1))
        self.shoot_cd = random.uniform(0, BOT_SHOOT_COOLDOWN)

    def update_ai(self, game, dt):
        if self.dead: 
            return
        p = game.player
        dx, dy = p.x - self.x, p.y - self.y
        dist = math.hypot(dx, dy)
        see = dist < BOT_VIEW_RANGE and not game.line_blocked(self.x, self.y, p.x, p.y)
        
        if see:
            self.state = 'chase'
            nx, ny = normalize(dx, dy)
            self.vx, self.vy = nx * BOT_SPEED, ny * BOT_SPEED
            self.shoot_cd -= dt
            if self.shoot_cd <= 0 and dist < BOT_VIEW_RANGE:
                self.shoot_cd = BOT_SHOOT_COOLDOWN
                ax, ay = normalize(p.x - self.x, p.y - self.y)
                b = Bullet(self.x + ax*(self.r+6), self.y + ay*(self.r+6), ax*900, ay*900, 'bot', 18)
                game.bullets.append(b)
        else:
            self.state = 'wander'
            if random.random() < 0.02:
                self.wander_dir = normalize(random.uniform(-1,1), random.uniform(-1,1))
            self.vx = self.wander_dir[0] * BOT_SPEED * 0.6
            self.vy = self.wander_dir[1] * BOT_SPEED * 0.6

#Bullet
class Bullet:
    def __init__(self, x, y, vx, vy, owner='bot', dmg=15):
        self.x, self.y, self.vx, self.vy = x, y, vx, vy
        self.owner, self.dmg, self.life, self.r = owner, dmg, BULLET_LIFE, 4

#Network Connection
class NetworkClient:
    def __init__(self, host, port, player_id, name="Player"):
        self.host, self.port = host, port
        self.player_id, self.name = player_id, name
        self.sock = None
        self.running = self.connected = False
        self.on_message = None

    def connect(self):
        try:
            self.sock = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
            self.sock.settimeout(5.0)
            self.sock.connect((self.host, self.port))
            self.sock.settimeout(None)
            self.running = self.connected = True
            threading.Thread(target=self._recv_loop, daemon=True).start()
            self.send({"type": "join", "id": self.player_id, "name": self.name})
            return True
        except Exception as e:
            print(f"Connection error: {e}")
            return False

    def send(self, obj):
        if not self.running: 
            return
        try:
            data = (json.dumps(obj) + "\n").encode("utf-8")
            self.sock.sendall(data)
        except:
            self.running = False

    def _recv_loop(self):
        buff = ""
        try:
            while self.running:
                chunk = self.sock.recv(4096).decode("utf-8")
                if not chunk: 
                    break
                buff += chunk
                while "\n" in buff:
                    line, buff = buff.split("\n", 1)
                    if line.strip():
                        try:
                            msg = json.loads(line)
                            if self.on_message: 
                                self.on_message(msg)
                        except: 
                            pass
        except: 
            pass
        finally:
            self.running = self.connected = False
            
    # Error Handling
    
    def close(self):
        self.running = False
        if self.sock:
            try: 
                self.sock.close()
            except: 
                pass

#Singleplayer and Multiplayer Game Loop
class Game:
    def __init__(self, multiplayer=False):
        pygame.init()
        self.screen = pygame.display.set_mode((SCREEN_W, SCREEN_H))
        pygame.display.set_caption(f"Zombs v3 ({'Multiplayer' if multiplayer else 'Singleplayer'})")
        self.clock = pygame.time.Clock()
        
        # Fonts
        self.font = pygame.font.SysFont("Consolas", 18)
        self.bigfont = pygame.font.SysFont("Consolas", 72)
        
        # Game objects
        self.camera = pygame.Rect(0, 0, SCREEN_W, SCREEN_H)
        self.player = Player(MAP_W/2, MAP_H/2)
        self.bullets, self.bots, self.obstacles, self.chests, self.powerups = [], [], [], [], []
        
        # Game state
        self.mouse_down = self.victory = False
        self.show_minimap = True
        self.flash_alpha = 0
        self.start_time = time.time()
        
        # Multiplayer
        self.multiplayer = multiplayer
        self.player_id = str(uuid.uuid4())[:8]
        self.net_client = None
        self.remote_players = {}
        self.lobby_players = {}
        self.is_host = False
        
        # Generate world
        self._spawn_world()
        if not multiplayer:
            self._spawn_bots()
        
        # Load assets
        self.assets = self._load_assets()
        self.sounds = self._load_sounds()

    def _load_assets(self):
        assets = {}
        asset_files = {
            'player': 'player.png', 
            'chest': 'chest.png', 
            'slot': 'slot.png', 
            'slot_hl': 'slot_highlight.png'
        }
        for gun in GUN_TYPES:
            asset_files[gun] = f"{gun.lower()}.png"
        
        for name, file in asset_files.items():
            path = os.path.join(ASSET_DIR, file)
            if os.path.exists(path):
                try: 
                    assets[name] = pygame.image.load(path).convert_alpha()
                except: 
                    pass
        return assets

#Sound Effects Loading
    
    def _load_sounds(self):
        sounds = {}
        try: 
            pygame.mixer.init()
        except: 
            return sounds
        
        sound_files = {
            'pistol': 'pistol.mp3', 
            'smg': 'smg.mp3', 
            'shotgun': 'shotgun.mp3',
            'sniper': 'sniper.mp3', 
            'reload': 'reload.mp3', 
            'hit': 'hit.mp3',
            'victory': 'victory.mp3'
        }
        
        for name, file in sound_files.items():
            path = os.path.join(SOUND_DIR, file)
            if os.path.exists(path):
                try: 
                    sounds[name] = pygame.mixer.Sound(path)
                except: 
                    pass
        return sounds

    def _spawn_world(self):
    # --- Seed selection ---
        if self.multiplayer:
            # Fixed seeds so all clients share the same map
            obstacle_seed, chest_seed, powerup_seed = 12345, 54321, 98765
        else:
            # Random seeds so each match is different
            obstacle_seed  = int(time.time()) & 0xFFFFFFFF
            chest_seed     = int(time.time() * 1.37) & 0xFFFFFFFF
            powerup_seed   = int(time.time() * 2.17) & 0xFFFFFFFF

        # Log seeds so you can replay the exact map later
        print(f"[WORLD SEEDS] Obstacles={obstacle_seed}, Chests={chest_seed}, Powerups={powerup_seed}")

        # --- Obstacles ---
        rng = DeterministicRandom(obstacle_seed)
        for _ in range(OBSTACLE_COUNT):
            w, h = rng.randint(120, 420), rng.randint(80, 420)
            x, y = rng.randint(60, MAP_W - w - 60), rng.randint(60, MAP_H - h - 60)
            if not pygame.Rect(x, y, w, h).collidepoint(MAP_W / 2, MAP_H / 2):
                self.obstacles.append(pygame.Rect(x, y, w, h))

        # --- Chests ---
        rng = DeterministicRandom(chest_seed)
        for _ in range(CHEST_COUNT):
            if self._place_item(rng, self.chests, 'chest', 28):
                self.chests[-1]['contents'] = rng.choice(list(GUN_TYPES.keys()) + ['medkit', 'medkit'])

        # --- Powerups ---
        rng = DeterministicRandom(powerup_seed)
        for _ in range(POWERUP_COUNT):
            if self._place_item(rng, self.powerups, 'powerup', 20):
                self.powerups[-1]['type'] = rng.choice(list(POWERUP_TYPES.keys()))
                self.powerups[-1]['bob'] = 0.0


    def _place_item(self, rng, container, item_type, radius):
        for _ in range(300):
            x, y = rng.randint(100, MAP_W-100), rng.randint(100, MAP_H-100)
            if self._can_place(x, y, radius):
                if item_type == 'chest':
                    item = {'x': x, 'y': y, 'opened': False}
                else:
                    item = {'x': x, 'y': y, 'collected': False}
                container.append(item)
                return True
        return False

    # Prvent Obstacle collisions
    def _can_place(self, x, y, radius):
        rect = pygame.Rect(x-radius, y-radius, radius*2, radius*2)
        return not any(rect.colliderect(obs) for obs in self.obstacles)

    def _spawn_bots(self):
        for i in range(BOT_COUNT):
            for _ in range(500):
                x, y = random.randint(60, MAP_W-60), random.randint(60, MAP_H-60)
                if length(x-self.player.x, y-self.player.y) > 300 and self._can_place(x, y, BOT_RADIUS+6):
                    self.bots.append(Bot(x, y, i))
                    break

    def line_blocked(self, x1, y1, x2, y2):
        steps = int(max(8, length(x2-x1, y2-y1)/32))
        for i in range(steps+1):
            t = i/steps
            x, y = x1+(x2-x1)*t, y1+(y2-y1)*t
            if any(obs.collidepoint(x, y) for obs in self.obstacles):
                return True
        return False

    def connect_to_server(self):
        self.net_client = NetworkClient(SERVER_HOST, SERVER_PORT, self.player_id)
        self.net_client.on_message = self._handle_network_message
        return self.net_client.connect()

    #Network message types
    
    def _handle_network_message(self, msg):
        msg_type = msg.get("type")
        if msg_type == "join":
            pid = msg.get("id")
            self.lobby_players[pid] = msg.get("name", "Player")
        elif msg_type == "leave":
            pid = msg.get("id")
            self.lobby_players.pop(pid, None)
            self.remote_players.pop(pid, None)
        elif msg_type == "start":
            self.victory = False
            self.start_time = time.time()
        if msg_type == "roster":
            for p in msg.get("players", []):
                pid, name = p["id"], p["name"]
                if pid != self.player_id and pid not in self.remote_players:
                    self.remote_players[pid] = RemotePlayer(pid, name)

        elif msg_type == "join":
            pid, name = msg.get("id"), msg.get("name", "Player")
            if pid != self.player_id:
                self.remote_players[pid] = RemotePlayer(pid, name)

        elif msg_type == "leave":
            pid = msg.get("id")
            self.remote_players.pop(pid, None)

        elif msg_type == "state":
            pid = msg.get("id")
            if pid in self.remote_players:
                rp = self.remote_players[pid]
                rp.x, rp.y = msg["x"], msg["y"]
                rp.vx, rp.vy = msg["vx"], msg["vy"]
                rp.angle, rp.hp = msg["angle"], msg["hp"]

        elif msg_type == "shoot":
            bx, by = msg["x"], msg["y"]
            vx, vy, dmg = msg["vx"], msg["vy"], msg["dmg"]
            self.bullets.append(Bullet(bx, by, vx, vy, 'remote', dmg))

        elif msg_type == "dead":
            pid = msg.get("id")
            if pid == self.player_id:
                self.player.dead = True
            elif pid in self.remote_players:
                self.remote_players[pid].dead = True

        elif msg_type == "respawn":
            pid = msg.get("id")
            if pid == self.player_id:
                self.player.x, self.player.y = msg["x"], msg["y"]
                self.player.hp = msg["hp"]
                self.player.dead = False
            elif pid in self.remote_players:
                rp = self.remote_players[pid]
                rp.x, rp.y = msg["x"], msg["y"]
                rp.hp, rp.dead = msg["hp"], False

        elif msg_type == "hp":
            # HP update from server
            pid = msg.get("id")
            if pid == self.player_id:
                self.player.hp = msg.get("hp", self.player.hp)
                if self.player.hp <= 0:
                    self.player.dead = True
            elif pid in self.remote_players:
                rp = self.remote_players[pid]
                rp.hp = msg.get("hp", rp.hp)
                if rp.hp <= 0:
                    rp.dead = True

    #Update stored stats
                
    def update(self, dt):
        # Handle input
        keys = pygame.key.get_pressed()
        mx, my = pygame.mouse.get_pos()
        world_mx, world_my = mx + self.camera.x, my + self.camera.y
        
        if self.player.dead: 
            return
        
        # Update powerups
        self.player.update_powerups(dt)
        
        # Movement
        dx = dy = 0
        if keys[pygame.K_w]: 
            dy -= 1
        if keys[pygame.K_s]: 
            dy += 1
        if keys[pygame.K_a]: 
            dx -= 1
        if keys[pygame.K_d]: 
            dx += 1
        
        if dx or dy:
            nx, ny = normalize(dx, dy)
            self.player.vx = nx * self.player.base_speed
            self.player.vy = ny * self.player.base_speed
        else:
            self.player.vx *= 0.8
            self.player.vy *= 0.8
        
        self._move_entity(self.player, dt)
        self.player.angle = math.atan2(world_my - self.player.y, world_mx - self.player.x)
        # Multiplayer sync
        if self.multiplayer and self.net_client and self.net_client.connected:
            self.net_client.send({
                "type": "state",
                "id": self.player_id,
                "x": self.player.x, "y": self.player.y,
                "vx": self.player.vx, "vy": self.player.vy,
                "angle": self.player.angle,
                "hp": self.player.hp
            })
        # Shooting
        self.player.last_shot += dt
        if (self.mouse_down or keys[pygame.K_SPACE]):
            bullets = self.player.shoot(world_mx, world_my)
            if bullets:
                self._play_gun_sound(self.player.gun.name)
                self.bullets.extend(bullets)
                # Send bullets to server so other clients can render
                if self.multiplayer and self.net_client and self.net_client.connected:
                    for b in bullets:
                        self.net_client.send({
                            "type": "shoot",
                            "id": self.player_id,
                            "x": b.x, "y": b.y,
                            "vx": b.vx, "vy": b.vy,
                            "dmg": b.dmg
                        })
        
        # Update timers
        if self.player.is_reloading:
            self.player.reload_timer -= dt
            if self.player.reload_timer <= 0:
                if self.player.gun:
                    self.player.mag[self.player.equipped] = self.player.gun.mag
                self.player.is_reloading = False
        
        if self.player.is_using_medkit:
            self.player.medkit_timer -= dt
            if self.player.medkit_timer <= 0:
                self.player.is_using_medkit = False
                self.player.hp = clamp(self.player.hp + MEDKIT_HEAL, 0, PLAYER_MAX_HP)
        
        # Update bullets
        for bullet in self.bullets[:]:
            bullet.x += bullet.vx * dt
            bullet.y += bullet.vy * dt
            bullet.life -= dt
            
            if (bullet.life <= 0 or bullet.x < 0 or bullet.y < 0 or 
                bullet.x > MAP_W or bullet.y > MAP_H or
                any(obs.collidepoint(bullet.x, bullet.y) for obs in self.obstacles)):
                self.bullets.remove(bullet)
                continue
            
            # Bullet collisions
            if bullet.owner == 'player':
                for bot in self.bots:
                    if not bot.dead and length(bot.x - bullet.x, bot.y - bullet.y) < bot.r + 6:
                        bot.hp -= bullet.dmg
                        self.bullets.remove(bullet)
                        if bot.hp <= 0:
                            bot.dead = True
                            self.player.kills += 1
                        break
                # Check hits on remote players in multiplayer
                if self.multiplayer:
                    hit_sent = False
                    for rp in list(self.remote_players.values()):
                        if rp.dead:
                            continue
                        if length(rp.x - bullet.x, rp.y - bullet.y) < rp.r + 6:
                            # Notify server of hit
                            if self.net_client and self.net_client.connected:
                                self.net_client.send({
                                    "type": "hit",
                                    "target_id": rp.id,
                                    "dmg": bullet.dmg
                                })
                            if bullet in self.bullets:
                                self.bullets.remove(bullet)
                            hit_sent = True
                            break
                    if hit_sent:
                        continue
            elif bullet.owner == 'bot':
                if length(self.player.x - bullet.x, self.player.y - bullet.y) < self.player.r + 6:
                    damage = bullet.dmg
                    if self.player.shield_active:
                        damage = int(damage * 0.4)
                    self.player.hp -= damage
                    self.flash_alpha = 160
                    if 'hit' in self.sounds:
                        self.sounds['hit'].play()
                    self.bullets.remove(bullet)
                    if self.player.hp <= 0:
                        self.player.dead = True
                        # Inform server of death in multiplayer
                        if self.multiplayer and self.net_client and self.net_client.connected:
                            self.net_client.send({"type": "dead", "id": self.player_id})
            elif bullet.owner == 'remote':
                # Remote bullets can hit the local player
                if length(self.player.x - bullet.x, self.player.y - bullet.y) < self.player.r + 6:
                    damage = bullet.dmg
                    if self.player.shield_active:
                        damage = int(damage * 0.4)
                    self.player.hp -= damage
                    self.flash_alpha = 160
                    if 'hit' in self.sounds:
                        self.sounds['hit'].play()
                    if bullet in self.bullets:
                        self.bullets.remove(bullet)
                    if self.player.hp <= 0:
                        self.player.dead = True
                        if self.multiplayer and self.net_client and self.net_client.connected:
                            self.net_client.send({"type": "dead", "id": self.player_id})
        
        # Update bots (singleplayer only)
        if not self.multiplayer:
            alive_bots = 0
            for bot in self.bots:
                if not bot.dead:
                    alive_bots += 1
                    bot.update_ai(self, dt)
                    self._move_entity(bot, dt)
            
            if alive_bots == 0 and not self.victory:
                self.victory = True
                self.victory_time = time.time() - self.start_time
                if 'victory' in self.sounds:
                        self.sounds['victory'].play()
        
        # Update powerup animations
        for powerup in self.powerups:
            if not powerup['collected']:
                powerup['bob'] += dt * 3
        
        # Update camera
        self.camera.centerx = clamp(self.player.x, SCREEN_W//2, MAP_W - SCREEN_W//2)
        self.camera.centery = clamp(self.player.y, SCREEN_H//2, MAP_H - SCREEN_H//2)

    def _move_entity(self, ent, dt):
        if hasattr(self.player, 'ghost_mode') and self.player.ghost_mode and ent == self.player:
            # Ghost mode - can pass through obstacles
            ent.x = clamp(ent.x + ent.vx * dt, ent.r, MAP_W - ent.r)
            ent.y = clamp(ent.y + ent.vy * dt, ent.r, MAP_H - ent.r)
            return
        
        nx = clamp(ent.x + ent.vx * dt, ent.r, MAP_W - ent.r)
        ny = clamp(ent.y + ent.vy * dt, ent.r, MAP_H - ent.r)
        
        future = pygame.Rect(nx-ent.r, ny-ent.r, ent.r*2, ent.r*2)
        if not any(future.colliderect(obs) for obs in self.obstacles):
            ent.x, ent.y = nx, ny
        else:
            # Try X movement only
            futurex = pygame.Rect(nx-ent.r, ent.y-ent.r, ent.r*2, ent.r*2)
            if not any(futurex.colliderect(obs) for obs in self.obstacles):
                ent.x = nx
            # Try Y movement only
            futurey = pygame.Rect(ent.x-ent.r, ny-ent.r, ent.r*2, ent.r*2)
            if not any(futurey.colliderect(obs) for obs in self.obstacles):
                ent.y = ny

    #Gun sound effects
    def _play_gun_sound(self, gun_name):
        sound_name = gun_name.lower()
        if sound_name in self.sounds:
            self.sounds[sound_name].play()

    def handle_events(self):
        for event in pygame.event.get():
            if event.type == pygame.QUIT:
                return "quit"
            elif event.type == pygame.MOUSEBUTTONDOWN and event.button == 1:
                self.mouse_down = True
            elif event.type == pygame.MOUSEBUTTONUP and event.button == 1:
                self.mouse_down = False
            elif event.type == pygame.KEYDOWN:
                if event.key == pygame.K_r:
                    if (self.player.gun and not self.player.is_reloading and 
                        self.player.mag[self.player.equipped] < self.player.gun.mag):
                        self.player.is_reloading = True
                        self.player.reload_timer = self.player.gun.reload_time
                        if 'reload' in self.sounds:
                            self.sounds['reload'].play()
                elif event.key == pygame.K_e:
                    self._interact_chest()
                elif event.key == pygame.K_f:
                    self._collect_powerup()
                elif event.key == pygame.K_q:
                    if (self.player.medkits > 0 and not self.player.is_using_medkit and 
                        self.player.hp < PLAYER_MAX_HP):
                        self.player.is_using_medkit = True
                        self.player.medkit_timer = MEDKIT_USE_TIME
                        self.player.medkits -= 1
                elif event.key == pygame.K_1:
                    self.player.equipped = 0
                elif event.key == pygame.K_2:
                    self.player.equipped = 1
                elif event.key == pygame.K_TAB:
                    self.show_minimap = not self.show_minimap
                elif event.key == pygame.K_l and self.player.dead:
                    # Respawn in multiplayer, restart in singleplayer
                    if self.multiplayer and self.net_client and self.net_client.connected:
                        self.player.hp = PLAYER_MAX_HP
                        self.player.dead = False
                        self.net_client.send({
                            "type": "respawn",
                            "id": self.player_id,
                            "x": MAP_W/2, "y": MAP_H/2,
                            "hp": self.player.hp
                        })
                        return "playing"
                    return "restart"
                elif event.key == pygame.K_RETURN and self.victory:
                    return "restart"
                elif event.key == pygame.K_ESCAPE:
                    return "menu"
        return "playing"

    #Chest Interactions
    def _interact_chest(self):
        for chest in self.chests:
            if not chest['opened'] and length(chest['x'] - self.player.x, chest['y'] - self.player.y) < 48:
                chest['opened'] = True
                if chest['contents'] == 'medkit':
                    if self.player.medkits < MAX_MEDKITS:
                        self.player.medkits += 1
                else:
                    # Pick up weapon
                    gun = GUN_TYPES[chest['contents']]
                    for i in range(MAX_WEAPON_SLOTS):
                        if self.player.inventory[i] is None:
                            self.player.inventory[i] = gun
                            self.player.mag[i] = gun.mag
                            self.player.equipped = i
                            return
                    # Replace current weapon
                    self.player.inventory[self.player.equipped] = gun
                    self.player.mag[self.player.equipped] = gun.mag
                return


    #Powerup Interaction
    def _collect_powerup(self):
        for powerup in self.powerups:
            if not powerup['collected'] and length(powerup['x'] - self.player.x, powerup['y'] - self.player.y) < 35:
                powerup['collected'] = True
                self.player.add_powerup(powerup['type'])
                return

    def draw(self):
        # Clear screen
        self.screen.fill((92, 150, 82))
        
        # Draw obstacles
        for obs in self.obstacles:
            rect = pygame.Rect(obs.x - self.camera.x, obs.y - self.camera.y, obs.width, obs.height)
            pygame.draw.rect(self.screen, (90,90,90), rect)
            pygame.draw.rect(self.screen, (60,60,60), rect, 2)
        
        # Draw chests
        for chest in self.chests:
            if chest['opened']: 
                continue
            x, y = int(chest['x'] - self.camera.x), int(chest['y'] - self.camera.y)
            if 'chest' in self.assets:
                img = self.assets['chest']
                self.screen.blit(img, (x - img.get_width()//2, y - img.get_height()//2))
            else:
                pygame.draw.rect(self.screen, (160,110,50), (x-16, y-12, 32, 24))
        
        # Draw powerups
        for powerup in self.powerups:
            if powerup['collected']: 
                continue
            ptype = POWERUP_TYPES[powerup['type']]
            x = int(powerup['x'] - self.camera.x)
            y = int(powerup['y'] - self.camera.y + math.sin(powerup['bob']) * 4)
            pygame.draw.circle(self.screen, ptype['color'], (x, y), 15)
            pygame.draw.circle(self.screen, WHITE, (x, y), 15, 2)
            # Draw icon letter
            letter = powerup['type'][0].upper()
            font_surf = self.font.render(letter, True, WHITE)
            self.screen.blit(font_surf, (x - font_surf.get_width()//2, y - font_surf.get_height()//2))
        
        # Draw bots
        for bot in self.bots:
            if bot.dead: 
                continue
            x, y = int(bot.x - self.camera.x), int(bot.y - self.camera.y)
            pygame.draw.circle(self.screen, (180,60,60), (x, y), bot.r)
            # Health bar
            hp_pct = bot.hp / BOT_HP
            pygame.draw.rect(self.screen, (20,20,20), (x-20, y-bot.r-12, 40, 6))
            pygame.draw.rect(self.screen, (40,200,40), (x-20, y-bot.r-12, int(40*hp_pct), 6))
        
        # Draw bullets
        for bullet in self.bullets:
            x, y = int(bullet.x - self.camera.x), int(bullet.y - self.camera.y)
            color = (240,220,80) if bullet.owner == 'player' else (220,120,80)
            pygame.draw.circle(self.screen, color, (x, y), bullet.r)
        
        # Draw player
        px, py = int(self.player.x - self.camera.x), int(self.player.y - self.camera.y)


        # Remote players
        for rp in self.remote_players.values():
            if rp.dead: 
                continue
            rx, ry = int(rp.x - self.camera.x), int(rp.y - self.camera.y)
            pygame.draw.circle(self.screen, rp.color, (rx, ry), rp.r)
            # direction line
            ax = rx + math.cos(rp.angle) * (rp.r + 12)
            ay = ry + math.sin(rp.angle) * (rp.r + 12)
            pygame.draw.line(self.screen, (250,250,100), (rx, ry), (ax, ay), 3)
            # name tag
            name_surf = self.font.render(rp.name, True, WHITE)
            self.screen.blit(name_surf, (rx - name_surf.get_width()//2, ry - rp.r - 18))
            
        # Player color based on powerups
        player_color = BLUE
        if self.player.shield_active:
            player_color = PURPLE
        elif self.player.ghost_mode:
            player_color = PINK
        elif self.player.regen_active:
            player_color = GREEN
        
        if 'player' in self.assets:
            img = self.assets['player']
            self.screen.blit(img, (px - img.get_width()//2, py - img.get_height()//2))
        else:
            pygame.draw.circle(self.screen, player_color, (px, py), self.player.r)
        
        # Visual effects for powerups
        if self.player.shield_active:
            pygame.draw.circle(self.screen, PURPLE, (px, py), self.player.r + 8, 3)
        if self.player.ghost_mode:
            # Draw translucent effect
            s = pygame.Surface((self.player.r*4, self.player.r*4))
            s.set_alpha(100)
            s.fill(PINK)
            self.screen.blit(s, (px - self.player.r*2, py - self.player.r*2))
        
        # Aiming line
        ax = px + math.cos(self.player.angle) * (self.player.r + 12)
        ay = py + math.sin(self.player.angle) * (self.player.r + 12)
        pygame.draw.line(self.screen, (220,220,220), (px, py), (ax, ay), 4)
        
        # Draw UI
        self._draw_ui()
        
        # Minimap
        if self.show_minimap:
            self._draw_minimap()
        
        # Victory screen
        if self.victory:
            overlay = pygame.Surface((SCREEN_W, SCREEN_H), pygame.SRCALPHA)
            overlay.fill((0,0,0,160))
            self.screen.blit(overlay, (0,0))
            
            txt = self.bigfont.render("VICTORY!", True, YELLOW)
            self.screen.blit(txt, (SCREEN_W//2 - txt.get_width()//2, SCREEN_H//2 - 80))
            
            if not self.multiplayer:
                info = self.font.render(f"Kills: {self.player.kills} Time: {self.victory_time:.1f}s", True, WHITE)
            else:
                info = self.font.render("Match Complete!", True, WHITE)
            self.screen.blit(info, (SCREEN_W//2 - info.get_width()//2, SCREEN_H//2))
            
            restart_txt = self.font.render("Press Enter to restart", True, WHITE)
            self.screen.blit(restart_txt, (SCREEN_W//2 - restart_txt.get_width()//2, SCREEN_H//2 + 30))
        
        # Flash effect
        if self.flash_alpha > 0:
            flash = pygame.Surface((SCREEN_W, SCREEN_H))
            flash.set_alpha(int(self.flash_alpha))
            flash.fill((255,0,0))
            self.screen.blit(flash, (0,0))
            self.flash_alpha = max(0, self.flash_alpha - 8)
        
        pygame.display.flip()

    def _draw_ui(self):
        # Health
        hp_text = self.font.render(f"HP: {int(self.player.hp)}", True, WHITE)
        self.screen.blit(hp_text, (12, 12))
        
        # Weapon slots
        slot_size = 64
        base_x = SCREEN_W//2 - (MAX_WEAPON_SLOTS * slot_size // 2)
        y = SCREEN_H - slot_size - 20
        
        for i in range(MAX_WEAPON_SLOTS):
            x = base_x + i * slot_size
            
            # Slot background
            color = (255,255,100) if i == self.player.equipped else (200,200,200)
            pygame.draw.rect(self.screen, color, (x, y, slot_size, slot_size), 3)
            
            gun = self.player.inventory[i]
            if gun:
                # Gun icon or name
                if gun.name in self.assets:
                    img = self.assets[gun.name]
                    self.screen.blit(img, (x + 4, y + 4))
                else:
                    gun_text = self.font.render(gun.name[0], True, BLACK)
                    self.screen.blit(gun_text, (x + 20, y + 20))
                
                # Ammo count
                ammo_text = self.font.render(f"{self.player.mag[i]}/{gun.mag}", True, WHITE)
                self.screen.blit(ammo_text, (x + 4, y + slot_size - 16))
            else:
                empty_text = self.font.render("Empty", True, GRAY)
                self.screen.blit(empty_text, (x + 8, y + 24))
            
            # Slot number
            num_text = self.font.render(str(i + 1), True, WHITE)
            self.screen.blit(num_text, (x + slot_size - 16, y + slot_size - 16))
        
        # Medkits
        medkit_text = self.font.render(f"Medkits: {self.player.medkits}", True, WHITE)
        self.screen.blit(medkit_text, (12, 36))
        
        # Medkit progress bar
        if self.player.is_using_medkit:
            progress = clamp(1 - (self.player.medkit_timer / MEDKIT_USE_TIME), 0, 1)
            pygame.draw.rect(self.screen, (30,30,30), (12, 60, 200, 12))
            pygame.draw.rect(self.screen, (100,255,100), (12, 60, int(200 * progress), 12))
        
        # Active powerups
        y_offset = 90
        for i, powerup in enumerate(self.player.active_powerups):
            ptype = POWERUP_TYPES[powerup['type']]
            
            # Powerup icon
            icon_rect = pygame.Rect(12, y_offset + i * 28, 20, 20)
            pygame.draw.rect(self.screen, ptype['color'], icon_rect)
            pygame.draw.rect(self.screen, WHITE, icon_rect, 2)
            
            # Timer bar
            timer_progress = powerup['time_left'] / ptype['duration']
            timer_width = 120
            pygame.draw.rect(self.screen, (30,30,30), (40, y_offset + i * 28 + 6, timer_width, 8))
            pygame.draw.rect(self.screen, ptype['color'], (40, y_offset + i * 28 + 6, int(timer_width * timer_progress), 8))
                
            # Text
            text = self.font.render(f"{ptype['name']}: {powerup['time_left']:.1f}s", True, WHITE)
            self.screen.blit(text, (170, y_offset + i * 28))
        
        # Controls hint
        hint = self.font.render("WASD:Move | 1/2:Switch | R:Reload | Q:Medkit | E:Chest | F:Powerup", True, WHITE)
        self.screen.blit(hint, (12, SCREEN_H - 24))
        
        # Current weapon info
        if self.player.gun:
            gun_info = self.font.render(f"{self.player.gun.name} | {self.player.mag[self.player.equipped]}/{self.player.gun.mag}", True, WHITE)
            self.screen.blit(gun_info, (12, SCREEN_H - 48))

    def _draw_minimap(self):
        mm_size = (240, 180)
        mm_surf = pygame.Surface(mm_size)
        mm_surf.fill((20,20,20))
        
        scale_x, scale_y = mm_size[0] / MAP_W, mm_size[1] / MAP_H
        
        # Draw obstacles
        for obs in self.obstacles:
            rect = pygame.Rect(int(obs.x * scale_x), int(obs.y * scale_y), 
                             max(1, int(obs.width * scale_x)), max(1, int(obs.height * scale_y)))
            pygame.draw.rect(mm_surf, (80,80,80), rect)
        
        # Draw chests
        for chest in self.chests:
            if not chest['opened']:
                x, y = int(chest['x'] * scale_x), int(chest['y'] * scale_y)
                pygame.draw.circle(mm_surf, (180,140,60), (x, y), 2)
        
        # Draw powerups
        for powerup in self.powerups:
            if not powerup['collected']:
                x, y = int(powerup['x'] * scale_x), int(powerup['y'] * scale_y)
                pygame.draw.circle(mm_surf, POWERUP_TYPES[powerup['type']]['color'], (x, y), 2)
        
        # Draw bots
        for bot in self.bots:
            if not bot.dead:
                x, y = int(bot.x * scale_x), int(bot.y * scale_y)
                pygame.draw.circle(mm_surf, (200,80,80), (x, y), 2)
        
        # Draw player
        px, py = int(self.player.x * scale_x), int(self.player.y * scale_y)
        pygame.draw.circle(mm_surf, (80,140,220), (px, py), 3)
        
        # Blit to main screen
        self.screen.blit(mm_surf, (SCREEN_W - mm_size[0] - 12, 12))

    def run(self):
        running = True
        while running:
            dt = self.clock.tick(FPS) / 1000.0
            
            result = self.handle_events()
            if result == "quit":
                running = False
            elif result == "restart":
                self.__init__(self.multiplayer)
                continue
            elif result == "menu":
                running = False
            
            self.update(dt)
            self.draw()
        
        if self.net_client:
            self.net_client.close()
        pygame.quit()

#Menu Initialization
class MainMenu:
    def __init__(self):
        pygame.init()
        self.screen = pygame.display.set_mode((SCREEN_W, SCREEN_H))
        pygame.display.set_caption("Zombs v3 - Enhanced")
        self.clock = pygame.time.Clock()
        self.font = pygame.font.SysFont("Consolas", 24)
        self.big_font = pygame.font.SysFont("Consolas", 48)
        self.choice = 0
        
    def run(self):
        while True:
            dt = self.clock.tick(FPS) / 1000.0
            
            for event in pygame.event.get():
                if event.type == pygame.QUIT:
                    pygame.quit()
                    sys.exit()
                elif event.type == pygame.KEYDOWN:
                    if event.key == pygame.K_UP:
                        self.choice = (self.choice - 1) % 3
                    elif event.key == pygame.K_DOWN:
                        self.choice = (self.choice + 1) % 3
                    elif event.key == pygame.K_RETURN:
                        if self.choice == 0:  # Singleplayer
                            game = Game(multiplayer=False)
                            game.run()
                        elif self.choice == 1:  # Multiplayer
                            game = Game(multiplayer=True)
                            if game.connect_to_server():
                                game.run()
                            else:
                                print("Failed to connect to server")
                        elif self.choice == 2:  # Quit
                            pygame.quit()
                            sys.exit()
                elif event.type == pygame.MOUSEMOTION:
                    mx, my = event.pos
                    # Check which button mouse is over
                    for i in range(3):
                        rect = pygame.Rect(SCREEN_W//2 - 150, 300 + i * 80, 300, 60)
                        if rect.collidepoint(mx, my):
                            self.choice = i
                elif event.type == pygame.MOUSEBUTTONDOWN and event.button == 1:
                    mx, my = event.pos
                    for i in range(3):
                        rect = pygame.Rect(SCREEN_W//2 - 150, 300 + i * 80, 300, 60)
                        if rect.collidepoint(mx, my):
                            if i == 0:  # Singleplayer
                                game = Game(multiplayer=False)
                                game.run()
                            elif i == 1:  # Multiplayer
                                game = Game(multiplayer=True)
                                if game.connect_to_server():
                                    game.run()
                                else:
                                    print("Failed to connect to server")
                            elif i == 2:  # Quit
                                pygame.quit()
                                sys.exit()
                        
            # Draw menu
            self.screen.fill((40, 60, 80))
            
            # Animated background
            for i in range(50):
                x = (time.time() * 40 + i * 127) % SCREEN_W
                y = (i * 71) % SCREEN_H
                pygame.draw.circle(self.screen, (60, 80, 100), (int(x), int(y)), 3)
            
            # Title
            title = self.big_font.render("ShootOut™", True, WHITE)
            self.screen.blit(title, (SCREEN_W//2 - title.get_width()//2, 150))
            
            # Subtitle
            subtitle = self.font.render("Made by Archit Das ©2025", True, RED)
            self.screen.blit(subtitle, (SCREEN_W//2 - subtitle.get_width()//2, 200))

            
            # Menu buttons
            options = ["Singleplayer", "Multiplayer", "Quit"]
            for i, option in enumerate(options):
                rect = pygame.Rect(SCREEN_W//2 - 150, 300 + i * 80, 300, 60)
                color = (100, 150, 200) if i == self.choice else (60, 90, 120)
                pygame.draw.rect(self.screen, color, rect, border_radius=15)
                pygame.draw.rect(self.screen, WHITE, rect, 3, border_radius=15)
                
                text = self.font.render(option, True, WHITE)
                text_rect = text.get_rect(center=rect.center)
                self.screen.blit(text, text_rect)
            
            # Instructions
            instructions = [
                "Arrow keys or mouse to navigate",
                "Enter or click to select",
                "E to Open Chests, F to use powerups, R to Reload, Q to use Medkits",
                "TAB to toggle minimap, L to Respawn after death",
                "|LORE|",
                "In the age before the war, peace was fragile.",
                "When resources dwindled, chaos took over.",
                "Now only the brave fight for survival."

            ]

            for i, instruction in enumerate(instructions):
                text = self.font.render(instruction, True, (200, 200, 200))
                self.screen.blit(text, (SCREEN_W//2 - text.get_width()//2, SCREEN_H - 200 + i * 25))
            
            pygame.display.flip()

if __name__ == "__main__":
    MainMenu().run()
