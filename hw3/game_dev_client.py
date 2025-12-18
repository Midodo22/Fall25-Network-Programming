import asyncio
import json
import logging
import os
import aiofiles
import aiofiles.os

import config
import utils as ut
from game_dev import manager as dev_manager

RESET_STYLE = "\033[0m"
BOLD_STYLE = "\033[1m"
COMMAND_COLOR = "\033[96m"
INFO_COLOR = "\033[92m"
WARNING_COLOR = "\033[93m"

PRE_LOGIN_MENU = [
    {
        "command": "REGISTER",
        "keyword": "register",
        "label": "register <Username> <Password> - Register new developer account",
        "aliases": ["r"]
    },
    {
        "command": "LOGIN",
        "keyword": "login",
        "label": "login <Username> <Password> - Log in",
        "aliases": ["l"]
    },
    {
        "command": "HELP",
        "keyword": "help",
        "label": "help - Display this help message",
        "aliases": ["h"]
    },
    {
        "command": "EXIT",
        "keyword": "exit",
        "label": "exit - Leave developer console",
        "aliases": ["quit", "q"]
    }
]

POST_LOGIN_MENU = [
    {
        "command": "LOGOUT",
        "keyword": "logout",
        "label": "logout - Log out"
    },
    {
        "command": "UPLOAD",
        "keyword": "upload",
        "label": "upload <game_name> - Upload a new game (expects <game_name>.py in games-<your_username>)"
    },
    {
        "command": "UPDATE",
        "keyword": "update",
        "label": "update <game_name> - Update an existing game"
    },
    {
        "command": "DELETE",
        "keyword": "delete",
        "label": "delete <game_name> - Delete one of your games"
    },
    {
        "command": "LIST_MINE",
        "keyword": "list",
        "label": "list - List games you have uploaded",
        "aliases": ["ls"]
    },
    {
        "command": "MARKET",
        "keyword": "market",
        "label": "market - View all games in the marketplace"
    },
    {
        "command": "HELP",
        "keyword": "help",
        "label": "help - Display this list of commands",
        "aliases": ["h"]
    },
    {
        "command": "EXIT",
        "keyword": "exit",
        "label": "exit - Leave developer console",
        "aliases": ["quit", "q"]
    }
]

DEV_SENDER = "game_dev"

pending_uploads = {}
pending_upload_confirms = {}
username = None
user_folder = None
logout_future = None


def _style_text(text, *styles):
    prefix = "".join(filter(None, styles))
    return f"{prefix}{text}{RESET_STYLE}" if prefix else text


def _format_command_line(line):
    cmd_text, desc = (line.split(" - ", 1) + [""])[:2]
    styled_cmd = _style_text(cmd_text.strip(), BOLD_STYLE, COMMAND_COLOR)
    if desc:
        return f"{styled_cmd} - {desc.strip()}"
    return styled_cmd


def _entry_keywords(entry):
    keywords = {entry["command"].lower()}
    keyword = entry.get("keyword")
    if keyword:
        keywords.add(keyword.lower())
    for alias in entry.get("aliases", []):
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


def _current_menu(logged_in):
    return POST_LOGIN_MENU if logged_in else PRE_LOGIN_MENU


def display_help(logged_in):
    print(f"\n{_style_text('Available commands:', BOLD_STYLE)}")
    entries = _current_menu(logged_in)
    for idx, entry in enumerate(entries, start=1):
        print(_format_command_line(f"{idx}. {entry['label']}"))
    print("")


def sanitize_username(name):
    cleaned = "".join(c if c.isalnum() or c in ("-", "_") else "_" for c in name)
    cleaned = cleaned.strip("_") or "developer"
    return cleaned


async def setup_user_directory(name):
    global user_folder
    safe_name = sanitize_username(name)
    user_folder = f"games-{safe_name}"
    peer_info_path = os.path.join(user_folder, "peer_info.json")
    if not await aiofiles.os.path.exists(user_folder):
        await aiofiles.os.makedirs(user_folder)
        logging.info(f"[Dev] Created directory {user_folder}")
    if not await aiofiles.os.path.exists(peer_info_path):
        async with aiofiles.open(peer_info_path, 'w') as f:
            await f.write(json.dumps({
                "role": None,
                "peer_ip": None,
                "peer_port": None,
                "own_port": None,
                "game_name": None
            }, ensure_ascii=False, indent=4))
        logging.info(f"[Dev] Created {peer_info_path}")
    return user_folder


