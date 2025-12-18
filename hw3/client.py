import asyncio
import json
import sys
import logging
import os
import aiofiles
import aiofiles.os
import config

os.environ.setdefault("SDL_AUDIODRIVER", "dummy")

TEXT_MODE_CLIENT = os.environ.get("TEXT_MODE_CLIENT", "").lower() in ("1", "true", "yes")

import utils as ut
import config
from config import tetris_server as tetris_server

# ANSI style helpers for nicer CLI output
RESET_STYLE = "\033[0m"
BOLD_STYLE = "\033[1m"
COMMAND_COLOR = "\033[96m"
INFO_COLOR = "\033[92m"
WARNING_COLOR = "\033[93m"

peer_info = {
    "role": None,
    "game_host": None,
    "game_port": None,
    "room_id": None,
}
GAME_VERSIONS_FILENAME = "game_versions.json"

PRE_LOGIN_MENU = [
    {
        "command": "REGISTER",
        "keyword": "register",
        "label": "register <Username> <Password> - Register new account"
    },
    {
        "command": "LOGIN",
        "keyword": "login",
        "label": "login <Username> <Password> - Log in"
    },
    {
        "command": "HELP",
        "keyword": "help",
        "label": "help - Display available commands"
    },
    {
        "command": "EXIT",
        "keyword": "exit",
        "label": "exit - Leave client"
    }
]

POST_LOGIN_MENU = [
    {
        "command": "LOGOUT",
        "keyword": "logout",
        "label": "logout - Log out"
    },
    {
        "command": "CREATE_ROOM",
        "keyword": "create",
        "label": "create <public/private> <game_name> - Create room"
    },
    {
        "command": "JOIN_ROOM",
        "keyword": "join",
        "label": "join <Room ID> - Join a public room"
    },
    {
        "command": "INVITE_PLAYER",
        "keyword": "invite",
        "label": "invite <Username> <Room ID> - Invite user to join room"
    },
    {
        "command": "SHOW_STATUS",
        "keyword": "status",
        "label": "status - Display current rooms and users"
    },
    {
        "command": "LIST_LOCAL_GAMES",
        "keyword": "games",
        "label": "games - Display the games you have downloaded"
    },
    {
        "command": "LEAVE_ROOM",
        "keyword": "leave",
        "label": "leave - Leave current room"
    },
    {
        "command": "MARKET",
        "keyword": "market",
        "label": "market - Enter the marketplace (display/get/review/leave)"
    },
    {
        "command": "LIST_ALL_GAMES",
        "keyword": "list",
        "label": "list - Display all the games you have downloaded"
    },
    {
        "command": "CHECK",
        "keyword": "check",
        "label": "check - Check invites",
        "requires_invite": True
    },
    {
        "command": "ACCEPT",
        "keyword": "accept",
        "label": "accept <Inviter> <Room ID> - Accept invite",
        "requires_invite": True
    },
    {
        "command": "DECLINE",
        "keyword": "decline",
        "label": "decline <Inviter> <Room ID> - Decline invite",
        "requires_invite": True
    },
    {
        "command": "START_GAME",
        "keyword": "start",
        "label": "start - Start game (room host only)",
        "requires_start": True
    },
    {
        "command": "HELP",
        "keyword": "help",
        "label": "help - Display available commands"
    },
    {
        "command": "EXIT",
        "keyword": "exit",
        "label": "exit - Leave client"
    }
]

MARKET_MENU = [
    {
        "command": "MARKET_DISPLAY",
        "keyword": "display",
        "label": "display - Show all available games"
    },
    {
        "command": "MARKET_GET",
        "keyword": "get",
        "label": "get <Game Name> - Download the selected game"
    },
    {
        "command": "MARKET_REVIEW",
        "keyword": "review",
        "label": "review <Game Name> - Leave or update your review"
    },
    {
        "command": "MARKET_VIEW_REVIEWS",
        "keyword": "reviews",
        "label": "reviews <Game Name> - Display the reviews for a game"
    },
    {
        "command": "MARKET_LEAVE",
        "keyword": "leave",
        "label": "leave - Return to the lobby market menu"
    },
    {
        "command": "MARKET_HELP",
        "keyword": "help",
        "label": "help - Display this marketplace help"
    },
    {
        "command": "MARKET_EXIT",
        "keyword": "exit",
        "label": "exit - Leave the client"
    }
]


def _style_text(text, *styles):
    prefix = "".join(filter(None, styles))
    return f"{prefix}{text}{RESET_STYLE}" if prefix else text


def _format_command_line(line, highlight=True):
    cmd_text, desc = (line.split(" - ", 1) + [""])[:2]
    styled_cmd = _style_text(f"{cmd_text.strip()}", BOLD_STYLE if highlight else "", COMMAND_COLOR)
    if desc:
        return f"{styled_cmd} - {desc.strip()}"
    return styled_cmd


