import hashlib

def hash(p):
    pswd = hashlib.sha1(str(p).encode('utf-8')).hexdigest()
    return str(pswd)

class users:
    def __init__(self):
        self.users = {
            "admin":{
                "password": "7110eda4d09e062aa5e4a390b0a572ac0d2c0220",  # 1234
                "status": 0
            }
        }
        self.user_count = 0
        
    def register(self, username, password):
        if username in self.users:
            print("Username exists, please choose a new one.")
            return False
        
        hashed_pswd = hash(password)
        self.users[username] = {
            "password": hashed_pswd,
            "status": 0
        }
        self.user_count += 1
        print("Registration successfull, please login.")
        return True
        
    def login(self, username, password):
        if username in self.users:
            hashed_pswd = hash(password)
            if self.users[username]["password"] == hashed_pswd:
                self.users[username]["status"] = 1
                print("Login successful")
                return True
            else:
                print("Password incorrect.")
                return False
        else:
            print("User not registered.")
        return False
    

if __name__ == '__main__':
    user = users()
    user.register('Mido', 'hello')

    user.login('Mido', "hello")
    user.register('Mido', 'asdjio')
