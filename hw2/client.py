import asyncio
import json
import sys
import logging
import random
import time
import threading
import queue as queue_module
from functools import partial
import contextlib
import os

os.environ.setdefault("SDL_AUDIODRIVER", "dummy")

TEXT_MODE_CLIENT = os.environ.get("TEXT_MODE_CLIENT", "").lower() in ("1", "true", "yes")

try:
    import tkinter as tk  # Dedicated opponent window
except Exception:  # pragma: no cover - tkinter might be absent
    tk = None

# Tk windows are fragile outside the main thread (common on remote desktops), so opt-out by default.
ENABLE_TK_VIEWER = os.environ.get("ENABLE_TK_VIEWER", "").lower() in ("1", "true", "yes")
if not ENABLE_TK_VIEWER:
    tk = None

try:
    import pygame
except Exception:
    pygame = None
    TEXT_MODE_CLIENT = True

import utils as ut
import config
from config import tetris_server as tetris_server
import game

peer_info = {
    "role": None,
    "game_host": None,
    "game_port": None,
    "room_id": None,
}

COMMAND_ALIASES = {
    "REGISTER": ["REGISTER", "reg", "r", "register"],
    "LOGIN": ["LOGIN", "login"],
    "LOGOUT": ["LOGOUT", "logout"],
    "CREATE_ROOM": ["CREATE_ROOM", "create", "c"],
    "INVITE_PLAYER": ["INVITE_PLAYER", "invite", "i"],
    "EXIT": ["EXIT", "exit", "quit", "q"],
    "HELP": ["HELP", "help", "h"],
    "SHOW_STATUS": ["SHOW_STATUS", "status", "s"],
    "CHECK": ["CHECK", "check"],
    "ACCEPT": ["ACCEPT", "accept"],
    "DECLINE": ["DECLINE", "decline"],
    "JOIN": ["JOIN", "join"],
    "WATCH": ["WATCH", "watch", "spectate", "observe"]
}

COMMANDS = [
    "register <Username> <Password> - Register new account",
    "login <Username> <Password> - Log in",
    "logout - Log out",
    "create <Room Type (private or public)> - Create room",
    "join <Room ID> - Join a public room",
    "invite <Username> <Room ID> - Invite user to join room",
    "check - Check invites.",
    "accept <Inviter> <Room ID> - Accept invite from <Username> to join room <Room ID>",
    "decline <Inviter> <Room ID> - Decline invite from <Username> to join room <Room ID>",
    "watch <Room ID> - Watch an in-progress public room",
    "exit - Leave client",
    "help - Displays list of available commands",
    "status - Displays current status",
]

"""
For server
"""
username = None


def empty_board(width=10, height=20):
    return [[0 for _ in range(width)] for _ in range(height)]


def normalize_board(board, width=10, height=20):
    if not board:
        return empty_board(width, height)
    normalized = []
    for y in range(height):
        if y < len(board):
            row = list(board[y][:width])
            if len(row) < width:
                row.extend([0] * (width - len(row)))
        else:
            row = [0] * width
        normalized.append(row)
    return normalized


def decode_board_rle(board_rle, width=10, height=20):
    """
    Fallback decoder for older snapshots that only provide RLE.
    Assumes each digit maps to a single cell; repeated digits are handled
    by sending them individually (lossy but acceptable for fallback).
    """
    board = empty_board(width, height)
    if not board_rle:
        return board
    rows = board_rle.split("|")
    for y in range(min(height, len(rows))):
        row_data = []
        for ch in rows[y]:
            if ch.isdigit():
                row_data.append(int(ch))
            if len(row_data) >= width:
                break
        while len(row_data) < width:
            row_data.append(0)
        board[y] = row_data
    return board


def default_player_state():
    return {
        "board": empty_board(),
        "active": None,
        "hold": None,
        "next": [],
        "score": 0,
        "lines": 0,
    }


def rgb_to_hex(color):
    return "#{:02x}{:02x}{:02x}".format(*color)


