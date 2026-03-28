#!/usr/bin/python
# -*- coding: utf-8 -*-
# llap/commsV2.py

from serial import Serial, SerialException
try:
    from Queue import Queue, Empty # Py2
except ImportError:
    from queue import Queue, Empty  # Py3
from threading import Thread
from time import sleep

BAUD = 9600
#RPI_PORT = '/dev/ttyAMA0'
RPI_PORT = '/dev/serial0'
PC_PORT = 'COM4'
TIMEOUT = 0.1 # Responses "should be sent back within 0.1 second" so allow 200ms.

LLAP_MESSAGE_LENGTH = 12
LLAP_START_CHAR = 'a'
LLAP_ACK = 'ACK'
EXPECT_ANYTHING = '*'

class SerialPort(object):
   ''' Interfaces with the serial port. '''
   def __init__(self):
      try:
         self._ser = Serial(RPI_PORT, BAUD, timeout = TIMEOUT)
      except SerialException:
         self._ser = Serial(PC_PORT, BAUD, timeout = TIMEOUT)

   def write(self, msg):
      try:
         text_type = unicode
      except NameError:
         text_type = str

      if isinstance(msg, text_type):
         msg = msg.encode('ascii')
      self._ser.write(msg)
      
   def read(self, size = 1):
      return self._ser.read(size)

   def read_all(self):
      chunks = []
      while True:
         c = self._ser.read(1)
         if c:
            chunks.append(c)
         else:
            break
      return ''.join(chunks)

   def close(self):
      try:
         if self._ser:
            self._ser.close()
      except Exception:
         pass

class LlapMessage(object):
   ''' Base class for all LLAP messages.'''
   def __init__(self, llap_hub):
      self._hub = llap_hub

class LlapOutputMessage(LlapMessage):
   ''' Base class for LLAP output messages. The message attribute is built from the
   device_id and data attributes. Knows how to send a generic message. '''
   def __init__(self, llap_hub, device_id = '', data = ''):
      super(LlapOutputMessage, self).__init__(llap_hub)
      self.device_id = device_id
      self.data = data

   @property
   def device_id(self):
      return self._device_id
   @device_id.setter
   def device_id(self, val):
      self._device_id = val
      self._message = '' # Force message to be built when it's next read.

   @property
   def data(self):
      return self._data
   @data.setter
   def data(self, val):
      self._data = val
      self._message = '' # Force message to be built when it's next read.

   @property
   def message(self):
      if not self._message:
         # Build message from device_id and data attributes
         msg = LLAP_START_CHAR + self.device_id + self.data
         self._message = msg.ljust(LLAP_MESSAGE_LENGTH, '-') # Pad to required length
      return self._message
      
   def send(self):
      self._hub.send_message(self.message)

class LlapCommand(LlapOutputMessage):
   ''' Represents LLAP commands. Knows how to send a command, wait for a response and retry
   if required. '''
   
   def __init__(self, llap_hub, device_id = '', data = '', expected_data = ''):
      super(LlapCommand, self).__init__(llap_hub, device_id, data)
      self.expected_data = expected_data
   
   @property
   def expected_data(self):
      return self._expected_data
   @expected_data.setter
   def expected_data(self, val):
      # If expected_data hasn't been sepcified, the response should echo the command
      self._expected_data = val if val else self.data

   def send(self):
      # Hub coordinator performs actual send/receive
      return self._hub._execute_command(self)

#class LlapCommandError(Exception): pass

class LlapAckMessage(LlapOutputMessage):
   def __init__(self, llap_hub, device_id = ''):
      super(LlapAckMessage, self).__init__(llap_hub, device_id, LLAP_ACK)

class LlapInputMessage(LlapMessage):
   ''' Base class for LLAP input messages. The device_id and data attributes are derived
   from the message attribute. Knows how to receive a generic message. '''
   def __init__(self, llap_hub, message = ''):
      super(LlapInputMessage, self).__init__(llap_hub)
      self.message = message

   @property
   def device_id(self):
      return self.message[1:3] if len(self.message) >= 3 else ''
      
   @property
   def data(self):
      return self.message[3:] if len(self.message) >= 4 else ''

   @property
   def message(self):
      return self._message
   @message.setter
   def message(self, val):
      self._message = val.rstrip('-') # Remove trailing '-' characters
      
   def receive(self):
      self.message = self._hub.receive_message()
      return self.device_id, self.data

class LlapResponse(LlapInputMessage):
   pass
   
class LlapAnnouncement(LlapInputMessage):
   ''' Represents an announcement message. Handles acknowledgement. '''
   
   def receive(self):
      ''' Overrides parent receive method. Receives a message and then acknowledges it. '''
      self.message = self._hub.receive_message()
      if self.device_id and self.data:
         ack = LlapAckMessage(self._hub, self.device_id)
         ack.send()
      return self.device_id, self.data

class LlapEmptyMessage(object):
   def __init__(self):
      self.device_id = ''
      self.data = ''
      self.message = ''

