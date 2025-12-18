import socket
BOARD_SIZE = 15

board = [[' ' for _ in range(BOARD_SIZE)] for _ in range(BOARD_SIZE)]

def print_board():
    print("     " + " | ".join(f"{i + 1:2}" for i in range(BOARD_SIZE)))
    print("   " + "-" * (BOARD_SIZE * 5 - 1))
    for i, row in enumerate(board):
        print(f"{i + 1:2} | " + ' | '.join(f"{cell:2}" for cell in row))
        print("   " + "-" * (BOARD_SIZE * 5 - 1)) 


def is_winner(player):
    for i in range(BOARD_SIZE):
        for j in range(BOARD_SIZE):
            if (check_direction(i, j, player, 1, 0) or
                check_direction(i, j, player, 0, 1) or 
                check_direction(i, j, player, 1, 1) or
                check_direction(i, j, player, 1, -1)):
                return True
    return False

def check_direction(x, y, player, dx, dy):
    count = 0
    for _ in range(5):
        if 0 <= x < BOARD_SIZE and 0 <= y < BOARD_SIZE and board[x][y] == player:
            count += 1
            x += dx
            y += dy
        else:
            break
    return count == 5

def handle_game(tcp_socket, player):
    try:
        if(player == 'X'):
            player ='\u2716'
        else:
            player = '\u2B24'
        now = '\u2716'
        global board
        while True:
            print_board()
            if now == player:
                while(1):
                    action = input(f"Your move ({player}): ")
                    if action.count(' ') == 1 and all(part.isdigit() for part in action.split() and len(action)>=3):
                        row, col = map(int, action.split())
                        if(col > 15 or row > 15 or col < 1 or row < 1):
                            print("invalid position")
                        else:
                            if(board[row-1][col-1] ==  '\u2716' or board[row-1][col-1] == '\u2B24'):
                                print("position have been selected")
                            else:
                                if(player == '\u2716'):
                                    board[row-1][col-1] = '\u2716'
                                else:
                                    board[row-1][col-1] = '\u2B24'
                                break
                    else:
                        print("invalid input")
                tcp_socket.send(f"{row} {col}".encode())
                if is_winner(player):
                    print_board()
                    board = [[' ' for _ in range(BOARD_SIZE)] for _ in range(BOARD_SIZE)]
                    return "W"
            else:
                print("Waiting for the other player's move...")
                move = tcp_socket.recv(1024).decode()
                row, col = map(int, move.split())
                if(now == '\u2716'):
                    board[row-1][col-1] = '\u2716'
                else:
                    board[row-1][col-1] = '\u2B24'
                if is_winner(now):
                    print_board()
                    board = [[' ' for _ in range(BOARD_SIZE)] for _ in range(BOARD_SIZE)]
                    return "L"

            if(now == '\u2B24'):
                now = '\u2716' 
            else:
                now = '\u2B24'
    except Exception:
        print("oppenent leave")
        return "W"