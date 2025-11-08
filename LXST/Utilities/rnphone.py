#!/usr/bin/env python3

import RNS
import os
import sys
import time
import signal
import threading
import argparse

from LXST._version import __version__
from LXST.Primitives.Telephony import Telephone
from RNS.vendor.configobj import ConfigObj

class ReticulumTelephone():
    STATE_AVAILABLE  = 0x00
    STATE_CONNECTING = 0x01
    STATE_RINGING    = 0x02
    STATE_IN_CALL    = 0x03

    HW_SLEEP_TIMEOUT = 15
    HW_STATE_IDLE    = 0x00
    HW_STATE_DIAL    = 0x01
    HW_STATE_SLEEP   = 0xFF
    KPD_NUMBERS      = ["0","1","2","3","4","5","6","7","8","9"]
    KPD_HEX_ALPHA    = ["A","B","C","D","E","F"]
    KPD_SYMBOLS      = ["*","#"]

    RING_TIME        = 30
    WAIT_TIME        = 60
    PATH_TIME        = 10

    def __init__(self, configdir, rnsconfigdir, verbosity = 0, service = False):
        self.service           = service
        self.configdir         = configdir
        self.config            = None
        self.should_run        = False
        self.telephone         = None
        self.state             = self.STATE_AVAILABLE
        self.hw_state          = self.HW_STATE_IDLE
        self.hw_last_event     = time.time()
        self.hw_input          = ""
        self.direction         = None
        self.last_input        = None
        self.first_run         = False
        self.ringtone_path     = None
        self.speaker_device    = None
        self.microphone_device = None
        self.ringer_device     = None
        self.keypad            = None
        self.display           = None
        self.allowed           = Telephone.ALLOW_ALL
        self.allow_phonebook   = False
        self.allowed_list      = []
        self.blocked_list      = []
        self.phonebook         = {}
        self.aliases           = {}
        self.names             = {}
        self.reload_config()
        self.main_menu()
        
        reticulum       = RNS.Reticulum(configdir=rnsconfigdir, loglevel=3+verbosity)
        self.telephone  = Telephone(self.identity, ring_time=self.ring_time, wait_time=self.wait_time)
        self.telephone.set_ringtone(self.ringtone_path)
        self.telephone.set_ringing_callback(self.ringing)
        self.telephone.set_established_callback(self.call_established)
        self.telephone.set_ended_callback(self.call_ended)
        self.telephone.set_speaker(self.speaker_device)
        self.telephone.set_microphone(self.microphone_device)
        self.telephone.set_ringer(self.ringer_device)
        self.telephone.set_allowed(self.allowed)
        self.telephone.set_blocked(self.blocked_list)

    def create_default_config(self):
        rnphone_config = ConfigObj(__default_rnphone_config__.splitlines())
        rnphone_config.filename = self.configpath
        rnphone_config.write()

    def reload_config(self):
        if self.service: RNS.log("Loading configuration...", RNS.LOG_DEBUG)
        if self.configdir == None:
            if os.path.isdir("/etc/rnphone") and os.path.isfile("/etc/rnphone/config"):
                self.configdir = "/etc/rnphone"
            elif os.path.isdir(RNS.Reticulum.userdir+"/.config/rnphone") and os.path.isfile(Reticulum.userdir+"/.config/rnphone/config"):
                self.configdir = RNS.Reticulum.userdir+"/.config/rnphone"
            else:
                self.configdir = RNS.Reticulum.userdir+"/.rnphone"

        self.configpath   = self.configdir+"/config"
        self.ignoredpath  = self.configdir+"/ignored"
        self.allowedpath  = self.configdir+"/allowed"
        self.identitypath = self.configdir+"/identity"
        self.storagedir   = self.configdir+"/storage"

        self.ring_time    = ReticulumTelephone.RING_TIME
        self.wait_time    = ReticulumTelephone.WAIT_TIME
        self.path_time    = ReticulumTelephone.PATH_TIME

        if not os.path.isdir(self.storagedir):
            os.makedirs(self.storagedir)
            ringer_tones = ["ringer.opus", "soft.opus"]
            sounds_path = os.path.abspath(os.path.join(os.path.dirname(__file__), "..", "Sounds"))
            if os.path.isdir(sounds_path):
                import shutil
                for filename in ringer_tones:
                    src_path = os.path.join(sounds_path, filename)
                    dst_path = os.path.join(self.configdir, filename)
                    if os.path.isfile(src_path):
                        RNS.log(f"Copying {src_path} to {dst_path}")
                        shutil.copy(src_path, dst_path)

        if not os.path.isfile(self.configpath):
            self.create_default_config()
            self.first_run = True

        if os.path.isfile(self.configpath):
            try:
                self.config = ConfigObj(self.configpath)
            except Exception as e:
                RNS.log("Could not parse the configuration at "+self.configpath, RNS.LOG_ERROR)
                RNS.log("Check your configuration file for errors!", RNS.LOG_ERROR)
                RNS.panic()

        # Generate or load primary identity
        if os.path.isfile(self.identitypath):
            try:
                self.identity = RNS.Identity.from_file(self.identitypath)
                if self.identity != None:
                    pass
                else:
                    RNS.log("Could not load the Primary Identity from "+self.identitypath, RNS.LOG_ERROR)
                    exit(1)
            except Exception as e:
                RNS.log("Could not load the Primary Identity from "+self.identitypath, RNS.LOG_ERROR)
                RNS.log("The contained exception was: %s" % (str(e)), RNS.LOG_ERROR)
                exit(1)
        else:
            try:
                print("No primary identity file found, creating new...")
                self.identity = RNS.Identity()
                self.identity.to_file(self.identitypath)
                print("Created new Primary Identity %s" % (str(self.identity)))
            except Exception as e:
                RNS.log("Could not create and save a new Primary Identity", RNS.LOG_ERROR)
                RNS.log("The contained exception was: %s" % (str(e)), RNS.LOG_ERROR)
                exit(1)

        self.apply_config()

    def __is_allowed(self, identity_hash):
        if identity_hash in self.allowed_list: return True
        else: return False

    def load_phonebook(self, phonebook):
        if self.service: RNS.log("Loading phonebook...", RNS.LOG_DEBUG)
        for name in phonebook:
            alias = None
            identity_hash = phonebook[name]
            if type(identity_hash) == list:
                components = identity_hash
                identity_hash = components[0]
                alias_input = components[1]
                alias = ""
                for c in alias_input:
                    if c in ["0", "1", "2", "3", "4", "5", "6", "7", "8", "9"]:
                        alias += c
                if len(alias) == 0: alias = None

            if len(identity_hash) == RNS.Reticulum.TRUNCATED_HASHLENGTH//8*2:
                if identity_hash != RNS.hexrep(self.identity.hash, delimit=False):
                    try:
                        hash_bytes = bytes.fromhex(identity_hash)
                        self.phonebook[name] = identity_hash
                        self.names[identity_hash] = name
                        if alias: self.aliases[identity_hash] = alias
                        if self.allow_phonebook: self.allowed_list.append(hash_bytes)
                    except Exception as e:
                        RNS.log(f"Could not load phonebook entry for {name}: {e}", RNS.LOG_ERROR)

    def apply_config(self):
        if "telephone" in self.config:
            config = self.config["telephone"]
            if "ringtone" in config: self.ringtone_path = os.path.join(self.configdir, config["ringtone"])
            if "speaker" in config: self.speaker_device = config["speaker"]
            if "microphone" in config: self.microphone_device = config["microphone"]
            if "ringer" in config: self.ringer_device = config["ringer"]
            if "allowed_callers" in config:
                allowed_callers = config["allowed_callers"]
                if str(allowed_callers).lower() == "all": self.allowed = Telephone.ALLOW_ALL
                elif str(allowed_callers).lower() == "none": self.allowed = Telephone.ALLOW_NONE
                elif str(allowed_callers).lower() == "phonebook":
                    self.allow_phonebook = True
                    self.allowed = self.__is_allowed
                elif type(config["allowed_callers"]) == list:
                    self.allowed = self.__is_allowed
                    for identity_hash in config["allowed_callers"]:
                        if len(identity_hash) == RNS.Reticulum.TRUNCATED_HASHLENGTH//8*2:
                            if identity_hash != RNS.hexrep(self.identity.hash, delimit=False):
                                try: hash_bytes = bytes.fromhex(identity_hash)
                                except Exception as e: RNS.log(f"Could not load allowed caller entry {identity_hash}: {e}", RNS.LOG_ERROR)
                                self.allowed_list.append(hash_bytes)

            if "blocked_callers" in config:
                blocked_callers = config["blocked_callers"]
                if not type(blocked_callers) == list: blocked_callers = [blocked_callers]
                if len(blocked_callers) > 0:
                    for identity_hash in blocked_callers:
                        if len(identity_hash) == RNS.Reticulum.TRUNCATED_HASHLENGTH//8*2:
                            if identity_hash != RNS.hexrep(self.identity.hash, delimit=False):
                                try: hash_bytes = bytes.fromhex(identity_hash)
                                except Exception as e: RNS.log(f"Could not load blocked caller entry {identity_hash}: {e}", RNS.LOG_ERROR)
                                self.blocked_list.append(hash_bytes)

        if "phonebook" in self.config:
            self.load_phonebook(self.config["phonebook"])

        if "hardware" in self.config:
            config = self.config["hardware"]
            if "keypad" in config:
                self.enable_keypad(config["keypad"].lower())
                if "keypad_hook_pin" in config: self.enable_hook(pin = config.as_int("keypad_hook_pin"))
            if "display" in config: self.enable_display(config["display"].lower())

        self.last_dialled_identity_hash = None

    def enable_keypad(self, driver):
        if self.service: RNS.log(f"Starting keypad: {driver}", RNS.LOG_DEBUG)
        if driver == "gpio_4x4":
            from LXST.Primitives.hardware.keypad_gpio_4x4 import Keypad
            self.keypad = Keypad(callback=self._keypad_event)
            self.keypad.start()
        else: raise OSError("Unknown keypad driver specified")

    def enable_hook(self, pin=None):
        if self.keypad: self.keypad.enable_hook(pin=pin)

    def enable_display(self, driver):
        if self.service: RNS.log(f"Starting display: {driver}", RNS.LOG_DEBUG)
        if self.display == None:
            if driver == "i2c_lcd1602":
                from LXST.Primitives.hardware.display_i2c_lcd1602 import LCD
                self.display = LCD()
            else: raise OSError("Unknown display driver specified")

            if self.display:
                threading.Thread(target=self._display_job, daemon=True).start()

    @property
    def is_available(self):
        return self.state == self.STATE_AVAILABLE

    @property
    def is_in_call(self):
        return self.state == self.STATE_IN_CALL

    @property
    def is_ringing(self):
        return self.state == self.STATE_RINGING

    @property
    def call_is_connecting(self):
        return self.state == self.STATE_CONNECTING

    @property
    def hw_is_idle(self):
        return self.hw_state == self.HW_STATE_IDLE

    @property
    def hw_is_dialing(self):
        return self.hw_state == self.HW_STATE_DIAL

    def start(self):
        if not self.should_run:
            signal.signal(signal.SIGINT, self.sigint_handler)
            signal.signal(signal.SIGTERM, self.sigterm_handler)
            self.telephone.announce()
            self.should_run = True
            self.run()

    def stop(self):
        self.should_run = False

    def dial(self, identity_hash):
        self.last_dialled_identity_hash = identity_hash
        self.telephone.set_busy(True)
        identity_hash = bytes.fromhex(identity_hash)
        destination_hash = RNS.Destination.hash_from_name_and_identity("lxst.telephony", identity_hash)
        if not RNS.Transport.has_path(destination_hash):
            RNS.Transport.request_path(destination_hash)
            if self.display: self.display.print("Finding path...", x=0, y=0)
            def spincheck():
                return RNS.Transport.has_path(destination_hash)
            self.__spin(spincheck, "Requesting path for call to "+RNS.prettyhexrep(identity_hash), self.path_time)
            if not spincheck():
                print("Path request timed out")
                if self.display:
                    self.display.print("Finding path", x=0, y=0)
                    self.display.print("timed out", x=0, y=1)
                    time.sleep(1.5)
                self.became_available()

        self.telephone.set_busy(False)
        if RNS.Transport.has_path(destination_hash):
            call_hops = RNS.Transport.hops_to(destination_hash)
            cs = "" if call_hops == 1 else "s"
            print(f"Connecting call over {call_hops} hop{cs}...")
            if self.display:
                call_hops_str = f"({call_hops}h{cs})"
                call_str = "Calling"; ns = self.display.COLS-(len(call_str)+len(call_hops_str)); s = " "*ns
                disp_str = f"{call_str}{s}{call_hops_str}"
                self.display.print(disp_str, x=0, y=0)

            identity = RNS.Identity.recall(destination_hash)
            self.call(identity)
        else:
            self.became_available()

    def redial(self, args=None):
        if self.last_dialled_identity_hash: self.dial(self.last_dialled_identity_hash)

    def call(self, remote_identity):
        print(f"Calling {RNS.prettyhexrep(remote_identity.hash)}...")
        self.state = self.STATE_CONNECTING
        self.caller = remote_identity
        self.direction = "to"
        self.telephone.call(self.caller)

    def ringing(self, remote_identity):
        if self.hw_state == self.HW_STATE_SLEEP: self.hw_state = self.HW_STATE_IDLE
        self.state = self.STATE_RINGING
        self.caller  = remote_identity
        self.direction = "from" if self.direction == None else "to"
        print(f"\n\nIncoming call from {RNS.prettyhexrep(self.caller.hash)}")
        print(f"Hit enter to answer, {Terminal.BOLD}r{Terminal.END} to reject")
        if self.display:
            hash_str = RNS.hexrep(self.caller.hash, delimit=False)
            if hash_str in self.aliases:
                remote_alias = self.aliases[hash_str]
                remote_name  = self.names[hash_str]
                self.display.print(remote_name, x=0, y=0)
                self.display.print(f"({remote_alias})".rjust(self.display.COLS," "), x=0, y=1)

            else:
                self.display.print(hash_str[:16], x=0, y=0)
                self.display.print(hash_str[16:], x=0, y=1)

    def call_ended(self, remote_identity):
        if self.is_in_call or self.is_ringing or self.call_is_connecting:
            if self.is_in_call:         print(f"Call with {RNS.prettyhexrep(self.caller.hash)} ended\n")
            if self.is_ringing:         print(f"Call {self.direction} {RNS.prettyhexrep(self.caller.hash)} was not answered\n")
            if self.call_is_connecting: print(f"Call to {RNS.prettyhexrep(self.caller.hash)} could not be connected\n")
            self.direction = None
            self.state = self.STATE_AVAILABLE
            self.became_available()

    def call_established(self, remote_identity):
        if self.call_is_connecting or self.is_ringing:
            self.state = self.STATE_IN_CALL
            print(f"Call established with {RNS.prettyhexrep(self.caller.hash)}")
            self.display_call_status()

    def display_call_status(self):
        def job():
            started = time.time()
            erase_str = ""
            while self.state == self.STATE_IN_CALL:
                elapsed      = round(time.time()-started)
                time_string  = RNS.prettytime(elapsed)
                stat_string  = f"In call for {time_string}, hit enter to hang up "
                print(f"\r{stat_string}", end="")
                erase_string = " "*len(stat_string)
                sys.stdout.flush()
                print(f"\r{erase_str}", end="")

                if self.display:
                    self.display.print("Call connected", x=0, y=0)
                    self.display.print(f"{time_string}", x=0, y=1)
                    time.sleep(1.00)
                else:
                    time.sleep(0.25)

            print(f"\r{erase_str}> ", end="")

        threading.Thread(target=job, daemon=True).start()

    def became_available(self):
        if not self.service:
            if self.is_available and self.first_run:
                hs = ""
                if not hasattr(self, "first_prompt"): hs = " (or ? for help)"; self.first_prompt = True
                print(f"Enter identity hash and hit enter to call{hs}\n", end="")
            print("> ", end="")
            sys.stdout.flush()

        if self.display:
            self.display.clear()
            self.display.print("Telephone Ready", x=0, y=0)
            self.display.print("", x=0, y=1)

        if self.display or self.keypad:
            self.hw_last_event = time.time()
            self.hw_input = ""
            self.hw_state = self.HW_STATE_IDLE

    def print_identity(self, args):
        print(f"Identity hash of this telephone: {RNS.prettyhexrep(self.identity.hash)}\n")

    def print_destination(self, args):
        print(f"Destination hash of this telephone: {RNS.prettyhexrep(self.telephone.destination.hash)}\n")

    def phonebook_menu(self, args=None):
        if len(self.phonebook) < 1:
            print("\nNo entries in phonebook\n")
        else:
            def exit_menu(args=None):
                print("Phonebook closed")
                self.main_menu()

            def dial_factory(identity_hash):
                def x(args=None): self.dial(identity_hash)
                return x

            print("")
            print(f"{Terminal.UNDERLINE}Phonebook{Terminal.END}")

            self.active_menu = {}
            maxaliaslen = 0
            for identity_hash in self.aliases: maxaliaslen = max(maxaliaslen, len(self.aliases[identity_hash]))
            maxlen = 0; maxnlen = max(maxaliaslen, len(str(len(self.phonebook)))); n = 0
            for name in self.phonebook: maxlen = max(maxlen, len(name))
            for name in self.phonebook:
                n += 1; identity_hash = self.phonebook[name]
                alias = n
                if identity_hash in self.aliases:
                    alias = self.aliases[identity_hash]
                spaces = maxlen-len(name); nspaces = maxnlen-len(str(alias)); s = " "
                print(f"  {Terminal.BOLD}{s*nspaces}{alias}{Terminal.END} {name}{s*spaces} : <{identity_hash}>")
                self.active_menu[f"{alias}"] = dial_factory(identity_hash)

            print(f"  {Terminal.BOLD}b{Terminal.END}ack{s*(max(0, maxlen+maxnlen-2))}: Back to main menu\n")
            self.active_menu["b"] = exit_menu
            self.active_menu["back"] = exit_menu
            self.active_menu["q"] = exit_menu
            self.active_menu["quit"] = exit_menu

    def main_menu(self, args=None):
        def m_help(argv):
            print("")
            print(f"{Terminal.UNDERLINE}Available commands{Terminal.END}")
            print(f"  {Terminal.BOLD}p{Terminal.END}honebook : Open the phonebook")
            print(f"  {Terminal.BOLD}r{Terminal.END}edial    : Call the last called identity again")
            print(f"  {Terminal.BOLD}i{Terminal.END}dentity  : Display the identity hash of this telephone")
            print(f"  {Terminal.BOLD}d{Terminal.END}esthash  : Display the destination hash of this telephone")
            print(f"  {Terminal.BOLD}a{Terminal.END}nnounce  : Send an announce from this telephone")
            print(f"  {Terminal.BOLD}q{Terminal.END}uit      : Exit the program")
            print(f"  {Terminal.BOLD}h{Terminal.END}elp      : This help menu")
            print("")
        
        def m_quit(argv):
            self.quit()

        def m_announce(argv):
            self.telephone.announce()
            print(f"Announce sent")

        self.active_menu = {"help": m_help,
                            "h": m_help,
                            "?": m_help,
                            "p": self.phonebook_menu,
                            "phonebook": self.phonebook_menu,
                            "r": self.redial,
                            "i": self.print_identity,
                            "identity": self.print_identity,
                            "d": self.print_destination,
                            "desthash": self.print_destination,
                            "a": m_announce,
                            "anounce": m_announce,
                            "redial": self.redial,
                            "exit": m_quit,
                            "quit": m_quit,
                            "q": m_quit}

    def run(self):
        if self.service:
            print(f"Reticulum Telephone Service is ready")
            print(f"Identity hash: {RNS.prettyhexrep(self.identity.hash)}")
        else:
            print(f"\n{Terminal.BOLD}Reticulum Telephone Utility is ready{Terminal.END}")
            print(f"  Identity hash: {RNS.prettyhexrep(self.identity.hash)}\n")

        if self.service:
            self.became_available()
            while self.should_run:
                time.sleep(0.5)

        else:
            while self.should_run:
                if self.is_available:
                    if self.last_input and len(self.last_input) == RNS.Reticulum.TRUNCATED_HASHLENGTH//8*2:
                        if self.is_available:
                            try:
                                self.dial(self.last_input)

                            except Exception as e:
                                print(f"Invalid identity hash: {e}\n")
                                RNS.trace_exception(e)

                    elif self.last_input and self.last_input.split(" ")[0] in self.active_menu:
                        self.active_menu[self.last_input.split(" ")[0]](self.last_input.split(" ")[1:])
                        self.became_available()

                    else:
                        self.became_available()

                elif self.is_ringing:
                    if self.last_input == "":
                        print(f"Answering call from {RNS.prettyhexrep(self.caller.hash)}")
                        if not self.telephone.answer(self.caller):
                            print(f"Could not answer call from {RNS.prettyhexrep(self.caller.hash)}")
                    else:
                        print(f"Rejecting call from {RNS.prettyhexrep(self.caller.hash)}")
                        self.telephone.hangup()

                elif self.is_in_call or self.call_is_connecting:
                    print(f"Hanging up call with {RNS.prettyhexrep(self.caller.hash)}")
                    self.telephone.hangup()

                self.last_input = input()

    def cleanup(self):
        if self.display: self.display.close()
        if self.keypad: self.keypad.stop()

    def quit(self):
        self.cleanup()
        exit(0)

    def __spin(self, until=None, msg=None, timeout=None):
        i = 0
        syms = "⢄⢂⢁⡁⡈⡐⡠"
        if timeout != None:
            timeout = time.time()+timeout

        print(msg+"  ", end=" ")
        while (timeout == None or time.time()<timeout) and not until():
            time.sleep(0.1)
            print(("\b\b"+syms[i]+" "), end="")
            sys.stdout.flush()
            i = (i+1)%len(syms)

        print("\r"+" "*len(msg)+"  \r", end="")

        if timeout != None and time.time() > timeout:
            return False
        else:
            return True

    def _display_job(self):
        while self.display:
            now = time.time()
            if self.is_available and self.hw_is_idle and (self.telephone and not self.telephone.busy):
                if now - self.hw_last_event >= self.HW_SLEEP_TIMEOUT:
                    self.hw_state = self.HW_STATE_SLEEP
                    self._sleep_display()

            time.sleep(1)

    def _sleep_display(self):
        if self.display: self.display.sleep()

    def _wake_display(self):
        if self.display: self.display.wake()

    def _update_display(self):
        if self.display:
            if self.hw_is_dialing:
                if len(self.hw_input) == 0: lookup_name = "Enter number"
                else: lookup_name = "Unknown"

                for identity_hash in self.aliases:
                    alias = self.aliases[identity_hash]
                    if self.hw_input == alias: lookup_name = self.names[identity_hash]

                self.display.print(f"{self.hw_input}", x=0, y=0)
                self.display.print(f"{lookup_name}", x=0, y=1)



    def _keypad_event(self, keypad, event):
        self.hw_last_event = time.time()
        if self.hw_state == self.HW_STATE_SLEEP:
            self.hw_state = self.HW_STATE_IDLE
            self._wake_display()
            self.became_available()

        if self.is_ringing:
            answer_events  = event[0] == "D" and event[1] == self.keypad.ec.DOWN
            answer_events |= event[0] == "hook" and event[1] == self.keypad.ec.UP
            if answer_events:
                print(f"Answering call from {RNS.prettyhexrep(self.caller.hash)}")
                if not self.telephone.answer(self.caller):
                    print(f"Could not answer call from {RNS.prettyhexrep(self.caller.hash)}")
            elif event[0] == "C" and event[1] == self.keypad.ec.DOWN:
                print(f"Rejecting call from {RNS.prettyhexrep(self.caller.hash)}")
                self.telephone.hangup()

        elif self.is_in_call or self.call_is_connecting:
            hangup_events  = event[0] == "D" and event[1] == self.keypad.ec.DOWN
            hangup_events |= event[0] == "hook" and event[1] == self.keypad.ec.DOWN
            if hangup_events:
                print(f"Hanging up call with {RNS.prettyhexrep(self.caller.hash)}")
                self.telephone.hangup()

        elif self.is_available and self.hw_is_idle:
            if event[0] == "A" and event[1] == self.keypad.ec.DOWN:
                self.hw_input = ""; self.hw_state = self.HW_STATE_DIAL
                self._update_display()

            if event[0] in self.KPD_NUMBERS and event[1] == self.keypad.ec.DOWN:
                self.hw_input += event[0]; self.hw_state = self.HW_STATE_DIAL
                self._update_display()

        elif self.is_available and self.hw_is_dialing:
            dial_event = False
            if event[1] == self.keypad.ec.DOWN:
                if event[0] in self.KPD_NUMBERS: self.hw_input += event[0]
                if event[0] == "A": self.became_available()
                if event[0] == "B": self.hw_input = self.hw_input[:-1]
                if event[0] == "C": self.hw_input = ""
                if event[0] == "D": dial_event = True

            if event[0] == "hook" and event[1] == self.keypad.ec.UP: dial_event = True

            if dial_event:
                for identity_hash in self.aliases:
                    alias = self.aliases[identity_hash]
                    if self.hw_input == alias:
                        self.hw_input = ""
                        self.hw_state = self.HW_STATE_IDLE
                        self.dial(identity_hash)
            
            self._update_display()

    def sigint_handler(self, signal, frame):
        self.cleanup()
        exit(0)

    def sigterm_handler(self, signal, frame):
        self.cleanup()
        exit(0)