class OpponentViewer(threading.Thread):
    def __init__(self, opponent_name):
        super().__init__(daemon=True)
        self.opponent_name = opponent_name
        self.queue = queue_module.Queue()
        self.state = default_player_state()
        self._running = True
        self.root = None
        self.canvas = None
        self.info_label = None
        self.cell = 24
        self.available = True

    def submit(self, state):
        if self._running:
            self.queue.put(state)

    def close(self):
        if self._running:
            self._running = False
            self.queue.put(None)

    def run(self):
        if tk is None:
            self.available = False
            return
        try:
            self.root = tk.Tk()
        except Exception as e:  # pragma: no cover
            logging.warning(f"Failed to initialize opponent viewer: {e}")
            self.available = False
            return
        self.root.title(f"Opponent: {self.opponent_name}")
        self.canvas = tk.Canvas(
            self.root,
            width=self.cell * 10,
            height=self.cell * 20,
            bg="#111111",
            highlightthickness=0
        )
        self.canvas.pack(padx=10, pady=10)
        self.info_label = tk.Label(self.root, text="", font=("Consolas", 12))
        self.info_label.pack(pady=(0, 10))
        self.root.protocol("WM_DELETE_WINDOW", self._on_close)
        self.root.after(50, self._pump_queue)
        self.root.mainloop()

    def _on_close(self):
        self._running = False
        if self.root is not None:
            self.root.destroy()

    def _pump_queue(self):
        if not self._running:
            return
        try:
            while True:
                update = self.queue.get_nowait()
                if update is None:
                    self._on_close()
                    return
                self.state = update
        except queue_module.Empty:
            pass
        self._render()
        self.root.after(50, self._pump_queue)

    def _render(self):
        board = normalize_board(self.state.get("board"))
        self.canvas.delete("all")
        for y in range(20):
            for x in range(10):
                color = BOARD_COLORS[board[y][x] % len(BOARD_COLORS)]
                fill = rgb_to_hex(color)
                self.canvas.create_rectangle(
                    x * self.cell,
                    y * self.cell,
                    (x + 1) * self.cell,
                    (y + 1) * self.cell,
                    fill=fill,
                    outline="#333333"
                )

        active = self.state.get("active")
        if active:
            shape = active.get("shape")
            shape_defs = game.TetrisGameLogic.SHAPES.get(shape)
            if shape_defs:
                rot = active.get("rot", 0) % len(shape_defs)
                coords = shape_defs[rot]
                for dx, dy in coords:
                    px = active.get("x", 0) + dx
                    py = active.get("y", 0) + dy
                    if 0 <= px < 10 and 0 <= py < 20:
                        self.canvas.create_rectangle(
                            px * self.cell,
                            py * self.cell,
                            (px + 1) * self.cell,
                            (py + 1) * self.cell,
                            outline="#ffffff",
                            width=2
                        )

        info_text = (
            f"Score: {self.state.get('score', 0)}  "
            f"Lines: {self.state.get('lines', 0)}  "
            f"Hold: {self.state.get('hold') or '-'}  "
            f"Next: {' '.join(self.state.get('next', [])) or '-'}"
        )
        self.info_label.config(text=info_text)


if tk is None:
    class OpponentViewer:  # type: ignore
        def __init__(self, *args, **kwargs):
            self.available = False

        def start(self):
            pass

        def submit(self, state):
            pass

        def close(self):
            pass
def draw_player_panel(surface, label, state, offset_x, offset_y, font, cell_size=24):
    board = normalize_board(state.get("board"))
    score = state.get("score", 0)
    lines = state.get("lines", 0)
    hold_piece = state.get("hold")
    next_pieces = state.get("next", [])
    active_piece = state.get("active")

    label_surface = font.render(f"{label} | Score: {score} | Lines: {lines}", True, (255, 255, 255))
    surface.blit(label_surface, (offset_x, offset_y - 30))

    # Draw board grid and filled cells
    for y in range(20):
        for x in range(10):
            color_idx = board[y][x]
            color = BOARD_COLORS[color_idx % len(BOARD_COLORS)]
            rect = pygame.Rect(offset_x + x * cell_size, offset_y + y * cell_size, cell_size - 2, cell_size - 2)
            pygame.draw.rect(surface, color, rect)
            pygame.draw.rect(surface, (40, 40, 40), rect, 1)

    # Overlay active piece
    if active_piece:
        shape = active_piece.get("shape")
        shape_defs = game.TetrisGameLogic.SHAPES.get(shape)
        if shape_defs:
            rot = active_piece.get("rot", 0) % len(shape_defs)
            coords = shape_defs[rot]
            color = PIECE_COLORS.get(shape, (255, 255, 255))
            for dx, dy in coords:
                px = active_piece.get("x", 0) + dx
                py = active_piece.get("y", 0) + dy
                if 0 <= px < 10 and 0 <= py < 20:
                    rect = pygame.Rect(offset_x + px * cell_size, offset_y + py * cell_size, cell_size - 2, cell_size - 2)
                    pygame.draw.rect(surface, color, rect)

    info_surface = font.render(f"Hold: {hold_piece or '-'} | Next: {' '.join(next_pieces) or '-'}", True, (200, 200, 200))
    surface.blit(info_surface, (offset_x, offset_y + 20 * cell_size + 10))

BOARD_COLORS = [
    (18, 18, 18),
    (0, 255, 255),
    (0, 0, 255),
    (255, 165, 0),
    (255, 255, 0),
    (0, 255, 0),
    (128, 0, 128),
    (255, 0, 0),
    (255, 105, 180),
]

PIECE_COLORS = {
    "I": (0, 255, 255),
    "O": (255, 255, 0),
    "T": (160, 0, 240),
    "S": (0, 255, 0),
    "Z": (255, 0, 0),
    "J": (0, 0, 255),
    "L": (255, 165, 0),
}

