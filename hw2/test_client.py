"""
Test client for directly connecting to the Tetris game server.
This bypasses the lobby system and connects straight to the game server.

Usage:
    python test_game_client.py <username> <game_server_ip> <game_server_port>

Example:
    python test_game_client.py Alice localhost 64050
"""

import asyncio
import json
import struct
import sys
import logging
import random
from datetime import datetime
import config

# Configure logging
logging.basicConfig(
    level=logging.INFO,
    format='%(asctime)s [%(levelname)s] %(message)s'
)

# Configuration
MAX_MSG_SIZE = 65536

class TestGameClient:
    def __init__(self, username, server_ip, server_port):
        self.username = username
        self.server_ip = server_ip
        self.server_port = server_port
        self.reader = None
        self.writer = None
        self.game_active = False
        self.input_seq = 0
        
        # Game state
        self.local_state = {}
        self.opponent_state = {}
    
    async def send_message(self, msg):
        """Send message using length-prefixed protocol"""
        try:
            if isinstance(msg, dict):
                msg = json.dumps(msg)
            
            message = msg.encode('utf-8')
            length = len(message)
            
            if length > MAX_MSG_SIZE:
                logging.error(f"Message length {length} bytes exceeds {MAX_MSG_SIZE}")
                return
            
            header = struct.pack('!I', length)
            self.writer.write(header + message)
            await self.writer.drain()
            logging.debug(f"Sent: {msg}")
        except Exception as e:
            logging.error(f"Failed to send message: {e}")
    
    async def unpack_message(self):
        """Receive message using length-prefixed protocol"""
        try:
            header = await self.reader.readexactly(4)
            (length,) = struct.unpack('!I', header)
            
            if length > MAX_MSG_SIZE:
                logging.warning(f"Received oversized message ({length} bytes)")
                await self.reader.readexactly(length)
                return None
            
            body = await self.reader.readexactly(length)
            return body.decode('utf-8')
        
        except asyncio.IncompleteReadError:
            logging.info("Connection closed by server")
            return None
        except Exception as e:
            logging.error(f"Failed to receive message: {e}")
            return None
    
    async def connect(self):
        """Connect to game server"""
        try:
            logging.info(f"Connecting to game server at {self.server_ip}:{self.server_port}...")
            self.reader, self.writer = await asyncio.open_connection(
                self.server_ip, 
                self.server_port
            )
            logging.info("✅ Connected successfully!")
            return True
        except Exception as e:
            logging.error(f"❌ Failed to connect: {e}")
            return False
    
    async def join_game(self):
        """Send JOIN message and wait for WELCOME"""
        # Send JOIN
        join_msg = {
            "type": "JOIN",
            "username": self.username
        }
        logging.info(f"Sending JOIN message for user: {self.username}")
        await self.send_message(join_msg)
        
        # Wait for WELCOME
        message = await self.unpack_message()
        if not message:
            logging.error("Failed to receive WELCOME message")
            return False
        
        try:
            welcome = json.loads(message)
            if welcome.get("type") == "WELCOME":
                print("\n" + "="*60)
                print("🎮 WELCOME TO TETRIS MULTIPLAYER 🎮")
                print("="*60)
                print(f"Role: {welcome.get('role')}")
                print(f"Seed: {welcome.get('seed')}")
                print(f"Bag Rule: {welcome.get('bagRule')}")
                print(f"Drop Speed: {welcome.get('gravityPlan', {}).get('dropMs')}ms")
                print("="*60 + "\n")
                
                logging.info(f"Received WELCOME - Role: {welcome.get('role')}")
                return True
            else:
                logging.error(f"Unexpected message type: {welcome.get('type')}")
                return False
        except json.JSONDecodeError as e:
            logging.error(f"Failed to parse WELCOME: {e}")
            return False
    
    async def send_input(self, action):
        """Send input action to server"""
        self.input_seq += 1
        
        input_msg = {
            "type": "INPUT",
            "username": self.username,
            "seq": self.input_seq,
            "ts": int(asyncio.get_event_loop().time() * 1000),
            "action": action
        }
        
        await self.send_message(input_msg)
        logging.info(f"📤 Sent INPUT: {action}")
    
    async def handle_server_messages(self):
        """Listen for messages from server"""
        self.game_active = True
        
        while self.game_active:
            message = await self.unpack_message()
            if not message:
                self.game_active = False
                break
            
            try:
                msg = json.loads(message)
                msg_type = msg.get("type")
                
                if msg_type == "SNAPSHOT":
                    await self.handle_snapshot(msg)
                
                elif msg_type == "GAME_START":
                    print("\n🚀 GAME STARTED! 🚀\n")
                    logging.info("Game has started")
                
                elif msg_type == "GAME_OVER":
                    await self.handle_game_over(msg)
                    self.game_active = False
                
                elif msg_type == "TEMPO":
                    drop_ms = msg.get("dropMs")
                    print(f"⚡ Speed increased! Now {drop_ms}ms per drop")
                    logging.info(f"Tempo update: {drop_ms}ms")
                
                else:
                    logging.warning(f"Unknown message type: {msg_type}")
            
            except json.JSONDecodeError as e:
                logging.error(f"Failed to parse message: {e}")
    
    async def handle_snapshot(self, msg):
        """Handle SNAPSHOT message"""
        username = msg.get("username")
        tick = msg.get("tick")
        score = msg.get("score")
        lines = msg.get("lines")
        level = msg.get("level")
        active = msg.get("active", {})
        
        if username == self.username:
            self.local_state = msg
            status = f"YOU"
        else:
            self.opponent_state = msg
            status = f"OPP"
        
        # Print compact state update
        print(f"[{status}] Tick:{tick:4d} | Score:{score:5d} | Lines:{lines:2d} | "
              f"Active:{active.get('shape','?')} at ({active.get('x',0)},{active.get('y',0)})")
    
    async def handle_game_over(self, msg):
        """Handle GAME_OVER message"""
        winner = msg.get("winner")
        reason = msg.get("reason")
        final_scores = msg.get("finalScores", {})
        
        print("\n" + "="*60)
        print("🏁 GAME OVER 🏁")
        print("="*60)
        print(f"Winner: {winner}")
        print(f"Reason: {reason.replace('_', ' ').title()}")
        print("\nFinal Scores:")
        for player, stats in final_scores.items():
            emoji = "👑" if player == winner else "  "
            print(f"{emoji} {player:15s}: {stats['score']:6d} points | {stats['lines']:3d} lines")
        print("="*60 + "\n")
        
        logging.info(f"Game over - Winner: {winner}")
    
    async def simulate_random_inputs(self):
        """Simulate random inputs for testing (auto-play mode)"""
        actions = ["LEFT", "RIGHT", "CW", "SOFT_DROP", "HARD_DROP"]
        
        print("\n🤖 AUTO-PLAY MODE ACTIVATED")
        print("Sending random inputs every 0.5-2 seconds...\n")
        
        await asyncio.sleep(2)  # Wait for game to start
        
        while self.game_active:
            # Random action
            action = random.choice(actions)
            await self.send_input(action)
            
            # Random delay
            await asyncio.sleep(random.uniform(0.5, 2.0))
    
    async def interactive_input(self):
        """Interactive mode - wait for user commands"""
        print("\n⌨️  INTERACTIVE MODE")
        print("Commands:")
        print("  left/l    - Move left")
        print("  right/r   - Move right")
        print("  cw        - Rotate clockwise")
        print("  ccw       - Rotate counter-clockwise")
        print("  down/d    - Soft drop")
        print("  drop/space- Hard drop")
        print("  hold/h    - Hold piece")
        print("  quit/q    - Quit game")
        print()
        
        loop = asyncio.get_event_loop()
        
        while self.game_active:
            try:
                # Get input without blocking
                user_input = await loop.run_in_executor(
                    None, 
                    lambda: input("> ").strip().lower()
                )
                
                if user_input in ["quit", "q"]:
                    print("Quitting...")
                    self.game_active = False
                    break
                
                # Map input to action
                action_map = {
                    "left": "LEFT", "l": "LEFT",
                    "right": "RIGHT", "r": "RIGHT",
                    "cw": "CW",
                    "ccw": "CCW",
                    "down": "SOFT_DROP", "d": "SOFT_DROP",
                    "drop": "HARD_DROP", "space": "HARD_DROP",
                    "hold": "HOLD", "h": "HOLD"
                }
                
                action = action_map.get(user_input)
                if action:
                    await self.send_input(action)
                else:
                    print(f"Unknown command: {user_input}")
            
            except EOFError:
                break
            except Exception as e:
                logging.error(f"Input error: {e}")
    
    async def run(self, mode="auto"):
        """Main run loop"""
        # Connect
        if not await self.connect():
            return
        
        # Join game
        if not await self.join_game():
            return
        
        # Start message handler
        message_task = asyncio.create_task(self.handle_server_messages())
        
        # Start input handler based on mode
        if mode == "auto":
            input_task = asyncio.create_task(self.simulate_random_inputs())
        else:
            input_task = asyncio.create_task(self.interactive_input())
        
        # Wait for either task to complete
        done, pending = await asyncio.wait(
            [message_task, input_task],
            return_when=asyncio.FIRST_COMPLETED
        )
        
        # Cancel remaining tasks
        for task in pending:
            task.cancel()
        
        # Close connection
        if self.writer:
            self.writer.close()
            await self.writer.wait_closed()
        
        print("\n👋 Disconnected from game server")
        logging.info("Client shut down")


