#!/usr/bin/env python3
"""
Multiplayer Tetris Game Server

Handles real-time 2-player tetris with:
- Server authority (all game logic on server)
- Client sends input events
- Server broadcasts state snapshots
- Length-prefixed framing protocol
"""

import asyncio
import json
import logging
import random
import struct
import time
from typing import Dict, List, Optional, Tuple

import config
import utils as ut
from game_templates import tetris as classic_tetris

# ============================================================================
# Tetris Game Logic (leveraging game_templates/tetris.py)
# ============================================================================


def _decode_shape(rot_code: str) -> List[Tuple[int, int]]:
    """Convert 4x4 hex mask into coordinate offsets (dx, dy)."""
    coords = []
    for char in rot_code:
        idx = int(char, 16)
        y, x = divmod(idx, 4)
        coords.append((x, y))
    return coords


class TetrisGameLogic:
    """Backwards compatible shim exposing SHAPES like the client expects."""
    SHAPES = {
        shape: [_decode_shape(rot) for rot in rots]
        for shape, rots in classic_tetris.shapes.items()
    }

Piece = classic_tetris.Piece
get_piece_blocks = classic_tetris.get_piece_blocks
move_piece = classic_tetris.move_piece
get_wall_kicks = classic_tetris.get_wall_kicks


def piece_fits(field: List[List[int]], piece: Piece, width: int = 10, height: int = 20) -> bool:
    """Wrapper for template's collision check (width/height kept for compatibility)."""
    return classic_tetris.piece_fits(field, piece)


def random_shape_bag():
    """Generator that yields random shapes following 7-bag rule from template"""
    return classic_tetris.random_shape_bag()


