from time import sleep
from struct import pack, unpack
from datetime import timedelta
import unittest 
from .line import Line

class PivError(RuntimeError):
    pass

class BadPivPacket(PivError):
    pass

class BadPivModuleType(PivError):
    pass

class BadPivRelpy(PivError):
    pass

def calcControl(data):
    rv = 0
    for b in data:
        rv ^= b
    return rv

class Piv(object):
    '''
    Volkov's protocol
    '''
    cstart = 0xAA
    cstop = 0xAB
    cshift = 0xAC
    escapedSymbols = (cstart, cstop, cshift)
    def __init__(self, line):
        assert(isinstance(line, Line))
        self.__line__ = line
        self.timeout = timedelta(seconds=1)
        
    def send(self, address, data):
        assert(isinstance(address, int))
        assert(address >= 0)
        assert(address < 256)
        body = bytearray()
        body.append(address)
        body += data        

        control = calcControl(body)
        assert(control < 256)
             
        body.append(control)
        buffer = bytearray()        
        buffer.append(Piv.cstart)
        for b in body:
            assert(b >=0 and b < 256)
            if b in Piv.escapedSymbols:
                buffer.append(Piv.cshift)
                buffer.append(b - Piv.cstart)
            else:
                buffer.append(b)
        buffer.append(Piv.cstop)
        self.__line__.write(buffer)
    eol = bytes([cstop])
    def receive(self, address):
        assert(isinstance(address, int))   
        data = self.__line__.readline(self.timeout, Piv.eol)
        if len(data) < 2:
            raise BadPivPacket(("Piv packet is too short", data))
        converted = bytearray()
        shifted = False
        for b in data:
            if b == Piv.cshift:
                if shifted:
                    raise BadPivPacket(("Invalid shift", data))
                shifted = True
                continue
            if shifted:
                if b + Piv.cstart > 255 or b in Piv.escapedSymbols:
                    raise BadPivPacket(("Invalid shift", data))                    
                b += Piv.cstart
            shifted = False
            assert(b >=0 and b < 256)
            converted.append(b)
        body = converted[0:-1]
        control = calcControl(body)
        if control != converted[-1]:
            raise BadPivPacket(("Bad control sum", converted))
        if body[0] != address:
            raise BadPivPacket(("Invalid address", data))
        return body[1:]
    def query(self, address, request):
        self.__line__.lock.acquire()
        try:
            self.send(address, request)
            return self.receive(address)
        finally:
            self.__line__.lock.release()
            

class PivModule(object):
    def __init__(self, piv, address):
        assert(isinstance(piv, Piv))
        self.__piv__ = piv
        self.__address__ = int(address)
    def query(self, request):
        return self.__piv__.query(self.__address__, request)

def unpackBits(count, number):
    rv = []
    for i in range(count):
        rv.append(bool(number & (1 << (count - i - 1))))
    return rv

def packBits(bits):
    rv = 0
    count = len(bits)
    for i in range(count):
        if bits[i]:
            rv |= (1 << (count - i -1))
    assert(count > 8 or rv < 256)
    return rv
    
