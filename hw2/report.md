# HW2 Report

## Overview
- Centralized lobby, mock DB server, and per-room authoritative game servers built on raw TCP with a length-prefixed framing protocol.
- Clients are CLI-driven with optional pygame/Tk rendering; all game logic, matchmaking, and persistence stay on the servers.
- Two-player Tetris matches (no garbage lines) with spectator support and server-side authority over gravity, bag order, scoring, and end-of-game resolution.

## Components
### Mock Database Server (`database.py`)
- TCP + JSON over the length-prefixed framing; enforced in `utils.py` (`send_message`, `unpack_message`) with 4-byte big-endian headers and a 64 KiB cap (`config.MAX_MSG_SIZE`).
- Commands: `REGISTER <username> <password>`, `LOGIN <username> <password> <ip> <port>`, `LOGOUT <username>`, `CREATE_ROOM <creator> <public|private>`, `INVITE_PLAYER <target> <room_id> <inviter>`, `ACCEPT <inviter> <room_id> <username>`, `DECLINE ...`, `JOIN_ROOM <room_id> <username>`, `SHOW_STATUS <username>`, `CHECK <username>`, `SERVER_CLOSED <username>`.
- State guarded by asyncio locks in `config.tetris_server`: `users`, `online_users` (status + invites), `rooms`, `game_servers`. Persistence goes to `data.json` through `db_lock` on each mutation; passwords stored as SHA-256 hashes (`utils.hash`).
- Room validation: max 2 players, public vs private checks, prevents duplicate joins or joining in-progress games. Invites are tracked per-user; accept/decline prunes invite lists and updates stored JSON.

### Lobby Server (`server.py`)
- Accepts client connections, immediately opens a TCP connection to the DB server; forwards commands via `utils.send_command` and streams DB responses back to clients.
- Tracks logged-in clients in `config.targets` so it can push invites and game start info directly to each writer/reader.
- Maintains in-memory mirrors of `online_users` and `rooms` with locks; updates status on login/logout and when games end (`handle_game_over`).
- Room lifecycle: `CREATE_ROOM` marks creator as in-room; `JOIN_ROOM` success triggers `send_p2p_info`, which marks room `In Game`, sets players to `in_game`, launches a dedicated game server (`game.start_game_server`), and sends each player `p2p_info` containing `role`, `room_id`, `game_host`, and the chosen port.
- Spectators: `WATCH <room_id>` allowed for public rooms that are `In Game`; lobby returns `watch_info` with host/port for connecting in watcher mode.

### Game Server (`game.py`)
- Spawned per room with `start_game_server`; selects a port in `config.GAME_PORT_RANGE` and generates a shared RNG seed.
- Authoritative Tetris logic in `TetrisBoard` (10x20 grid, 7-bag via `game_templates/tetris.py`). Supports move left/right, soft/hard drop, CW/CCW rotate with wall kicks, hold (once per piece), gravity, and line clears; score += 100 per cleared line, hard-drop grants +2 per row.
- Handshake: client sends `JOIN` (or `WATCH`); once two players connect, each receives `WELCOME {role, seed, bagRule:"7bag", gravityPlan}`. Players reply `READY`; when both ready, the tick loop starts.
- Tick loop at ~60 FPS: applies gravity every `gravity_interval` (starts 500 ms; drops by 50 ms every 60 s to a 150 ms floor) and broadcasts `TEMPO` on changes. Snapshots broadcast every ~100 ms.
- Snapshots: for each player, server sends both their own and opponent state `{type: "SNAPSHOT", tick, userId, username, boardRLE, active{shape,x,y,rot}, hold, next[3], score, lines, level, gameOver, ts}`; watchers receive both players’ snapshots.
- Inputs: clients stream `{type:"INPUT", action}` where action ∈ {LEFT, RIGHT, SOFT_DROP, HARD_DROP, CW, CCW, HOLD}; all processed server-side for authority. No garbage/attack lines are generated.
- End condition: when any board reports `game_over`, game stops; winner is the surviving player, otherwise highest score as tie-breaker. `END {winner, reason, results, duration}` sent to players and watchers.

### Client (`client.py`)
- CLI shell for lobby commands: register/login/logout, create/join room, invite/accept/decline, check invites, show status, watch, exit. Uses the same framing helpers for lobby traffic.
- Game client: by default pygame GUI (falls back to text mode if pygame absent); renders own board plus opponent state and can open a Tk side window for the opponent. In watcher mode, it only subscribes to snapshots.

## Networking & Protocol
- **Framing**: `header=struct.pack('!I', len(body)); body` encoded UTF-8. Receiver uses `readexactly(4)` then `readexactly(length)`; rejects >64 KiB and logs oversized attempts.
- **Lobby/DB messages**: commands built as `{"sender": "client|lobby", "status": "command", "command": "LOGIN", "params": [...]}`; responses use `build_response` with `status` in {success,error,status,update,invite,invite_declined,p2p_info,watch_info} and optional `params`/`message` strings for display.
- **Game messages**: `JOIN`/`WATCH` → `WELCOME`; `READY`; gameplay `INPUT`; periodic `SNAPSHOT`; optional `TEMPO`; terminal `END`. All JSON strings wrapped in the framing header.

## Data Model & Files
- `data.json`:
  - `users`: `{ username: { password: <sha256> } }`
  - `online_users`: `{ username: { status, ip, port, invites[] } }`
  - `rooms`: `{ room_id: { creator, players[], type, status, game_type:"tetris", game_results{score,winner} } }`
- Configurable endpoints in `config.py`: lobby `PORT=52273`, DB `DB_PORT=52274`, game servers `GAME_PORT_RANGE=52275-52325`, host default `192.168.56.1` (adjustable), log files `logger.log` and `snapshots.log`.

## Synchronization & Consistency
- Shared RNG seed and 7-bag generation ensure identical piece order for both players and watchers.
- Server-authoritative logic: clients only send inputs; server simulates state and is the sole source of truth for scoring, gravity, and game-over detection.
- Periodic snapshots (~100 ms) keep clients synchronized and let spectators display both boards. Gravity changes are pushed via `TEMPO` so clients can adjust local pacing.

## Gameplay Rules & Flow
- Board 10×20; no garbage/attack lines. Controls: left/right, soft drop, hard drop, CW/CCW rotate with wall kicks, hold once per piece. Gravity accelerates over time based on the timed-step plan.
- Win condition: survival-first (opponent top-out) with highest-score fallback if both top out or remain; end message includes per-player `score` and `lines`.
- Opponent visibility: client renders opponent board and can open a dedicated Tk window; watchers subscribe to both players’ snapshots in read-only mode.

## Running Order (typical demo)
1) `python database.py` to start the DB server.
2) `python server.py` to start the lobby.
3) Run `python client.py` locally for each player (and watchers) to register/login, create/join a room, and let the lobby auto-spawn the game server when two players are present.
