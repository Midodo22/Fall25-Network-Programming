import asyncio
import json
import logging
import random
import time
import struct
from dataclasses import dataclass, asdict
from typing import Dict, List, Optional, Tuple
from enum import Enum
import config

# ============================================================================
# DATA STRUCTURES
# ============================================================================

class Action(Enum):
    LEFT = "LEFT"
    RIGHT = "RIGHT"
    CW = "CW"           # Clockwise rotation
    CCW = "CCW"         # Counter-clockwise rotation
    SOFT_DROP = "SOFT_DROP"
    HARD_DROP = "HARD_DROP"
    HOLD = "HOLD"

class TetriminoShape(Enum):
    I = "I"
    O = "O"
    T = "T"
    S = "S"
    Z = "Z"
    J = "J"
    L = "L"

@dataclass
class ActivePiece:
    shape: str
    x: int
    y: int
    rot: int  # 0-3

@dataclass
class PlayerState:
    username: str
    board: List[List[int]]  # 20x10 grid
    active: Optional[ActivePiece]
    hold: Optional[str]
    score: int
    lines: int
    level: int
    last_input_seq: int
    writer: any
    ready: bool = False
    game_over: bool = False

# ============================================================================
# TETRIS GAME LOGIC
# ============================================================================

class TetrisBag:
    """7-bag system with Fisher-Yates shuffle"""
    def __init__(self, seed: int):
        self.rng = random.Random(seed)
        self.current_bag = []
        self.next_bag = []
        self._refill_bag()
    
    def _refill_bag(self):
        """Create a new shuffled bag of all 7 tetriminos"""
        shapes = [s.value for s in TetriminoShape]
        self.rng.shuffle(shapes)
        return shapes
    
    def get_next(self) -> str:
        """Get next piece from bag"""
        if not self.current_bag:
            self.current_bag = self.next_bag if self.next_bag else self._refill_bag()
            self.next_bag = self._refill_bag()
        
        return self.current_bag.pop(0)
    
    def peek_next(self, count: int = 3) -> List[str]:
        """Peek at next N pieces"""
        preview = self.current_bag.copy()
        if len(preview) < count:
            preview.extend(self.next_bag)
        return preview[:count]


class TetrisGameLogic:
    """Core Tetris game logic"""
    
    # Tetrimino shapes (relative coordinates for each rotation)
    SHAPES = {
        "I": [[(0,1),(1,1),(2,1),(3,1)], [(2,0),(2,1),(2,2),(2,3)], 
              [(0,2),(1,2),(2,2),(3,2)], [(1,0),(1,1),(1,2),(1,3)]],
        "O": [[(1,0),(2,0),(1,1),(2,1)]] * 4,
        "T": [[(1,0),(0,1),(1,1),(2,1)], [(1,0),(1,1),(2,1),(1,2)],
              [(0,1),(1,1),(2,1),(1,2)], [(1,0),(0,1),(1,1),(1,2)]],
        "S": [[(1,0),(2,0),(0,1),(1,1)], [(1,0),(1,1),(2,1),(2,2)],
              [(1,1),(2,1),(0,2),(1,2)], [(0,0),(0,1),(1,1),(1,2)]],
        "Z": [[(0,0),(1,0),(1,1),(2,1)], [(2,0),(1,1),(2,1),(1,2)],
              [(0,1),(1,1),(1,2),(2,2)], [(1,0),(0,1),(1,1),(0,2)]],
        "J": [[(0,0),(0,1),(1,1),(2,1)], [(1,0),(2,0),(1,1),(1,2)],
              [(0,1),(1,1),(2,1),(2,2)], [(1,0),(1,1),(0,2),(1,2)]],
        "L": [[(2,0),(0,1),(1,1),(2,1)], [(1,0),(1,1),(1,2),(2,2)],
              [(0,1),(1,1),(2,1),(0,2)], [(0,0),(1,0),(1,1),(1,2)]]
    }
    
    @staticmethod
    def create_empty_board(height=20, width=10) -> List[List[int]]:
        return [[0 for _ in range(width)] for _ in range(height)]
    
    @staticmethod
    def check_collision(board: List[List[int]], piece: ActivePiece) -> bool:
        """Check if piece collides with board or boundaries"""
        coords = TetrisGameLogic.SHAPES[piece.shape][piece.rot]
        for dx, dy in coords:
            x, y = piece.x + dx, piece.y + dy
            if x < 0 or x >= 10 or y >= 20:
                return True
            if y >= 0 and board[y][x] != 0:
                return True
        return False
    
    @staticmethod
    def lock_piece(board: List[List[int]], piece: ActivePiece, color: int = 1):
        """Lock piece into board"""
        coords = TetrisGameLogic.SHAPES[piece.shape][piece.rot]
        for dx, dy in coords:
            x, y = piece.x + dx, piece.y + dy
            if 0 <= y < 20 and 0 <= x < 10:
                board[y][x] = color
    
    @staticmethod
    def clear_lines(board: List[List[int]]) -> int:
        """Clear completed lines and return count"""
        lines_cleared = 0
        y = 19
        while y >= 0:
            if all(cell != 0 for cell in board[y]):
                board.pop(y)
                board.insert(0, [0] * 10)
                lines_cleared += 1
            else:
                y -= 1
        return lines_cleared
    
    @staticmethod
    def compress_board(board: List[List[int]]) -> str:
        """RLE compression for board state"""
        result = []
        for row in board:
            count = 1
            prev = row[0]
            for cell in row[1:]:
                if cell == prev:
                    count += 1
                else:
                    result.append(f"{count}{prev}" if count > 1 else str(prev))
                    prev = cell
                    count = 1
            result.append(f"{count}{prev}" if count > 1 else str(prev))
            result.append("|")
        return "".join(result[:-1])


