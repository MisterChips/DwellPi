#!/usr/bin/python
# -*- coding: utf-8 -*-
# llap/devicesV2.py

from time import sleep
from commsV2 import LlapCommand, EXPECT_ANYTHING

UNKNOWN_TEMP = 99.9

class GenericDevice(object):
   '''
   Generic commands

           * APVER - LLAP version
           * DEVTYPE - Device type
           * DEVNAME - Device name
           * DEVNAME - Device name
           * HELLO - Hello (PING)
           * SER - Serial number
           * FVER - Firmware version
           * CHDEVID - Change device ID
           * PANID - Change PANID
           * REBOOT - Restart the device
           * BATT - Battery level
           * RETRIES - No of messages to try to get an ACK
   '''
   def __init__(self, llap_hub, device_id = '--'):
      self._announce_handlers = {}
      self._cmd = LlapCommand(llap_hub)
      self._hub = llap_hub
      self.device_id = device_id
      self._llap_version = None
      self._device_type = None
      self._device_name = None
      self._serial_number = None
      self._firmware_version = None
      self._battery_level = None
      self._hub.add_announcement_handler(device_id, self._handle_announcements)

   def add_announcement_handler(self, announce_type, handler):
      self._announce_handlers[announce_type] = handler

   def add_default_announcement_handler(self, handler):
      self.add_announcement_handler('STARTED', handler)
      self.add_announcement_handler('ERROR', handler)
      self.add_announcement_handler('BATTLOW', handler)

   @property
   def device_id(self):
      return self._cmd.device_id
   @device_id.setter
   def device_id(self, val):
      self._cmd.device_id = val

   def hello(self):
      return self.send_command('HELLO').data

   def reboot(self):
      return self.send_command('REBOOT').data

   def changedevice_id(self, new_id):
      data = self.send_command('CHDEVID' + new_id).data
      if not data:
         return # Unsuccessful
      self._hub.remove_announcement_handler(self.device_id)
      self._hub.add_announcement_handler(new_id, self._handle_announcements)
      self.reboot()
      sleep(1) # Allow the device to settle
      self.device_id = new_id

   def change_panid(self, new_id):
      self.send_command('PANID' + new_id)
      self.reboot()

   def retries(self):
      return self.send_command('RETRIES').data

   @property
   def llap_version(self):
      if not self._llap_version:
         data = self.send_command('APVER').data
         self._llap_version = data[5:] if len(data) >= 6 else '?'
      return self._llap_version

   @property
   def device_type(self):
      self._device_type = self._device_type or self.send_command('DEVTYPE', EXPECT_ANYTHING).data or '?'
      return self._device_type

   @property
   def device_name(self):
      self._device_name = self._device_name or self.send_command('DEVNAME', EXPECT_ANYTHING).data or '?'
      return self._device_name

   @property
   def serial_number(self):
      if not self._serial_number:
         data = self.send_command('SER').data
         self._serial_number = data[3:] if len(data) >= 4 else '?'
      return self._serial_number

   @property
   def firmware_version(self):
      if not self._firmware_version:
         data = self.send_command('FVER').data
         self._firmware_version = data[4:] if len(data) >= 5 else '?'
      return self._firmware_version

   @property
   def battery_level(self):
      if not self._battery_level:
         data = self.send_command('BATT').data
         self._battery_level = data[4:] if len(data) >= 5 else '?'
      return self._battery_level

   def send_command(self, cmd_text, expected_data = ''):
      self._cmd.data = cmd_text
      self._cmd.expected_data = expected_data
      return self._hub.send_command(self._cmd)

   def _parse_announcement(self, data):
      if data.startswith('ERROR'):
         return 'ERROR', data[5:]
      else:
         return data, None

   def _handle_announcements(self, device_id, data):
      announce_type, value = self._parse_announcement(data)
      if announce_type in self._announce_handlers:
         self._announce_handlers[announce_type](device_id, announce_type, value)

   def __str__(self):
      s = '''\
Device ID        : %s
LLAP Version     : %s
Device Type      : %s
Device Name      : %s
Serial Number    : %s
Firmware Version : %s
Battery Level    : %s
'''
      return s % (self.device_id, self.llap_version, self.device_type,
                  self.device_name, self.serial_number,
                  self.firmware_version, self.battery_level)

class SleepableDevice(GenericDevice):

   def add_default_announcement_handler(self, handler):
      super(SleepableDevice, self).add_default_announcement_handler(handler)
      self.add_announcement_handler('SLEEPING', handler)
      self.add_announcement_handler('AWAKE', handler)

   def sleep(self, periods, period_unit):
      ''' From docs:
      SLEEP - Requests the device go into low power mode (only applies to sleeping devices)
      aXXSLEEP999P
      Request that the device sleep for 999 periods, the response echos the command,
      the device will then send the notification aXXSLEEPING- when going to sleep, and
      the announcement aXXAWAKE---- when the device reawakens.
      Periods can be S(seconds), M(minutes), H(hours), D(days)
      '''
      data = 'SLEEP' + periods.rjust(3, '0') + period_unit
      return self.send_command(data).data

   def set_interval(self, periods, period_unit):
      ''' From docs:
      INTVL - Sets the sleep interval between "activities" (only applies to cyclic sleeping devices)
      XXINTVL999P
      Set the cyclic sleep interval to 999 periods
      Periods can be S(seconds), M(minutes), H(hours), D(days)
      '''
      data = 'INTVL' + str(periods).rjust(3, '0') + period_unit
      return self.send_command(data).data

   def start_cycling(self):
      ''' From docs:
      CYCLE - Start cyclic mode with ACKs  (only applies to cyclic sleeping devices)
      aXXCYCLE---
      Request that the device starts a cyclic sleep - the device should sleep for
      the sleep interval, awaken and send any readings, the device will expect an
      ACK from the hub, aXXACK------, if it doesn't receive one it will try by
      default another 5 times 193ms apart (the amount is variable - see command RETRIES)
      '''
      return self.send_command('CYCLE').data

   def wake(self):
      return self.send_command('WAKE').data

