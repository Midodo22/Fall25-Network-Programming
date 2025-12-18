import asyncio
import contextlib
import json
import logging
import os
import random
import threading
import queue
from dataclasses import dataclass, replace

import aiofiles

try:
    import tkinter

    TK_AVAILABLE = True
except Exception:  # pragma: no cover - environments without Tk
    tkinter = None
    TK_AVAILABLE = False


server_close_event = None
score_log_cache = {}


async def send_message(writer, message):
    """Send JSON message with newline framing."""
    try:
        data = json.dumps(message) + "\n"
        writer.write(data.encode())
        await writer.drain()
    except Exception as exc:
        logging.error(f"Failed to send message: {exc}")


async def get_user_input(prompt):
    loop = asyncio.get_event_loop()
    return await loop.run_in_executor(None, lambda: input(prompt).strip())


SHAPES = {
    "O": ["56a9", "6a95", "a956", "956a"],
    "I": ["4567", "26ae", "ba98", "d951"],
    "J": ["0456", "2159", "a654", "8951"],
    "L": ["2654", "a951", "8456", "0159"],
    "T": ["1456", "6159", "9654", "4951"],
    "Z": ["0156", "2659", "a954", "8451"],
    "S": ["1254", "a651", "8956", "0459"],
}

AUTO_DROP_INTERVAL = 1.0  # Seconds between automatic soft drops
FILE_RELAY_ROOT = ""


def _should_force_file_relay():
    return os.environ.get("FORCE_TETRIS_FILE_RELAY", "").lower() in ("1", "true", "yes")


def _relay_channel_id(peer_info):
    game_name = peer_info.get("game_name", "game")
    try:
        own = int(peer_info.get("own_port", 0))
        peer = int(peer_info.get("peer_port", 0))
    except (TypeError, ValueError):
        own = peer_info.get("own_port")
        peer = peer_info.get("peer_port")
    ordered = sorted([own, peer])
    return f"{game_name}_{ordered[0]}_{ordered[1]}"


class FileStreamReader:
    def __init__(self, path):
        self.path = path
        self._offset = 0
        self._buffer = ""
        self._closed = False

    async def readline(self):
        while not self._closed:
            newline_idx = self._buffer.find("\n")
            if newline_idx != -1:
                line = self._buffer[: newline_idx + 1]
                self._buffer = self._buffer[newline_idx + 1 :]
                return line.encode()
            try:
                async with aiofiles.open(self.path, "r") as f:
                    await f.seek(self._offset)
                    chunk = await f.read()
            except FileNotFoundError:
                chunk = ""
            if chunk:
                self._offset += len(chunk)
                self._buffer += chunk
                continue
            await asyncio.sleep(0.2)
        return b""

    def close(self):
        self._closed = True


class FileStreamWriter:
    def __init__(self, path):
        self.path = path
        self._buffer = bytearray()
        self._closed = False

    def write(self, data):
        if self._closed:
            return
        self._buffer.extend(data)

    async def drain(self):
        if self._closed or not self._buffer:
            return
        async with aiofiles.open(self.path, "a") as f:
            await f.write(self._buffer.decode())
        self._buffer.clear()

    def close(self):
        self._closed = True

    async def wait_closed(self):
        return


class FileRelayChannel:
    def __init__(self, peer_info, role):
        self.role = role
        self.peer_info = peer_info
        self.channel_id = _relay_channel_id(peer_info)
        prefix = f"relay_{self.channel_id}"
        base = FILE_RELAY_ROOT or ""
        self.host_to_client = os.path.join(base, f"{prefix}_h2c.log")
        self.client_to_host = os.path.join(base, f"{prefix}_c2h.log")
        if role == "host":
            self.out_path = self.host_to_client
            self.in_path = self.client_to_host
        else:
            self.out_path = self.client_to_host
            self.in_path = self.host_to_client
        self.reader = FileStreamReader(self.in_path)
        self.writer = FileStreamWriter(self.out_path)

    async def send_json(self, payload):
        data = json.dumps(payload) + "\n"
        self.writer.write(data.encode())
        await self.writer.drain()

    async def recv_json(self):
        line = await self.reader.readline()
        if not line:
            return None
        return json.loads(line.decode())

    def cleanup(self):
        for path in (self.host_to_client, self.client_to_host):
            try:
                os.remove(path)
            except FileNotFoundError:
                pass
            except OSError:
                pass