# ============================================================================
# GAME SERVER
# ============================================================================

class TetrisGameServer:
    def __init__(self, room_id: str):
        self.room_id = room_id
        self.host_port = None  # Will be assigned when server starts
        self.seed = random.randint(100000, 999999999)
        self.bag = TetrisBag(self.seed)
        
        self.players: Dict[str, PlayerState] = {}  # Changed to username key
        self.tick = 0
        self.game_started = False
        self.game_over = False
        
        # Timing
        self.drop_interval = 0.5  # 500ms initial drop speed
        self.last_drop_time = time.time()
        self.snapshot_interval = 1.0  # Send snapshot every 1 second
        self.last_snapshot_time = time.time()
        
        # Input buffer for latency handling
        self.input_buffer = []
        
        logging.info(f"[Game] Initialized game server for room {room_id} with seed {self.seed}")
    
    async def handle_client(self, reader, writer):
        """Handle individual client connection"""
        addr = writer.get_extra_info('peername')
        logging.info(f"[Game] Client connected from {addr}")
        username = None
        
        try:
            # Wait for player identification using unpack_message
            message = await self.unpack_message(reader)
            if not message:
                logging.error(f"[Game] No message received from {addr}")
                return
            
            try:
                msg = json.loads(message)
            except json.JSONDecodeError as e:
                logging.error(f"[Game] Invalid JSON from {addr}: {e}")
                return
            
            if msg.get("type") != "JOIN":
                logging.error(f"[Game] Invalid first message from {addr}")
                return
            
            username = msg.get("username")
            if not username:
                logging.error(f"[Game] No username provided from {addr}")
                return
            
            # Create player state
            player = PlayerState(
                username=username,
                board=TetrisGameLogic.create_empty_board(),
                active=None,
                hold=None,
                score=0,
                lines=0,
                level=1,
                last_input_seq=0,
                writer=writer,
                ready=False
            )
            
            self.players[username] = player
            
            # Send welcome message
            welcome_msg = {
                "type": "WELCOME",
                "role": f"P{len(self.players)}",
                "seed": self.seed,
                "bagRule": "7bag",
                "gravityPlan": {
                    "mode": "fixed",
                    "dropMs": int(self.drop_interval * 1000)
                }
            }
            await self.send_message(writer, welcome_msg)
            
            logging.info(f"[Game] Player {username} joined")
            
            # If both players connected, start game
            if len(self.players) == 2 and not self.game_started:
                await self.start_game()
            
            # Handle player inputs
            await self.handle_player_input(reader, player)
            
        except Exception as e:
            logging.error(f"[Game] Error handling client {addr}: {e}")
        finally:
            if username and username in self.players:
                del self.players[username]
            writer.close()
            await writer.wait_closed()
    
    async def handle_player_input(self, reader, player: PlayerState):
        """Process input from a player"""
        try:
            while not self.game_over:
                message = await self.unpack_message(reader)
                if not message:
                    break
                
                try:
                    msg = json.loads(message)
                except json.JSONDecodeError as e:
                    logging.error(f"[Game] Invalid JSON from {player.username}: {e}")
                    continue
                
                if msg.get("type") == "INPUT":
                    await self.process_input(player, msg)
                elif msg.get("type") == "READY":
                    player.ready = True
                    if all(p.ready for p in self.players.values()):
                        await self.start_game()
                
        except Exception as e:
            logging.error(f"[Game] Error processing input from {player.username}: {e}")
    
    async def process_input(self, player: PlayerState, msg: dict):
        """Process player input action"""
        if player.game_over or not player.active:
            return
        
        action = msg.get("action")
        seq = msg.get("seq", 0)
        
        # Ignore old inputs
        if seq <= player.last_input_seq:
            return
        
        player.last_input_seq = seq
        
        # Process action
        piece = player.active
        old_x, old_y, old_rot = piece.x, piece.y, piece.rot
        
        if action == "LEFT":
            piece.x -= 1
        elif action == "RIGHT":
            piece.x += 1
        elif action == "CW":
            piece.rot = (piece.rot + 1) % 4
        elif action == "CCW":
            piece.rot = (piece.rot - 1) % 4
        elif action == "SOFT_DROP":
            piece.y += 1
        elif action == "HARD_DROP":
            while not TetrisGameLogic.check_collision(player.board, piece):
                piece.y += 1
            piece.y -= 1
            await self.lock_and_spawn(player)
            return
        elif action == "HOLD":
            await self.handle_hold(player)
            return
        
        # Check collision and revert if needed
        if TetrisGameLogic.check_collision(player.board, piece):
            piece.x, piece.y, piece.rot = old_x, old_y, old_rot
            
            # If soft drop failed, lock piece
            if action == "SOFT_DROP":
                await self.lock_and_spawn(player)
        
        # Broadcast state change to all players
        await self.broadcast_snapshot(player)
    
    async def handle_hold(self, player: PlayerState):
        """Handle hold piece action"""
        if not player.active:
            return
        
        current_shape = player.active.shape
        
        if player.hold:
            # Swap with hold
            player.active = ActivePiece(shape=player.hold, x=4, y=0, rot=0)
            player.hold = current_shape
        else:
            # Put in hold and get new piece
            player.hold = current_shape
            player.active = ActivePiece(
                shape=self.bag.get_next(),
                x=4, y=0, rot=0
            )
        
        # Check if new piece collides (game over)
        if TetrisGameLogic.check_collision(player.board, player.active):
            player.game_over = True
            await self.handle_player_loss(player)
    
    async def lock_and_spawn(self, player: PlayerState):
        """Lock current piece and spawn new one"""
        # Lock piece
        TetrisGameLogic.lock_piece(player.board, player.active)
        
        # Clear lines
        lines_cleared = TetrisGameLogic.clear_lines(player.board)
        if lines_cleared > 0:
            player.lines += lines_cleared
            player.score += lines_cleared ** 2 * 100
            
            # Check win condition (20 lines)
            if player.lines >= 20:
                await self.handle_player_win(player)
                return
        
        # Spawn new piece
        player.active = ActivePiece(
            shape=self.bag.get_next(),
            x=4, y=0, rot=0
        )
        
        # Check game over
        if TetrisGameLogic.check_collision(player.board, player.active):
            player.game_over = True
            await self.handle_player_loss(player)
    
    async def start_game(self):
        """Start the game for all players"""
        if self.game_started:
            return
        
        self.game_started = True
        logging.info(f"[Game] Starting game for room {self.room_id}")
        
        # Spawn initial pieces for all players
        for player in self.players.values():
            player.active = ActivePiece(
                shape=self.bag.get_next(),
                x=4, y=0, rot=0
            )
        
        # Start game loop
        asyncio.create_task(self.game_loop())
        
        # Notify all players game started
        start_msg = {
            "type": "GAME_START",
            "timestamp": int(time.time() * 1000)
        }
        await self.broadcast(start_msg)
    
    async def game_loop(self):
        """Main game loop - handles gravity and periodic updates"""
        while not self.game_over:
            current_time = time.time()
            
            # Apply gravity
            if current_time - self.last_drop_time >= self.drop_interval:
                self.last_drop_time = current_time
                await self.apply_gravity()
            
            # Send periodic snapshots
            if current_time - self.last_snapshot_time >= self.snapshot_interval:
                self.last_snapshot_time = current_time
                for player in self.players.values():
                    if not player.game_over:
                        await self.broadcast_snapshot(player)
            
            self.tick += 1
            await asyncio.sleep(0.016)  # ~60 FPS
    
    async def apply_gravity(self):
        """Apply gravity to all active pieces"""
        for player in self.players.values():
            if player.game_over or not player.active:
                continue
            
            player.active.y += 1
            
            if TetrisGameLogic.check_collision(player.board, player.active):
                player.active.y -= 1
                await self.lock_and_spawn(player)
    
    async def broadcast_snapshot(self, player: PlayerState):
        """Broadcast player state snapshot to all clients"""
        if not player.active:
            return
        
        snapshot = {
            "type": "SNAPSHOT",
            "tick": self.tick,
            "username": player.username,  # Changed from userId
            "boardRLE": TetrisGameLogic.compress_board(player.board),
            "active": {
                "shape": player.active.shape,
                "x": player.active.x,
                "y": player.active.y,
                "rot": player.active.rot
            },
            "hold": player.hold,
            "next": self.bag.peek_next(3),
            "score": player.score,
            "lines": player.lines,
            "level": player.level,
            "at": int(time.time() * 1000)
        }
        
        await self.broadcast(snapshot)
    
    async def handle_player_win(self, winner: PlayerState):
        """Handle player winning (cleared 20 lines)"""
        self.game_over = True
        
        result_msg = {
            "type": "GAME_OVER",
            "winner": winner.username,
            "reason": "lines_cleared",
            "finalScores": {
                p.username: {"score": p.score, "lines": p.lines}
                for p in self.players.values()
            }
        }
        
        await self.broadcast(result_msg)
        logging.info(f"[Game] Player {winner.username} won room {self.room_id}")
    
    async def handle_player_loss(self, loser: PlayerState):
        """Handle player losing (topped out)"""
        # Check if other player is still alive
        other_players = [p for p in self.players.values() if not p.game_over]
        
        if len(other_players) == 1:
            winner = other_players[0]
            self.game_over = True
            
            result_msg = {
                "type": "GAME_OVER",
                "winner": winner.username,
                "reason": "opponent_topped_out",
                "finalScores": {
                    p.username: {"score": p.score, "lines": p.lines}
                    for p in self.players.values()
                }
            }
            
            await self.broadcast(result_msg)
            logging.info(f"[Game] Player {winner.username} won room {self.room_id} (opponent topped out)")
    
    async def broadcast(self, message: dict):
        """Broadcast message to all connected players"""
        disconnected = []
        for username, player in self.players.items():
            try:
                await self.send_message(player.writer, message)
            except Exception as e:
                logging.error(f"[Game] Failed to send to {player.username}: {e}")
                disconnected.append(username)
        
        # Clean up disconnected players
        for username in disconnected:
            del self.players[username]
    
    async def send_message(self, writer, msg):
        """Send message using the standard protocol with length header"""
        try:
            if isinstance(msg, dict):
                msg = json.dumps(msg)
            
            message = msg.encode('utf-8')
            length = len(message)
            
            # If message too long, log error
            if length > config.MAX_MSG_SIZE:
                logging.error(f"[Game] Message length {length} bytes exceeds {config.MAX_MSG_SIZE}")
                return
            
            # Format message 
            # [4-byte length (uint32, network byte order)] [body: length bytes (custom format)]
            header = struct.pack('!I', length)
            writer.write(header + message)
            
            await writer.drain()
            logging.debug(f"[Game] Sent message: {msg}")
        except Exception as e:
            logging.error(f"[Game] Failed to send message: {e}")
    
    async def unpack_message(self, reader):
        """Unpack message using the standard protocol with length header"""
        try:
            header = await reader.readexactly(4)
            (length,) = struct.unpack('!I', header)
            
            # Ignore oversized body and report error
            if length > config.MAX_MSG_SIZE:
                logging.warning(f"[Game] Received oversized message ({length} bytes)")
                await reader.readexactly(length)
                return None
            
            body = await reader.readexactly(length)
            return body.decode('utf-8')
        
        except asyncio.IncompleteReadError:
            # Normal disconnection
            logging.info("[Game] Connection closed by peer")
            return None
        
        except Exception as e:
            logging.error(f"[Game] Failed to receive message: {e}")
            return None