async def handle_server_messages(reader, writer, logged_in, shutdown_event):
    global username
    global user_folder
    global logout_future
    while True:
        try:
            message = await ut.unpack_message(reader)
            if message is None:
                if not shutdown_event.is_set():
                    print("\nServer disconnected.")
                if logout_future and not logout_future.done():
                    logout_future.set_result(False)
                shutdown_event.set()
                break
            try:
                message_json = json.loads(message)
            except json.JSONDecodeError:
                print(f"\nServer: {message}")
                continue
            status = message_json.get("status")
            msg = message_json.get("message", "")

            if status == "success":
                if msg.startswith("REGISTRATION_SUCCESS"):
                    print(_style_text("Registration successful. Please log in.", INFO_COLOR))
                elif msg.startswith("LOGIN_SUCCESS"):
                    print(_style_text("Login successful.", INFO_COLOR))
                    logged_in.value = True
                    if username:
                        await setup_user_directory(username)
                    display_help(True)
                elif msg.startswith("LOGOUT_SUCCESS"):
                    print(_style_text("Logout successful.", INFO_COLOR))
                    logged_in.value = False
                    username = None
                    user_folder = None
                    if logout_future and not logout_future.done():
                        logout_future.set_result(True)
                    display_help(False)
                elif msg.startswith("UPLOAD_GAME_SUCCESS"):
                    game_name = message_json.get("game_name")
                    if game_name in pending_upload_confirms:
                        pending_upload_confirms[game_name].set_result(True)
                        pending_upload_confirms.pop(game_name, None)
                        print(_style_text(f"Game {game_name} uploaded successfully.", INFO_COLOR))
                elif msg.startswith("UPDATE_GAME_SUCCESS"):
                    game_name = message_json.get("game_name")
                    if game_name in pending_upload_confirms:
                        pending_upload_confirms[game_name].set_result(True)
                        pending_upload_confirms.pop(game_name, None)
                        print(_style_text(f"Game {game_name} updated successfully.", INFO_COLOR))
                elif msg.startswith("DELETE_GAME_SUCCESS"):
                    game_name = message_json.get("game_name")
                    print(_style_text(f"Game {game_name} deleted successfully.", INFO_COLOR))
                elif "games" in message_json:
                    scope = message_json.get("scope", "own")
                    games_list = message_json.get("games", [])
                    header = "Marketplace games:" if scope == "all" else "Your games:"
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
                        if scope == "all":
                            publisher = game.get("publisher", "unknown")
                            print(_style_text(f"Publisher: {publisher}", COMMAND_COLOR))
                        print("")
                else:
                    print(f"\nServer: {msg}")

            elif status == "ready":
                game_name = message_json.get("game_name")
                if game_name in pending_uploads:
                    pending_uploads[game_name].set_result(True)
                    pending_uploads.pop(game_name, None)

            elif status == "error":
                print(_style_text(f"\nError: {msg}", WARNING_COLOR))
                if "already logged in" in msg.lower():
                    print(_style_text("If this account is stuck, try running 'logout' to reset the previous session.", WARNING_COLOR))

            else:
                print(f"\nServer: {message_json}")

        except Exception as e:
            if not shutdown_event.is_set():
                print(f"\nError receiving data from server: {e}")
            break


async def get_user_input(prompt):
    loop = asyncio.get_event_loop()
    return await loop.run_in_executor(None, lambda: input(prompt).strip())


async def forward_command(writer, command, params):
    await ut.send_command(DEV_SENDER, writer, command, params)


async def request_logout(writer, logged_in, silent=False, force=False):
    global logout_future
    if not logged_in.value and not force:
        if not silent:
            print("You are not logged in.")
        return
    if logout_future and not logout_future.done():
        if not silent:
            print("Logout already in progress...")
        return
    loop = asyncio.get_event_loop()
    logout_future = loop.create_future()
    await ut.send_command(DEV_SENDER, writer, "LOGOUT", [])
    try:
        await asyncio.wait_for(logout_future, timeout=10)
    except asyncio.TimeoutError:
        if not silent:
            print("Server did not confirm the logout in time.")
    finally:
        logout_future = None