def main():
    app = None
    try:
        parser = argparse.ArgumentParser(description="Reticulum Telephone Utility")

        parser.add_argument("-l", "--list-devices", action="store_true", help="list available audio devices", default=False)
        parser.add_argument("--config", action="store", default=None, help="path to config directory", type=str)
        parser.add_argument("--rnsconfig", action="store", default=None, help="path to alternative Reticulum config directory", type=str)
        parser.add_argument("-s", "--service", action="store_true", help="run as a service", default=False)
        parser.add_argument("--systemd", action="store_true", help="display example systemd unit", default=False)
        parser.add_argument("--version", action="version", version="rnphone {version}".format(version=__version__))
        parser.add_argument('-v', '--verbose', action='count', default=0)

        args = parser.parse_args()

        if args.list_devices:
            import LXST
            RNS.loglevel = 0
            print("\nAvailable audio devices:")
            for device in LXST.Sources.Backend().soundcard.all_speakers():  print(f"  Output : {device}")
            for device in LXST.Sinks.Backend().soundcard.all_microphones(): print(f"  Input  : {device}")
            exit(0)

        if args.systemd:
            print("To install rnphone as a system service, paste the")
            print("systemd unit configuration below into a new file at:\n")
            print("/etc/systemd/system/rnphone.service\n")
            print("Then enable the service at boot by running:\n\nsudo systemctl enable rnphone\n")
            print("--- begin systemd unit snipped ---\n")
            print(__systemd_unit__.replace("USERNAME", os.getlogin()))
            print("---  end systemd unit snipped  ---\n")
            exit(0)

        ReticulumTelephone(configdir = args.config,
                           rnsconfigdir = args.rnsconfig,
                           verbosity = args.verbose,
                           service = args.service).start()

    except KeyboardInterrupt:
        if app: app.quit()
        print("")
        exit()