def _filter_menu(menu, *, include_invites=False, include_start=False):
    filtered = []
    for entry in menu:
        if entry.get("requires_invite") and not include_invites:
            continue
        if entry.get("requires_start") and not include_start:
            continue
        filtered.append(entry)
    return filtered


def _entry_keywords(entry):
    keywords = {entry["command"].lower()}
    keyword = entry.get("keyword")
    if keyword:
        keywords.add(keyword.lower())
    for alias in entry.get("keywords", []):
        keywords.add(alias.lower())
    return keywords


def resolve_menu_command(user_input, menu_entries):
    lowered = user_input.lower()
    for idx, entry in enumerate(menu_entries, start=1):
        if lowered == str(idx):
            return entry["command"]
        if lowered in _entry_keywords(entry):
            return entry["command"]
    return None

"""
For server
"""
pending_invitations = []
username = None
user_folder = None
pending_uploads = {}
pending_upload_confirms = {}
pending_downloads = {}
pending_review_requests = {}
room_info = {}
current_room_id = None
current_room_players = []
DEV_GAMES_DIRECTORY = "games"
market_mode = False


def reset_current_room_state():
    global current_room_id, current_room_players
    current_room_id = None
    current_room_players = []


def set_current_room_state(room_id, players=None):
    global current_room_id, current_room_players
    current_room_id = room_id
    if players is None:
        current_room_players = []
    else:
        current_room_players = list(players)


def has_pending_invites():
    return bool(pending_invitations)


def is_room_host():
    return bool(username) and current_room_players and current_room_players[0] == username


def can_start_game():
    return current_room_id is not None and is_room_host() and len(current_room_players) >= 2

def sanitize_username(username):
    cleaned = "".join(c if c.isalnum() or c in ("-", "_") else "_" for c in username)
    cleaned = cleaned.strip("_") or "player"
    return cleaned


def remove_invite(inviter, room_id):
    for idx, invite in enumerate(pending_invitations):
        if invite["inviter"] == inviter and invite["room_id"] == room_id:
            pending_invitations.pop(idx)
            return True
    return False


def display_help(logged_in=False, has_invites=False, show_check=False, show_start=False):
    base_menu = POST_LOGIN_MENU if logged_in else PRE_LOGIN_MENU
    include_invites = has_invites or show_check
    entries = _filter_menu(base_menu, include_invites=include_invites, include_start=show_start)
    print(f"\n{_style_text('Available commands:', BOLD_STYLE)}")
    for idx, entry in enumerate(entries, start=1):
        print(_format_command_line(f"{idx}. {entry['label']}"))

    tip = "Enter the number next to a command or type the command name shown above. Eg. 1 name pass"
    print(f"\n{_style_text(tip, INFO_COLOR)}\n")


def display_market_help():
    print(f"\n{_style_text('Marketplace commands:', BOLD_STYLE)}")
    for idx, entry in enumerate(MARKET_MENU, start=1):
        print(_format_command_line(f"{idx}. {entry['label']}"))
    print("")


def enter_market_mode():
    global market_mode
    market_mode = True
    print(_style_text("\nEntered marketplace mode. Use 'leave' to return to the lobby.", INFO_COLOR))
    display_market_help()


def exit_market_mode():
    global market_mode
    if market_mode:
        print(_style_text("\nLeaving marketplace, returning to lobby commands.", INFO_COLOR))
    market_mode = False


async def setup_user_directory(username):
    global user_folder
    safe_name = sanitize_username(username)
    user_folder = f"games-{safe_name}"
    peer_info_path = os.path.join(user_folder, "peer_info.json")
    versions_path = os.path.join(user_folder, GAME_VERSIONS_FILENAME)
    try:
        if not await aiofiles.os.path.exists(user_folder):
            await aiofiles.os.makedirs(user_folder)
            print(f"已創建資料夾：{user_folder}")
            logging.info(f"已創建資料夾：{user_folder}")
        else:
            print(f"資料夾已存在：{user_folder}")
            logging.info(f"資料夾已存在：{user_folder}")
            
        if not await aiofiles.os.path.exists(peer_info_path):
            initial_peer_info = {
                "role": None,
                "peer_ip": None,
                "peer_port": None,
                "own_port": None,
                "game_name": None
            }
            async with aiofiles.open(peer_info_path, 'w') as f:
                await f.write(json.dumps(initial_peer_info, ensure_ascii=False, indent=4))
            print(f"已創建 peer_info.json 文件。")
            logging.info(f"已創建 peer_info.json 文件：{peer_info_path}")
        else:
            print(f"peer_info.json 文件已存在：{peer_info_path}")
            logging.info(f"peer_info.json 文件已存在：{peer_info_path}")
        if not await aiofiles.os.path.exists(versions_path):
            async with aiofiles.open(versions_path, 'w') as vf:
                await vf.write(json.dumps({}, ensure_ascii=False, indent=4))
            logging.info(f"已創建 {versions_path}")
    except Exception as e:
        print(f"設定用戶資料夾時發生錯誤：{e}")
        logging.error(f"設定用戶資料夾時發生錯誤：{e}")
    return user_folder