if pygame:
    INSTANT_ACTION_KEYS = {
        pygame.K_UP: "CW",
        pygame.K_x: "CW",
        pygame.K_z: "CCW",
        pygame.K_SPACE: "HARD_DROP",
        pygame.K_c: "HOLD",
    }
    
    REPEATABLE_KEYS = {
        pygame.K_LEFT: ("LEFT", 0.15),
        pygame.K_RIGHT: ("RIGHT", 0.15),
        pygame.K_DOWN: ("SOFT_DROP", 0.08),
    }
else:
    INSTANT_ACTION_KEYS = {}
    REPEATABLE_KEYS = {}


async def handle_server_messages(reader, writer, game_in_progress, logged_in):
    while True:
        try:
            # data = await reader.readline()
            message = await ut.unpack_message(reader)
            if message is None:
                async with tetris_server.rooms_lock:
                    for room in tetris_server.rooms:
                        if room['creator'] not in tetris_server.online_users:
                            del tetris_server.rooms[room['room_id']]
                print("\nServer has disconnected.")
                logging.info("Server has disconnected.")
                game_in_progress.value = False
                break

            try:
                message_json = json.loads(message)
                status = message_json.get("status")
                msg = message_json.get("message", "")

                if status == "success":
                    if msg.startswith("REGISTRATION_SUCCESS"):
                        print("\nRegistration successful, please log in.\n")
                    
                    elif msg.startswith("LOGIN_SUCCESS"):
                        print("\nYou have logged in successfully.\n")
                        logged_in.value = True
                    
                    elif msg.startswith("LOGOUT_SUCCESS"):
                        print("\nYou have logged out successfully.")
                        logged_in.value = False
                    
                    elif msg.startswith("CREATE_ROOM_SUCCESS"):
                        parts = msg.split()
                        room_id = parts[1]
                        print(f"\nRoom successfully created. The room ID is {room_id}.\n")
                    
                    elif msg.startswith("JOIN_ROOM_SUCCESS"):
                        parts = msg.split()
                        room_id = parts[1]
                        print(f"\nSuccessfully joined room {room_id}.\n")
                        
                    elif msg.startswith("INVITE_SENT"):
                        parts = msg.split()
                        target_username = parts[1]
                        print(f"\nYour invite for {target_username} has been sent.")
                    
                    elif msg.startswith("DECLINED_INVITE"):
                        parts = msg.split()
                        inviter = parts[0]
                        room_id = parts[1]
                        print(f"\nSuccessfully declined invite from {inviter} to room {room_id}.")

                elif status == "error":
                    print(f"\nError: {msg}\n")
                    
                elif status == "invite":
                    parts = msg.split()
                    inviter = parts[0]
                    room_id = parts[1]
                    print(f"You have been invited by {inviter} to join room {room_id}.")
                    print("Use the command \"accept <username> <room_id>\" to accept the invite, or use \"check\" to check your invites.")
                
                elif status == "invite_declined":
                    parts = msg.split()
                    sender = parts[0]
                    room_id = parts[1]
                    print(f"\nUser {sender} has declined your invite to room {room_id}.")
                    logging.info(f"User {sender} declined joining {room_id}.")

                elif status == "update":
                    update_type = message_json.get("type")
                    if update_type == "online_users":
                        online_users = message_json.get("data", [])
                        display_online_users(online_users)
                    elif update_type == "room_status":
                        room_id = message_json.get("room_id")
                        updated_status = message_json.get("status")
                        print(f"\nRoom {room_id} status updated as {updated_status}")

                elif status == "p2p_info":
                    peer_info["role"] = message_json.get("role")
                    peer_info["game_host"] = message_json.get("game_host")
                    peer_info["game_port"] = int(message_json.get("game_port"))
                    peer_info["room_id"] = message_json.get("room_id")
                    room_id = peer_info["room_id"]
                    host = peer_info["game_host"]
                    port = peer_info["game_port"]
                    print(f"\nRoom {room_id} ready. Connect to {host}:{port}.")
                    logging.info(f"Connecting to central game server {host}:{port} for room {room_id}")

                    game_in_progress.value = True
                    asyncio.create_task(initiate_game(game_in_progress, writer, room_id))
                
                elif status == "watch_info":
                    room_id = message_json.get("room_id")
                    host = message_json.get("game_host")
                    port = int(message_json.get("game_port"))
                    if not room_id or not host or not port:
                        print("\nUnable to watch room. Missing server info.")
                        logging.error(f"watch_info missing data: {message_json}")
                        continue
                    print(f"\nWatching room {room_id}. Connect to {host}:{port}.")
                    logging.info(f"Watching central game server {host}:{port} for room {room_id}")
                    game_in_progress.value = True
                    asyncio.create_task(initiate_watch(game_in_progress, writer, room_id, host, port))

                elif status == "status":
                    print(f"\n{msg}")

                else:
                    print(f"\nServer：{message}")

            except json.JSONDecodeError:
                print(f"\nServer：{message}")

        except Exception as e:
            if not game_in_progress.value:
                print(f"\nError while receiving data from server: {e}")
                logging.error(f"Error when receiving data from server: {e}")
                game_in_progress.value = False
            break