__default_rnphone_config__ = """# This is an example rnphone config file.
# You should probably edit it to suit your
# intended usage.

[telephone]
    # You can define the ringtone played when the
    # phone is ringing. Must be in OPUS format, and
    # located in the rnphone config directory.
    
    ringtone = ringer.opus

    # You can define the preferred audio devices
    # to use as the speaker output, ringer output
    # and microphone input. The names do not have
    # to be an exact match to your full soundcard
    # device name, but will be fuzzy matched.
    # You can list available device names with:
    # rnphone -l
    
    # speaker = device name
    # microphone = device name
    # ringer = device name

    # You can configure who is allowed to call
    # this telephone. This can be set to either
    # "all", "none", "phonebook" or a list of
    # identity hashes. See examples below.

    # allowed_callers = all
    # allowed_callers = none
    # allowed_callers = phonebook
    # allowed_callers = b8d80b1b7a9d3147880b366995422a45, fcfb80d4cd3aab7c8710541fb2317974

    # It is also possible to block specific
    # callers on a per-identity basis.

    # blocked_callers = f3e8c3359b39d36f3baff0a616a73d3e, 5d2d14619dfa0ff06278c17347c14331

[phonebook]
    # You can add entries to the phonebook for
    # quick dialling by adding them here

    # Mary = f3e8c3359b39d36f3baff0a616a73d3e
    # Jake = b8d80b1b7a9d3147880b366995422a45
    # Dean = 05d4c6697bb38e5458a3077571157bfa

    # You can optionally specify a numerical
    # alias for calling with a physical keypad

    # Rudy = 5d2d14619dfa0ff06278c17347c14331, 241
    # Josh = fcfb80d4cd3aab7c8710541fb2317974, 7907

[hardware]
    # If the required hardware is connected, and
    # the neccessary modules installed, you can
    # enable various hardware components.
    
    # keypad = gpio_4x4
    # display = i2c_lcd1602

    # If you have a keypad connected, you can
    # also enable a GPIO pin for detecting
    # on-hook/off-hook status

    # keypad_hook_pin = 5

    # You can configure a pin for muting the
    # ringer amplifier, if available

    # amp_mute_pin = 25
    # amp_mute_level = high
"""

__systemd_unit__ = """# This systemd unit allows installing rnphone
# as a system service on Linux-based devices
[Unit]
Description=Reticulum Telephone Service
After=sound.target

[Service]
# Wait 30 seconds for WiFi and audio
# hardware to initialise.
ExecStartPre=/bin/sleep 30
Type=simple
Environment="DISPLAY=:0"
Environment="XAUTHORITY=/home/USERNAME/.Xauthority"
Environment="XDG_RUNTIME_DIR=/run/user/1000"
Restart=always
RestartSec=5
User=USERNAME
ExecStart=/home/USERNAME/.local/bin/rnphone --service -vvv

[Install]
WantedBy=graphical.target
"""

class Terminal():
    if not RNS.vendor.platformutils.is_windows():
        UNDERLINE = "\033[4m"
        BOLD = "\033[1m"
        END = "\033[0m"
    else:
        UNDERLINE = ""
        BOLD = ""
        END = ""

if __name__ == "__main__":
    main()