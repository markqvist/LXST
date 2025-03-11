import os
import time
import threading
from importlib.util import find_spec
if find_spec("RPi"): import RPi.GPIO as GPIO
else: raise OSError(f"No GPIO module available, cannot use {os.path.basename(__file__)} driver")

class Event:
    UP    = 0x00
    DOWN  = 0x01

class Keypad():
    ROWS             = 4
    COLS             = 4
    SCAN_INTERVAL_MS = 20

    LOW              = 0x00
    HIGH             = 0x01

    DEFAULT_MAP      = [["1", "2", "3", "A"],
                        ["4", "5", "6", "B"],
                        ["7", "8", "9", "C"],
                        ["*", "0", "#", "D"]]

    DEFAULT_ROWPINS  = [21, 20, 16, 12]
    DEFAULT_COLPINS  = [26, 19, 13, 6]
    DEFAULT_HOOKPIN  = 5
    HOOK_DEBOUNCE_MS = 150

    def __init__(self, row_pins=None, col_pins=None, key_map=None, callback=None):
        if not row_pins == None and (not type(row_pins) == list or len(row_pins) != 4):
            raise ValueError("Invalid row pins specification")
        if not col_pins == None and (not type(col_pins) == list or len(col_pins) != 4):
            raise ValueError("Invalid row pins specification")

        self.row_pins   = row_pins or self.DEFAULT_ROWPINS
        self.col_pins   = col_pins or self.DEFAULT_COLPINS
        self.scan_lock  = threading.Lock()
        self.callback   = callback
        self.hook_time  = 0
        self.hook_pin   = None
        self.on_hook    = True
        self.check_hook = False
        self.should_run = False
        self.ec         = Event
        self.set_key_map(key_map)

    def enable_hook(self, pin=None):
        if pin == None: pin = self.DEFAULT_HOOKPIN
        self.hook_pin = pin
        GPIO.setup(self.hook_pin, GPIO.IN, pull_up_down=GPIO.PUD_UP)
        self.key_states["hook"] = False
        self.check_hook = True

    def set_key_map(self, key_map):
        self.key_map    = key_map or self.DEFAULT_MAP
        self.key_states = {}
        for row in self.key_map:
            for key in row: self.key_states[key] = False

    def is_down(self, key):
        if not key in self.key_states: return False
        else:
            return self.key_states[key]

    def is_up(self, key):
        if not key in self.key_states: return False
        else:
            return not self.key_states[key]

    def __job(self):
        while self.should_run:
            self.__scan()
            time.sleep(self.SCAN_INTERVAL_MS/1000)

    def __handle(self, active_keys):
        events = []
        for key in self.key_states:
            if self.key_states[key] == False:
                if key in active_keys:
                    self.key_states[key] = True
                    events.append((key, Event.DOWN))

            elif self.key_states[key] == True:
                if not key in active_keys:
                    self.key_states[key] = False
                    events.append((key, Event.UP))

        if callable(self.callback):
            for event in events:
                self.callback(self, event)

    def __scan(self):
        active_keys = []
        for row in range(0, self.ROWS):
            GPIO.setup(self.row_pins[row], GPIO.OUT)
            GPIO.output(self.row_pins[row], GPIO.HIGH)
            for col in range(0, self.COLS):
                if GPIO.input(self.col_pins[col]):
                    active_keys.append(self.key_map[row][col])

            GPIO.output(self.row_pins[row], GPIO.LOW)
            GPIO.setup(self.row_pins[row], GPIO.IN, pull_up_down=GPIO.PUD_OFF)

        if self.check_hook:
            on_hook = GPIO.input(self.hook_pin) == GPIO.LOW

            if on_hook:
                active_keys.append("hook")
                self.hook_time = time.time()

            if self.key_states["hook"] == True and not on_hook:
                if time.time()-self.hook_time < self.HOOK_DEBOUNCE_MS/1000:
                    active_keys.append("hook")
                else:
                    self.hook_time = time.time()

        if len(active_keys) >= 0 and len(active_keys) <= 4: self.__handle(active_keys)

    def start(self):
        GPIO.setwarnings(False)
        GPIO.setmode(GPIO.BCM)
        for row_pin in self.row_pins: GPIO.setup(row_pin, GPIO.OUT)
        for col_pin in self.col_pins: GPIO.setup(col_pin, GPIO.IN, pull_up_down=GPIO.PUD_DOWN)

        self.should_run = True
        threading.Thread(target=self.__job, daemon=True).start()

    def stop(self):
        self.should_run = False