async def get_user_input(prompt):
    loop = asyncio.get_event_loop()
    return await loop.run_in_executor(None, lambda: input(prompt).strip())


async def handle_user_input(writer, game_in_progress, logged_in):
    while True:
        global username
        try:
            if game_in_progress.value:
                await asyncio.sleep(0.1)
                continue
            await asyncio.sleep(1)
            user_input = await get_user_input("Input a command: ")
            if not user_input:
                continue
            parts = user_input.split()
            if not parts:
                continue
            command_input = parts[0].lower()
            params = parts[1:]

            command = None
            for cmd, aliases in COMMAND_ALIASES.items():
                if command_input in [alias.lower() for alias in aliases]:
                    command = cmd
                    break

            if not command:
                print("Invalid command, input 'help' to see list of available commands.")
                continue

            if command == "EXIT":
                print("Exiting...")
                logging.info("User chose to leave client.")
                if logged_in.value:
                    await ut.send_command("client", writer, "LOGOUT", [])
                game_in_progress.value = False
                try:
                    writer.close()
                    await writer.wait_closed()
                except:
                    pass
                # make sure program exits
                asyncio.get_event_loop().stop()
                break

            elif command == "HELP":
                print("\nAvailable commands:")
                for cmd in COMMANDS:
                    print(cmd)
                print("")
                continue

            elif command == "REGISTER":
                if len(params) != 2:
                    print("Usage: reg <username> <password>")
                    continue
                await ut.send_command("client", writer, "REGISTER", params)

            elif command == "LOGIN":
                if len(params) != 2:
                    print("Usage: login <username> <password>")
                    continue
                username = params[0]
                await ut.send_command("client", writer, "LOGIN", params)

            elif command == "LOGOUT":
                if not logged_in.value:
                    print("You aren't logged in.")
                    continue
                await ut.send_command("client", writer, "LOGOUT", [])
                
            elif command == "JOIN":
                if len(params) != 1:
                    print("Usage: join <Room ID>")
                    continue
                await ut.send_command("client", writer, "JOIN_ROOM", params)
            
            elif command == "WATCH":
                if len(params) != 1:
                    print("Usage: watch <Room ID>")
                    continue
                if not logged_in.value:
                    print("You must login before watching games.")
                    continue
                await ut.send_command("client", writer, "WATCH", params)
                

            elif command == "CREATE_ROOM":
                if len(params) != 1:
                    print("Usage: create <Room Type [public, private]>")
                    continue
                await ut.send_command("client", writer, "CREATE_ROOM", params)

            elif command == "INVITE_PLAYER":
                if len(params) != 2:
                    print("Usage: invite <Port> <Room ID>")
                    continue
                await ut.send_command("client", writer, "INVITE_PLAYER", params)

            elif command == "ACCEPT":
                if len(params) != 2:
                    print("Usage: accept <Inviter> <Room ID>")
                    continue
                await ut.send_command("client", writer, "ACCEPT", params)

            elif command == "DECLINE":
                if len(params) != 2:
                    print("Usage: decline <Inviter> <Room ID>")
                    continue
                await ut.send_command("client", writer, "DECLINE", params)

            elif command == "SHOW_STATUS":
                await ut.send_command("client", writer, "SHOW_STATUS", [])
                
            elif command == "CHECK":
                await ut.send_command("client", writer, "CHECK", [])

            elif command == "JOIN_ROOM":
                if len(params) != 1:
                    print("Usage: join <Room ID>")
                    continue
                await ut.send_command("client", writer, "JOIN_ROOM", params)

            else:
                print("Invalid command, input 'help' to see list of available commands.")
        except KeyboardInterrupt:
            print("Exiting...")
            logging.info("User chose to leave client via keyboard interrupt.")
            await ut.send_command("client", writer, "LOGOUT", [])
            game_in_progress.value = False
            writer.close()
            await writer.wait_closed()
            break
        except Exception as e:
            print(f"Error when sending command: {e}")
            logging.error(f"Error when sending command: {e}")
            game_in_progress.value = False
            writer.close()
            await writer.wait_closed()
            break


"""
For game
"""


async def initiate_game(game_in_progress, writer, room_id):
    logging.info(f"Initiating game for room {room_id}...")
    try:
        await start_game_session(peer_info.get("game_host"), peer_info.get("game_port"), room_id, mode="player")

    finally:
        game_in_progress.value = False
        await ut.send_command("client", writer, "GAME_OVER", [])


