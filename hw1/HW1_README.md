# File Structure
## server.py
- Starts server
- Functions
    - handle_create_room
    - handle_client
    - handle_show_status
    - handle_game_over
    - handle_decline_invite
    - handle_accept_invite
    - handle_invite_player

## client.py
- Client-related functions
    - handle_server_messages
    - get_user_input
    - handle_user_input
- Game-related functions
    - initiate_game
    - start_game_as_host
    - handle_game_client
    - start_game_as_client
    - game_loop
    - check_move
    - get_move
- Broadcast-related functions
    - display_online_users
    - display_public_rooms
- For inviting
    - udp_listener
    - udp_discover_players
    - send_udp_invite
    - 

## utils.py
- General
    - send_message
    - broadcast
    - build_response
    - build_command
    - send_command
    - send_lobby_info
    - get_port
- User management
    - hash
    - handle_register
    - handle_login
    - handle_logout
- Logging
    - init_logging

## game.py

## config.py
- class server
- ports

# Homework Requirements
## Lobby server
- User registration, login
- User list database
- If player status on lobby server, not allowed to use connection info in following part

## Player login
1. Player connects to lobby via **TCP**
2. Login or register
    - Confirm login

## Game setup
- Player B runs on CSIT sever, on **UDP** port > 10000
1. Player A: scans servers to find player B
2. A sends B UDP invitation
3. B receive
    - Decline: B continues waiting
    - Accept: Notify A, A starts TCP server and sends port info to B4.
4. Connect to A via TCP
5. Start game session

Player A first creates a room, then they scan server for other available players, server will then print available players. Then player A can use the invite command to invite a player B.

## Gaming
- Use **TCP** for message exchange and communication
- Should include turn management to synchronize actions
- Must maintain consistent view of game state
- Terminate when game ends or player chooses to quit


# Notes
## TODOs
1. sever.py 374