@dataclass(frozen=True)
class Piece:
    shape: str
    rot: int = 0
    x: int = 0
    y: int = 0


def get_piece_blocks(piece):
    for char in SHAPES[piece.shape][piece.rot % 4]:
        y, x = divmod(int(char, 16), 4)
        yield piece.x + x, piece.y - y


def move_piece(piece, *, rot=0, dx=0, dy=0):
    rot = (piece.rot + rot) % 4
    x = piece.x + dx
    y = piece.y + dy
    return replace(piece, rot=rot, x=x, y=y)


def get_wall_kicks(piece, *, rot=0):
    return [
        move_piece(piece, rot=rot, dx=dx, dy=dy)
        for dx, dy in [(0, 0), (-1, 0), (1, 0), (0, -1)]
    ]


def piece_fits(field, piece):
    width = len(field[0])
    height = len(field)
    for x, y in get_piece_blocks(piece):
        if not 0 <= x < width:
            return False
        if not 0 <= y < height:
            return False
        if field[y][x]:
            return False
    return True


class SimpleTetris:
    """Self-contained Tetris implementation adapted from games/tetris_template."""

    def __init__(self, width=10, height=20, seed=None):
        self.width = width
        self.height = height
        self._rng = random.Random(seed)
        self.field = [[0 for _ in range(width)] for _ in range(height)]
        self.next_pieces = []
        self._shape_gen = self._random_shape_bag()
        self._fill_preview()
        self.piece = self._get_next_piece()
        self.hold_piece = None
        self.can_hold = True
        self.score = 0
        self.lines = 0
        self.game_over = False

    def _random_shape_bag(self):
        """Yield shapes following the 7-bag rule."""
        bag = list(SHAPES)
        yield self._rng.choice("IJLT")
        while True:
            self._rng.shuffle(bag)
            yield from bag

    def _fill_preview(self):
        while len(self.next_pieces) < 3:
            self.next_pieces.append(next(self._shape_gen))

    def _spawn_piece(self, shape):
        return Piece(shape=shape, x=self.width // 2 - 2, y=self.height - 1)

    def _get_next_piece(self):
        if not self.next_pieces:
            self._fill_preview()
        shape = self.next_pieces.pop(0)
        self._fill_preview()
        return self._spawn_piece(shape)

    def _place_new_piece(self):
        self.piece = self._get_next_piece()
        self.can_hold = True
        if not piece_fits(self.field, self.piece):
            self.game_over = True

    def _freeze_piece(self):
        for x, y in get_piece_blocks(self.piece):
            if 0 <= y < self.height and 0 <= x < self.width:
                self.field[y][x] = 1

    def _clear_lines(self):
        new_field = [row for row in self.field if not all(row)]
        cleared = self.height - len(new_field)
        self.field = new_field + [[0] * self.width for _ in range(cleared)]
        if cleared:
            self.lines += cleared
            self.score += cleared * 100

    def _move(self, *, rot=0, dx=0, dy=0):
        candidates = get_wall_kicks(self.piece, rot=rot) if rot else [move_piece(self.piece, dx=dx, dy=dy)]
        for candidate in candidates:
            if piece_fits(self.field, candidate):
                self.piece = candidate
                return True
        if dy == -1:
            self._freeze_piece()
            self._clear_lines()
            self._place_new_piece()
        return False

    def move_left(self):
        self._move(dx=-1)

    def move_right(self):
        self._move(dx=1)

    def soft_drop(self):
        self._move(dy=-1)

    def rotate_left(self):
        self._move(rot=-1)

    def rotate_right(self):
        self._move(rot=1)

    def hard_drop(self):
        dropped = 0
        while self._move(dy=-1):
            dropped += 1
        self.score += dropped * 2

    def hold(self):
        if not self.can_hold:
            return
        current_shape = self.piece.shape
        if self.hold_piece is None:
            self.hold_piece = current_shape
            self.piece = self._get_next_piece()
        else:
            self.hold_piece, swap_shape = current_shape, self.hold_piece
            self.piece = self._spawn_piece(swap_shape)
            if not piece_fits(self.field, self.piece):
                self.game_over = True
        self.can_hold = False

    def apply_command(self, command):
        commands = {
            "left": self.move_left,
            "right": self.move_right,
            "down": self.soft_drop,
            "drop": self.hard_drop,
            "rotleft": self.rotate_left,
            "rotright": self.rotate_right,
            "hold": self.hold,
        }
        action = commands.get(command)
        if action:
            action()
        else:
            raise ValueError("Unknown command")

    def board_to_rle(self):
        grid = [row[:] for row in self.field]
        if self.piece:
            for x, y in get_piece_blocks(self.piece):
                if 0 <= y < self.height and 0 <= x < self.width:
                    grid[y][x] = 2
        rows = []
        for row in reversed(grid):
            rows.append("".join(str(cell) for cell in row))
        return "|".join(rows)

    def render_text_board(self):
        grid = [row[:] for row in self.field]
        if self.piece:
            for x, y in get_piece_blocks(self.piece):
                if 0 <= y < self.height and 0 <= x < self.width:
                    grid[y][x] = 2
        lines = []
        for row in reversed(grid):
            line = "".join("#" if cell else "." for cell in row)
            lines.append(line)
        return lines

    def snapshot(self):
        return {
            "board": self.board_to_rle(),
            "score": self.score,
            "lines": self.lines,
            "game_over": self.game_over,
        }


class TetrisGUI:
    BLOCK_SIZE = 24

    def __init__(self, title, width=10, height=20):
        self.width = width
        self.height = height
        self.queue = queue.Queue()
        self.command_queue = queue.Queue()
        self.closed = threading.Event()
        self.thread = None
        self.root = None
        self.canvas = None
        self.blocks = {}
        self.score_var = None
        if TK_AVAILABLE:
            self.thread = threading.Thread(target=self._run_gui, args=(title,), daemon=True)
            self.thread.start()

    def _run_gui(self, title):
        try:
            self.root = tkinter.Tk()
            self.root.title(f"Tetris - {title}")
            self.canvas = tkinter.Canvas(
                self.root,
                width=self.width * self.BLOCK_SIZE,
                height=self.height * self.BLOCK_SIZE,
                bg="#1e272e",
            )
            self.canvas.pack(padx=10, pady=10)
            self.score_var = tkinter.StringVar(value="Score: 0 | Lines: 0")
            score_label = tkinter.Label(self.root, textvariable=self.score_var, font=("Arial", 12))
            score_label.pack()

            def on_key(event):
                key = event.keysym.lower()
                mapping = {
                    "left": "left",
                    "right": "right",
                    "down": "down",
                    "up": "rotleft",
                    "space": "drop",
                    "z": "rotleft",
                    "x": "rotright",
                    "c": "hold",
                    "return": "drop",
                }
                command = mapping.get(key)
                if command:
                    self.command_queue.put(command)

            for x in range(self.width):
                for y in range(self.height):
                    rect = self.canvas.create_rectangle(
                        x * self.BLOCK_SIZE,
                        (self.height - y - 1) * self.BLOCK_SIZE,
                        (x + 1) * self.BLOCK_SIZE,
                        (self.height - y) * self.BLOCK_SIZE,
                        fill="#ecf0f1",
                        outline="#2f3640",
                    )
                    self.blocks[(x, y)] = rect

            def poll_queue():
                if self.closed.is_set():
                    self.root.destroy()
                    return
                try:
                    while True:
                        item = self.queue.get_nowait()
                        if item is None:
                            self.closed.set()
                            self.root.destroy()
                            return
                        board_lines, score, lines = item
                        self._apply_board(board_lines, score, lines)
                except queue.Empty:
                    pass
                self.root.after(50, poll_queue)

            self.root.bind("<Key>", on_key)
            poll_queue()
            self.root.mainloop()
        except Exception as exc:
            logging.error(f"Tetris GUI error: {exc}")

    def _apply_board(self, board_lines, score, lines):
        if not self.canvas:
            return
        for y, row in enumerate(board_lines):
            for x, cell in enumerate(row):
                rect = self.blocks.get((x, len(board_lines) - y - 1))
                if not rect:
                    continue
                color = "#3498db" if cell != "." else "#ecf0f1"
                self.canvas.itemconfigure(rect, fill=color)
        if self.score_var:
            self.score_var.set(f"Score: {score} | Lines: {lines}")

    def update_board(self, board_lines, score, lines):
        if not TK_AVAILABLE or not self.thread:
            return
        # ensure we always have a snapshot of the board
        copied = list(board_lines)
        self.queue.put((copied, score, lines))

    def close(self):
        if not TK_AVAILABLE or not self.thread:
            return
        self.closed.set()
        self.queue.put(None)
        self.thread.join(timeout=2)


def log_score_if_changed(label, score, lines):
    key = f"{label}"
    previous = score_log_cache.get(key)
    current = (score, lines)
    if previous != current:
        score_log_cache[key] = current
        print(f"[{label}] Score: {score} Lines: {lines}")


def render_remote_board(board_rle):
    if not board_rle:
        return []
    rows = board_rle.split("|")
    rendered = []
    for row in rows:
        rendered.append("".join("#" if char != "0" else "." for char in row))
    return rendered


async def print_and_sync_board(role, board_lines, snapshot, writer, game_over_event=None, gui=None):
    if gui:
        gui.update_board(board_lines, snapshot.get("score", 0), snapshot.get("lines", 0))
    else:
        for line in board_lines:
            print(f"[{role}] {line}")
    log_score_if_changed(role, snapshot.get("score", 0), snapshot.get("lines", 0))
    await send_message(writer, {"type": "SNAPSHOT", "from": role, **snapshot})
    if snapshot.get("game_over"):
        await send_message(writer, {"type": "GAME_OVER", "reason": f"{role} topped out"})
        print(f"[{role}] Game over! Score: {snapshot.get('score')}, Lines: {snapshot.get('lines')}")
        if game_over_event and not game_over_event.is_set():
            game_over_event.set()
        return True
    return False


async def auto_drop_loop(role, game, writer, lock, game_over_event, interval=AUTO_DROP_INTERVAL, gui=None):
    try:
        while not game_over_event.is_set():
            await asyncio.sleep(interval)
            if game_over_event.is_set():
                break
            async with lock:
                if game.game_over:
                    break
                game.soft_drop()
                board_state = game.render_text_board()
                snapshot = game.snapshot()
            if gui:
                gui.update_board(board_state, snapshot.get("score", 0), snapshot.get("lines", 0))
            finished = await print_and_sync_board(role, board_state, snapshot, writer, game_over_event, gui)
            if finished:
                return
    except asyncio.CancelledError:
        pass


async def wait_for_gui_command(gui, game_over_event):
    if not gui:
        return ""
    while not game_over_event.is_set():
        if gui.closed.is_set():
            return ""
        try:
            command = gui.command_queue.get(timeout=0.05)
            return command
        except queue.Empty:
            await asyncio.sleep(0.05)
    return ""


async def play_local_game(role, game, writer):
    print(f"\n[{role}] Commands: left, right, down, rotleft, rotright, hold, drop, quit")
    gui = TetrisGUI(role, width=game.width, height=game.height) if TK_AVAILABLE else None
    game_lock = asyncio.Lock()
    game_over_event = asyncio.Event()

    async with game_lock:
        board_state = game.render_text_board()
        snapshot = game.snapshot()
    await print_and_sync_board(role, board_state, snapshot, writer, gui=gui)

    drop_task = asyncio.create_task(
        auto_drop_loop(role, game, writer, game_lock, game_over_event, AUTO_DROP_INTERVAL, gui)
    )
    try:
        while not game_over_event.is_set():
            if gui:
                command = await wait_for_gui_command(gui, game_over_event)
                if game_over_event.is_set():
                    break
            else:
                user_input_task = asyncio.create_task(get_user_input(f"[{role}] Move: "))
                wait_task = asyncio.create_task(game_over_event.wait())
                done, pending = await asyncio.wait(
                    {user_input_task, wait_task}, return_when=asyncio.FIRST_COMPLETED
                )
                if wait_task in done and game_over_event.is_set():
                    user_input_task.cancel()
                    break
                command = ""
                if user_input_task in done:
                    command = (user_input_task.result() or "").lower()
                for task in pending:
                    task.cancel()
            if not command:
                continue
            if command in ("quit", "exit"):
                await send_message(writer, {"type": "GAME_OVER", "reason": f"{role} quit"})
                print("You ended the session.")
                game_over_event.set()
                break
            try:
                async with game_lock:
                    game.apply_command(command)
                    board_state = game.render_text_board()
                    snapshot = game.snapshot()
                finished = await print_and_sync_board(
                    role, board_state, snapshot, writer, game_over_event, gui
                )
                if finished:
                    break
            except ValueError:
                print("Unknown command.")
    finally:
        game_over_event.set()
        drop_task.cancel()
        with contextlib.suppress(asyncio.CancelledError):
            await drop_task
        if gui:
            gui.close()


async def handle_remote_updates(reader, label):
    try:
        while True:
            data = await reader.readline()
            if not data:
                print(f"[{label}] disconnected.")
                return
            try:
                message = json.loads(data.decode())
            except json.JSONDecodeError:
                continue
            msg_type = message.get("type")
            if msg_type == "SNAPSHOT":
                score = message.get("score", 0)
                lines = message.get("lines", 0)
                log_score_if_changed(label, score, lines)
            elif msg_type == "GAME_OVER":
                print(f"\n[{label}] reports game over: {message.get('reason')}")
                return
            elif msg_type == "INIT":
                continue
    except asyncio.CancelledError:
        pass


async def run_tetris_session(reader, writer, role, remote_label, seed):
    game = SimpleTetris(seed=seed)
    remote_task = asyncio.create_task(handle_remote_updates(reader, remote_label))
    local_task = asyncio.create_task(play_local_game(role, game, writer))
    done, pending = await asyncio.wait(
        [remote_task, local_task],
        return_when=asyncio.FIRST_COMPLETED
    )
    for task in pending:
        task.cancel()
    writer.close()
    await writer.wait_closed()


async def start_tetris_game_as_host(own_port, peer_info):
    global server_close_event
    if _should_force_file_relay():
        await start_tetris_game_via_file(peer_info, role="host")
        return
    try:
        server_close_event = asyncio.Event()
        connection_event = asyncio.Event()

        async def client_connected(reader, writer):
            connection_event.set()
            seed = random.randint(0, 1_000_000)
            await send_message(writer, {"type": "INIT", "seed": seed})
            await run_tetris_session(reader, writer, "Host", "Client", seed)
            server_close_event.set()

        server = await asyncio.start_server(client_connected, "0.0.0.0", own_port)
        print(f"Tetris host listening on {own_port}")

        async def stop_server():
            await server_close_event.wait()
            server.close()
            await server.wait_closed()
            print("Tetris host closed.")

        async with server:
            serve_task = asyncio.create_task(server.serve_forever())
            stop_task = asyncio.create_task(stop_server())
            try:
                await asyncio.wait_for(connection_event.wait(), timeout=5)
            except asyncio.TimeoutError:
                print("連線逾時，改用本地檔案通道進行遊戲。")
                server_close_event.set()
                server.close()
                await server.wait_closed()
                serve_task.cancel()
                stop_task.cancel()
                with contextlib.suppress(asyncio.CancelledError):
                    await serve_task
                    await stop_task
                await start_tetris_game_via_file(peer_info, role="host")
                return
            await asyncio.gather(serve_task, stop_task)
    except (PermissionError, OSError) as exc:
        logging.warning(f"TCP hosting unavailable ({exc}); falling back to file relay.")
        print("無法建立 TCP 主機，改用本地檔案通道。")
        await start_tetris_game_via_file(peer_info, role="host")


async def start_tetris_game_as_client(peer_ip, peer_port, peer_info):
    if _should_force_file_relay():
        await start_tetris_game_via_file(peer_info, role="client")
        return
    retries = 0
    writer = None
    while retries < 10:
        try:
            reader, writer = await asyncio.open_connection(peer_ip, peer_port)
            break
        except (PermissionError, OSError) as exc:
            logging.warning(f"TCP client connection unavailable ({exc}); falling back to file relay.")
            print("無法以 TCP 連線至主機，改用本地檔案通道。")
            await start_tetris_game_via_file(peer_info, role="client")
            return
        except ConnectionRefusedError:
            retries += 1
            await asyncio.sleep(1)
    if writer is None:
        print("Unable to connect to host, using local relay instead.")
        await start_tetris_game_via_file(peer_info, role="client")
        return

    init_data = await reader.readline()
    if not init_data:
        print("Host closed connection.")
        writer.close()
        await writer.wait_closed()
        return
    message = json.loads(init_data.decode())
    if message.get("type") != "INIT":
        print("Unexpected handshake from host.")
        writer.close()
        await writer.wait_closed()
        return
    seed = message.get("seed")
    print(f"Joined Tetris host on {peer_ip}:{peer_port} (seed {seed})")
    await run_tetris_session(reader, writer, "Client", "Host", seed)


async def start_tetris_game_via_file(peer_info, role):
    channel = FileRelayChannel(peer_info, role)
    try:
        if role == "host":
            seed = random.randint(0, 1_000_000)
            await channel.send_json({"type": "INIT", "seed": seed})
            print(f"Using file relay channel {channel.channel_id} (seed {seed})")
            await run_tetris_session(channel.reader, channel.writer, "Host", "Client", seed)
        else:
            print(f"Waiting for host via file relay channel {channel.channel_id}...")
            message = await channel.recv_json()
            if not message or message.get("type") != "INIT":
                print("Failed to receive host handshake via file relay.")
                return
            seed = message.get("seed")
            print(f"Joined file relay channel with seed {seed}")
            await run_tetris_session(channel.reader, channel.writer, "Client", "Host", seed)
    finally:
        channel.reader.close()
        channel.writer.close()
        await channel.writer.wait_closed()
        if role == "host":
            channel.cleanup()


async def main(peer_info):
    role = peer_info.get("role")
    own_port = peer_info.get("own_port")
    peer_ip = peer_info.get("peer_ip")
    peer_port = peer_info.get("peer_port")

    if None in [role, own_port, peer_ip, peer_port]:
        print("Missing peer info, cannot start.")
        return

    if role == "host":
        await start_tetris_game_as_host(int(own_port), peer_info)
    elif role == "client":
        await start_tetris_game_as_client(peer_ip, int(peer_port), peer_info)
    else:
        print("Unknown role provided in peer info.")