class LlapHub(object):
   ''' Manages communication with LLAP devices. It is assumed that there is only one
   hub operating. The worker task coordinates all communication with the local serial
   port. Queues are used to interface with the worker task. ''' 
   def __init__(self, serial_port = None, allowed_attempts = 5):
      self._ser = serial_port or SerialPort()
      self._announce_handlers = {}
      self.allowed_attempts = allowed_attempts
      self._command_queue = Queue()
      self._response_queue = Queue()
      self._announce_queue = Queue()

      # --- NEW: receive buffer so we don't drop partial frames ---
      self._rx_buf = ''  # Py2 str of bytes
      self._stopping = False
      self._threads = []

   def add_announcement_handler(self, device_id, handler):
      self._announce_handlers[device_id] = handler

   def remove_announcement_handler(self, device_id):
      del self._announce_handlers[device_id]

   def start(self):
      self._threads.append(self._start_thread(self._coordinate_serial_comms))
      self._threads.append(self._start_thread(self._handle_announcements))

   def stop(self):  # NEW
      self._stopping = True
      # unblock queues/reads best-effort
      try:
         self._announce_queue.put(None)
      except Exception:
         pass
      try:
         self._ser.close()
      except Exception:
         pass
      # join threads briefly (py2 friendly)
      for t in self._threads:
         try:
            t.join(1.0)
         except Exception:
            pass

   def send_command(self, llap_cmd, timeout = None):
      ''' Send a command and wait for the associated response. '''
      self._command_queue.put(llap_cmd)
      timeout = self._set_min_timeout(timeout)
      return self._response_queue.get(block = True, timeout = timeout)

   def send_message(self, msg):
      return self._ser.write(msg)

   def receive_message(self):
      """
      Return one full 12-byte LLAP frame when available, else ''.
      Buffers partial reads so we don't lose messages.
      """
      if self._stopping:
         return ''
      # First, try to quickly drain any waiting bytes
      try:
         more = self._ser.read_all()
         if more:
            self._rx_buf += more
      except Exception:
         return ''

      # If we still don't have enough for a full frame, read what we can
      if len(self._rx_buf) < LLAP_MESSAGE_LENGTH:
         try:
            need = LLAP_MESSAGE_LENGTH - len(self._rx_buf)
            chunk = self._ser.read(need)
            if chunk:
               self._rx_buf += chunk
         except Exception:
            pass

      if len(self._rx_buf) >= LLAP_MESSAGE_LENGTH:
         msg = self._rx_buf[:LLAP_MESSAGE_LENGTH]
         self._rx_buf = self._rx_buf[LLAP_MESSAGE_LENGTH:]
         return msg

      return ''

   def _execute_command(self, command):
      """
      Runs in the coordinator thread: send the command and wait for its response.
      """
      attempts = 0
      while 1:
         if self._stopping:
            return LlapEmptyMessage()
         # write command
         self._ser.write(command.message)

         # wait for a response frame
         response = LlapResponse(self)
         response_id, response_data = response.receive()

         if (response_id == command.device_id and
                 (command.expected_data == EXPECT_ANYTHING or response_data.startswith(command.expected_data))):
            return response

         attempts += 1
         if attempts >= self.allowed_attempts:
            return LlapEmptyMessage()

   def _coordinate_serial_comms(self):
      while not self._stopping:
         command = self._get_command_from_queue()
         if command:
            response = self._execute_command(command)
            try:
               self._response_queue.put(response)
            except Exception:
               pass

         # Only try announcement receive if not stopping
         if self._stopping:
            break

         announcement = LlapAnnouncement(self)
         announcement.receive()
         if announcement.device_id and announcement.data:
            try:
               self._announce_queue.put(announcement)
            except Exception:
               pass

   def _get_command_from_queue(self):
      try:
         return self._command_queue.get_nowait() # Non-blocking
      except Empty:
         return None
   
   def _handle_announcements(self):
      while not self._stopping:
         an = self._announce_queue.get()
         if an is None or self._stopping:
            break
         if an.device_id and an.device_id in self._announce_handlers:
            handler = self._announce_handlers[an.device_id]
            handler(an.device_id, an.data)

   def _start_thread(self, worker):
      t = Thread(target=worker)
      t.daemon = True
      t.start()
      return t

   def _set_min_timeout(self, timeout):
      if not timeout:
         # Timeout hasn't been set so leave it as is
         return timeout
      # Allow time for all communication to finish
      min_timeout = (TIMEOUT * self.allowed_attempts) + TIMEOUT
      return timeout if timeout > min_timeout else min_timeout

if __name__ == '__main__':
   
   DEVICE_ID = 'RB'

   def report_announcement(device_id, data):
      if device_id:
         print ('Announcement: %s %s' % (device_id, data))

   hub = LlapHub()
   hub.add_announcement_handler(DEVICE_ID, report_announcement)
   hub.start()
   
   def issue_command(data):
      cmd.data = data
      resp = hub.send_command(cmd, 0.001)
      print ('Response:     %s %s' % (resp.device_id, resp.data))

   cmd = LlapCommand(hub, DEVICE_ID)
   while 1:
      issue_command('RELAYAON')
      sleep(1)
      issue_command('RELAYAOFF')
      sleep(5)
      issue_command('REBOOT')
      sleep(2)