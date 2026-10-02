import math, random, time, threading, uuid, traceback, os, re
from flask import Flask, request, send_from_directory
from flask_socketio import SocketIO
import config as C

PROJECT_FOLDER = os.path.dirname(os.path.abspath(__file__))
PAGE_FOLDER = PROJECT_FOLDER if os.path.exists(os.path.join(PROJECT_FOLDER, "index.html")) else os.path.join(PROJECT_FOLDER, "templates")
app = Flask(__name__)
socketio = SocketIO(app, async_mode="threading", cors_allowed_origins="*")

ARENA_WIDTH, ARENA_HEIGHT, PLAYER_RADIUS, SECONDS_PER_TICK = C.WIDTH, C.HEIGHT, C.PLAYER_RADIUS, 1 / C.TICK_RATE
state_lock = threading.RLock()
players, bullets = {}, []
match = {"score": [0, 0], "winner": -1, "result_screen_until": 0, "ends_at": 0}
ARENA_WALLS = sorted({*C.BASE_WALLS, *[(ARENA_WIDTH - x - w, ARENA_HEIGHT - y - h, w, h) for x, y, w, h in C.BASE_WALLS]})


def is_point_inside_any_wall(x, y, padding=0):
    return any(wx - padding < x < wx + ww + padding and wy - padding < y < wy + wh + padding
               for wx, wy, ww, wh in ARENA_WALLS)


def count_human_players_per_team():
    return [sum(1 for p in players.values() if not p["is_bot"] and p["team"] == team) for team in (0, 1)]


def build_lobby_info():
    return {"teams": count_human_players_per_team(), "max_team": C.MAX_TEAM_SIZE, "max": C.MAX_PLAYERS,
            "names": C.TEAM_NAMES, "max_name": C.MAX_NAME_LEN}


def make_unique_player_name(raw_name):
    base_name = re.sub(r"[^A-Za-z0-9 _-]", "", str(raw_name or "")).strip()[:C.MAX_NAME_LEN] or "Player"
    taken_names = {p["name"].lower() for p in players.values()}
    candidate, suffix_number = base_name, 1
    while candidate.lower() in taken_names:
        suffix_number += 1
        candidate = base_name[:C.MAX_NAME_LEN - len(str(suffix_number))] + str(suffix_number)
    return candidate


def create_player(name, team, is_bot=False):
    return {"name": make_unique_player_name(name), "team": team, "is_bot": is_bot, "kills": 0, "deaths": 0,
            "aim_angle": 0.0, "move_direction": (1, 0), "next_shot_time": 0, "dash_ready_time": 0,
            "respawn_time": 0, "last_input_time": 0, "invulnerable_until": 0, "shots_fired": 0, "shots_hit": 0}


def place_player_at_spawn_point(player, now):
    for _ in range(40):
        x = random.randint(90, 230) if player["team"] == 0 else random.randint(ARENA_WIDTH - 230, ARENA_WIDTH - 90)
        y = random.randint(90, ARENA_HEIGHT - 90)
        if not is_point_inside_any_wall(x, y, PLAYER_RADIUS):
            break
    player.update(x=x, y=y, health=C.MAX_HP, is_dead=False, dash_end_time=0, held_keys={}, is_firing=False,
                  invulnerable_until=now + C.SPAWN_PROTECT)


def fill_teams_with_bots():
    human_counts = count_human_players_per_team()
    for team in (0, 1):
        team_bot_keys = [key for key, p in players.items() if p["is_bot"] and p["team"] == team]
        wanted_bot_count = max(0, C.BOTS_PER_TEAM - human_counts[team])
        for key in team_bot_keys[wanted_bot_count:]:
            del players[key]
        for _ in range(wanted_bot_count - len(team_bot_keys)):
            bot = create_player(random.choice(C.BOT_NAMES), team, True)
            players["bot-" + uuid.uuid4().hex[:6]] = bot
            place_player_at_spawn_point(bot, time.time())