async def copy_game_from_dev_folder(game_name):
    """
    Copy a game script from the developer's shared folder into the logged-in user's folder.
    """
    if not user_folder:
        print("請先登入以建立個人遊戲資料夾。")
        logging.error("User folder unavailable when attempting local download.")
        return False
    source_path = os.path.join(DEV_GAMES_DIRECTORY, f"{game_name}.py")
    if not os.path.exists(source_path):
        print(f"無法找到開發者遊戲檔案：{source_path}")
        logging.error(f"Developer game file missing: {source_path}")
        return False
    try:
        if not await aiofiles.os.path.exists(user_folder):
            await aiofiles.os.makedirs(user_folder)
        destination_path = os.path.join(user_folder, f"{game_name}.py")
        async with aiofiles.open(source_path, 'rb') as src:
            data = await src.read()
        async with aiofiles.open(destination_path, 'wb') as dst:
            await dst.write(data)
        print(f"已將 {game_name}.py 下載到 {destination_path}")
        logging.info(f"Copied {source_path} -> {destination_path}")
        return True
    except Exception as e:
        print(f"複製遊戲檔案時發生錯誤：{e}")
        logging.error(f"Failed to copy local developer game: {e}")
        return False


async def list_downloaded_games():
    """
    Display the games that have been downloaded to the user's folder.
    """
    if not user_folder:
        print("請先登入以查看已下載的遊戲。")
        return
    try:
        if not await aiofiles.os.path.exists(user_folder):
            print("尚未有任何下載的遊戲。")
            return
        entries = await aiofiles.os.listdir(user_folder)
        games = sorted(name[:-3] for name in entries if name.endswith(".py"))
        if not games:
            print("尚未有任何下載的遊戲。")
            return
        print(f"\n{_style_text('Downloaded games:', BOLD_STYLE)}")
        for game in games:
            print(f"- {game}")
    except Exception as e:
        print(f"列出已下載遊戲時發生錯誤：{e}")
        logging.error(f"Failed to list downloaded games: {e}")


async def _game_versions_path():
    if not user_folder:
        return None
    return os.path.join(user_folder, GAME_VERSIONS_FILENAME)


async def _ensure_versions_file():
    path = await _game_versions_path()
    if not path:
        return None
    if not await aiofiles.os.path.exists(path):
        async with aiofiles.open(path, 'w') as f:
            await f.write(json.dumps({}, ensure_ascii=False, indent=4))
    return path


async def load_local_game_versions():
    path = await _ensure_versions_file()
    if not path:
        return {}
    try:
        async with aiofiles.open(path, 'r') as f:
            content = await f.read()
            return json.loads(content) if content else {}
    except Exception as e:
        logging.error(f"Unable to read game versions: {e}")
        return {}


async def save_local_game_versions(data):
    path = await _ensure_versions_file()
    if not path:
        return
    async with aiofiles.open(path, 'w') as f:
        await f.write(json.dumps(data, ensure_ascii=False, indent=4))


async def get_local_game_version(game_name):
    versions = await load_local_game_versions()
    return versions.get(game_name)


async def set_local_game_version(game_name, version):
    if not version:
        return
    versions = await load_local_game_versions()
    versions[game_name] = version
    await save_local_game_versions(versions)


async def download_game_from_server(game_name, writer, *, silent=False):
    if user_folder is None:
        if not silent:
            print("尚未設定用戶專屬資料夾。")
        logging.error("User folder not available for download.")
        return False
    loop = asyncio.get_event_loop()
    download_future = loop.create_future()
    pending_downloads[game_name] = download_future
    await ut.send_command("client", writer, "DOWNLOAD_GAME_FILE", [game_name])
    try:
        await asyncio.wait_for(download_future, timeout=15)
        return True
    except asyncio.TimeoutError:
        if not silent:
            print("下載遊戲檔案超時。")
        logging.error(f"Download timed out for {game_name}")
        return False
    except Exception as e:
        if not silent:
            print(f"下載遊戲檔案失敗：{e}")
        logging.error(f"Download failed for {game_name}: {e}")
        return False
    finally:
        pending_downloads.pop(game_name, None)


async def ensure_local_game_version(game_name, expected_version, writer):
    if not expected_version:
        return True
    current_version = await get_local_game_version(game_name)
    if current_version == expected_version:
        return True
    print(f"{game_name} 版本落後（目前 {current_version or '未知'}，需要 {expected_version}），正在自動更新...")
    success = await download_game_from_server(game_name, writer)
    if success:
        print(f"{game_name} 已更新至最新版本。")
    else:
        print(f"{game_name} 更新失敗，請稍後再試。")
    return success


