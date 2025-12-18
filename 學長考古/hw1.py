import socket
import random

portA = 10009
tcpPort = 13243

BOARD_SIZE = 15

servers = [
    "140.113.235.151", 
    "140.113.235.152",
    "140.113.235.153",
    "140.113.235.154"
]
def get_ip():
    try:
        s = socket.socket(socket.AF_INET, socket.SOCK_DGRAM)
        s.connect(("8.8.8.8", 80))
        ip = s.getsockname()[0]
    finally:
        s.close()
    return ip

board = [[' ' for _ in range(BOARD_SIZE)] for _ in range(BOARD_SIZE)]

def print_board():
    # Print column labels
    print("     " + " | ".join(f"{i + 1:2}" for i in range(BOARD_SIZE)))
    print("   " + "-" * (BOARD_SIZE * 5 - 1))  # Divider for column labels

    for i, row in enumerate(board):
        # Print row label and the row itself
        print(f"{i + 1:2} | " + ' | '.join(f"{cell:2}" for cell in row))
        print("   " + "-" * (BOARD_SIZE * 5 - 1))  # Divider for rows


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
    now = 'X'
    while True:
        print_board()
        if now == player:
            while(1):
                row, col = map(int, input(f"Your move ({player}): ").split())
                if(col > 15 or row > 15 or col < 1 or row < 1):
                    print("invalid position")
                else:
                    if(board[row-1][col-1] == 'X' or board[row-1][col-1] == 'O'):
                        print("position have been selected")
                    else:
                        board[row-1][col-1] = player
                        break
            tcp_socket.send(f"{row} {col}".encode())
            if is_winner(player):
                print_board()
                print(f"Player {player} wins!")
                tcp_socket.close()
                break
        else:
            print("Waiting for the other player's move...")
            move = tcp_socket.recv(200).decode()
            row, col = map(int, move.split())
            board[row-1][col-1] = now
            if is_winner(now):
                print_board()
                print(f"Player {now} wins!")
                tcp_socket.close()
                break

        if(now == 'O'):
            now = 'X' 
        else:
            now = 'O'

def player_a():
    waiting_players = []
    check_socket = socket.socket(socket.AF_INET, socket.SOCK_DGRAM)
    check_socket.settimeout(0.5)
    hostA = get_ip()
    check_socket.bind(('',portA))
    for i in servers:
        for port in range(11000,11021):
            if(i != hostA and port != portA):
                try:
                    check_socket.sendto("checking".encode(), (i,port))
                    data, _ = check_socket.recvfrom(200)
                    if(data.decode() == "waiting"):
                        waiting_players.append((i,port))
                except:
                    a=1

    check_socket.close()

    if waiting_players:
        print("Found waiting players at the following servers:")
        for i in waiting_players:
            print(f"IP: {i[0]}, Port: {i[1]}")
        chose = input("chosing player: ")
        chosen_player = waiting_players[int(chose)-1]
        hostB = chosen_player[0]
        portB = chosen_player[1]

        udp_socket = socket.socket(socket.AF_INET,socket.SOCK_DGRAM)
        udp_socket.bind(('',portA))
        udp_socket.sendto("game invitation".encode(),(hostB,portB))
        print("waiting for reply")
        data,addr = udp_socket.recvfrom(200)
        if(data.decode() =="accept"):
            print("invitation have been accept")
        
            udp_socket.sendto(str(tcpPort).encode(),(hostB,portB))
            tcp_socket = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
            tcp_socket.bind(('',tcpPort))
            tcp_socket.listen(1)
            new_tcp,addr = tcp_socket.accept()
            print(f"Player B tcp_socketected from {addr}")
            handle_game(new_tcp, 'X')

        else:
            print("invitation have been reject")
            udp_socket.close()
    else:
        print("No waiting players found.")

def player_b():
    
    hostB = get_ip()
    portB = random.randint(11000, 11020)
    print(f"your port is {portB} ")

    udp_socket = socket.socket(socket.AF_INET,socket.SOCK_DGRAM)
    udp_socket.bind((hostB,portB))

    while(1):
        print("waiting")
        data,addr = udp_socket.recvfrom(200)
        if(data.decode() == "checking"):
            udp_socket.sendto("waiting".encode(),(addr[0],addr[1]))
            data,addr = udp_socket.recvfrom(200)
        if(data.decode() == "game invitation"):
            ans = input("accpet or not (y/n): ")
            if(ans == "y"):
                udp_socket.sendto("accept".encode(),(addr[0],addr[1]))
                data,addr = udp_socket.recvfrom(200)
                ip = addr[0]
                tcp_port = data.decode()
                tcp_socket = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
                tcp_socket.connect((ip, int(tcp_port)))
                handle_game(tcp_socket, 'O')
                break

            else:
                udp_socket.sendto("reject",(addr[0],addr[1]))
                print("reject invitation")


def main():
    choice = input("Choose your role (A/B): ").strip().upper()
    if choice == 'A':
        player_a()
    elif choice == 'B':
        player_b()
    else:
        print("Invalid choice! Please choose 'A' or 'B'.")

if __name__ == "__main__":
    main()