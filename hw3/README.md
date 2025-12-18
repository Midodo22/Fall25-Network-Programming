# Initializing
Please first git clone this repository to your local machine.
```
git clone https://github.com/Midodo22/Fall25-Network-Programming.git
```
and run `make`
## Game Dev
There are a few ways to initialize the game dev files.
Default game dev accounts are:
| Username    | Password |
| -------- | ------- |
| dev1     | 111    |
| dev2     | 222    |

### Option 1. Run `make` command in the terminal. </br>
If you get the error ``.venv/bin/python not found``, run the following command first:
``chmod +x .venv/bin/python``,then run `make` again. </br>
This creates two users called dev and dev1, you can then run the file `game_dev_client.py` to access the game dev client and upload the games from there. </br> You can upload `rps.py` with dev1 and `tetris.py` with dev2.

### Option 2. Manually copy the game files.
If you don't mind using the default game dev accounts, run the `game_dev_client.py` file and login with the credentials above.
Then copy the game files you want to upload into the folders named `games-dev1` and `games-dev2`  from `games`, then use the `upload <game_name>` command in the game dev console to upload the game.

### Option 3. Create your own game dev account.
If you want a game dev account with your preferred username, you can run the `game_dev_client.py` file and register a new account. After registering, login, and a folder named `games-<your_username>` will be created in the root directory. Copy the game files you want to upload into that folder from `games`, then use the `upload <game_name>` command in the game dev console to upload the game.