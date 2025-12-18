import asyncio
import logging
import os
from typing import Dict, Optional

import aiofiles
import aiofiles.os


READY_TIMEOUT = 10
CONFIRM_TIMEOUT = 15


async def _wait_for_future(future: asyncio.Future, timeout: int, label: str, key: str) -> bool:
    try:
        await asyncio.wait_for(future, timeout=timeout)
        return True
    except asyncio.TimeoutError:
        logging.error("[Dev] Timed out waiting for %s for %s", label, key)
    except Exception as exc:  # pragma: no cover - defensive
        logging.error("[Dev] Error waiting for %s for %s: %s", label, key, exc)
    return False


async def _send_game_file(game_name: str, file_path: str, writer, send_message) -> bool:
    try:
        file_size = os.path.getsize(file_path)
    except OSError as exc:
        logging.error("[Dev] Cannot stat %s: %s", file_path, exc)
        return False

    await send_message(writer, {"file_size": file_size})
    async with aiofiles.open(file_path, "rb") as f:
        data = await f.read()
    writer.write(data)
    await writer.drain()
    logging.info("[Dev] Sent %s (%d bytes)", game_name, file_size)
    return True


async def _prepare_file(game_name: str, user_folder: str) -> Optional[str]:
    if not user_folder:
        print("Please log in first to set up your developer folder.")
        return None
    file_path = os.path.join(user_folder, f"{game_name}.py")
    if not await aiofiles.os.path.exists(file_path):
        print(f"Game file not found: {file_path}")
        return None
    return file_path


async def upload_game(
    game_name: str,
    description: str,
    user_folder: str,
    writer,
    forward_command,
    send_message,
    pending_uploads: Dict[str, asyncio.Future],
    pending_upload_confirms: Dict[str, asyncio.Future],
) -> bool:
    file_path = await _prepare_file(game_name, user_folder)
    if not file_path:
        return False

    loop = asyncio.get_event_loop()
    ready_future = loop.create_future()
    pending_uploads[game_name] = ready_future
    await forward_command(writer, "UPLOAD_GAME", [game_name, description or ""])

    ready_ok = await _wait_for_future(ready_future, READY_TIMEOUT, "ready", game_name)
    pending_uploads.pop(game_name, None)
    if not ready_ok:
        print("Server did not acknowledge upload readiness in time.")
        return False

    if not await _send_game_file(game_name, file_path, writer, send_message):
        return False

    confirm_future = loop.create_future()
    pending_upload_confirms[game_name] = confirm_future
    confirm_ok = await _wait_for_future(confirm_future, CONFIRM_TIMEOUT, "confirmation", game_name)
    pending_upload_confirms.pop(game_name, None)
    if not confirm_ok:
        print("Upload confirmation timed out.")
        return False
    return True


async def update_game(
    game_name: str,
    description: Optional[str],
    user_folder: str,
    writer,
    forward_command,
    send_message,
    pending_uploads: Dict[str, asyncio.Future],
    pending_upload_confirms: Dict[str, asyncio.Future],
) -> bool:
    file_path = await _prepare_file(game_name, user_folder)
    if not file_path:
        return False

    loop = asyncio.get_event_loop()
    ready_future = loop.create_future()
    pending_uploads[game_name] = ready_future
    payload = [game_name]
    if description is not None:
        payload.append(description)
    await forward_command(writer, "UPDATE_GAME", payload)

    ready_ok = await _wait_for_future(ready_future, READY_TIMEOUT, "ready", game_name)
    pending_uploads.pop(game_name, None)
    if not ready_ok:
        print("Server did not acknowledge update readiness in time.")
        return False

    if not await _send_game_file(game_name, file_path, writer, send_message):
        return False

    confirm_future = loop.create_future()
    pending_upload_confirms[game_name] = confirm_future
    confirm_ok = await _wait_for_future(confirm_future, CONFIRM_TIMEOUT, "confirmation", game_name)
    pending_upload_confirms.pop(game_name, None)
    if not confirm_ok:
        print("Update confirmation timed out.")
        return False
    return True


async def delete_game(game_name: str, writer, forward_command) -> None:
    if not game_name:
        print("Usage: delete <game_name>")
        return
    await forward_command(writer, "DELETE_GAME", [game_name])


async def list_own_games(writer, forward_command) -> None:
    await forward_command(writer, "LIST_OWN_GAMES", [])