async def main():
    """Main entry point"""
    # Parse command line arguments
    if len(sys.argv) < 1:
        print("Usage: python test_game_client.py <username> <server_ip> <server_port> [mode]")
        print()
        print("Arguments:")
        print("  username    - Your player name")
        print("  server_ip   - Game server IP (e.g., localhost)")
        print("  server_port - Game server port (e.g., 64050)")
        print("  mode        - 'auto' for auto-play or 'manual' for interactive (default: auto)")
        print()
        print("Examples:")
        print("  python test_game_client.py Alice localhost 64050")
        print("  python test_game_client.py Bob 192.168.1.100 64050 manual")
        sys.exit(1)
    
    username = sys.argv[1]
    server_ip = config.HOST
    server_port = 52274
    mode = sys.argv[4] if len(sys.argv) > 4 else "auto"
    
    if mode not in ["auto", "manual"]:
        print(f"Invalid mode: {mode}. Use 'auto' or 'manual'")
        sys.exit(1)
    
    print("\n" + "="*60)
    print("🎮 TETRIS TEST CLIENT 🎮")
    print("="*60)
    print(f"Username: {username}")
    print(f"Server: {server_ip}:{server_port}")
    print(f"Mode: {mode.upper()}")
    print("="*60 + "\n")
    
    client = TestGameClient(username, server_ip, server_port)
    
    try:
        await client.run(mode)
    except KeyboardInterrupt:
        print("\n\n⚠️  Interrupted by user")
        logging.info("Interrupted by user")
    except Exception as e:
        logging.error(f"Unexpected error: {e}", exc_info=True)


if __name__ == "__main__":
    try:
        asyncio.run(main())
    except KeyboardInterrupt:
        print("\nExiting...")