async def initiate_watch(game_in_progress, writer, room_id, host, port):
    logging.info(f"Initiating watch session for room {room_id}...")
    try:
        await start_game_session(host, port, room_id, mode="watcher")
    finally:
        game_in_progress.value = False


async def start_game_session(game_ip, game_port, room_id, max_retries=10, retry_delay=2, mode="player"):
    if not game_ip or not game_port:
        logging.error("Missing game server info, cannot join game.")
        print("Missing game server info, cannot join game.")
        return

    candidates = [game_ip]
    if game_ip not in ("127.0.0.1", "localhost"):
        candidates.append("127.0.0.1")

    for candidate in candidates:
        success = await connect_with_retries(candidate, game_port, max_retries, retry_delay, room_id, mode)
        if success:
            return
        else:
            logging.warning(f"Failed to connect via {candidate}, trying next candidate if available.")

    print("Unable to connect to the game server. Please try again later.")
    logging.error("All connection attempts to the game server failed.")


async def connect_with_retries(host, port, max_retries, retry_delay, room_id, mode):
    retries = 0
    while retries < max_retries:
        try:
            print(f"Connecting to game server at {host}:{port}... [Attempt {retries + 1}/{max_retries}]")
            logging.info(f"Connecting to game server at {host}:{port}... [Attempt {retries + 1}]")
            await connect_to_game_server(host, port, username, room_id, mode)
            return True
        except ConnectionRefusedError:
            retries += 1
            if retries >= max_retries:
                logging.error(f"Failed to connect to {host}:{port} after {max_retries} attempts.")
                return False
            print(f"Connection refused, retrying in {retry_delay} seconds...")
            await asyncio.sleep(retry_delay)
        except Exception as e:
            logging.error(f"Failed to connect to game server {host}:{port}: {e}")
            print(f"Error connecting to game server {host}:{port}: {e}")
            return False


async def connect_to_game_server(ip, port, username, room_id, mode="player"):
    """
    Connect to the game server and handle the game session.
    """
    writer = None
    try:
        reader, writer = await asyncio.open_connection(ip, port)
        print(f"Successfully connected to game server at {ip}:{port}")
        logging.info(f"Connected to game server at {ip}:{port}")
        
        # Send JOIN/WATCH message
        if mode == "watcher":
            join_msg = {
                "type": "WATCH",
                "username": username,
                "roomId": room_id
            }
        else:
            join_msg = {
                "type": "JOIN",
                "username": username
            }
        await ut.send_message(writer, join_msg)
        logging.info(f"Sent {join_msg['type']} message with username: {username}")
        
        # Wait for WELCOME message
        welcome_data = await ut.unpack_message(reader)
        if not welcome_data:
            logging.error("Failed to receive WELCOME message")
            return
        
        try:
            welcome_msg = json.loads(welcome_data)
            if welcome_msg.get("type") == "WELCOME":
                role = welcome_msg.get("role")
                seed = welcome_msg.get("seed")
                bag_rule = welcome_msg.get("bagRule")
                gravity = welcome_msg.get("gravityPlan")
                
                print(f"\n=== Game Starting ===")
                print(f"Role: {role}")
                print(f"Seed: {seed}")
                print(f"Bag Rule: {bag_rule}")
                print(f"Gravity: {gravity['dropMs']}ms per drop")
                print(f"======================\n")
                
                logging.info(f"Received WELCOME - Role: {role}, Seed: {seed}")
        except json.JSONDecodeError as e:
            logging.error(f"Failed to parse WELCOME message: {e}")
            return
        
        if mode != "watcher":
            ready_msg = {
                "type": "READY",
                "username": username
            }
            await ut.send_message(writer, ready_msg)
            logging.info("Sent READY signal to game server")
        
        # Start game loop
        await game_loop(reader, writer, username, mode=mode)
        
    except Exception as e:
        logging.error(f"Error in game session: {e}")
        print(f"Game session error: {e}")
    finally:
        if writer:
            writer.close()
            await writer.wait_closed()
        logging.info("Disconnected from game server")