# ============================================================================
# MAIN ENTRY POINT
# ============================================================================

async def find_available_port(start_port: int, end_port: int, max_retries: int = 50) -> Optional[int]:
    """
    Try to find an available port within the specified range.
    Returns the port number if successful, None otherwise.
    """
    attempted_ports = set()
    
    for attempt in range(max_retries):
        # Generate random port within range, avoiding already tried ports
        available_ports = [p for p in range(start_port, end_port + 1) if p not in attempted_ports]
        
        if not available_ports:
            logging.error(f"[Game] All ports in range exhausted after {attempt} attempts")
            return None
        
        port = random.choice(available_ports)
        attempted_ports.add(port)
        
        try:
            # Try to bind to the port
            server = await asyncio.start_server(
                lambda r, w: None,  # Dummy handler
                '0.0.0.0',
                port
            )
            
            # If successful, close it immediately and return the port
            server.close()
            await server.wait_closed()
            
            logging.info(f"[Game] Found available port: {port}")
            return port
            
        except OSError as e:
            if e.errno == 98 or e.errno == 48:  # Address already in use (Linux/Mac)
                logging.debug(f"[Game] Port {port} already in use, trying another...")
                continue
            else:
                logging.error(f"[Game] Unexpected error binding to port {port}: {e}")
                continue
        except Exception as e:
            logging.error(f"[Game] Unexpected error testing port {port}: {e}")
            continue
    
    logging.error(f"[Game] Failed to find available port after {max_retries} attempts")
    return None


