from line import Timeout
from datetime import timedelta

class AdamError(RuntimeError):
    pass

class BadModuleType(AdamError):
    def __init__(self, expected, actual):
        self.expected = expected
        self.actual = actual
    def __str__(self):
        return "Bad ADAM module type: %s, expected: %s" % (self.actual, self.expected)

def toString(input):
    if isinstance(input, str):
        return input
    try:
        if isinstance(input, bytes) or isinstance(input, bytearray):
            return input.decode("utf-8")
    except UnicodeDecodeError:
        return ""
    raise TypeError("toString() accept only strings, bytes, or bytearrays")
    
class BadReply(AdamError):
    def __init__(self, request, reply, expected=None):
        self.request = toString(request)
        self.reply = toString(reply)
        self.expected = expected
    def __str__(self):
        rv = "Reply to request " + self.request + " is wrong: " + self.reply
        if (self.expected):
            rv += ", " + self.expected
        return rv 


class AdamModule(object):
    def __init__(self, line, address):
        self.__line__ = line
        assert(address >= 0)
        assert(address < 256)        
        self.__addressNum__ = address
        self.__address__ = bytes("%02X" % address, "utf-8")
        assert(len(self.__address__) == 2) 
        self.timeout = timedelta(seconds=1)
    def query(self, command):
        command = bytes(command, "utf-8")
        address = self.__address__
        request = b"$" + address + command
        self.__line__.lock.acquire()
        try:
            self.__line__.write(request + b"\r")
            try:
                line = self.__line__.readline(self.timeout)
            except Timeout as e:
                raise Timeout("Timeout while waiting for reply for query: " + request.decode("utf-8")) from e
        finally:
            self.__line__.lock.release()
            
        if len(line) < 3:
            raise BadReply(request, line, " reply is too short")
        if line[0:1] != b'!':
            raise BadReply(request, line, " reply should start with !")
        if line[1:3] != address:
            raise BadReply(request, line, " reply should begin with address of module: " + address)
        return line[3:].decode("utf-8")
    def write(self, data):
        address = self.__address__
        data = bytes(data, "utf-8")
        request = b"#" + address + data
        self.__line__.lock.acquire()
        try:
            self.__line__.write(request + b"\r")
            line = self.__line__.readline(self.timeout)
        except Timeout as e:
            raise Timeout("Error while waiting for reply to write request: " + request.decode("utf-8")) from e
        finally:
            self.__line__.lock.release()
        if line == b">":
            return
        elif line[0:1] == b'!':
            if line[1:3] != address:
                raise BadReply(request, line, " wrong address in reply")
            if len(line) == 3:
                return
            if line[3:] != data:
                raise BadReply(request, line, " wrong data in reply")
        elif line[0:1] == b'?':
            raise BadReply(request, line, " malformed write request")
        raise BadReply(request, line, " unknown reply type")
                 

class Adam4068(AdamModule):
    """ 8-channel relay """
    def __init__(self, line, address):
        AdamModule.__init__(self, line, address)
        t = self.query("M")
        if t == "4068":
            self.channelCount=8
        elif t == "4060":
            self.channelCount=4
        else:
            raise BadModuleType("4068", t)
    def setChannel(self, channel, enabled=True):
        """ Switches channel to given position """ 
        if channel < 0 or channel > 7: 
            raise ValueError("Channel should be in [0..7]")
        if enabled:
            enabled = 1
        else:
            enabled = 0
        data = "1%X0%X" % (channel, enabled)
        self.write(data)
    
class Adam4024(AdamModule):
    """ 4-channel analog output module """
    def __init__(self, line, address):
        AdamModule.__init__(self, line, address)  
        t = self.query("M")
        if t != "4024":
            raise BadModuleType("4024", t)
    def __validateChannel__(self, channel):
        if channel < 0 or channel > 3:
            raise ValueError("Invalid channel: %d. Channel should be in  [0..3]" % channel)        
    def setChannel(self, channel, value):
        """ Sets channel output value in volts or miliampers
            Use setChannelOutputRange() to configure current/voltage mode.
        """
        channel = int(channel)
        self.__validateChannel__(channel)
        value = float(value)
        data = "C%X%+07.3f" % (channel, value)
        self.write(data)
    def setChannelOutputRange(self, channel, rangeMode):
        """ Allowed ranges:
        0 -   0 ~ 20 mA
        1 -   4 ~ 20 mA 
        2 - -10 ~ +10 V
        """
        channel = int(channel)
        self.__validateChannel__(channel)      
        if not rangeMode in (0, 1, 2):
            raise ValueError("Invalid rangeMode: %d, range should be in [0,1,2]" % rangeMode)
        query = "7C%dR3%d" % (channel, rangeMode)
        reply = self.query(query)
        if reply != "":
            raise BadReply(query, reply, " reply should be empty string")
        
        
    