class ThermistorBoard(SleepableDevice):

   def __init__(self, llap_hub, device_id = '--'):
      super(ThermistorBoard, self).__init__(llap_hub, device_id)
      self._temp = UNKNOWN_TEMP

   def add_default_announcement_handler(self, handler):
      super(ThermistorBoard, self).add_default_announcement_handler(handler)
      self.add_announcement_handler('TEMP', handler)
      self.add_announcement_handler('TMPA', handler)

   def calibrate_thermistor(self, bval):
      # BVAL99999 (defaults to 3977)
      self.send_command('BVAL' + bval)

   @property
   def temp(self):
      if not self._temp:
         data = self.send_command('TEMP').data
         self._temp = float(data[4:]) if len(data) >= 5 else UNKNOWN_TEMP
      return self._temp

   def _parse_announcement(self, data):
      if data.startswith('TEMP'):
         self._temp = float(data[4:])
         return 'TEMP', self._temp
      elif data.startswith('TMPA'):
         self._temp = float(data[4:])
         return 'TMPA', self._temp
      else:
         return super(ThermistorBoard, self)._parse_announcement(data)

   def __str__(self):
      s = super(ThermistorBoard, self).__str__()
      s += 'Temp.            : %s\n' % self.temp
      return s

class DualRelayBoard(GenericDevice):
   def __init__(self, llap_hub, device_id = '--'):
      super(DualRelayBoard, self).__init__(llap_hub, device_id)
      self.relay_a = Relay(self, 'A')
      self.relay_b = Relay(self, 'B')

   def __str__(self):
      s = super(DualRelayBoard, self).__str__()
      s += str(self.relay_a)
      s += str(self.relay_b)
      return s

class Relay(object):
   '''
   Relay-specific specific commands

           * RELAYAON - Turn relay A on
           * RELAYAOFF - Turn relay A off
           * RELAYATOG - Toggle relay A
           * RELAYBON - Turn relay B on
           * RELAYBOFF - Turn relay B off
           * RELAYBTOG - Toggle relay B
   '''
   def __init__(self, board, relaydevice_id):
      self._board = board
      self._relaydevice_id = relaydevice_id
      self._cmd_prefix = 'RELAY' + relaydevice_id
      self._status = None

   @property
   def status(self):
      if self._status is None:
         data = self._board.send_command(self._cmd_prefix).data
         self._data2status(data)
      return self._status
   @status.setter
   def status(self, status):
      status_text = 'ON' if status else 'OFF'
      cmd_text = self._cmd_prefix + status_text
      data = self._board.send_command(cmd_text).data
      self._data2status(data)

   def on(self):
      self.status = True
      return self.status

   def off(self):
      self.status = False
      return self.status

   def toggle(self):
      cmd_text = self._cmd_prefix + 'TOG'
      data = self._board.send_command(cmd_text, self._cmd_prefix).data
      return self._data2status(data)

   #def _data2status(self, data):
   #   if not data:
   #      return self._status

   #   status_text = data[6:] if len(data) >= 7 else ''

   #   if status_text == 'ON':
   #      self._status = True
   #   elif status_text == 'OFF':
   #      self._status = False
   #   else:
   #      return self._status

   #   return self._status

   def _data2status(self, data):
      if not data:
         print("[LLAP] %s no data; keeping status=%r" % (self._cmd_prefix, self._status))
         return self._status

      status_text = data[6:] if len(data) >= 7 else ''
      old_status = self._status
      self._status = True if status_text == 'ON' else False
      print("[LLAP] %s data=%r status_text=%r old=%r new=%r" %
            (self._cmd_prefix, data, status_text, old_status, self._status))
      return self._status

   def __str__(self):
      if self._status is True:
         status_text = 'On'
      elif self._status is False:
         status_text = 'Off'
      else:
         status_text = 'Unknown'
      return 'Relay %s status   : %s\n' % (self._relaydevice_id, status_text)

if __name__ == '__main__':

   from llap.commsV2 import LlapHub
   from threading import Thread

   DEVICE_ID = 'RB'

   def handle_announcements(device_id, announce_type, value):
         print ("Announcement '%s' from device '%s' with value '%s'" % (announce_type, device_id, value))

   hub = LlapHub()
   rb = DualRelayBoard(hub, DEVICE_ID)
   rb.add_default_announcement_handler(handle_announcements)
   hub.start()

   print ('---')
   print (rb)
   print ('---')
   print (rb)
   print ('---')
   print ('Hello ', rb.hello())
   #print ('Reboot', rb.reboot())
   sleep(2)
   #rb.changedevice_id('RX')
   #rb.change_panid(self, 'FFFE')

   while 1:
      print ('---')
      #print ('Relay A On     ', rb.relay_a.on())
      #print ('Relay B Off    ', rb.relay_b.off())

      print ('Relay A        ', rb.relay_a.status)
      print ('Relay B        ', rb.relay_b.status)

      sleep(6)

      #print ('Relay A Toggle ', rb.relay_a.toggle())
      #print ('Relay B Toggle ', rb.relay_b.toggle())

      #print ('Relay A        ', rb.relay_a.status)
      #print ('Relay B        ', rb.relay_b.status)

      #print ('Relay A Off    ', rb.relay_a.off())
      #print ('Relay B Off    ', rb.relay_b.off())

      #print ('Relay A        ', rb.relay_a.status)
      #print ('Relay B        ', rb.relay_b.status)