def push_player_out_of_walls_and_bounds(player):
    player["x"] = min(max(player["x"], PLAYER_RADIUS), ARENA_WIDTH - PLAYER_RADIUS)
    player["y"] = min(max(player["y"], PLAYER_RADIUS), ARENA_HEIGHT - PLAYER_RADIUS)
    for wall_x, wall_y, wall_width, wall_height in ARENA_WALLS:
        closest_x = min(max(player["x"], wall_x), wall_x + wall_width)
        closest_y = min(max(player["y"], wall_y), wall_y + wall_height)
        offset_x, offset_y = player["x"] - closest_x, player["y"] - closest_y
        distance = math.hypot(offset_x, offset_y)
        if distance < PLAYER_RADIUS:
            if distance == 0:
                player["y"] -= PLAYER_RADIUS
            else:
                player["x"] += offset_x / distance * (PLAYER_RADIUS - distance)
                player["y"] += offset_y / distance * (PLAYER_RADIUS - distance)


def finish_match(winning_team, now):
    match["winner"], match["result_screen_until"] = winning_team, now + C.GAME_OVER_SECONDS


def handle_player_death(victim, killer, now):
    victim["is_dead"], victim["respawn_time"], victim["deaths"] = True, now + C.RESPAWN, victim["deaths"] + 1
    if not killer:
        return
    killer["kills"] += 1
    match["score"][killer["team"]] += 1
    socketio.emit("feed", {"k": killer["name"], "kt": killer["team"], "v": victim["name"], "vt": victim["team"]})
    if match["score"][killer["team"]] >= C.WIN_KILLS:
        finish_match(killer["team"], now)


def start_new_match(now):
    match.update(score=[0, 0], winner=-1, ends_at=now + C.MATCH_TIME)
    bullets.clear()
    for player in players.values():
        player.update(kills=0, deaths=0, shots_fired=0, shots_hit=0)
        place_player_at_spawn_point(player, now)


def start_dash_if_ready(player, now):
    if not player["is_dead"] and now >= player["dash_ready_time"]:
        player["dash_end_time"], player["dash_ready_time"] = now + C.DASH_TIME, now + C.DASH_CD


