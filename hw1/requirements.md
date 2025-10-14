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

## Gaming
- Use **TCP** for message exchange and communication
- Should include turn management to synchronize actions
- Must maintain consistent view of game state
- Terminate when game ends or player chooses to quit
