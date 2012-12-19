from datetime import datetime, timedelta
from errno import EAGAIN
from threading import Lock

def total_seconds(delta):
    assert(isinstance(delta, timedelta))
    try:
        return delta.total_seconds()
    except AttributeError:
        return delta.microseconds / 1000000. + delta.seconds + delta.days * 3600*24

class Timeout(RuntimeError):
    pass

def tryUntilTimeout(action, timeout):
    """ Tries perform action until timeout is reached
        timeout argument should be of type timedelta
        Action should:
        - accept a single argument - time until final timeout
        - return false value if tries should be continued
        Returns last action result
    """
    assert(isinstance(timeout, timedelta))
    until = datetime.now() + timeout
    while True:  
        rv = action(timeout)
        if rv:
            return rv
        timeout = until - datetime.now()
        if timeout < timedelta(0):
            return rv

def tohex(data):
    rv=""
    for b in data:
        rv+="%02X" % b
    return rv

class PersistentSocket(object):
    """Imitates auto-reconnecting socket"""
    def __init__(self, address):
        self.address = address
        self.__socket__ = create_connection(self.address)         
    @staticmethod
    def create_connection(address):
        return PersistentSocket(address)
    def settimeout(self, timeout):
        return self.__socket__.settimeout(timeout)
    def gettimeout(self):
        return self.__socket__.gettimeout()
    def recv(self, byteCount):
        return self.__socket__.recv(byteCount)
    def sendall(self, data):
        
        return self.__socket__.sendall(data)

class Line(object):
    """Abstract RS485 line"""
    def __init__(self):
        self.__buffer__ = bytearray()
        self.lock = Lock()
    def write(self, data):
        raise NotImplemented

    def readWithTimeout(self, timeout):
        """Reads into buffer until at least one byte is read or timeout is expired."""
        assert(isinstance(timeout, timedelta))
        raise NotImplemented
    def readline(self, timeout, delimiter=b'\r'):
        assert(isinstance(timeout, timedelta))
        def tryReadLine(timeout):
            def processBuf():
                eolPosition = self.__buffer__.find(delimiter)
                if eolPosition >= 0:
                    line = self.__buffer__[0:eolPosition]
                    self.__buffer__ = self.__buffer__[eolPosition + len(delimiter):]
                    return line
                return None
            line = processBuf()
            if line:
                return line
            self.readWithTimeout(timeout)
            return processBuf()
        line = tryUntilTimeout(tryReadLine, timeout)
        if not line:
            raise Timeout("Line read timeout. Data read so far: " + str(self.__buffer__))
        return line

class SerialLine(Line):
    """Makes use of RS232 to RS485 converters"""
    from serial import Serial, SerialTimeoutException
    def __init__(self, serial):
        assert(isinstance(serial, SerialLine.Serial))
        Line.__init__(self)
        self.__serial__ = serial
    def write(self, data):
        self.__serial__.write(data)
    def readWithTimeout(self, timeout):
        assert(isinstance(timeout, timedelta))
        if (self.__serial__.inWaiting() > 0):
            self.__buffer__ += self.__serial__.read(self.__serial__.inWaiting())
            return
        self.__serial__.timeout = total_seconds(timeout)
        try:
            self.__buffer__ += self.__serial__.read(1)
        except SerialLine.SerialTimeoutException:
            pass


class SocketLine(Line):
    """Makes use of TCP/IP to RS485 converters"""
    from socket import error as socket_error, timeout as socket_timeout, create_connection
    def __init__(self, socket):
        Line.__init__(self)
        self.__socket__ = socket
    def readWithTimeout(self, timeout):
        """Reads socket into buffer until at least one byte is read or timeout is expired."""
        assert(isinstance(timeout, timedelta))
        socket = self.__socket__
        try:
            socket.settimeout(total_seconds(timeout))
            data = socket.recv(4092)
            if len(data):
                self.__buffer__ += data
                return
            #print("Waiting")
            self.__buffer__ += socket.recv(1)
        except socket_timeout as e:
            return
        except socket_error as e:
            if e.errno == EAGAIN:
                return
            raise       
                        
    def write(self, data):
        socket = self.__socket__
        oldtimeout = socket.gettimeout()
        try:
            self.__socket__.sendall(data)
        finally:
            socket.settimeout(oldtimeout)


class DebugLine(object):
    def __init__(self, line, prefix=""):
        self.__line__ = line
        self.prefix = prefix
        self.lock = Lock()
    def write(self, data):
        print(self.prefix,"sending ",tohex(data))
        self.__line__.write(data)
    def readline(self, timeout, delimiter=b'\r'):
        rv = self.__line__.readline(timeout, delimiter)
        print(self.prefix,"read line",tohex(rv))
        return rv
    def readWithTimeout(self, timeout):
        rv = self.__line__.readWithTimeout(timeout)
        print(self.prefix,"read ",tohex(rv))
        return rv
    

        
        
