import asyncio
import json
import logging

ASCII_ART = {
    'rock': '''
        _______
    ---'   ____)
          (_____)
          (_____)
          (____)
    ---.__(___)
    ''',
    'paper': '''
         _______
    ---'    ____)____
               ______)
              _______)
             _______)
    ---.__________)
    ''',
    'scissors': '''
        _______
    ---'   ____)____
              ______)
           __________)
          (____)
    ---.__(___)
    '''
}

VALID_MOVES = ['rock', 'paper', 'scissors']

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
        await start_rps_game_as_host(own_port, peer_info)
    elif role == "client":
        await start_rps_game_as_client(peer_ip, peer_port, peer_info)
    else:
        print("無效的角色，無法啟動遊戲")

# -------------------------
# Rock-Paper-Scissors (RPS) 遊戲函數
# -------------------------

async def start_rps_game_as_host(own_port, peer_info):
    server = await asyncio.start_server(lambda r, w: handle_rps_client(r, w, peer_info), '0.0.0.0', own_port)
    logging.info(f"等待客戶端連接於 {own_port} 作為 RPS 主機...")
    print(f"等待客戶端連接於 {own_port} 作為 RPS 主機...")
    
    global server_close_event
    server_close_event = asyncio.Event()

    async def stop_server():
        await server_close_event.wait()
        server.close()
        await server.wait_closed()
        print("遊戲伺服器已關閉。")

    async with server:
        await asyncio.gather(server.serve_forever(), stop_server())

async def handle_rps_client(reader, writer, peer_info):
    try:
        print("RPS 客戶端已連接。")
        await rps_game_loop(reader, writer, "Host", peer_info)
    except Exception as e:
        logging.error(f"RPS 主機錯誤：{e}")
    finally:
        writer.close()
        await writer.wait_closed()

async def start_rps_game_as_client(peer_ip, peer_port, peer_info, max_retries=10, retry_delay=2):
    writer = None
    retries = 0

    while retries < max_retries:
        try:
            print(f"正在連接到 {peer_ip}:{peer_port} 的 RPS 主機作為客戶端...（嘗試 {retries + 1}）")
            reader, writer = await asyncio.open_connection(peer_ip, peer_port)
            print("已成功連接到主機。")
            await rps_game_loop(reader, writer, "Client", peer_info)
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
            logging.error(f"啟動 RPS 客戶端模式時失敗：{e}")
            break

    if writer is not None:
        writer.close()
        await writer.wait_closed()

async def rps_game_loop(reader, writer, role, peer_info):
    my_move = None
    opponent_move = None
    game_over = False

    while not game_over:
        if role == "Host":
            # Host move
            my_move = await get_rps_move("Host")
            await send_message(writer, {"move": my_move})
            print("等待對手的移動...")
            data = await reader.read(1024)
            if not data:
                print("對手已斷開連接。")
                game_over = True
                break
            try:
                message = json.loads(data.decode())
                opponent_move = message.get("move")
                if opponent_move not in VALID_MOVES:
                    print("收到無效的移動。")
                    continue
            except json.JSONDecodeError:
                print("收到無效的訊息。")
                continue
        else:
            # Client move
            print("等待對手的移動...")
            data = await reader.read(1024)
            if not data:
                print("對手已斷開連接。")
                game_over = True
                break
            try:
                message = json.loads(data.decode())
                opponent_move = message.get("move")
                if opponent_move not in VALID_MOVES:
                    print("收到無效的移動。")
                    continue
            except json.JSONDecodeError:
                print("收到無效的訊息。")
                continue
            my_move = await get_rps_move("Client")
            await send_message(writer, {"move": my_move})

        result = determine_rps_winner(my_move, opponent_move, role)
        display_rps_result(my_move, opponent_move, result, role)
        game_over = True
        server_close_event.set()

async def get_rps_move(player):
    while True:
        move = await get_user_input(f"玩家 {player}，請選擇 rock、paper 或 scissors：")
        move = move.strip().lower()
        if move in VALID_MOVES:
            print(ASCII_ART.get(move, ''))
            return move
        else:
            print("無效的選擇，請再試一次。")

def determine_rps_winner(my_move, opponent_move, role):
    if my_move == opponent_move:
        return "平局"
    elif (my_move == 'rock' and opponent_move == 'scissors') or \
         (my_move == 'paper' and opponent_move == 'rock') or \
         (my_move == 'scissors' and opponent_move == 'paper'):
        return f"玩家 {role} 獲勝"
    else:
        return f"玩家 {'Client' if role == 'Host' else 'Host'} 獲勝"

def display_rps_result(my_move, opponent_move, result, role):
    print("\n=== 遊戲結果 ===")
    print(f"您的移動：{my_move}")
    print(ASCII_ART.get(my_move, ''))
    print(f"對手的移動：{opponent_move}")
    print(ASCII_ART.get(opponent_move, ''))
    print(f"結果：{result}")
    print("================")