class Kshd(PivModule):
    invalidCoordinate = unpack("!i", b'\x80\x00\x00\x00')
    def __init__(self, piv, address):
        PivModule.__init__(self, piv, address)
        data = self.query(b'\x01')
        if data[0:2] != b'WS':
            raise BadPivModuleType(data)
        self.getCoordinate()
        self.lastCoordinate = 0
    class Status(object):
        def __init__(self, b):
            b = int(b)
            self.__b__ = b
            rv = self
            rv.ready = b & 1
            rv.moving = b & 2
            rv.atMinus = b & 4
            rv.atPlus = b & 8
            rv.atZero = b & 16
            rv.exactSpeed = b & 32
        def __repr__(self):
            return "piv.Kshd.Status(0x%X)" % self.__b__
    class Configuration(object):
        """ Holds part of Kshd settings
            contains fields:
            moveCurrent
            holdCurrent
            holdDelay (time in seconds to hold the motor after stop)
            accLeave (leave with acceleration)
            leaveK  (leave automatically)
            softK (stop on with acceleration)
            zeroOpened, plusOpened, minusOpened (are True if corresponding pin switch is normally opened)
            half is True for 8-phase mode, False for 4-phase  
        """
        def __init__(self, moveCurrent=0, holdCurrent=0, holdDelay=0, accLeave=True, leaveK = False, softK=True, zeroOpened=True, plusOpened=True, minusOpened=True, half=True):
            self.moveCurrent, self.holdCurrent, self.holdDelay = map(float, (moveCurrent, holdCurrent, holdDelay))
            if self.holdDelay * 30 > 255:
                raise ValueError("Hold delay is too big: %f" % self.holdDelay)
            self.accLeave, self.leaveK, self.softK, self.zeroOpened, self.plusOpened, self.minusOpened, self.half = map(bool, (accLeave, leaveK, softK, zeroOpened, plusOpened, minusOpened, half))
        currentMap=[0, 0.2, 0.3, 0.5, 0.6, 1.0, 2.0, 3.5]
        @staticmethod
        def codeToCurrent(code):
            code = int(code)
            if code < 0 or code > 7:
                raise ValueError("Invalid current code: " + code)
            return Kshd.Configuration.currentMap[code]
        @staticmethod
        def currentToCode(value):
            currentMap = Kshd.Configuration.currentMap
            value = float(value)
            if value < 0 or value > 3.5:
                raise ValueError("Can't set current %f" % value)
            if value == currentMap[len(currentMap)-1]:
                return len(currentMap)-1
            for code in range(len(currentMap)):
                if currentMap[code] > value:
                    return code - 1
            raise ValueError("Can't set current %f" % value)
        @staticmethod
        def fromWord(word):
            assert(len(word)==4)
            moveCurrent = Kshd.Configuration.codeToCurrent(word[0])
            holdCurrent = Kshd.Configuration.codeToCurrent(word[1])
            holdDelay = float(int(word[2]))/30.
            cfg = int(word[3])
            accLeave, leaveK, softK, zeroOpened, plusOpened, minusOpened, dummy, half = unpackBits(8, cfg)
            if dummy:
                raise ValueError("Second bit of configuration word should always be zero: %02x" % cfg)
            return Kshd.Configuration(moveCurrent, holdCurrent, holdDelay, accLeave, leaveK, softK, zeroOpened, plusOpened, minusOpened, half)
        def toWord(self):
            word = bytearray(4)
            currentToCode = Kshd.Configuration.currentToCode
            word[0] = currentToCode(self.moveCurrent)
            word[1] = currentToCode(self.holdCurrent)
            word[2] = int(self.holdDelay * 30.)
            cfg = packBits((self.accLeave, self.leaveK, self.softK, self.zeroOpened, self.plusOpened, self.minusOpened, False, self.half))
            assert(cfg >= 0)
            assert(cfg < 256)
            word[3]=cfg
            return word
        def __repr__(self):
            return "piv.Kshd.Configuration(moveCurrent=%f, holdCurrent=%f, holdDelay = %f, accLeave=%r, leaveK=%r, softK=%r, zeroOpened=%r, plusOpened=%r, minusOpened=%r, half=%r" % (self.moveCurrent, self.holdCurrent, self.holdDelay, self.accLeave, self.leaveK, self.softK, self.zeroOpened, self.plusOpened, self.minusOpened, self.half)
    class SpeedConf(object):
        def __init__(self, min, max, acc):
            self.min = int(min)
            self.max = int(max)
            self.acc = int(acc)
            self.__normalize__()
        @staticmethod
        def fromWord(word):
            assert(len(word)==6)
            return Kshd.SpeedConf(*unpack("!HHH", word))
        def toWord(self):
            self.__normalize__()
            return pack("!HHH", self.min, self.max, self.acc)
        def __normalize__(self):
            if self.min < 32:
                self.min=32
            if self.min > 12000:
                self.min = 12000
            if self.max < 32:
                self.max = 32
            if self.max > 12000:
                self.max = 12000
            if self.acc < 32:
                self.acc = 32
            if self.acc > 65535:
                self.acc = 65535
        def __repr__(self): 
            return "piv.Kshd.SpeedConf(%d, %d, %d)" % (self.min, self.max, self.acc)
    def __queryForStatus__(self, data):
        reply = self.query(data)
        if len(reply) != 1:
            raise BadPivRelpy("Invalid reply: %s for query: %s" % (str(reply), str(data)))
        return Kshd.Status(reply[0])
    def status(self):
        return self.__queryForStatus__(b'\x03')
    def waitReady(self):
        while(not self.status().ready):
            sleep(0.1)
            pass
    def goWithSpeed(self, steps, stepTime):        
        return self.__queryForStatus__(b'\x11'+pack("!iI", steps, stepTime))
    def stop(self):
        return self.__queryForStatus__(b'\x08')
    def getCoordinate(self):
        if not self.status().ready:
            return self.lastCoordinate
        reply = self.query(b'\x14')
        if len(reply)!=4:
            raise BadPivRelpy("Invalid position reply: "+str(reply))
        rv = unpack("!i", reply)
        if rv[0] == Kshd.invalidCoordinate:
            try:
                self.setCoordinate(0)
            except:
                pass
            raise BadPivRelpy("Invalid coordinate")
        self.lastCoordinate = rv[0]
        return rv[0]
    def setCoordinate(self, x):
        return self.__queryForStatus__(b'\x13'+pack("!i", x))
    def getStepsToGo(self):
        reply = self.query(b'\x0C')
        return unpack("!I", reply)[0]
    def getConfiguration(self):
        reply = self.query(b'\x0D')
        if len(reply) != 4:
            raise BadPivRelpy("Kshd configuration should be 4 bytes length: "+str(reply))
        return Kshd.Configuration.fromWord(reply)
    def setConfiguration(self, conf):
        assert(isinstance(conf, Kshd.Configuration))
        return self.__queryForStatus__(b'\x06'+conf.toWord())
    def go(self, steps):
        steps = int(steps)
        return self.__queryForStatus__(b'\x04'+pack("!i", steps))
    def freqEmit(self):
        self.__piv__.send(self.__address__, b'\x10')
    def getSpeed(self):
        reply = self.query(b'\x0E')
        if len(reply)!=6:
            raise ValueError("Invalid speed reply: "+str(reply))
        try:
            return Kshd.SpeedConf.fromWord(reply)
        except ValueError:
            self.setSpeed(Kshd.SpeedConf(1000, 6000, 10000))
            raise
    def setSpeed(self, speedConf):
        assert(isinstance(speedConf, Kshd.SpeedConf))
        word = speedConf.toWord()
        rv = self.__queryForStatus__(b'\x07'+word)
        check = self.query(b'\x0E')
        if check != word:
            raise RuntimeError("Failed to write speed. Written: %X, read: %X" % ())
        return rv
        