def render_reviews(game_name, reviews):
    print(f"\n{_style_text(f'Reviews for {game_name}:', BOLD_STYLE)}")
    if not reviews:
        print(_style_text("No reviews yet. Be the first to rate this game!", WARNING_COLOR))
        return
    for review in reviews:
        rating = review.get("rating", "N/A")
        user = review.get("username", "unknown")
        comment = review.get("comment", "")
        timestamp = review.get("timestamp", "")
        print(_style_text(f"{user} rated {rating}/5", COMMAND_COLOR))
        if comment:
            print(_style_text(f"Comment: {comment}", INFO_COLOR))
        if timestamp:
            print(f"Time: {timestamp}")
        print("")


async def request_game_reviews(game_name, writer):
    loop = asyncio.get_event_loop()
    future = loop.create_future()
    pending_review_requests[game_name] = future
    await ut.send_command("client", writer, "GET_REVIEWS", [game_name])
    try:
        reviews = await asyncio.wait_for(future, timeout=10)
        return reviews
    except asyncio.TimeoutError:
        print("取得評價逾時，請稍後再試。")
        return None
    except Exception as e:
        print(f"無法取得評價：{e}")
        return None
    finally:
        pending_review_requests.pop(game_name, None)


async def prompt_for_rating():
    while True:
        rating_input = await get_user_input("請輸入評分 (1-5)： ")
        try:
            rating = int(rating_input)
        except ValueError:
            print("評分必須是數字。")
            continue
        if 1 <= rating <= 5:
            return rating
        print("評分必須介於 1 到 5 之間。")


async def handle_market_review(game_name, writer):
    reviews = await request_game_reviews(game_name, writer)
    if reviews is None:
        return
    render_reviews(game_name, reviews)
    decision = (await get_user_input("是否要留下評價？(y/n): ")).lower()
    if decision not in ("y", "yes"):
        return
    rating = await prompt_for_rating()
    comment = await get_user_input("請輸入評語： ")
    await ut.send_command("client", writer, "LEAVE_REVIEW", [game_name, str(rating), comment])

