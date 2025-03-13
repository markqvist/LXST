import os
import time
import threading
from importlib.util import find_spec
if find_spec("smbus"): import smbus
else: raise OSError(f"No smbus module available, cannot use {os.path.basename(__file__)} driver")

class LCD():
    DEFAULT_ADDR   = 0x27
    DEFAULT_I2C_CH = 1
    COLS           = 16
    ROWS           = 2

    MODE_CHR       = 0x01
    MODE_CMD       = 0x00

    ROW_1          = 0x80
    ROW_2          = 0xC0

    BACKLIGHT_ON   = 0x08
    BACKLIGHT_OFF  = 0x00
    FLAG_ENABLE    = 0b00000100
    FLAG_RS        = 0b00000001

    T_PULSE        = 0.5/1000
    T_DELAY        = 0.5/1000

    CMD_INIT1      = 0x33
    CMD_INIT2      = 0x32
    CMD_CLEAR      = 0x01

    SHARED_BUS     = None

    def __init__(self, address=None):
        if not LCD.SHARED_BUS: LCD.SHARED_BUS = smbus.SMBus(self.DEFAULT_I2C_CH)
        self.address   = address or self.DEFAULT_ADDR
        self.bus       = LCD.SHARED_BUS
        self.row       = LCD.ROW_1
        self.backlight = LCD.BACKLIGHT_ON
        self.__init_display()

    def __init_display(self):
        self.__send_command(LCD.CMD_INIT1)
        self.__send_command(LCD.CMD_INIT2)
        self.__send_command(0x28)           # Data length, number of lines, font size
        self.__send_command(0x0C)           # Display on, cursor off, blink off
        self.__send_command(LCD.CMD_CLEAR)
        time.sleep(LCD.T_DELAY)

    def __send_command(self, command):
        byte  = command & 0xF0 # Transmit MSBs
        byte |= 0x04; self.__send_byte(byte); time.sleep(LCD.T_PULSE)
        byte &= 0xFB; self.__send_byte(byte)

        byte  = (command & 0x0F) << 4 # Transmit LSBs
        byte |= 0x04; self.__send_byte(byte); time.sleep(LCD.T_PULSE)
        byte &= 0xFB; self.__send_byte(byte)

    def __send_data(self, data):
        byte  = data & 0xF0 # Transmit MSBs
        byte |= 0x05; self.__send_byte(byte); time.sleep(LCD.T_PULSE)
        byte &= 0xFB; self.__send_byte(byte)

        byte  = (data & 0x0F) << 4 # Transmit LSBs
        byte |= 0x05; self.__send_byte(byte); time.sleep(LCD.T_PULSE)
        byte &= 0xFB; self.__send_byte(byte)

    def __send_byte(self, byte):
        self.bus.write_byte(self.address, byte | self.backlight)

    def print(self, string, x=0, y=0):
        string = string.ljust(LCD.COLS," ")
        if x <  0: x = 0
        if x > 15: x = 15
        if y <  0: y = 0
        if y >  1: y = 1
        if self.is_sleeping: self.wake()
        self.__send_command(0x80 + 0x40 * y + x) # Set cursor location
        for i in range(LCD.COLS): self.__send_data(ord(string[i]))

    def clear(self):
        self.print("", x=0, y=0)
        self.print("", x=0, y=1)

    @property
    def is_sleeping(self):
        return self.backlight == LCD.BACKLIGHT_OFF

    def sleep(self):
        self.backlight = LCD.BACKLIGHT_OFF
        self.__send_command(LCD.CMD_CLEAR)

    def wake(self):
        self.backlight = LCD.BACKLIGHT_ON
        self.__init_display()

    def close(self):
        self.sleep()
        self.bus.close()
        self.bus = None
        LCD.SHARED_BUS = None