async def start_game_server(room_id: str, port_range: Optional[Tuple[int, int]] = None) -> Optional[Tuple[asyncio.Server, int]]:
    """
    Start game server for a specific room.
    Tries to find an available port within the specified range.
    
    Returns: (server, port) if successful, None if failed
    """
    # Use config port range if not specified
    if port_range is None:
        if hasattr(config, 'GAME_PORT_RANGE'):
            port_range = config.GAME_PORT_RANGE
        else:
            # Fallback to P2P port range if GAME_PORT_RANGE not defined
            port_range = config.P2P_PORT_RANGE
    
    start_port, end_port = port_range
    
    # Find available port
    available_port = await find_available_port(start_port, end_port)
    
    if available_port is None:
        logging.error(f"[Game] Could not find available port for room {room_id}")
        return None
    
    # Create game server instance
    game_server = TetrisGameServer(room_id)
    game_server.host_port = available_port
    
    try:
        # Start the actual game server
        server = await asyncio.start_server(
            game_server.handle_client,
            '0.0.0.0',
            available_port
        )
        
        addr = server.sockets[0].getsockname()
        logging.info(f"[Game] Game server for room {room_id} running on {addr}")
        
        return server, available_port
        
    except Exception as e:
        logging.error(f"[Game] Failed to start game server on port {available_port}: {e}")
        return None


async def run_game_server(room_id: str, port_range: Optional[Tuple[int, int]] = None):
    """
    Convenience function to start and run game server until completion.
    """
    result = await start_game_server(room_id, port_range)
    
    if result is None:
        logging.error(f"[Game] Failed to start game server for room {room_id}")
        return
    
    server, port = result
    
    async with server:
        try:
            await server.serve_forever()
        except KeyboardInterrupt:
            logging.info(f"[Game] Game server for room {room_id} interrupted")
        finally:
            server.close()
            await server.wait_closed()
            logging.info(f"[Game] Game server for room {room_id} closed")


if __name__ == "__main__":
    logging.basicConfig(
        level=logging.INFO,
        format='%(asctime)s [%(levelname)s] %(message)s'
    )
    
    # Example usage
    asyncio.run(run_game_server("test_room"))