async def handle_server_messages(reader, writer, game_in_progress, logged_in, shutdown_event):
    while True:
        try:
            # data = await reader.readline()
            message = await ut.unpack_message(reader)
            if message is None:
                if not shutdown_event.is_set():
                    async with tetris_server.rooms_lock:
                        for room in tetris_server.rooms:
                            if room['creator'] not in tetris_server.online_users:
                                del tetris_server.rooms[room['room_id']]
                    print("\nServer has disconnected.")
                    logging.info("Server has disconnected.")
                    shutdown_event.set()
                game_in_progress.value = False
                break

            try:
                message_json = json.loads(message)
                if not isinstance(message_json, dict):
                    print(f"\nServer：{message}")
                    continue
                status = message_json.get("status")
                msg = message_json.get("message", "")

                if status == "success":
                    params_list = message_json.get("params") or []
                    if msg.startswith("REGISTRATION_SUCCESS"):
                        print("\nRegistration successful, please log in.\n")
                    
                    elif msg.startswith("LOGIN_SUCCESS"):
                        print("\nYou have logged in successfully.\n")
                        logged_in.value = True
                        pending_invitations.clear()
                        room_info.clear()
                        reset_current_room_state()
                        if username:
                            await setup_user_directory(username)
                        display_help(
                            True,
                            has_pending_invites(),
                            show_check=has_pending_invites(),
                            show_start=can_start_game()
                        )
                    
                    elif msg.startswith("LOGOUT_SUCCESS"):
                        print("\nYou have logged out successfully.")
                        logged_in.value = False
                        pending_invitations.clear()
                        room_info.clear()
                        reset_current_room_state()
                        exit_market_mode()
                        pending_review_requests.clear()
                        display_help(False)
                    
                    elif msg.startswith("CREATE_ROOM_SUCCESS"):
                        parts = msg.split()
                        room_id = parts[1]
                        print(f"\nRoom successfully created. The room ID is {room_id}.\n")
                        players_snapshot = None
                        if len(params_list) >= 2 and isinstance(params_list[1], list):
                            players_snapshot = params_list[1]
                        elif username:
                            players_snapshot = [username]
                        set_current_room_state(room_id, players_snapshot)
                    
                    elif msg.startswith("JOIN_ROOM_SUCCESS"):
                        parts = msg.split()
                        room_id = parts[1]
                        print(f"\nSuccessfully joined room {room_id}.\n")
                        players_snapshot = params_list[1] if len(params_list) >= 2 and isinstance(params_list[1], list) else None
                        set_current_room_state(room_id, players_snapshot)
                    
                    elif msg.startswith("LEAVE_ROOM_SUCCESS"):
                        parts = msg.split()
                        room_id = parts[1] if len(parts) > 1 else ""
                        print(f"\nYou have left room {room_id}.\n")
                        reset_current_room_state()
                        
                    elif msg.startswith("INVITE_SENT"):
                        parts = msg.split()
                        target_username = parts[1]
                        print(f"\nYour invite for {target_username} has been sent.")
                    
                    elif msg.startswith("DECLINED_INVITE"):
                        parts = msg.split()
                        inviter = parts[0]
                        room_id = parts[1]
                        print(f"\nSuccessfully declined invite from {inviter} to room {room_id}.")
                    
                    elif msg.startswith("UPLOAD_GAME_SUCCESS"):
                        game_name = message_json.get('game_name')
                        if game_name in pending_upload_confirms:
                            pending_upload_confirms[game_name].set_result(True)
                    elif msg.startswith("LEAVE_REVIEW_SUCCESS"):
                        game_name = message_json.get("game_name", "")
                        print(_style_text(f"已新增 {game_name} 的評價！", INFO_COLOR))
                            
                    elif 'games' in message_json:
                        logging.info("收到遊戲列表。")
                        games_list = message_json['games']
                        scope = message_json.get('scope', 'own')
                        header = "Marketplace games:" if scope == 'all' else "Your published games:"
                        print(f"\n{_style_text(header, BOLD_STYLE)}")
                        if not games_list:
                            print(_style_text("(No games found)", WARNING_COLOR))
                        for game in games_list:
                            name_line = _style_text(f"Game: {game['name']}", BOLD_STYLE)
                            desc_line = _style_text(f"Description: {game['description']}", INFO_COLOR)
                            version_line = _style_text(f"Version: {game['version']}", INFO_COLOR)
                            print(name_line)
                            print(desc_line)
                            print(version_line)
                            if scope == 'all':
                                publisher = game.get('publisher', 'unknown')
                                print(_style_text(f"Publisher: {publisher}", COMMAND_COLOR))
                            print("")
                    elif 'reviews' in message_json:
                        game_name = message_json.get("game_name")
                        reviews_list = message_json.get("reviews", [])
                        future = pending_review_requests.get(game_name)
                        if future and not future.done():
                            future.set_result(reviews_list)

                elif status == "error":
                    print(f"\nError: {msg}\n")
                    
                elif status == "invite":
                    parts = msg.split()
                    inviter = parts[0]
                    room_id = parts[1]
                    pending_invitations.append({"inviter": inviter, "room_id": room_id})
                    print(f"You have been invited by {inviter} to join room {room_id}.")
                    display_help(
                        logged_in.value,
                        has_pending_invites(),
                        show_check=True,
                        show_start=can_start_game()
                    )
                    print("Use the command \"accept <username> <room_id>\" to accept the invite, or use \"check\" to check your invites.")
                
                elif status == "invite_declined":
                    parts = msg.split()
                    sender = parts[0]
                    room_id = parts[1]
                    print(f"\nUser {sender} has declined your invite to room {room_id}.")
                    logging.info(f"User {sender} declined joining {room_id}.")
                
                elif status == "file_transfer":
                    game_name = message_json.get("game_name")
                    file_size = int(message_json.get("file_size", 0))
                    version = message_json.get("version")
                    file_content = await reader.readexactly(file_size)
                    file_path = os.path.join(user_folder, game_name + ".py")
                    async with aiofiles.open(file_path, 'wb') as f:
                        await f.write(file_content)
                    await set_local_game_version(game_name, version)
                    download_future = pending_downloads.get(game_name)
                    if download_future and not download_future.done():
                        download_future.set_result(version or True)
                        pending_downloads.pop(game_name, None)
                        print(f"已下載遊戲檔案 {game_name}.py （版本 {version or '未知'}）")
                    else:
                        print(f"{game_name} 已自動同步為最新版本（{version or '未知'}）。")

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
                    asyncio.create_task(
                        process_p2p_info_message(message_json, writer, game_in_progress)
                    )
                
                elif status == "host_transfer":
                    new_host = message_json.get("new_host")
                    room_id = message_json.get("room_id")
                    if new_host == username:
                        print(f"\n[系統通知] 您已成為房間 {room_id} 的新房主。")
                    else:
                        print(f"\n[系統通知] 玩家 {new_host} 現在是房間 {room_id} 的房主。")
                
                elif status == "ready":
                    game_name = message_json.get('game_name')
                    if game_name in pending_uploads:
                        pending_uploads[game_name].set_result(True)
                        del pending_uploads[game_name] 

                elif status == "status":
                    print(f"\n{msg}")
                    rooms_data = message_json.get("rooms_data")
                    if rooms_data:
                        for room in rooms_data:
                            rid = room.get("room_id")
                            gname = room.get("game_name")
                            if rid and gname:
                                room_info[rid] = gname

                else:
                    print(f"\nServer：{message}")

            except json.JSONDecodeError:
                print(f"\nServer：{message}")

        except Exception as e:
            if not shutdown_event.is_set():
                print(f"\nError while receiving data from server: {e}")
                logging.error(f"Error when receiving data from server: {e}")
            game_in_progress.value = False
            break


