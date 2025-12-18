import asyncio
import json
import logging

async def send_message(writer, message):
    try:
        data = json.dumps(message) + '\n'
        writer.write(data.encode())
        await writer.drain()
    except Exception as e:
        logging.error(f"發送消息失敗：{e}")

async def get_user_input(prompt):
    loop = asyncio.get_event_loop()
    return await loop.run_in_executor(None, lambda: input(prompt).strip().lower())

async def main(peer_info):
    role = peer_info.get("role")
    own_port = peer_info.get("own_port")
    peer_ip = peer_info.get("peer_ip")
    peer_port = peer_info.get("peer_port")

    if None in [role, own_port, peer_ip, peer_port]:
        print("錯誤：缺少必要的 P2P 連接資訊。")
        logging.error("缺少必要的 P2P 連接資訊。")
        return

    try:
        own_port = int(own_port)
        peer_port = int(peer_port)
    except ValueError:
        print("錯誤：無效的端口號。")
        logging.error("無效的端口號。")
        return

    if role == "host":
        await start_tictactoe_game_as_host(own_port, peer_info)
    elif role == "client":
        await start_tictactoe_game_as_client(peer_ip, peer_port, peer_info)
    else:
        print("無效的角色，無法啟動遊戲")

# -------------------------
# Tic-Tac-Toe (TTT) 遊戲函數
# -------------------------

async def start_tictactoe_game_as_host(own_port, peer_info):
    server = await asyncio.start_server(lambda r, w: handle_tictactoe_client(r, w, peer_info), '0.0.0.0', own_port)
    logging.info(f"等待客戶端連接於 {own_port} 作為 Tic-Tac-Toe 主機...")
    print(f"等待客戶端連接於 {own_port} 作為 Tic-Tac-Toe 主機...")
    
    global server_close_event
    server_close_event = asyncio.Event()

    async def stop_server():
        await server_close_event.wait()
        server.close()
        await server.wait_closed()
        print("遊戲伺服器已關閉。")

    async with server:
        await asyncio.gather(server.serve_forever(), stop_server())

async def handle_tictactoe_client(reader, writer, peer_info):
    try:
        print("Tic-Tac-Toe 客戶端已連接。")
        await tictactoe_game_loop(reader, writer, "Host", peer_info)
    except Exception as e:
        logging.error(f"Tic-Tac-Toe 主機錯誤：{e}")
    finally:
        writer.close()
        await writer.wait_closed()

async def start_tictactoe_game_as_client(peer_ip, peer_port, peer_info, max_retries=10, retry_delay=2):
    writer = None
    retries = 0

    while retries < max_retries:
        try:
            print(f"正在連接到 {peer_ip}:{peer_port} 的 Tic-Tac-Toe 主機作為客戶端...（嘗試 {retries + 1}）")
            reader, writer = await asyncio.open_connection(peer_ip, peer_port)
            print("已成功連接到主機。")
            await tictactoe_game_loop(reader, writer, "Client", peer_info)
            break

        except ConnectionRefusedError:
            retries += 1
            if retries >= max_retries:
                logging.error(f"嘗試 {max_retries} 次後連接失敗。")
                print(f"嘗試 {max_retries} 次後連接失敗。正在退出...")
                return
            else:
                print(f"連接被拒絕，{retry_delay} 秒後重試...")
                await asyncio.sleep(retry_delay)

        except Exception as e:
            logging.error(f"啟動 Tic-Tac-Toe 客戶端模式時失敗：{e}")
            break

    if writer is not None:
        writer.close()
        await writer.wait_closed()

async def tictactoe_game_loop(reader, writer, role, peer_info):
    board = [' ' for _ in range(9)]
    my_symbol = 'X' if role == "Host" else 'O'
    opponent_symbol = 'O' if role == "Host" else 'X'
    current_turn = 'X'  # 'X' moves first
    game_over = False

    while not game_over:
        display_board(board)
        if current_turn == my_symbol:
            move = await get_tictactoe_move(board, my_symbol)
            board[move] = my_symbol
            await send_message(writer, {"move": move})
        else:
            print("等待對手的移動...")
            data = await reader.read(1024)
            if not data:
                print("對手已斷開連接。")
                game_over = True
                break
            message = json.loads(data.decode())
            move = message.get("move")
            board[move] = opponent_symbol

        if check_winner(board, my_symbol):
            display_board(board)
            print(f"玩家 {my_symbol} 獲勝!")
            game_over = True
            server_close_event.set()
        elif check_winner(board, opponent_symbol):
            display_board(board)
            print(f"玩家 {opponent_symbol} 獲勝!")
            game_over = True
            server_close_event.set()
        elif ' ' not in board:
            display_board(board)
            print("平局!")
            game_over = True
            server_close_event.set()
        else:
            # Switch turns
            current_turn = opponent_symbol if current_turn == my_symbol else my_symbol

def display_board(board):
    print("\n當前棋盤：")
    display = [str(i+1) if cell == ' ' else cell for i, cell in enumerate(board)]
    print(f" {display[0]} | {display[1]} | {display[2]} ")
    print("---+---+---")
    print(f" {display[3]} | {display[4]} | {display[5]} ")
    print("---+---+---")
    print(f" {display[6]} | {display[7]} | {display[8]} ")
    print("")

async def get_tictactoe_move(board, player):
    while True:
        try:
            move = int(await get_user_input(f"玩家 {player}，請輸入您的移動 (1-9)：")) - 1
            if 0 <= move <= 8 and board[move] == ' ':
                return move
            else:
                print("無效的移動，請再試一次。")
        except ValueError:
            print("請輸入 1 到 9 之間的數字。")

def check_winner(board, player):
    win_conditions = [
        [0,1,2], [3,4,5], [6,7,8],  # rows
        [0,3,6], [1,4,7], [2,5,8],  # columns
        [0,4,8], [2,4,6]            # diagonals
    ]
    return any(all(board[pos] == player for pos in condition) for condition in win_conditions)