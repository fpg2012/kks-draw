import ssl
import json
from json import JSONDecodeError
import tornado.web
import tornado.websocket
import tornado.ioloop
import tornado.httpserver
import tornado.options
from tornado.escape import url_escape, url_unescape
import random
import json
import base64
import re

class Game:

    def __init__(self, manager):
        self.deck = self.__init_deck()
        self.conns = set()
        self.__code = base64.b16encode(random.randbytes(3)).decode()
        self.__draw_code = base64.b16encode(random.randbytes(2)).decode()
        self.__current_tile = 'CRFRR'
        self.last_drawer = None
        self.manager = manager
    
    def deck_size(self):
        return len(self.deck)

    @property
    def current_tile(self):
        return self.__current_tile
    
    def draw_tile(self, drawer):
        self.__draw_code = base64.b16encode(random.randbytes(2)).decode()
        self.last_drawer = drawer
        self.broadcast(json.dumps({
            "event": "tile",
            "tile": self.deck.pop(),
            'drawer': drawer.name,
        }))

    @property
    def draw_code(self):
        return self.__draw_code

    @property
    def code(self):
        return self.__code
    
    def __init_deck(self):
        deck = []
        deck.extend(['FFFFK'] * 4)
        deck.extend(['FFRFK'] * 2)
        deck.extend(['CCCCCa'])
        deck.extend(['CCFCC'] * 3)

        deck.extend(['CCFCCa'])
        deck.extend(['CCRCC'])
        deck.extend(['CCRCCa'] * 2)
        deck.extend(['CFFCC'] * 3)

        deck.extend(['CFFCCa'] * 2)
        deck.extend(['CRRCC'] * 3)
        deck.extend(['CRRCCa'] * 2)
        deck.extend(['FCFCC'])

        deck.extend(['FCFCCa'] * 2)
        deck.extend(['CFFCF'] * 2)
        deck.extend(['CFCFF'] * 3)
        deck.extend(['CFFFF'] * 5)

        deck.extend(['CFRRR'] * 3)
        deck.extend(['CRRFR'] * 3)
        deck.extend(['CRRRR'] * 3)
        deck.extend(['CRFRR'] * 3) # starting tile

        deck.extend(['RFRFR'] * 8)
        deck.extend(['FFRRR'] * 9)
        deck.extend(['FRRRR'] * 4)
        deck.extend(['RRRRR'])

        random.shuffle(deck)
        return deck
    
    def broadcast(self, msg):
        for conn in self.conns:
            conn.write_message(msg)
        
    def add_conn(self, conn):
        self.conns.add(conn)

    def update_user_list(self):
        self.broadcast(json.dumps({
            'event': 'update_user_list',
            'in_game_players': [conn.name for conn in self.conns],
        }))
        print([conn.name for conn in self.conns])
    
    def remove_conn(self, conn):
        self.conns.remove(conn)
        if len(self.conns) == 0:
            self.manager.remove_game(self)
        self.update_user_list()

class GameManager:
    
    def __init__(self):
        self.games = {}
    
    def new_game(self):
        game = Game(self)
        self.games[game.code] = game
        print('new game: ', game.code)
        return game
    
    def get_game(self, code):
        return self.games[code]
    
    def remove_game(self, game):
        if game in self.games.values():
            self.games.pop(game.code)

game_manager = GameManager()

class NewGameHandler(tornado.web.RequestHandler):

    def get(self):
        global game_manager
        game = game_manager.new_game()
        self.write(json.dumps({
            'game_code': game.code,
            'draw_code': game.draw_code,
        }))

class PlayerHandler(tornado.websocket.WebSocketHandler):

    def __init__(self, application, request, **kwargs):
        self.game = None
        self.name = None
        super().__init__(application, request, **kwargs)

    def get_game_code(self):
        s = re.split(r'/', self.request.path)
        print(s)
        if len(s) == 3:
            return url_unescape(s[-1])
        else:
            return ''

    def open(self):
        global game_manager
        code = self.get_game_code()
        print('code: ', code)
        if code == '':
            return
        game = game_manager.get_game(code)
        if game is None:
            return
        self.game = game
        self.game.add_conn(self)
        print('open')
        last_drawer = 'base'
        if self.game.last_drawer is not None:
            last_drawer = self.game.last_drawer.name
        try:
            self.write_message(json.dumps({
                'event': 'tile',
                'tile': self.game.current_tile,
                'drawer': last_drawer,
            }))
        except tornado.websocket.WebSocketClosedError:
            self.game.remove_conn(self)

    def on_message(self, message):
        try:
            print(self.game)
            m = json.loads(message)
            print(m)
            method = m['method']
            if method == 'draw':
                draw_code = m['draw_code']
                if (self.game.last_drawer is None or self.game.last_drawer != self) and draw_code == self.game.draw_code:
                    self.game.draw_tile(self)
                    self.write_message(json.dumps({
                        'event': 'draw_ok',
                        'next_draw_code': self.game.draw_code
                    }))
                else:
                    raise KeyError('invalid_draw')
            elif method == 'join':
                name = m['name']
                self.name = name
                self.game.update_user_list()
            else:
                raise KeyError('invalid_method')
        except KeyError as err:
            self.write_message(json.dumps({
                'event': 'error',
                'msg': 'invalid_request',
            }))
            return
        except JSONDecodeError as err:
            self.write_message(json.dumps({
                'event': 'error',
                'msg': 'invalid_json',
            }))
            return
        except Exception as err:
            self.write_message(json.dumps({
                'event': 'error',
                'msg': 'error',
            }))
            return
        
    def on_close(self):
        if self.game is not None:
            self.game.remove_conn(self)

class MainHandler(tornado.web.RequestHandler):
    def get(self):
        s = re.split(r'/', self.request.path)
        print(s, len(s))
        if len(s) == 2:
            self.write(url_unescape(s[-1]))
        else:
            self.set_status(400)
            self.finish()

if __name__ == '__main__':
    tornado.options.define("port", default=6037, help="port to listen on")
    tornado.options.parse_command_line()
    application = tornado.web.Application([
        (r'/code', NewGameHandler),
        (r'/game/.*', PlayerHandler),
        (r'/(.*)', tornado.web.StaticFileHandler, { 'path': '.', 'default_filename': 'index.html' }),
    ])
    application.listen(tornado.options.options.port)
    tornado.ioloop.IOLoop.current().start()