async def process_p2p_info_message(message_json, writer, game_in_progress):
    global username
    room_id = message_json.get("room_id")
    if room_id and message_json.get("game_name"):
        room_info[room_id] = message_json["game_name"]
    if message_json.get("role") == "host" and room_id:
        base_players = list(current_room_players) if current_room_players else []
        if not base_players and username:
            base_players = [username]
        elif base_players and username and base_players[0] != username:
            base_players.insert(0, username)
        if len(base_players) < 2:
            base_players = list(base_players)
            base_players.append("opponent")
        set_current_room_state(room_id, base_players)
    elif room_id and current_room_id is None:
        set_current_room_state(room_id, current_room_players if current_room_players else None)
    new_peer_info = {
        "role": message_json.get("role"),
        "peer_ip": message_json.get("peer_ip"),
        "peer_port": message_json.get("peer_port"),
        "own_port": message_json.get("own_port"),
        "game_name": message_json.get("game_name")
    }
    await update_peer_info(new_peer_info)
    current_peer_info = await read_peer_info()
    if current_peer_info is None:
        print("錯誤：無法讀取 peer_info。")
        logging.error("Failed to read peer_info after p2p_info.")
        return
    required_fields = ["role", "peer_ip", "peer_port", "own_port", "game_name"]
    missing = [field for field in required_fields if not current_peer_info.get(field)]
    if missing:
        print(f"錯誤：收到不完整的連線資訊，缺少 {', '.join(missing)}。")
        logging.error(f"Incomplete p2p_info: missing {missing}")
        return
    expected_version = message_json.get("game_version")
    version_ready = await ensure_local_game_version(current_peer_info["game_name"], expected_version, writer)
    if not version_ready:
        logging.error(f"Failed to synchronize game version for {current_peer_info['game_name']}")
        return
    logging.info(
        f"角色：{current_peer_info['role']}，對等方 IP：{current_peer_info['peer_ip']}，"
        f"對等方 Port：{current_peer_info['peer_port']}，自身 Port：{current_peer_info['own_port']}")
    print(
        f"\n角色：{current_peer_info['role']}，對等方 IP：{current_peer_info['peer_ip']}，"
        f"對等方 Port：{current_peer_info['peer_port']}，自身 Port：{current_peer_info['own_port']}")
    game_in_progress.value = True
    asyncio.create_task(
        initiate_game(current_peer_info["game_name"], game_in_progress, writer, user_folder)
    )


async def get_user_input(prompt):
    loop = asyncio.get_event_loop()
    return await loop.run_in_executor(None, lambda: input(prompt).strip())