async def game_loop(reader, writer, username, mode="player"):
    if TEXT_MODE_CLIENT or pygame is None:
        return await text_mode_game_loop(reader, writer, username, mode=mode)
    """
    Render local/opponent boards with pygame and stream keyboard inputs to the game server.
    """
    is_watcher = mode == "watcher"
    pygame.init()
    screen = pygame.display.set_mode((960, 640))
    pygame.display.set_caption("Multiplayer Tetris" if not is_watcher else "Tetris Watch Mode")
    font = pygame.font.SysFont("consolas", 20)
    clock = pygame.time.Clock()

    player_states = {}
    opponent_name = None
    info_banner = "Watching players..." if is_watcher else "Waiting for another player..."
    final_message = None
    opponent_viewer = None

    game_active = True
    input_seq = 0
    repeat_timestamps = {key: 0 for key in REPEATABLE_KEYS}
    post_game_timer = None
    input_queue: asyncio.Queue[str] = asyncio.Queue(maxsize=32)
    input_task = None

    def ensure_state(name):
        if name not in player_states:
            player_states[name] = default_player_state()
        return player_states[name]

    async def enqueue_input(action):
        if is_watcher:
            return
        if not action or not game_active:
            return
        try:
            await input_queue.put(action)
        except asyncio.CancelledError:
            raise

    async def flush_input_queue():
        nonlocal input_seq
        try:
            while True:
                action = await input_queue.get()
                if not action:
                    input_queue.task_done()
                    continue
                input_seq += 1
                payload = {
                    "type": "INPUT",
                    "action": action,
                    "seq": input_seq,
                    "ts": int(time.time() * 1000)
                }
                await ut.send_message(writer, payload)
                input_queue.task_done()
        except asyncio.CancelledError:
            pass

    def ensure_opponent_viewer(name):
        if is_watcher:
            return
        nonlocal opponent_viewer
        if tk is None:
            return
        if opponent_viewer is None:
            viewer = OpponentViewer(name)
            viewer.start()
            if viewer.available:
                opponent_viewer = viewer

    async def handle_server_messages():
        nonlocal game_active, opponent_name, info_banner, final_message
        try:
            while True:
                message = await ut.unpack_message(reader)
                if not message:
                    info_banner = "Lost connection to the game server."
                    game_active = False
                    break

                try:
                    msg = json.loads(message)
                except json.JSONDecodeError:
                    logging.error(f"Failed to parse game message: {message}")
                    continue

                msg_type = msg.get("type")
                if msg_type == "SNAPSHOT":
                    player = msg.get("username")
                    board = msg.get("board")
                    if not board:
                        board = decode_board_rle(msg.get("boardRLE"))
                    state = ensure_state(player)
                    state["board"] = board
                    state["active"] = msg.get("active")
                    state["hold"] = msg.get("hold")
                    state["next"] = msg.get("next", [])
                    state["score"] = msg.get("score", 0)
                    state["lines"] = msg.get("lines", 0)
                    if not is_watcher and player != username:
                        opponent_name = player
                        ensure_opponent_viewer(opponent_name)
                        if opponent_viewer:
                            mirror_state = {
                                "board": [row[:] for row in state["board"]],
                                "active": state.get("active"),
                                "hold": state.get("hold"),
                                "next": list(state.get("next", [])),
                                "score": state.get("score", 0),
                                "lines": state.get("lines", 0)
                            }
                            opponent_viewer.submit(mirror_state)
                elif msg_type == "GAME_START":
                    info_banner = "Spectating match..." if is_watcher else "Game started! Clear lines to win."
                elif msg_type in ("GAME_OVER", "END"):
                    final_message = msg
                    info_banner = f"Winner: {msg.get('winner')}"
                    game_active = False
                    break
                elif msg_type == "TEMPO":
                    drop_ms = msg.get("dropMs")
                    info_banner = f"Gravity: {drop_ms} ms per drop"
        except Exception as e:
            logging.error(f"Error receiving game message: {e}")
            game_active = False

    server_task = asyncio.create_task(handle_server_messages())
    if not is_watcher:
        input_task = asyncio.create_task(flush_input_queue())

    running = True
    while running:
        pending_actions = []
        # Handle pygame events without blocking
        for event in pygame.event.get():
            if event.type == pygame.QUIT:
                running = False
                game_active = False
                break
            if not game_active:
                continue
            if is_watcher:
                if event.type == pygame.KEYDOWN and event.key in (pygame.K_ESCAPE, pygame.K_q):
                    running = False
                    game_active = False
                    break
                continue
            if event.type == pygame.KEYDOWN:
                if event.key in INSTANT_ACTION_KEYS:
                    pending_actions.append(INSTANT_ACTION_KEYS[event.key])
                if event.key in REPEATABLE_KEYS:
                    pending_actions.append(REPEATABLE_KEYS[event.key][0])
                    repeat_timestamps[event.key] = time.time()
            elif event.type == pygame.KEYUP and event.key in REPEATABLE_KEYS:
                repeat_timestamps[event.key] = 0

        if game_active and not is_watcher and pygame.key.get_focused():
            pressed = pygame.key.get_pressed()
            now = time.time()
            for key, (action, interval) in REPEATABLE_KEYS.items():
                if pressed[key]:
                    last_sent = repeat_timestamps.get(key, 0)
                    if now - last_sent >= interval:
                        pending_actions.append(action)
                        repeat_timestamps[key] = now

        for action in pending_actions:
            await enqueue_input(action)

        screen.fill((10, 10, 10))

        if is_watcher:
            players = sorted(player_states.keys())
            if players:
                first = player_states.get(players[0], default_player_state())
                draw_player_panel(screen, f"{players[0]}", first, 80, 120, font)
            else:
                waiting_text = font.render("Waiting for player snapshots...", True, (200, 200, 200))
                screen.blit(waiting_text, (80, 120))
            if len(players) > 1:
                second = player_states.get(players[1], default_player_state())
                draw_player_panel(screen, f"{players[1]}", second, 520, 120, font)
            else:
                status = font.render("Waiting for opponent...", True, (200, 200, 200))
                screen.blit(status, (520, 120))
        else:
            local_state = player_states.get(username, default_player_state())
            draw_player_panel(screen, f"You ({username})", local_state, 80, 120, font)

            if opponent_name:
                if tk is None:
                    opponent_state = player_states.get(opponent_name, default_player_state())
                    draw_player_panel(screen, f"Rival ({opponent_name})", opponent_state, 520, 120, font)
                else:
                    status = f"Opponent window: {opponent_name}"
                    status_text = font.render(status, True, (200, 200, 200))
                    screen.blit(status_text, (520, 150))
            else:
                waiting_text = font.render("Waiting for rival snapshot...", True, (200, 200, 200))
                screen.blit(waiting_text, (520, 120))

        info_text = font.render(info_banner, True, (255, 255, 255))
        screen.blit(info_text, (80, 60))

        if final_message:
            winner = final_message.get("winner", "N/A")
            reason = final_message.get("reason", "")
            final_scores = final_message.get("finalScores")
            results_list = final_message.get("results")
            if not final_scores and isinstance(results_list, list):
                final_scores = {
                    entry.get("username") or entry.get("userId"): entry
                    for entry in results_list
                }
            if not isinstance(final_scores, dict):
                final_scores = {}
            summary = font.render(f"Game Over - Winner: {winner} ({reason})", True, (255, 215, 0))
            screen.blit(summary, (80, 520))
            y = 550
            for player, stats in final_scores.items():
                stat_text = font.render(
                    f"{player}: {stats.get('score', 0)} pts, {stats.get('lines', 0)} lines",
                    True,
                    (220, 220, 220)
                )
                screen.blit(stat_text, (80, y))
                y += 24

        pygame.display.flip()
        clock.tick(60)
        
        # Give other tasks a chance to run without blocking pygame
        await asyncio.sleep(0.001)

        if not game_active:
            if final_message:
                if post_game_timer is None:
                    post_game_timer = time.time()
                elif time.time() - post_game_timer > 5:
                    running = False
            else:
                running = False

    if not server_task.done():
        server_task.cancel()
        with contextlib.suppress(asyncio.CancelledError):
            await server_task
    if input_task:
        input_task.cancel()
        with contextlib.suppress(asyncio.CancelledError):
            await input_task

    pygame.display.quit()
    pygame.quit()
    if opponent_viewer:
        opponent_viewer.close()
        if hasattr(opponent_viewer, "join"):
            opponent_viewer.join(timeout=2)


