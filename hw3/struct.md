# user side(with gui)
- connect
- login/register
- lobby
    - browse room(with refresh button)
    - browse game (with refresh button)
    - browse users (with refresh button)
    - create a room
    - join a room
- created/joined a room
    - a ready funtion which needs
        - check if user have donwloaded the latest game
            - if not, downloaded from server
        - a confirmation from user
    - constently checking to room user's state
    - if all user is ready, then start the game
- when starting the game, the parent process should tell the clild process the ip:port to connect to
- game...
- when game ended, user is required to rate the game
- quit -> delete all the game under user's side

# dev side (can be done with cli only)
- connect
- login/register
- lobby
    - browse the game created by the dev
    - browse all the games
    - upload a game ( or update )
        -  if its update a game, have a update log with version
    - delete a game
    - quit

# server side
- load user/dev and game list from json
- create lobby, listening to new connection
    - seperate handler for user and dev
- user requests
    - lobby operation (create/join/browse rooms)
    - room operation (ready, automatic start if all user is ready and satisfy the game requirement off the game)
- dev requests
    - browse (his own / all game)
    - upload to the game database, update json
    - delete a game
- room operations
    - wait until all the player is ready
    - start a child process and deal with connection(i don't know if we should assign a port to process or let the process to create the socket)
    - wait until the game is over, have user to rate the game, update to the game's review
    