async def handle_user_input(writer, game_in_progress, logged_in, shutdown_event):
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
            command_input = parts[0]
            params = parts[1:]
            command = None

            if market_mode:
                market_command = resolve_menu_command(command_input, MARKET_MENU)
                if not market_command:
                    print("Unknown marketplace command. Type 'help' for options.")
                    continue
                if market_command == "MARKET_DISPLAY":
                    await ut.send_command("client", writer, "LIST_ALL_GAMES", [])
                    continue
                if market_command == "MARKET_GET":
                    if len(params) != 1:
                        print("用法：get <game_name>")
                        continue
                    success = await download_game_from_server(params[0], writer)
                    if success:
                        print(f"{params[0]} 下載完成。")
                    continue
                if market_command == "MARKET_REVIEW":
                    if len(params) != 1:
                        print("用法：review <game_name>")
                        continue
                    await handle_market_review(params[0], writer)
                    continue
                if market_command == "MARKET_VIEW_REVIEWS":
                    if len(params) != 1:
                        print("用法：reviews <game_name>")
                        continue
                    reviews = await request_game_reviews(params[0], writer)
                    if reviews is not None:
                        render_reviews(params[0], reviews)
                    continue
                if market_command == "MARKET_LEAVE":
                    exit_market_mode()
                    display_help(
                        logged_in.value,
                        has_pending_invites(),
                        show_check=has_pending_invites(),
                        show_start=can_start_game()
                    )
                    continue
                if market_command == "MARKET_HELP":
                    display_market_help()
                    continue
                if market_command == "MARKET_EXIT":
                    command = "EXIT"

            if command is None:
                logged_state = logged_in.value
                include_invites = has_pending_invites()
                include_start = can_start_game()
                active_menu = _filter_menu(
                    POST_LOGIN_MENU if logged_state else PRE_LOGIN_MENU,
                    include_invites=include_invites,
                    include_start=include_start
                )
                command = resolve_menu_command(command_input, active_menu)

            if not command:
                print("Invalid command, input 'help' to see list of available commands.")
                continue

            if command == "EXIT":
                print("Exiting...")
                logging.info("User chose to leave client.")
                if logged_in.value:
                    await ut.send_command("client", writer, "LOGOUT", [])
                game_in_progress.value = False
                exit_market_mode()
                try:
                    writer.close()
                    await writer.wait_closed()
                except Exception:
                    pass
                shutdown_event.set()
                break

            elif command == "HELP":
                invites_pending = has_pending_invites()
                display_help(
                    logged_in.value,
                    invites_pending,
                    show_check=invites_pending,
                    show_start=can_start_game()
                )
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

            elif command == "MARKET":
                if not logged_in.value:
                    print("請先登入才能進入市集。")
                    continue
                enter_market_mode()
                continue
                
            elif command == "CREATE_ROOM":
                if len(params) != 2:
                    print("用法：create <public/private> <game_name>")
                    continue
                room_type = params[0]
                game_name = params[1]
                if user_folder is None:
                    print("尚未設定用戶專屬資料夾。")
                    logging.error("用戶專屬資料夾未設定。")
                    continue
                game_folder = user_folder
                file_path = os.path.join(game_folder, game_name + '.py')
                logging.debug(f"遊戲檔案路徑：{file_path}")
                if not os.path.exists(file_path):
                    print(f"遊戲檔案 {game_name}.py 不存在，正在從伺服器下載...")
                else:
                    print(f"遊戲檔案 {game_name}.py 已存在，更新中...")
                success = await download_game_from_server(game_name, writer)
                if not success:
                    continue
                await ut.send_command("client", writer, "CREATE_ROOM", [room_type, game_name])

            elif command == "INVITE_PLAYER":
                if len(params) != 2:
                    print("Usage: invite <Username> <Room ID>")
                    continue
                await ut.send_command("client", writer, "INVITE_PLAYER", params)

            elif command == "JOIN_ROOM":
                if len(params) != 1:
                    print("用法：join <房間ID>")
                    continue
                room_id = params[0]
                game_name = room_info.get(room_id)
                if game_name:
                    if user_folder is None:
                        print("尚未設定用戶專屬資料夾。")
                        logging.error("用戶專屬資料夾未設定。")
                        continue
                    file_path = os.path.join(user_folder, game_name + '.py')
                    if not os.path.exists(file_path):
                        print(f"遊戲檔案 {game_name}.py 不存在，正在從伺服器下載...")
                    else:
                        print(f"遊戲檔案 {game_name}.py 已存在，更新中...")
                    success = await download_game_from_server(game_name, writer)
                    if not success:
                        continue
                await ut.send_command("client", writer, "JOIN_ROOM", [room_id])

            elif command == "ACCEPT":
                if not pending_invitations:
                    print("You do not have any pending invites.")
                    continue
                if len(params) != 2:
                    print("Usage: accept <Inviter> <Room ID>")
                    continue
                inviter, room_id = params
                if not remove_invite(inviter, room_id):
                    print("Invite not found.")
                    continue
                await ut.send_command("client", writer, "ACCEPT", [inviter, room_id])

            elif command == "DECLINE":
                if not pending_invitations:
                    print("You do not have any pending invites.")
                    continue
                if len(params) != 2:
                    print("Usage: decline <Inviter> <Room ID>")
                    continue
                inviter, room_id = params
                if not remove_invite(inviter, room_id):
                    print("Invite not found.")
                    continue
                await ut.send_command("client", writer, "DECLINE", [inviter, room_id])

            elif command == "SHOW_STATUS":
                await ut.send_command("client", writer, "SHOW_STATUS", [])
                
            elif command == "CHECK":
                if not has_pending_invites():
                    print("You do not have any pending invites.")
                    continue
                await ut.send_command("client", writer, "CHECK", [])

            elif command == "LEAVE_ROOM":
                if not logged_in.value:
                    print("尚未登入。")
                    continue
                await ut.send_command("client", writer, "LEAVE_ROOM", [])
            
            elif command == "START_GAME":
                if not logged_in.value:
                    print("尚未登入。")
                    continue
                if current_room_id is None:
                    print("You are not currently in a room.")
                    continue
                if not is_room_host():
                    print("Only the room host can start the game.")
                    continue
                if not can_start_game():
                    print("The room must have two players before starting the game.")
                    continue
                await ut.send_command("client", writer, "START_GAME", [])
            elif command == "LIST_ALL_GAMES":
                if not logged_in.value:
                    print("尚未登入。")
                    continue
                await ut.send_command("client", writer, "LIST_ALL_GAMES", [])
            elif command == "LIST_LOCAL_GAMES":
                await list_downloaded_games()
            
            elif command == "DOWNLOAD_LOCAL":
                if len(params) != 1:
                    print("用法：download <game_name>")
                    continue
                await copy_game_from_dev_folder(params[0])

            else:
                print("Invalid command, input 'help' to see list of available commands.")
        except KeyboardInterrupt:
            print("Exiting...")
            logging.info("User chose to leave client via keyboard interrupt.")
            if logged_in.value:
                await ut.send_command("client", writer, "LOGOUT", [])
            game_in_progress.value = False
            try:
                writer.close()
                await writer.wait_closed()
            except Exception:
                pass
            shutdown_event.set()
            break
        except Exception as e:
            print(f"Error when sending command: {e}")
            logging.error(f"Error when sending command: {e}")
            game_in_progress.value = False
            try:
                writer.close()
                await writer.wait_closed()
            except Exception:
                pass
            shutdown_event.set()
            break