def _format_ascii_board(state, label):
    board = normalize_board(state.get("board"))
    header = f"{label} | Score: {state.get('score', 0)} | Lines: {state.get('lines', 0)}"
    lines = [header]
    lines.append("+--------------------+")
    for row in reversed(board):
        row_str = ''.join('██' if cell else '  ' for cell in row)
        lines.append(f"|{row_str}|")
    lines.append("+--------------------+")
    lines.append(f"Hold: {state.get('hold') or '-'} | Next: {' '.join(state.get('next', [])) or '-'}")
    return '\n'.join(lines)


TEXT_INPUT_MAP = {
    "left": "LEFT",
    "l": "LEFT",
    "a": "LEFT",
    "right": "RIGHT",
    "r": "RIGHT",
    "d": "RIGHT",
    "down": "SOFT_DROP",
    "s": "SOFT_DROP",
    "soft": "SOFT_DROP",
    "drop": "HARD_DROP",
    "hard": "HARD_DROP",
    "space": "HARD_DROP",
    "cw": "CW",
    "rotate": "CW",
    "ccw": "CCW",
    "z": "CCW",
    "hold": "HOLD",
    "h": "HOLD",
}


async def text_mode_game_loop(reader, writer, username, mode="player"):
    player_states = {}
    opponent_name = None
    is_watcher = mode == "watcher"
    info_banner = "Watching players..." if is_watcher else "Waiting for another player..."
    final_message = None
    game_active = True
    input_seq = 0
    last_render = 0.0

    def ensure_state(name):
        if name not in player_states:
            player_states[name] = default_player_state()
        return player_states[name]

    async def send_input(action):
        nonlocal input_seq
        if is_watcher or not action or not game_active:
            return
        input_seq += 1
        payload = {
            "type": "INPUT",
            "action": action,
            "seq": input_seq,
            "ts": int(time.time() * 1000)
        }
        await ut.send_message(writer, payload)

    def render():
        nonlocal last_render
        now = time.time()
        if now - last_render < 0.3:
            return
        last_render = now
        print("\033[2J\033[H", end="")
        title = "=== Tetris Watch Mode ===" if is_watcher else "=== Multiplayer Tetris (Text Mode) ==="
        print(title)
        if is_watcher:
            if not player_states:
                print("Waiting for player snapshots...")
            for name in sorted(player_states.keys()):
                print("")
                print(_format_ascii_board(player_states[name], f"{name}"))
        else:
            local_state = player_states.get(username, default_player_state())
            opponent_state = player_states.get(opponent_name, default_player_state()) if opponent_name else None
            print(_format_ascii_board(local_state, f"You ({username})"))
            if opponent_state:
                print("")
                print(_format_ascii_board(opponent_state, f"Rival ({opponent_name})"))
            else:
                print("\nWaiting for rival snapshot...")
        print(f"\nInfo: {info_banner}")
        if final_message:
            print(f"\nWinner: {final_message.get('winner', 'N/A')} Reason: {final_message.get('reason', '')}")

    async def handle_server_messages():
        nonlocal opponent_name, info_banner, final_message, game_active
        try:
            while True:
                message = await ut.unpack_message(reader)
                if not message:
                    info_banner = "Lost connection to the game server."
                    game_active = False
                    break
                try:
                    msg = json.loads(message)
                except json.JSONDecodeError:
                    continue
                msg_type = msg.get("type")
                if msg_type == "SNAPSHOT":
                    player = msg.get("username")
                    board = msg.get("board")
                    if not board:
                        board = decode_board_rle(msg.get("boardRLE"))
                    state = ensure_state(player)
                    state["board"] = board
                    state["active"] = msg.get("active")
                    state["hold"] = msg.get("hold")
                    state["next"] = msg.get("next", [])
                    state["score"] = msg.get("score", 0)
                    state["lines"] = msg.get("lines", 0)
                    if player != username:
                        opponent_name = player
                    render()
                elif msg_type == "GAME_START":
                    info_banner = "Spectating match..." if is_watcher else "Game started! Type commands to move."
                elif msg_type in ("GAME_OVER", "END"):
                    final_message = msg
                    info_banner = f"Winner: {msg.get('winner')}"
                    game_active = False
                    render()
                    break
                elif msg_type == "TEMPO":
                    drop_ms = msg.get("dropMs")
                    info_banner = f"Gravity: {drop_ms} ms per drop"
        except Exception as e:
            logging.error(f"Error receiving text-mode game message: {e}")
            game_active = False

    async def command_loop():
        nonlocal game_active
        while game_active:
            cmd = await get_user_input("Action (left/right/down/drop/cw/ccw/hold/quit): ")
            if cmd is None:
                continue
            cmd = cmd.strip().lower()
            if not cmd:
                continue
            if cmd in ("quit", "exit"):
                game_active = False
                break
            if is_watcher:
                print("Watching mode: only 'quit' is supported.")
                continue
            action = TEXT_INPUT_MAP.get(cmd)
            if action:
                await send_input(action)
            else:
                print("Unknown action. Allowed: left/right/down/drop/cw/ccw/hold/quit")

    server_task = asyncio.create_task(handle_server_messages())
    command_task = asyncio.create_task(command_loop())
    done, pending = await asyncio.wait(
        [server_task, command_task],
        return_when=asyncio.FIRST_COMPLETED
    )
    for task in pending:
        task.cancel()
        with contextlib.suppress(asyncio.CancelledError):
            await task