async def handle_user_input(writer, logged_in, shutdown_event):
    global username
    while True:
        try:
            await asyncio.sleep(1)
            user_input = await get_user_input("dev> ")
            if not user_input:
                continue
            parts = user_input.split()
            command_input = parts[0]
            params = parts[1:]

            resolved_command = resolve_menu_command(command_input, _current_menu(logged_in.value))

            if not resolved_command:
                print("Unknown command. Type 'help' to see available commands.")
                continue

            if resolved_command == "EXIT":
                print("Exiting...")
                logging.info("[Dev] User chose to exit developer client.")
                shutdown_event.set()
                if logged_in.value:
                    await request_logout(writer, logged_in, silent=True)
                try:
                    writer.close()
                    await writer.wait_closed()
                except Exception:
                    pass
                break

            if resolved_command == "HELP":
                display_help(logged_in.value)
                continue

            if resolved_command == "REGISTER":
                if len(params) != 2:
                    print("Usage: register <username> <password>")
                    continue
                await ut.send_command(DEV_SENDER, writer, "REGISTER", params)
                continue

            if resolved_command == "LOGIN":
                if logged_in.value:
                    print("Already logged in.")
                    continue
                if len(params) != 2:
                    print("Usage: login <username> <password>")
                    continue
                username = params[0]
                await ut.send_command(DEV_SENDER, writer, "LOGIN", params)
                continue

            if resolved_command == "LOGOUT":
                await request_logout(writer, logged_in, force=not logged_in.value)
                continue

            if not logged_in.value:
                print("Please log in first.")
                continue

            if resolved_command == "UPLOAD":
                if len(params) != 1:
                    print("Usage: upload <game_name>")
                    continue
                game_name = params[0]
                description = await get_user_input("Enter game description: ")
                await dev_manager.upload_game(
                    game_name,
                    description,
                    user_folder,
                    writer,
                    forward_command,
                    ut.send_message,
                    pending_uploads,
                    pending_upload_confirms,
                )
                continue

            if resolved_command == "UPDATE":
                if len(params) != 1:
                    print("Usage: update <game_name>")
                    continue
                game_name = params[0]
                description = await get_user_input("Enter new description (leave blank to keep current): ")
                await dev_manager.update_game(
                    game_name,
                    description if description != "" else None,
                    user_folder,
                    writer,
                    forward_command,
                    ut.send_message,
                    pending_uploads,
                    pending_upload_confirms,
                )
                continue

            if resolved_command == "DELETE":
                if len(params) != 1:
                    print("Usage: delete <game_name>")
                    continue
                game_name = params[0]
                await dev_manager.delete_game(game_name, writer, forward_command)
                continue

            if resolved_command == "LIST_MINE":
                await dev_manager.list_own_games(writer, forward_command)
                continue

            if resolved_command == "MARKET":
                await ut.send_command(DEV_SENDER, writer, "LIST_ALL_GAMES", [])
                continue

            print("Unknown command. Type 'help' to see available commands.")

        except KeyboardInterrupt:
            print("\nExiting...")
            logging.info("[Dev] Keyboard interrupt received, closing developer client.")
            shutdown_event.set()
            if logged_in.value:
                await request_logout(writer, logged_in, silent=True)
            try:
                writer.close()
                await writer.wait_closed()
            except Exception:
                pass
            break
        except Exception as e:
            if not shutdown_event.is_set():
                print(f"Error sending command: {e}")
            logging.error(f"[Dev] Error sending command: {e}")
            shutdown_event.set()
            try:
                writer.close()
                await writer.wait_closed()
            except Exception:
                pass
            break


async def main():
    ut.init_logging()
    server_ip = config.HOST
    server_port = config.PORT
    try:
        reader, writer = await asyncio.open_connection(server_ip, server_port)
        print("Connected to lobby server.")
    except Exception as e:
        print(f"Unable to connect to server: {e}")
        return

    logged_in = type('', (), {'value': False})()
    shutdown_event = asyncio.Event()

    asyncio.create_task(handle_server_messages(reader, writer, logged_in, shutdown_event))
    asyncio.create_task(handle_user_input(writer, logged_in, shutdown_event))
    display_help(False)
    await shutdown_event.wait()
    print("Developer console closed.")
    logging.info("[Dev] Developer console closed.")


if __name__ == "__main__":
    try:
        asyncio.run(main())
    except KeyboardInterrupt:
        pass