"""
For game
"""

async def read_peer_info():
    global user_folder
    peer_info_path = os.path.join(user_folder, "peer_info.json")
    try:
        async with aiofiles.open(peer_info_path, 'r') as f:
            content = await f.read()
            return json.loads(content)
    except Exception as e:
        print(f"讀取 peer_info.json 時發生錯誤：{e}")
        logging.error(f"讀取 peer_info.json 時發生錯誤：{e}")
        return None

async def update_peer_info(new_info):
    global user_folder
    peer_info_path = os.path.join(user_folder, "peer_info.json")
    try:
        current_info = await read_peer_info()
        if current_info is None:
            current_info = {}
        current_info.update(new_info)
        async with aiofiles.open(peer_info_path, 'w') as f:
            await f.write(json.dumps(current_info, ensure_ascii=False, indent=4))
        logging.info(f"更新 peer_info.json：{new_info}")
    except Exception as e:
        print(f"更新 peer_info.json 時發生錯誤：{e}")
        logging.error(f"更新 peer_info.json 時發生錯誤：{e}")

async def initiate_game(game_name, game_in_progress, writer, user_folder):
    try:
        if not game_name:
            print("無法啟動遊戲：未知遊戲名稱。")
            logging.error("Missing game name for initiate_game.")
            return
        game_folder = user_folder if user_folder else 'games'  # 確保使用正確的遊戲目錄
        file_path = os.path.join(game_folder, game_name + ".py")
        print(f"正在執行遊戲 {game_name}...")
        if not os.path.exists(file_path):
            print(f"遊戲檔案 {game_name} 不存在。")
            logging.error(f"遊戲檔案 {game_name} 不存在於 {game_folder}。")
            return

        peer_info = await read_peer_info()
        if peer_info is None:
            print("錯誤：無法讀取 peer_info。")
            logging.error("無法讀取 peer_info。")
            return
        
        required_fields = ["role", "peer_ip", "peer_port", "own_port", "game_name"]
        missing_fields = [field for field in required_fields if peer_info.get(field) is None]
        if missing_fields:
            print(f"錯誤：peer_info 缺少字段：{', '.join(missing_fields)}")
            logging.error(f"peer_info 缺少字段：{', '.join(missing_fields)}")
            return

        game_globals = {}   
        game_globals['peer_info'] = peer_info
        try:
            async with aiofiles.open(file_path, 'r') as f:
                code = await f.read()
            exec(code, game_globals)
            if 'main' in game_globals and callable(game_globals['main']):
                await game_globals['main'](peer_info)
            else:
                print("遊戲腳本不包含 main() 函數。")
                logging.error("遊戲腳本不包含 main() 函數。")
        except Exception as e:
            print(f"讀取或執行遊戲腳本時發生錯誤：{e}")
            logging.error(f"讀取或執行遊戲腳本時發生錯誤：{e}")
    except Exception as e:
        print(f"遊戲執行時發生錯誤：{e}")
        logging.error(f"遊戲執行時發生錯誤：{e}")
    finally:
        reset_current_room_state()
        game_in_progress.value = False
        await ut.send_command("client", writer, "GAME_OVER", [])


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
    return

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
    shutdown_event = asyncio.Event()

    asyncio.create_task(handle_server_messages(reader, writer, game_in_progress, logged_in, shutdown_event))
    asyncio.create_task(handle_user_input(writer, game_in_progress, logged_in, shutdown_event))

    display_help(False)

    await shutdown_event.wait()

    print("Client end closed.")
    logging.info("Client end closed.")
    sys.exit()


if __name__ == "__main__":
    try:
        asyncio.run(main())
    except Exception as e:
        print(f"Client end terminated with error: {e}")
        logging.error(f"Client end terminated with error: {e}")