"""
For broadcast
"""
def display_online_users(online_users):
    print("\n--- List of Online Users ---")
    if not online_users:
        print("No users are online :(")
    else:
        for user in online_users:
            name = user.get("username", "未知")
            status = user.get("status", "未知")
            print(f"User: {name} - Status: {status}")
    print("----------------------------\nInput a command: ")


async def main():
    ut.init_logging()

    server_ip = config.HOST
    server_port = config.PORT

    try:
        reader, writer = await asyncio.open_connection(server_ip, server_port)
        print("Successfully connected to lobby server.")
        logging.info(f"Successfully connected to lobby server {server_ip}:{server_port}")
    except ConnectionRefusedError:
        print("Connection declined, please check if the server is running.")
        logging.error("Connection declined, please check if the server is running.")
        return
    except Exception as e:
        print(f"Unable to connect to server: {e}")
        logging.error(f"Unable to connect to server: {e}")
        return

    game_in_progress = type('', (), {'value': False})()
    logged_in = type('', (), {'value': False})()

    asyncio.create_task(handle_server_messages(reader, writer, game_in_progress, logged_in))
    asyncio.create_task(handle_user_input(writer, game_in_progress, logged_in))

    print("\nAvailable commands: ")
    for cmd in COMMANDS:
        print(cmd)
    print("")

    await asyncio.Future()

    print("Client end closed.")
    logging.info("Client end closed.")
    sys.exit()


if __name__ == "__main__":
    try:
        asyncio.run(main())
    except Exception as e:
        print(f"Client end terminated with error: {e}")
        logging.error(f"Client end terminated with error: {e}")