class TetrisBoard:
    """Single player's tetris board and game state"""
    
    def __init__(self, width: int = 10, height: int = 20, seed: int = None):
        self.width = width
        self.height = height
        self.seed = seed
        
        # Initialize RNG with seed for consistency
        if seed is not None:
            random.seed(seed)
        
        # Initialize shape generator BEFORE getting pieces
        self._shape_gen = random_shape_bag()
        
        self.field = [[0 for _ in range(width)] for _ in range(height)]
        self.next_pieces: List[str] = []
        self._fill_preview()
        self.piece = self._get_next_piece()
        self._fill_preview()
        self.hold_piece = None
        self.can_hold = True
        
        self.score = 0
        self.lines = 0
        self.game_over = False
        
        # Gravity
        self.level = 1
        self.gravity_ticks = 0
        self.gravity_per_frame = 1  # Pixels to drop per frame
    
    def _fill_preview(self) -> None:
        while len(self.next_pieces) < 3:
            self.next_pieces.append(next(self._shape_gen))
    
    def _spawn_piece(self, shape: str) -> Piece:
        return Piece(shape=shape, x=self.width // 2 - 2, y=self.height - 1)
    
    def _get_next_piece(self) -> Piece:
        """Get next piece centered at top"""
        self._fill_preview()
        shape = self.next_pieces.pop(0)
        self._fill_preview()
        return self._spawn_piece(shape)
    
    def _place_new_piece(self) -> None:
        """Place a new piece; set game_over if it doesn't fit"""
        self.piece = self._get_next_piece()
        self.can_hold = True
        if not classic_tetris.piece_fits(self.field, self.piece):
            self.game_over = True
    
    def _freeze_piece(self) -> None:
        """Lock piece into field"""
        for x, y in get_piece_blocks(self.piece):
            if 0 <= y < self.height:
                self.field[y][x] = 1
    
    def _clear_lines(self) -> int:
        """Clear full lines and return number cleared"""
        new_field = [row for row in self.field if not all(row)]
        num_cleared = self.height - len(new_field)
        self.field = new_field + [[0] * self.width for _ in range(num_cleared)]
        
        if num_cleared > 0:
            self.lines += num_cleared
            self.score += num_cleared * 100
        
        return num_cleared
    
    def _move(self, *, rot: int = 0, dx: int = 0, dy: int = 0) -> bool:
        """Move/rotate piece. Returns True if movement succeeded"""
        if rot:
            candidates = get_wall_kicks(self.piece, rot=rot)
        else:
            candidates = [move_piece(self.piece, dx=dx, dy=dy)]
        
        moved = False
        for candidate in candidates:
            if piece_fits(self.field, candidate, self.width, self.height):
                self.piece = candidate
                moved = True
                break
        
        # If trying to move down and failed, lock piece
        if dy == -1 and not moved:
            self._freeze_piece()
            self._clear_lines()
            self._place_new_piece()
        
        return moved
    
    def apply_gravity(self) -> None:
        """Apply gravity (automatic drop)"""
        self._move(dy=-1)
    
    def hold(self) -> None:
        """Hold current piece"""
        if not self.can_hold:
            return
        
        current_shape = self.piece.shape
        if self.hold_piece is None:
            self.hold_piece = current_shape
            self.piece = self._get_next_piece()
        else:
            self.hold_piece, swap_shape = current_shape, self.hold_piece
            self.piece = self._spawn_piece(swap_shape)
            if not classic_tetris.piece_fits(self.field, self.piece):
                self.game_over = True
                return
        self.can_hold = False
    
    def rotate_cw(self) -> None:
        """Rotate clockwise"""
        self._move(rot=1)
    
    def rotate_ccw(self) -> None:
        """Rotate counter-clockwise"""
        self._move(rot=-1)
    
    def move_left(self) -> None:
        """Move left"""
        self._move(dx=-1)
    
    def move_right(self) -> None:
        """Move right"""
        self._move(dx=1)
    
    def soft_drop(self) -> None:
        """Soft drop (accelerated gravity)"""
        self._move(dy=-1)
    
    def hard_drop(self) -> None:
        """Hard drop (instant to bottom)"""
        while self._move(dy=-1):
            self.score += 2
    
    def board_to_rle(self) -> str:
        """Encode board as RLE string (pipe-separated rows) top-to-bottom"""
        rows = []
        for row in reversed(self.field):
            row_str = ''.join(str(cell) for cell in row)
            rows.append(row_str)
        return '|'.join(rows)
    
    def get_snapshot(self, user_id: str, tick: int, username: Optional[str] = None) -> dict:
        """Generate state snapshot for broadcasting"""
        active = None
        if self.piece:
            active = {
                'shape': self.piece.shape,
                'x': self.piece.x,
                'y': self.piece.y,
                'rot': self.piece.rot
            }
        
        client_y = self.height - 1 - self.piece.y if self.piece else 0
        return {
            'type': 'SNAPSHOT',
            'tick': tick,
            'userId': user_id,
            'username': username or user_id,
            'boardRLE': self.board_to_rle(),
            'active': None if not active else {
                **active,
                'y': client_y
            },
            'hold': self.hold_piece,
            'next': self.next_pieces[:3],
            'score': self.score,
            'lines': self.lines,
            'level': self.level,
            'gameOver': self.game_over,
            'ts': int(time.time() * 1000)
        }


# ============================================================================
# Multiplayer Game Server
# ============================================================================

class GameServerContext:
    """Context for a 2-player game instance"""
    
    def __init__(self, room_id: str, player_ids: List[str], seed: int):
        self.room_id = room_id
        self.player_ids = player_ids
        self.seed = seed
        
        # Player connections
        self.players: Dict[str, asyncio.StreamWriter] = {}
        self.usernames: Dict[str, str] = {}
        self.ready_count = 0
        self.tick_task: Optional[asyncio.Task] = None
        self.game_start_event = asyncio.Event()
        
        # Game state
        self.boards: Dict[str, TetrisBoard] = {}
        for pid in player_ids:
            self.boards[pid] = TetrisBoard(seed=seed)
        
        self.tick = 0
        self.game_active = False
        self.game_start_time = None
        self.game_end_time = None
        self.winner = None
        self.game_over_reason = None
        
        # Timing
        self.gravity_interval = 500  # ms
        self.snapshot_interval = 100  # ms
        
        self.lock = asyncio.Lock()
    
    def is_full(self) -> bool:
        """Check if both players connected"""
        return len(self.players) == 2
    
    async def wait_for_both_players(self) -> bool:
        """Wait up to 30s for both players to connect"""
        start = time.time()
        while not self.is_full() and time.time() - start < 30:
            await asyncio.sleep(0.1)
        return self.is_full()
    
    async def start_game(self) -> None:
        """Start the actual game"""
        async with self.lock:
            if self.game_active:
                return
            self.game_active = True
            self.game_start_time = time.time()
            self.tick = 0
            self.game_start_event.set()
            logging.info(f"[Game] Room {self.room_id} game starting")


async def handle_player_connection(reader: asyncio.StreamReader, 
                                   writer: asyncio.StreamWriter,
                                   game_ctx: GameServerContext) -> None:
    """Handle a single player connection"""
    addr = writer.get_extra_info('peername')
    username = None
    user_id = None
    
    try:
        # Receive JOIN message
        join_data = await ut.unpack_message(reader)
        if not join_data:
            logging.error(f"[Game] Failed to receive JOIN from {addr}")
            return
        
        try:
            join_msg = json.loads(join_data)
            username = join_msg.get('username')
            if not username:
                raise ValueError("No username in JOIN")
            
            # Find matching player ID
            async with game_ctx.lock:
                for pid in game_ctx.player_ids:
                    if pid not in game_ctx.players:
                        user_id = pid
                        game_ctx.players[user_id] = writer
                        game_ctx.usernames[user_id] = username
                        break
            
            if not user_id:
                logging.warning(f"[Game] Room full, rejecting {username}")
                await ut.send_message(writer, {'type': 'ERROR', 'message': 'Game full'})
                return
            
            logging.info(f"[Game] Player {username} ({user_id}) connected from {addr}")
            
            # Send WELCOME once both players connected
            while not game_ctx.is_full():
                await asyncio.sleep(0.1)
            
            welcome_msg = {
                'type': 'WELCOME',
                'role': 'P1' if user_id == game_ctx.player_ids[0] else 'P2',
                'seed': game_ctx.seed,
                'bagRule': '7bag',
                'gravityPlan': {
                    'mode': 'fixed',
                    'dropMs': game_ctx.gravity_interval
                }
            }
            await ut.send_message(writer, welcome_msg)
            logging.info(f"[Game] Sent WELCOME to {username}")
            
            # Wait for READY
            ready_data = await ut.unpack_message(reader)
            if ready_data:
                ready_msg = json.loads(ready_data)
                if ready_msg.get('type') == 'READY':
                    async with game_ctx.lock:
                        game_ctx.ready_count += 1
                    logging.info(f"[Game] Player {username} ready ({game_ctx.ready_count}/2)")
            
            # Start game when both ready
            while game_ctx.ready_count < 2 and not game_ctx.game_active:
                await asyncio.sleep(0.1)
            
            # If this is the second player and game isn't active yet, start it
            if not game_ctx.game_active and game_ctx.ready_count >= 2:
                await game_ctx.start_game()
            
            # Game loop: receive inputs and send snapshots
            await game_player_loop(reader, writer, game_ctx, user_id, username)
        
        except json.JSONDecodeError as e:
            logging.error(f"[Game] JSON decode error from {addr}: {e}")
        except Exception as e:
            logging.error(f"[Game] Error handling player from {addr}: {e}")
    
    finally:
        if user_id:
            async with game_ctx.lock:
                if user_id in game_ctx.players:
                    del game_ctx.players[user_id]
                if user_id in game_ctx.usernames:
                    del game_ctx.usernames[user_id]
            logging.info(f"[Game] Player {username} ({user_id}) disconnected")
        
        try:
            writer.close()
            await writer.wait_closed()
        except Exception:
            pass


async def game_player_loop(reader: asyncio.StreamReader,
                          writer: asyncio.StreamWriter,
                          game_ctx: GameServerContext,
                          user_id: str,
                          username: str) -> None:
    """Main loop for a player during active game"""
    
    input_task = asyncio.create_task(receive_player_input(reader, game_ctx, user_id))
    
    try:
        while game_ctx.game_active and not game_ctx.boards[user_id].game_over:
            await asyncio.sleep(0.016)  # ~60 FPS
    finally:
        input_task.cancel()


async def receive_player_input(reader: asyncio.StreamReader,
                              game_ctx: GameServerContext,
                              user_id: str) -> None:
    """Receive and process player inputs"""
    try:
        while game_ctx.game_active:
            input_data = await ut.unpack_message(reader)
            if not input_data:
                break
            
            try:
                msg = json.loads(input_data)
                if msg.get('type') != 'INPUT':
                    continue
                
                action = msg.get('action', '').upper()
                board = game_ctx.boards[user_id]
                
                # Apply action to board
                if action == 'LEFT':
                    board.move_left()
                elif action == 'RIGHT':
                    board.move_right()
                elif action == 'SOFT_DROP':
                    board.soft_drop()
                elif action == 'HARD_DROP':
                    board.hard_drop()
                elif action == 'CW':
                    board.rotate_cw()
                elif action == 'CCW':
                    board.rotate_ccw()
                elif action == 'HOLD':
                    board.hold()
                
                logging.debug(f"[Game] Player {user_id} action: {action}")
            
            except json.JSONDecodeError:
                pass
    
    except asyncio.CancelledError:
        pass


async def game_tick_loop(game_ctx: GameServerContext) -> None:
    """Main game loop: gravity, snapshots, game-over detection"""
    try:
        while game_ctx.game_active:
            game_ctx.tick += 1
            current_time = time.time() - game_ctx.game_start_time
            
            # Apply gravity periodically
            if game_ctx.tick % max(1, int(game_ctx.gravity_interval / 16)) == 0:
                for user_id in game_ctx.player_ids:
                    board = game_ctx.boards[user_id]
                    if not board.game_over:
                        board.apply_gravity()
            
            # Send snapshots periodically
            if game_ctx.tick % max(1, int(game_ctx.snapshot_interval / 16)) == 0:
                await broadcast_snapshots(game_ctx)
            
            # Check for game over
            game_overs = sum(1 for b in game_ctx.boards.values() if b.game_over)
            if game_overs > 0:
                game_ctx.game_active = False
                game_ctx.game_end_time = time.time()
                await end_game(game_ctx)
                break
            
            await asyncio.sleep(0.016)  # ~60 FPS
    
    except asyncio.CancelledError:
        pass


async def broadcast_snapshots(game_ctx: GameServerContext) -> None:
    """Send game state snapshots to all connected players"""
    snapshots = {}
    for user_id in game_ctx.player_ids:
        board = game_ctx.boards[user_id]
        username = game_ctx.usernames.get(user_id, user_id)
        snapshots[user_id] = board.get_snapshot(user_id, game_ctx.tick, username=username)
    
    # Send each player their own snapshot + opponent's
    for user_id in game_ctx.players:
        try:
            # Send own state
            await ut.send_message(game_ctx.players[user_id], snapshots[user_id])
            
            # Send opponent state
            opponent_id = game_ctx.player_ids[1] if game_ctx.player_ids[0] == user_id else game_ctx.player_ids[0]
            if opponent_id in snapshots:
                await ut.send_message(game_ctx.players[user_id], snapshots[opponent_id])
        
        except Exception as e:
            logging.error(f"[Game] Failed to send snapshot to {user_id}: {e}")


async def end_game(game_ctx: GameServerContext) -> None:
    """Handle game end and determine winner"""
    results = []
    
    for user_id in game_ctx.player_ids:
        board = game_ctx.boards[user_id]
        results.append({
            'userId': user_id,
            'score': board.score,
            'lines': board.lines,
            'gameOver': board.game_over
        })
    
    # Determine winner: whoever didn't game over, or highest score
    active_players = [r for r in results if not r['gameOver']]
    if len(active_players) == 1:
        game_ctx.winner = active_players[0]['userId']
        game_ctx.game_over_reason = 'opponent_topped_out'
    elif active_players:
        winner = max(active_players, key=lambda x: x['score'])
        game_ctx.winner = winner['userId']
        game_ctx.game_over_reason = 'highest_score'
    else:
        # Both topped out, highest score wins
        winner = max(results, key=lambda x: x['score'])
        game_ctx.winner = winner['userId']
        game_ctx.game_over_reason = 'both_topped_out'
    
    # Send end message
    end_msg = {
        'type': 'END',
        'winner': game_ctx.winner,
        'reason': game_ctx.game_over_reason,
        'results': results,
        'duration': game_ctx.game_end_time - game_ctx.game_start_time
    }
    
    for user_id in game_ctx.players:
        try:
            await ut.send_message(game_ctx.players[user_id], end_msg)
        except Exception as e:
            logging.error(f"[Game] Failed to send END to {user_id}: {e}")
    
    logging.info(f"[Game] Game ended. Winner: {game_ctx.winner}. Results: {results}")


async def run_game_server(room_id: str, player_ids: List[str], host: str = '0.0.0.0', port: int = None) -> Tuple[asyncio.Server, int, asyncio.Task, GameServerContext]:
    """Run a game server instance for one room"""
    
    if port is None:
        port = ut.get_game_port()
    
    # Create game context
    seed = random.randint(100000, 999999)
    game_ctx = GameServerContext(room_id, player_ids, seed)
    
    async def handle_connection(reader, writer):
        await handle_player_connection(reader, writer, game_ctx)
    
    # Start server
    server = await asyncio.start_server(handle_connection, host, port)
    
    async def tick_runner():
        try:
            await game_ctx.game_start_event.wait()
            await game_tick_loop(game_ctx)
        except asyncio.CancelledError:
            pass
    
    tick_task = asyncio.create_task(tick_runner())
    game_ctx.tick_task = tick_task
    
    logging.info(f"[Game] Game server started for room {room_id} on port {port}")
    
    return server, port, tick_task, game_ctx


# ============================================================================
# Integration with Lobby Server
# ============================================================================

async def start_game_server(room_id: str, host_bind: str = '0.0.0.0'):
    """
    Called by lobby server to start a new game instance.
    Returns (server, port, tick_task, game_ctx) tuple or None on failure.
    """
    try:
        port = ut.get_game_port()
        
        # Get player IDs (using room_id for now; could lookup from DB)
        player_ids = [f'P1_{room_id}', f'P2_{room_id}']
        
        # Create and return server with all necessary info
        result = await run_game_server(room_id, player_ids, host_bind, port)
        
        if result:
            # Return all components so lobby can manage them
            return result
        else:
            return None
    
    except Exception as e:
        logging.error(f"[Game] Failed to start game server for room {room_id}: {e}")
        return None


# ============================================================================
# Main
# ============================================================================

async def main():
    """Test/demo: run a single game instance"""
    ut.init_logging()
    logging.info("[Game] Game server module loaded")
    
    # This is primarily imported; main() is rarely called directly
    await asyncio.Future()  # Run forever


if __name__ == "__main__":
    logging.basicConfig(
        level=logging.INFO,
        format='%(asctime)s [%(levelname)s] %(message)s'
    )
    asyncio.run(main())