def has_clear_line_of_sight(from_x, from_y, to_x, to_y):
    sample_count = int(math.hypot(to_x - from_x, to_y - from_y) // 24) + 1
    return not any(is_point_inside_any_wall(from_x + (to_x - from_x) * i / sample_count,
                                            from_y + (to_y - from_y) * i / sample_count)
                   for i in range(1, sample_count))


def update_bot_decision(bot, now):
    enemies = [p for p in players.values() if p["team"] != bot["team"] and not p["is_dead"]]
    if not enemies:
        bot["held_keys"], bot["is_firing"] = {}, False
        return
    target = min(enemies, key=lambda p: (p["x"] - bot["x"]) ** 2 + (p["y"] - bot["y"]) ** 2)
    offset_x, offset_y = target["x"] - bot["x"], target["y"] - bot["y"]
    distance = math.hypot(offset_x, offset_y) or 1
    if now > bot.get("strafe_change_time", 0):
        bot["strafe_change_time"], bot["strafe_side"] = now + random.uniform(.6, 1.4), random.choice((-1, 1))
    can_see_target = distance < C.BOT_RANGE and has_clear_line_of_sight(bot["x"], bot["y"], target["x"], target["y"])
    approach_factor = 1 if not can_see_target or distance > C.BOT_KEEP_DIST + 80 else -1 if distance < C.BOT_KEEP_DIST - 80 else 0
    direction_x, direction_y, strafe_strength = offset_x / distance, offset_y / distance, bot["strafe_side"] * .8
    wanted_x = direction_x * approach_factor - direction_y * strafe_strength
    wanted_y = direction_y * approach_factor + direction_x * strafe_strength
    bot["held_keys"] = {"l": int(wanted_x < -.3), "r": int(wanted_x > .3), "u": int(wanted_y < -.3), "d": int(wanted_y > .3)}
    bot["aim_angle"] = math.atan2(offset_y, offset_x) + random.gauss(0, C.BOT_AIM_ERROR)
    bot["is_firing"] = can_see_target
    if can_see_target and distance > 400 and random.random() < .004:
        start_dash_if_ready(bot, now)


def advance_players(seconds_elapsed, now, match_is_live):
    for player in players.values():
        if player["is_dead"]:
            if match_is_live and now >= player["respawn_time"]:
                place_player_at_spawn_point(player, now)
            continue
        if player["is_bot"]:
            update_bot_decision(player, now)
        keys = player["held_keys"] if match_is_live else {}
        move_x, move_y = keys.get("r", 0) - keys.get("l", 0), keys.get("d", 0) - keys.get("u", 0)
        move_length = math.hypot(move_x, move_y)
        if move_length:
            move_x, move_y = move_x / move_length, move_y / move_length
            player["move_direction"] = (move_x, move_y)
        speed = C.SPEED
        if match_is_live and now < player["dash_end_time"]:
            (move_x, move_y), speed = player["move_direction"], C.DASH_SPEED
        player["x"] += move_x * speed * seconds_elapsed
        player["y"] += move_y * speed * seconds_elapsed
        push_player_out_of_walls_and_bounds(player)
        if player["is_firing"] and match_is_live and now >= player["next_shot_time"] and len(bullets) < C.MAX_BULLETS:
            player["shots_fired"] += 1
            angle = player["aim_angle"]
            player["next_shot_time"] = now + C.FIRE_GAP * (C.BOT_FIRE_SLOW if player["is_bot"] else 1)
            bullets.append({"x": player["x"] + math.cos(angle) * 24, "y": player["y"] + math.sin(angle) * 24,
                            "angle": angle, "team": player["team"], "owner_name": player["name"],
                            "expires_at": now + C.BULLET_LIFE})


def advance_bullets(seconds_elapsed, now):
    surviving_bullets = []
    for bullet in bullets:
        bullet["x"] += math.cos(bullet["angle"]) * C.BULLET_SPEED * seconds_elapsed
        bullet["y"] += math.sin(bullet["angle"]) * C.BULLET_SPEED * seconds_elapsed
        left_arena = not (0 < bullet["x"] < ARENA_WIDTH and 0 < bullet["y"] < ARENA_HEIGHT)
        if now > bullet["expires_at"] or left_arena or is_point_inside_any_wall(bullet["x"], bullet["y"]):
            continue
        bullet_hit_someone = False
        if match["winner"] < 0:
            for victim in players.values():
                close_enough = math.hypot(victim["x"] - bullet["x"], victim["y"] - bullet["y"]) < PLAYER_RADIUS + 4
                if not victim["is_dead"] and victim["team"] != bullet["team"] and close_enough:
                    bullet_hit_someone = True
                    if now >= victim["invulnerable_until"]:
                        victim["health"] -= C.BULLET_DAMAGE
                        shooter = next((p for p in players.values() if p["name"] == bullet["owner_name"]), None)
                        if shooter:
                            shooter["shots_hit"] += 1
                        if victim["health"] <= 0:
                            handle_player_death(victim, shooter, now)
                    break
        if not bullet_hit_someone:
            surviving_bullets.append(bullet)
    bullets[:] = surviving_bullets


def broadcast_game_state(now):
    socketio.emit("s", {
        "p": [{"id": p["name"], "t": p["team"], "x": round(p["x"]), "y": round(p["y"]), "a": round(p["aim_angle"], 2),
               "hp": p["health"], "k": p["kills"], "d": p["deaths"], "dead": p["is_dead"], "bot": p["is_bot"],
               "sh": p["shots_fired"], "ht": p["shots_hit"], "inv": now < p["invulnerable_until"],
               "rs": round(max(0, p["respawn_time"] - now), 1) if p["is_dead"] else 0,
               "cd": round(max(0, p["dash_ready_time"] - now), 2)} for p in players.values()],
        "b": [[round(b["x"]), round(b["y"]), b["team"], round(b["angle"], 2)] for b in bullets],
        "sc": match["score"], "over": match["winner"], "t": max(0, math.ceil(match["ends_at"] - now)),
        "nx": max(0, math.ceil(match["result_screen_until"] - now)) if match["winner"] >= 0 else 0})


def advance_game_one_tick(seconds_elapsed, now):
    with state_lock:
        if all(p["is_bot"] for p in players.values()):
            return
        if match["winner"] >= 0 and now > match["result_screen_until"]:
            start_new_match(now)
        if match["winner"] < 0 and now >= match["ends_at"]:
            team_zero_score, team_one_score = match["score"]
            finish_match(0 if team_zero_score > team_one_score else 1 if team_one_score > team_zero_score else 2, now)
        advance_players(seconds_elapsed, now, match["winner"] < 0)
        advance_bullets(seconds_elapsed, now)
        broadcast_game_state(now)


def run_game_loop():
    previous_tick_time = time.time()
    while True:
        socketio.sleep(SECONDS_PER_TICK)
        now = time.time()
        seconds_elapsed, previous_tick_time = min(now - previous_tick_time, 0.1), now
        try:
            advance_game_one_tick(seconds_elapsed, now)
        except Exception:
            traceback.print_exc()


@app.route("/")
def serve_game_page():
    return send_from_directory(PAGE_FOLDER, "index.html", max_age=0)


@app.route("/graphics.json")
def serve_graphics_file():
    return send_from_directory(PROJECT_FOLDER, "graphics.json", mimetype="application/json", max_age=0)


@socketio.on("connect")
def send_lobby_info_to_new_connection():
    socketio.emit("lobby", build_lobby_info(), to=request.sid)


def remove_player_and_rebalance_bots(socket_id):
    if players.pop(socket_id, None):
        fill_teams_with_bots()
        socketio.emit("lobby", build_lobby_info())


@socketio.on("disconnect")
def handle_disconnect():
    with state_lock:
        remove_player_and_rebalance_bots(request.sid)


@socketio.on("leave")
def handle_leave_request():
    with state_lock:
        remove_player_and_rebalance_bots(request.sid)


@socketio.on("join")
def handle_join_request(join_data):
    socket_id = request.sid
    join_data = join_data if isinstance(join_data, dict) else {}

    def deny_join(reason):
        socketio.emit("denied", {"reason": reason}, to=socket_id)

    with state_lock:
        if socket_id in players:
            return
        human_counts = count_human_players_per_team()
        if sum(human_counts) >= C.MAX_PLAYERS:
            return deny_join(f"Server is full ({sum(human_counts)}/{C.MAX_PLAYERS} players). Try again later.")
        team = join_data.get("team")
        if team not in (0, 1):
            team = 0 if human_counts[0] <= human_counts[1] else 1
        other_team = 1 - team
        if human_counts[team] >= C.MAX_TEAM_SIZE:
            return deny_join(f"{C.TEAM_NAMES[team]} team is full ({human_counts[team]}/{C.MAX_TEAM_SIZE}).")
        if human_counts[team] - human_counts[other_team] >= C.MAX_TEAM_DIFF:
            return deny_join(f"{C.TEAM_NAMES[team]} has enough players - join {C.TEAM_NAMES[other_team]} to keep the teams fair.")
        is_first_human = sum(human_counts) == 0
        player = create_player(join_data.get("name"), team)
        players[socket_id] = player
        fill_teams_with_bots()
        if is_first_human:
            start_new_match(time.time())
        else:
            place_player_at_spawn_point(player, time.time())
        socketio.emit("hello", {"id": player["name"], "team": team, "w": ARENA_WIDTH, "h": ARENA_HEIGHT,
                                "walls": ARENA_WALLS, "names": C.TEAM_NAMES, "win": C.WIN_KILLS,
                                "dash_cd": C.DASH_CD}, to=socket_id)
        socketio.emit("lobby", build_lobby_info())


@socketio.on("input")
def handle_player_input(input_data):
    player, now = players.get(request.sid), time.time()
    if not player or not isinstance(input_data, dict) or now - player["last_input_time"] < 1 / C.MAX_INPUT_RATE:
        return
    try:
        pressed = input_data.get("k") if isinstance(input_data.get("k"), dict) else {}
        aim_angle = float(input_data.get("a", 0))
        if math.isfinite(aim_angle):
            player["held_keys"] = {key: 1 if pressed.get(key) else 0 for key in "lrud"}
            player["aim_angle"], player["is_firing"], player["last_input_time"] = aim_angle, bool(input_data.get("f")), now
    except (TypeError, ValueError):
        pass


@socketio.on("dash")
def handle_dash_request():
    player = players.get(request.sid)
    if player:
        start_dash_if_ready(player, time.time())


if __name__ == "__main__":
    socketio.start_background_task(run_game_loop)
    socketio.run(app, host=os.environ.get("HOST", C.HOST), port=int(os.environ.get("PORT", C.PORT)), allow_unsafe_werkzeug=True)
