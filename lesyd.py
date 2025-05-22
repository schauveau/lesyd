#!/usr/bin/python3

import os
import io
import sys
import paho.mqtt.client as mqtt
import argparse
import time
import queue
import signal
import json
import yaml
import yamale
import logging
import logging.config as LoggingConfig

LESYD_VERSION = "1.0"

DEFAULT_STATE_REFRESH=30
DEFAULT_INPUT_REFRESH=6
DEFAULT_HOLDING_REFRESH=30

PRESETS = {
    'F2400-B': {
        'manufacturer':'Fossibot',
        'model_id': 'F2400',
        'ac_charging_levels': [ 300, 500, 700, 900, 1100 ],
        'extension1': False,
        'extension2': False,
    }, 
    'F3600Pro': {
        'manufacturer':'Fossibot',
        'model_id': 'F3600-Pro',
        'ac_charging_levels': [ 400, 800, 1200, 1600, 2200 ],
        'extension1': True,
        'extension2': True,
    }
}


# see https://github.com/23andMe/Yamale
YAMALE_SCHEMA = yamale.make_schema(content="""
global:        include('Global',required=False)
mqtt_client:   include('MqttInfo')
mqtt_sydpower: include('MqttInfo', required=False)
devices:       map( include('DeviceInfo'), key=include('DeviceMac'), min=1 )
---

DeviceMac: regex('^[0-9a-f]{12}$')

PowerLevel: int(min=1)

DeviceInfo:
   name:            regex('^[0-9a-zA-Z_]+$',required=False)
   preset:          str(required=False)
   manufacturer:    str(required=False) 
   model_id:        str(required=False)
   extension1:      bool(required=False)
   extension2:      bool(required=False)
   exclude:         list(str,required=False)
   loglevel:        include('LogLevel',required=False)
   logging_config:  str(required=False)
   state_refresh:   int(min=3,max=60,required=False)
   input_refresh:   int(min=3,max=60,required=False)
   holding_refresh: int(min=3,max=60,required=False)
   ac_charging_levels: list(include('PowerLevel'),min=1,required=False)
   guess_ac_input_power: bool(required=False)

Tls:
   ca_certs: str(required=False)
   certfile: str(required=False)
   keyfile:  str(required=False)
   keyfile_password:  str(required=False)
   version:  enum('default','tlsv1.2','tlsv1.1','tlsv1',required=False)
   ciphers:  str(required=False)
   insecure: bool(required=False)

MqttInfo:
   transport: enum('unix','tcp','websocket',required=False)
   hostname:  str(required=False)
   port:      int(min=0,max=65535,required=False)
   username:  str(required=False)
   password:  str(required=False)
   tls:       include('Tls', required=False)

LogLevel: enum('DEBUG','INFO','WARNING','ERROR','CRITICAL')

Global:
   lesyd_name:   regex('^[0-9a-zA-Z_]+$',required=False)
   logconfig:    str(required=False)
   logfile:      str(required=False)
   loglevel:     include('LogLevel',required=False)   
   ha_discovery: bool(required=False)
   ha_prefix:    str(required=False)


""")


# Some YAML configuration file. 
# They are used to validate the YAML config parser. 
# Also, the first one can be printed with --sample-config 
YAML_SAMPLES=[
    '''
global:
    loglevel: INFO   # one of DEBUG, INFO, WARNING, ERROR, CRITICAL
    
# The client MQTT broker where the 'lesyd' message are produced.
# See https://eclipse.dev/paho/files/paho.mqtt.python/html/client.html for more details.
# TODO: Add support for websockets transport?

# The mqtt_client section is mandatory but all fields are optionals
mqtt_client:
     hostname: 'mqtt.private' # default is 'localhost' 
     port:     1234           # default ports are 1883 (mqtt), 8883 (mqtts)   
     username: 'foobar'       
     password: 'mysecret'   

# Describe the connection to the MQTT broker receiving the device messages.
# If not set, the 'mqtt_client' connection is re-used instead.
#mqtt_sydpower:
#    hostname: 'mqtt.myhomenetwork'
#    port: 1883

devices:
  'abcdefabcdef':
     name: 'my_f2400'      
     exclude: [ dc_output  ]  
     loglevel: DEBUG 
  'abcdef123456':
     name: 'my_f3600'          
    
'''
,
'''
mqtt_client:
    hostname: 'localhost'
    port: 444
    username: 'foobar'   
    password: '@MYSECRET@'
devices:
    'AAABBBCCCDDD':
       name: foobar

'''
]

DEFAULT_LOGGING_INI = '''
[loggers]
keys=root

[handlers]
keys=consoleHandler,fileHandler_%(has_logfile)s

[formatters]
keys=fileFormatter,consoleFormatter

[logger_root]
level=%(loglevel)s
handlers=consoleHandler,fileHandler_%(has_logfile)s

[handler_consoleHandler]
class=StreamHandler
level=DEBUG
formatter=consoleFormatter
args=(sys.stderr,)

[handler_fileHandler_yes]
class=FileHandler
level=DEBUG
formatter=fileFormatter
args=('%(logfile)s',)

[handler_fileHandler_no]
class=NullHandler

[formatter_fileFormatter]
format=%(asctime)s [%(levelname)s] %(name)s: %(message)s
datefmt=%Y-%m-%d-%H:%M:%S

[formatter_consoleFormatter]
format=[%(levelname)s] %(name)s: %(message)s
datefmt=%Y-%m-%d-%H:%M:%S
'''

main = None    # will contain the main Lesyd object

COUNT_IREG = 80 
IREG_AC_CHARGING_RATE = 2  
IREG_AC_CHARGING_POWER = 3  
IREG_DC_CHARGING_POWER = 4
IREG_TOTAL_INPUT_POWER = 6
IREG_DC_OUTPUT_POWER_1 = 9
IREG_LED_POWER = 15
IREG_AC_OUTPUT_VOLTAGE = 18
IREG_AC_OUTPUT_FREQUENCY = 19
IREG_AC_OUTPUT_POWER = 20 
IREG_AC_INPUT_VOLTAGE = 21 
IREG_AC_INPUT_FREQUENCY = 22
IREG_LED_STATE = 25
IREG_USB_OUTPUT_POWER_1 = 30 
IREG_USB_OUTPUT_POWER_2 = 31
IREG_USB_OUTPUT_POWER_3 = 34
IREG_USB_OUTPUT_POWER_4 = 35
IREG_USB_OUTPUT_POWER_5 = 36
IREG_USB_OUTPUT_POWER_6 = 37
IREG_STATUS_BITS = 41
IREG_STATE_OF_CHARGE_1 = 53
IREG_STATE_OF_CHARGE_2 = 55
IREG_STATE_OF_CHARGE = 56
IREG_AC_CHARGING_BOOKING = 57
IREG_TIME_TO_FULL = 58
IREG_TIME_TO_EMPTY = 59

COUNT_HREG = 80 
HREG_AC_CHARGING_RATE = 13  
HREG_DC_MAX_CHARGING_CURRENT = 20
HREG_USB_OUTPUT = 24        
HREG_DC_OUTPUT  = 25
HREG_AC_OUTPUT  = 26
HREG_LED        = 27
HREG_KEY_SOUND  = 56
HREG_AC_SILENT_CHARGING = 57
HREG_AC_CHARGING_BOOKING = 63
HREG_DISCHARGE_LOWER_LIMIT = 66
HREG_AC_CHARGING_UPPER_LIMIT = 67

def homeassistant_discovery(lesyd, device, mqtt_client):

    unique_id = lesyd.name + "_" + device.mac 

    discovery = {
        'device': {
            "identifiers": [ unique_id ] ,
            "name":         device.name,
            "manufacturer": device.manufacturer, 
            "model_id":     device.model_id,   
            "hw_version": "1.0rev2", 
            # "via_device": "lesyd_bridge_0x123456789abcdef"
        },
        'origin': {
            "name":"LeSyd",
            "sw": LESYD_VERSION ,
            "url": "https://github.com/"
        },
        'availability' : [
            { 
                "topic": lesyd.will_topic,
            },
            { 
                "topic": device.topic_status,
            }
        ],
        "availability_mode": "all",
        'components': {
        },        
        'state_topic': device.topic_state,        
    }

    # "entity_category": "diagnostic",
    # "entity_category": "config",
            
    components = {
        ##### Obsolete entities must be provided with their platform to clean them from the HA database
        "dc_input_power": {
            "platform": "sensor",
        },
        ##### Sensor #####
        "state_of_charge": {
            "platform": "sensor",
            "name": "State of Charge",
            "device_class": "battery",   
            "unit_of_measurement": "%",
        },
        "ac_output_power": {
            "platform": "sensor",
            "name": "AC Output Power",
            "device_class": "power",
            "unit_of_measurement": "W"
        },
        "dc_output_power": {
            "platform": "sensor",
            "name": "DC Output Power",
            "device_class": "power",
            "unit_of_measurement": "W"
        },
        "dc_charging_power": {
            "platform": "sensor",
            "name": "DC Charging Power",
            "device_class": "power",
            "unit_of_measurement": "W"
        },
        "usb_output_power": {
            "platform": "sensor",
            "name": "USB Output Power",
            "device_class": "power",
            "unit_of_measurement": "W"
        },
        "ac_input_power": {
            "platform": "sensor",
            "name": "AC Input Power",
            "device_class": "power",
            "unit_of_measurement": "W"
        },
        "ac_charging_power": {
            "platform": "sensor",
            "name": "AC Charging Power",
            "device_class": "power",
            "unit_of_measurement": "W"
        },
        "charging_power": {
            "platform": "sensor",
            "name": "Charging Power",
            "device_class": "power",
            "unit_of_measurement": "W"
        },
        "total_input_power": {
            "platform": "sensor",
            "name": "Total Input Power",
            "device_class": "power",
            "unit_of_measurement": "W"
        },
        "ac_charging_rate": {
            "platform": "sensor",
            "name": "AC Charging Rate",
            "entity_category": "diagnostic", 
        },
        "ac_charging_level": {
            "platform": "sensor",
            "name": "AC Charging Level",
            "device_class": "power",
            "unit_of_measurement": "W",
            "entity_category": "diagnostic", 
        },
        ##### Select #####
        "led":{
            "platform": "select",
            "name": "Led",
            "options": device.LED_CHOICES,
        },
        ##### Number #####
        "ac_charging_booking": {
            "platform": "number",
            "name": "AC Charging Booking",
            "unit_of_measurement": "min",
            "min"  : 0,
            "max"  : device.MAX_AC_CHARGING_BOOKING,
            "step" : 1
        },
        "dc_max_charging_current": {
            "platform": "number",
            "name": "DC Max Charging Current",
            "unit_of_measurement": "A",
            "min"  : 1,
            "max"  : device.DC_MAX_CHARGING_CURRENT,
            "step" : 1,
            "entity_category": "config",
        },
        "discharge_lower_limit": {
            "platform": "number",
            "name": "Discharge Lower Limit",
            "unit_of_measurement": "%",
            "min"  : device.MIN_DISCHARGE_LOWER_LIMIT/10.0,
            "max"  : device.MAX_DISCHARGE_LOWER_LIMIT/10.0,
            "step" : 0.1,
            "entity_category": "config",
        },
        "ac_charging_upper_limit": {
            "platform": "number",
            "name": "AC Charging Upper Limit",
            "unit_of_measurement": "%",
            "min"  : device.MIN_AC_CHARGING_UPPER_LIMIT/10.0,
            "max"  : device.MAX_AC_CHARGING_UPPER_LIMIT/10.0,
            "step" : 0.1,
            "entity_category": "config",
        },

        ##### Switch #####
        'ac_output': {
            "platform": "switch",
            "name": "AC Output",
            "payload_on": True,
            "payload_off": False,
        },        
        'usb_output': {
            "platform": "switch",
            "name": "USB Output",
            "payload_on": True,
            "payload_off": False,
        },        
        'dc_output': {
            "platform": "switch",
            "name": "DC Output",
            "payload_on": True,
            "payload_off": False,
        },
        'ac_silent_charging': {
            "platform": "switch",
            "name": "AC Silent Charging",
            "icon": "mdi:fan",
            "payload_on": True,
            "payload_off": False,
        },
        'key_sound': {
            "platform": "switch",
            "name": "Key Sound",
            "payload_on": True,
            "payload_off": False,
            "entity_category": "config",
        },
        
    }

    for key, entry in components.items():
        
        platform = entry['platform']        

        if key in device.state:
            
            entry['unique_id'] = unique_id + "_"+key  
            entry["object_id"] = device.name + "_"+key  

            if "value_template" not in entry:
                entry["value_template"] = "{{ value_json."+key+" }}"

            if "command_topic" not in entry:
                if platform in ["switch","number","select"] :
                    entry["command_topic"] = device.topic_state + "/set/" + key
            discovery['components'][key] = entry 
            
        else:
            # Clear obsolete entries by publishing an empty component specification.
            # The platform field is still mandatory.
            discovery['components'][key] = { 'platform': entry['platform'] }             
            continue

    topic = lesyd.ha_prefix+'/device/lesyd/{}/config'.format(device.mac.lower())
    
    device.logger.info("Publish HA discovery on %s",topic)
    
    payload = json.dumps(discovery, sort_keys=True)
    mqtt_client.publish(topic, payload, retain=True)
    
class Device():

    MODBUS_CHANNEL=0x11
    
    FUNC_READ_HOLDING_REGISTERS=3
    FUNC_READ_INPUT_REGISTERS=4
    FUNC_WRITE_HOLDING_REGISTER=6

    LED_CHOICES=['Off', "On", "SOS", "Flash"]

    # Up to 24 hours of MAX_AC_CHARGING_BOOKING
    MAX_AC_CHARGING_BOOKING=24*60-1   

    MIN_DISCHARGE_LOWER_LIMIT=0
    MAX_DISCHARGE_LOWER_LIMIT=500      # 50.0% 
    
    MIN_AC_CHARGING_UPPER_LIMIT=600    # 60% 
    MAX_AC_CHARGING_UPPER_LIMIT=1000   # 100% 
        
    def __init__(self, lesyd, mac, config):

        self.lesyd = lesyd
        self.mac  = mac    # The mac address (12 lowercase hexa characters)

        device_options = config['devices'][self.mac].copy()

        self.name = device_options.get('name') or mac   # A user friendly name (unique) 
        
        self.logger = logging.getLogger("lesyd.dev."+self.name)

        print("======", self.logger, self.logger.level, self.logger.parent, self.logger.propagate, self.logger.getEffectiveLevel())
        
        if self.name in ['bridge']:
            self.logger.error("Device name '%s' is reserved.", self.name)            
            sys.exit(1)
        
        if lesyd.find_device_by_name(self.name) is not None: 
            self.logger.error("Device name '%s' is already taken.", self.name)            
            sys.exit(1)

        MAC=self.mac.upper()
        
        # The topics for the SYDPOWER MQTT server 
        self.topic_response       = MAC+'/device/response/client/data'
        self.topic_response_04    = MAC+'/device/response/client/04'        
        self.topic_response_state = MAC+'/device/response/state'     
        self.topic_request        = MAC+'/client/request/data'

        # The topics for the LOCAL MQTT server
        self.topic_root        = lesyd.name + "/" + self.name
        self.topic_state       = self.topic_root + "/state"
        #self.topic_config       = self.topic_state + '/config'

        # 
        # 
        #
        self.topic_status = self.topic_root + '/status'        
        self.status = 'offline'       # The current status 
        self.status_confirmed = False # True after receiving confirmation that the availibility message was delivered 
        self.status_time = 0 # time of the last status publication

                        
        self.payload_ReadAllInputRegisters   = self.encode_ReadInputRegisters(0,COUNT_IREG)
        self.payload_ReadAllHoldingRegisters = self.encode_ReadHoldingRegisters(0,COUNT_HREG)

        # When the input and holding responses where updated for the last time  
        self.input_response_time    = 0.0
        self.holding_response_time  = 0.0

        # When the last message was received from the device
        self.last_device_time = 0.0
        
        # The device can only process one request at a time (because of MODBUS?)    
        # so the request payloads to mqtt_sydpower are consumed from a queue.
        # A request is simply described by its payload.
        self.request_queue = queue.Queue()
        # The payload of the last request for which we are currenly awaiting a response.
        self.current_request = None 
        # and when that request was published.
        self.current_request_time = 0   
        # The timeout after which we stop waiting for the request.
        self.request_timeout = 0.3

        # All possible fields. Some may be excluded from the published state        
        self.all_fields = [
            'ac_charging_booking',
            'ac_output',
            'ac_output_power',
            'ac_silent_charging',
            'ac_input_power',
            'ac_charging_power',
            'dc_charging_power',
            'charging_power',
            'total_input_power',
            'dc_output',
            'led' ,
            'state_of_charge',
            'usb_output' ,
            'dc_max_charging_current',
            'key_sound',
            'ac_charging_rate',
            'ac_charging_upper_limit',
            'discharge_lower_limit',
            'ac_charging_level',
            'usb_output_power',
            'dc_output_power',            
        ]

        self.state_last_time = 0   # Time of the last state publication   
        self.state_last = None     # Last published state   
        self.state = { k: None for k in self.all_fields }
        
        # Merge default options into the device options

        options = {
            # First the real default values
            'loglevel' : config.get('loglevel','warning') ,
            'manufacturer': 'Unknown',
            'model_id': 'Unknown',
            'extension1': False,
            'extension2': False,
            'state_refresh': DEFAULT_STATE_REFRESH,
            'input_refresh': DEFAULT_INPUT_REFRESH,
            'holding_refresh': DEFAULT_HOLDING_REFRESH,
            'guess_ac_input_power': False,
            'exclude' : []
        }
            
        # Apply 'preset' if specified
        preset_name = device_options.get('preset')
        if preset_name:
            preset = PRESETS.get(preset_name)
            if preset:
                options.update(preset) 
            else:
                self.logger.warning("Unknown preset '{}'".format(preset_name))            

        options.update(device_options)
        
        #################################### 

        self.manufacturer    = options['manufacturer']
        self.model_id        = options['model_id']
        self.extension1      = options['extension1']
        self.extension2      = options['extension2']
        self.state_refresh   = options['state_refresh']
        self.input_refresh   = options['input_refresh']
        self.holding_refresh = options['holding_refresh']
        self.loglevel        = options['loglevel']
        self.guess_ac_input_power = options['guess_ac_input_power']

        self.ac_charging_levels = options['ac_charging_levels']
        if self.ac_charging_levels is None:
            del self.state['ac_charging_level']

        if not self.guess_ac_input_power:
            del self.state['ac_input_power']
            
        self.DC_MAX_CHARGING_CURRENT = 20  # TODO: add config option 
        
        # Probably not needed except for debug
        self.options = options 
        self.logger.info("%s ==> %s", self.mac, options)

        exclude = options.get('exclude',[]) or [] 
        for field in exclude:
            if field in self.state.keys():
                del self.state[field]     

    # Set the current status to either 'online' or 'offline'
    def set_status(self, value): 
        if value != self.status:
            # Make sure that a new status message will be successfully published
            # as soon as possible.
            self.status = value
            self.status_confirmed = False  
            self.status_time = 0

    def on_tic(self, main):

        now = time.time()

        # Assume offline if nothing was received from the device for a long time
        # TODO: the delay should be configurable.
        if now > self.last_device_time + 20:
            self.set_status('offline')

        if main.mqtt_client.is_connected() :

            # publish or re-publish the device status. 
            if not self.status_confirmed:                
                if now > self.status_time + 10:
                    self.lesyd.mqtt_client.publish(self.topic_status, self.status, retain=True)
                    self.status_time = now
            
            ### Publish the device 'state' 
            if self.state_last is None:
                # At startup, wait for the state to be fully populated
                do_publish = not (None in self.state.values())
            elif self.state != self.state_last:
                do_publish = True
            elif now > self.state_last_time + self.state_refresh :
                do_publish = True
            else:
                do_publish = False

            if do_publish:
                self.logger.debug("Publish state %s",self.state)                                
                main.mqtt_client.publish(self.topic_state,
                                         json.dumps(self.state,sort_keys=True))
                self.state_last = self.state.copy()
                self.state_last_time = now        

        if main.mqtt_sydpower.is_connected() :

            ### The device can only process one request at a time so
            ### send them one by one

            if self.current_request:
                if now > self.current_request_time + self.request_timeout:
                    # We do not want to be stuck if a message was lost
                    # so stop waiting for a response after a short delay.
                    self.current_request = None
                elif self.request_queue.qsize() > 10: 
                    # Do not wait if the queue is growing too much 
                    self.current_request = None

            if self.current_request is None:

                # Note: internal request ReadAllInputRegisters and ReadAllHoldingRegisters have 
                # higher priority than the queued requests. Send the one that is
                # the most overdue.

                input_overdue   = now - (self.input_response_time   + self.input_refresh   )
                holding_overdue = now - (self.holding_response_time + self.holding_refresh )

                payload = None
                if input_overdue >= max(0,holding_overdue):
                    # print("request ReadAllInputRegisters")
                    payload = self.payload_ReadAllInputRegisters
                    self.input_response_time = now
                elif holding_overdue >= max(0,input_overdue):
                    # print("request ReadAllHoldingRegisters")
                    payload = self.payload_ReadAllHoldingRegisters
                    self.holding_response_time = now 
                elif not self.request_queue.empty():
                    payload = self.request_queue.get(False)

                if payload:
                    main.mqtt_sydpower.publish(self.topic_request, payload)        
                    self.current_request      = payload
                    self.current_request_time = time.time()                               
                
    def update_state(self, field, value):

        # convert 'ac_charging_rate' to 'ac_charging_level' if we have the values.
        if field == 'ac_charging_rate' and self.ac_charging_levels:
            # if the array is too small, use the latest value.
            level = self.ac_charging_levels[ min(value-1,len(self.ac_charging_levels)-1) ]
            self.update_state('ac_charging_level',level)            
        
        if field in self.state:
            self.state[field] = value
                
            
    def process_sydpower_state(self, msg):

        payload = msg.payload

        self.last_device_time = time.time()

        status = 'online'
        if len(payload)==1 :
            code = payload[0]
            if code == 0x30:
                # Sent by the device before it turns off. 
                # Is that a 'will' message?
                # Unfortunately, it is not retained.
                status = 'offline'
            elif code == 0x31:
                # Sent by the device after connecting.
                # Is that a 'birth' message? 
                pass

        self.set_status(status) 
        
    def process_sydpower_response(self, msg):
        #print("=== process_response_msg by device", self.name )
        now = time.time()
        
        payload = msg.payload

        self.set_status('online')
        self.last_device_time = now 
        
        try:
            if not self.check_crc(payload):
                raise Exception("bad crc")
            
            if payload[0] != self.MODBUS_CHANNEL:
                raise Exception("bad channel")
            
            func = payload[1]
            if func == self.FUNC_READ_HOLDING_REGISTERS:

                first = self.get_word(payload,2)
                count = self.get_word(payload,4)
                if first != 0 or count != 80 :
                    raise Exception("partial data")
                data = self.get_words(payload, 6, 80)

                self.holding_response_time = now 

                # Most holding registers are redundant with an input register
                # but it is better to update the state as soon as possible.
                
                self.update_state( 'ac_silent_charging', bool(data[HREG_AC_SILENT_CHARGING]) )
                self.update_state( 'ac_output',  bool(data[HREG_AC_OUTPUT]) ) 
                self.update_state( 'dc_output',  bool(data[HREG_DC_OUTPUT]) ) 
                self.update_state( 'usb_output', bool(data[HREG_USB_OUTPUT]) ) 
                self.update_state( 'dc_max_charging_current', data[HREG_DC_MAX_CHARGING_CURRENT] ) 
                self.update_state( 'ac_charging_booking', data[HREG_AC_CHARGING_BOOKING] )
                self.update_state( 'key_sound', bool(data[HREG_AC_CHARGING_BOOKING]) )
                self.update_state( 'ac_charging_rate', data[HREG_AC_CHARGING_RATE] )

                self.update_state( 'discharge_lower_limit',   data[HREG_DISCHARGE_LOWER_LIMIT]/10.0 )
                self.update_state( 'ac_charging_upper_limit', data[HREG_AC_CHARGING_UPPER_LIMIT]/10.0 )


            elif func == self.FUNC_READ_INPUT_REGISTERS:

                first = self.get_word(payload,2)
                count = self.get_word(payload,4)
                if first != 0 or count != 80 :
                    raise Exception("partial data")
                data = self.get_words(payload, 6, 80)
                
                self.input_response_time = now 
                
                self.update_state( 'state_of_charge', data[IREG_STATE_OF_CHARGE] / 10.0 ) 
               
                status_bits = data[IREG_STATUS_BITS]
                self.update_state( 'ac_output',  (status_bits & (1<<11)) != 0 ) 
                self.update_state( 'dc_output',  (status_bits & (1<<10)) != 0 ) 
                self.update_state( 'usb_output', (status_bits & (1<<9)) != 0 ) 
                # TODO: we could also provide the status_bits in the state.  
                
                self.update_state( 'total_input_power', data[IREG_TOTAL_INPUT_POWER] ) 

                self.update_state( 'charging_power', data[IREG_AC_CHARGING_POWER]+data[IREG_DC_CHARGING_POWER] ) 
                self.update_state( 'ac_charging_power', data[IREG_AC_CHARGING_POWER] ) 
                self.update_state( 'dc_charging_power', data[IREG_DC_CHARGING_POWER] ) 

                # There is no register for the ac_input_power but we can infer it
                # from the total_input_power (so AC+DC) and dc_charging_power
                # HOW ACCURATE IS THAT?
                if self.guess_ac_input_power:
                    self.update_state( 'ac_input_power', max(0,data[IREG_TOTAL_INPUT_POWER] - data[IREG_DC_CHARGING_POWER] ) )
                
                self.update_state( 'ac_output_power', data[IREG_AC_OUTPUT_POWER] ) 
                self.update_state( 'ac_charging_booking', data[IREG_AC_CHARGING_BOOKING] ) 
                self.update_state( 'ac_charging_rate', data[IREG_AC_CHARGING_RATE] )
                self.update_state( 'usb_output_power',
                                   (
                                       data[IREG_USB_OUTPUT_POWER_1]+
                                       data[IREG_USB_OUTPUT_POWER_2]+
                                       data[IREG_USB_OUTPUT_POWER_3]+
                                       data[IREG_USB_OUTPUT_POWER_4]+
                                       data[IREG_USB_OUTPUT_POWER_5]+
                                       data[IREG_USB_OUTPUT_POWER_6]
                                   ) / 10.0
                                  ) 
                self.update_state( 'dc_output_power',
                                   (
                                       data[IREG_LED_POWER]+
                                       data[IREG_DC_OUTPUT_POWER_1]
                                   ) / 10.0
                                  )

                


                self.update_state( 'led', self.LED_CHOICES[data[IREG_LED_STATE] & 0x3]) 

            elif func == self.FUNC_WRITE_HOLDING_REGISTER:
                # This is a device response to a valid FUNC_WRITE_HOLDING_REGISTER request.
                # 
                # The write may be valid but that does not necessarily mean that the requested
                # value was written. We are supposed to send only only valid value but other
                # clients may write something else. So we only 'accept' values that we know
                # are valid. 
                #                           
                # Processing those responses is not strictly needed but that can improve the
                # responsiveness.
                #
                hreg = self.get_word(payload,2) 
                value = self.get_word(payload,4) 

                ok = False
                if hreg==HREG_AC_SILENT_CHARGING:
                    if value==0 or value==1:
                        ok = True
                        self.update_state( 'ac_silent_charging', bool(value))

                elif hreg==HREG_AC_OUTPUT:
                    if value==0 or value==1:
                        ok = True
                        self.update_state( 'ac_output', bool(value))

                elif hreg==HREG_KEY_SOUND:
                    if value==0 or value==1:
                        ok = True
                        self.update_state( 'key_sound', bool(value))

                elif hreg==HREG_DC_OUTPUT:
                    if value==0 or value==1:
                        ok = True
                        self.update_state( 'dc_output', bool(value))

                elif hreg==HREG_USB_OUTPUT:
                    if value==0 or value==1:
                        ok = True
                        self.update_state( 'usb_output', bool(value))
                        
                elif hreg==HREG_DISCHARGE_LOWER_LIMIT:
                    if self.MIN_DISCHARGE_LOWER_LIMIT <= value <= self.MAX_DISCHARGE_LOWER_LIMIT:
                        ok = True
                        self.update_state( 'discharge_lower_limit', value/10.0)                        

                elif hreg==HREG_AC_CHARGING_UPPER_LIMIT:
                    if self.MIN_AC_CHARGING_UPPER_LIMIT <= value <= self.MAX_AC_CHARGING_UPPER_LIMIT:
                        ok = True
                        self.update_state( 'ac_charging_upper_limit', value/10.0)

                elif hreg==HREG_AC_CHARGING_BOOKING:
                    if 0 <= value and value <= self.MAX_AC_CHARGING_BOOKING:
                        ok = True
                        self.update_state( 'ac_charging_booking', value )

                elif hreg==HREG_DC_MAX_CHARGING_CURRENT:
                    if not (0 <= value and value <= self.MAX_AC_CHARGING_BOOKING):
                        ok = True
                        self.update_state( 'dc_max_charging_current', value )

                if not ok:
                    # provoque a request for holding registers
                    self.holding_response_time = 0
            elif func == self.FUNC_WRITE_HOLDING_REGISTER & 0x80:
                # TODO: this is an error response on FUNC_WRITE_HOLDING_REGISTER
                pass
            else:
                raise Exception("unknown function")
                
        except Exception as e:
            self.logger.error("%s",repr(e))


    # Convert a payload to a bool
    def payload_to_bool(self, payload):
        s = payload.decode().lower()
        if s in [ 'on' , '1', 't', 'true' ]:
            return True
        if s in [ 'off' , '0', 'f', 'false' ]:
            return False        
        raise ValueError
    
    def payload_to_int(self, payload, minval, maxval):
        v = int(payload.decode())
        if v>=minval and v<=maxval:
            return v
        raise ValueError
    
    def payload_to_float(self, payload, minval, maxval):
        v = float(payload.decode())
        if v>=minval and v<=maxval:
            return v
        raise ValueError

    def process_status_msg(self, msg):
        value = msg.payload.decode()
        if self.status == value:
            self.status_confirmed = True            
        
    def process_command(self, msg):

        if msg.topic.startswith(self.topic_state) : 
            command = msg.topic[ len(self.topic_state) : ]
        
            self.logger.debug("Processing command %s", command)
            try:            
                if command=='/set/ac_output':
                    value   = int(self.payload_to_bool(msg.payload))
                    request = self.encode_WriteHoldingRegister(HREG_AC_OUTPUT, value)
                    self.request_queue.put(request)                
                elif command=='/set/dc_output':
                    value   = int(self.payload_to_bool(msg.payload))
                    request = self.encode_WriteHoldingRegister(HREG_DC_OUTPUT, value)
                    self.request_queue.put(request)  
                elif command=='/set/usb_output':
                    value   = int(self.payload_to_bool(msg.payload))
                    request = self.encode_WriteHoldingRegister(HREG_USB_OUTPUT, value)
                    self.request_queue.put(request)  
                elif command=='/set/ac_silent_charging':
                    value   = int(self.payload_to_bool(msg.payload))
                    request = self.encode_WriteHoldingRegister(HREG_AC_SILENT_CHARGING, value)
                    self.request_queue.put(request)  
                elif command=='/set/key_sound':
                    value   = int(self.payload_to_bool(msg.payload))
                    request = self.encode_WriteHoldingRegister(HREG_KEY_SOUND, value)
                    self.request_queue.put(request)  
                elif command=='/set/led':                    
                    value = None
                    arg = msg.payload.decode().lower()
                    for i in range(len(self.LED_CHOICES)):
                        if arg == self.LED_CHOICES[i].lower():
                            value = i
                            break
                    if type(value) == int:
                        request = self.encode_WriteHoldingRegister(HREG_LED, value)
                        self.request_queue.put(request)                    
                elif command=='/set/ac_charging_booking':
                    value   = int(self.payload_to_int(msg.payload,0,self.MAX_AC_CHARGING_BOOKING))
                    request = self.encode_WriteHoldingRegister(HREG_AC_CHARGING_BOOKING, value)
                    self.request_queue.put(request)  
                elif command=='/set/dc_max_charging_current':
                    value   = int(self.payload_to_int(msg.payload,1,self.DC_MAX_CHARGING_CURRENT))
                    request = self.encode_WriteHoldingRegister(HREG_DC_MAX_CHARGING_CURRENT, value)
                    self.request_queue.put(request)  
                elif command=='/set/discharge_lower_limit':
                    value   = int(self.payload_to_float(msg.payload,
                                                        self.MIN_DISCHARGE_LOWER_LIMIT/10.0,
                                                        self.MAX_DISCHARGE_LOWER_LIMIT/10.0)*10.0)
                    request = self.encode_WriteHoldingRegister(HREG_DISCHARGE_LOWER_LIMIT, value)
                    self.request_queue.put(request)  
                elif command=='/set/ac_charging_upper_limit':
                    value   = int(self.payload_to_float(msg.payload,
                                                        self.MIN_AC_CHARGING_UPPER_LIMIT/10.0,
                                                        self.MAX_AC_CHARGING_UPPER_LIMIT/10.0)*10.0)
                    request = self.encode_WriteHoldingRegister(HREG_AC_CHARGING_UPPER_LIMIT, value)
                    self.request_queue.put(request)  
                else:
                    self.logger.error("Unknown command %s",command) 
            except ValueError:
                pass
        
                
    
    # Compute a CRC for a modbus message    
    def compute_crc(self, buf, size:int):
        crc = 0xFFFF
        for i in range(size):
            crc ^= buf[i]
            for bit in range(8):
                if crc & 0x0001:
                    crc >>= 1
                    crc ^= 0xA001
                else:
                    crc >>= 1

        return [ (crc & 0xFF00) >> 8 , crc & 0xFF ]

    def append_crc(self, buf: bytearray):
        hi,lo = self.compute_crc(buf,len(buf))
        buf.append(hi)
        buf.append(lo)

    def check_crc(self, buf):
        if len(buf) < 2:
            return False
        hi,lo = self.compute_crc(buf,len(buf)-2)
        return (hi==buf[-2] and lo==buf[-1])

    # Extract a single 16 word from a bytes or bytearray buffer
    def get_word(self, buf: bytes|bytearray , index:int) -> int:
        try:
            return ((buf[index]&0xFF)<<8) + (buf[index+1]&0xFF)
        except:
            raise Exception('[modbus] malformed message')

    # Extract n 16bit words from a bytes of bytearray buffer 
    def get_words(self, buf: bytes|bytearray, index:int, n:int) -> [int] :
        return list( self.get_word(buf,index+2*x) for x in range(n) )

    # Append a 16 bit word at the end of bytearray 
    def append_word(self, buf:bytearray ,value:int) -> None :
        buf.append((value>>8)&0xFF)
        buf.append(value&0xFF)

    def check_size(self, buf: bytes|bytearray , arg_size:int, payload_size:int) -> None:
        if len(buf) != 4+arg_size+payload_size :
            raise Exception('[modbus] malformed message')

    def encode_ReadHoldingRegisters(self, start:int, count:int) -> bytearray :
        msg = bytearray()
        msg.append(self.MODBUS_CHANNEL)
        msg.append(self.FUNC_READ_HOLDING_REGISTERS)
        self.append_word(msg,start)
        self.append_word(msg,count)
        self.append_crc(msg)
        return msg

    def encode_ReadInputRegisters(self, start:int, count:int) -> bytearray :
        msg = bytearray()
        msg.append(self.MODBUS_CHANNEL)
        msg.append(self.FUNC_READ_INPUT_REGISTERS)
        self.append_word(msg,start)
        self.append_word(msg,count)
        self.append_crc(msg)
        return msg
    
    def encode_WriteHoldingRegister(self, index:int, value:int) -> bytearray :
        msg = bytearray()
        msg.append(self.MODBUS_CHANNEL)
        msg.append(self.FUNC_WRITE_HOLDING_REGISTER)
        self.append_word(msg,index)
        self.append_word(msg,value)
        self.append_crc(msg)
        return msg


class LeSyd :

    # args is typically a 'argparse.Namespace' object but any object with 
    # the following attributes will do (or use setattr(args, NAME, VALUE) to
    # manually set attributes).
    #
    #  - args.mqtt_hostname   (str)       The hostname or IP address of the mqtt server
    #  - args.mqtt_port       (int)       The MQTT port
    #  - args.mqtt_username   (str|None)  The MQTT username
    #  - args.mqtt_password   (str|None)  The MQTT password
    #
    def __init__(self) :


        default_log_fmt       = "[%(levelname)s] %(name)s: %(message)s"
        default_log_time_fmt  = "%(asctime)s "+default_log_fmt
        default_log_date_fmt = "%Y-%m-%d-%H:%M:%S"
        
        logging.basicConfig(stream=sys.stderr,
                            format=default_log_fmt,
                            datefmt=default_log_date_fmt,
                            )
        
        self.logger = logging.getLogger("lesyd")
        # self.logger.setLevel(logging.INFO)

        parser = argparse.ArgumentParser()

        parser.add_argument('-c', '--config')
        parser.add_argument('--logconfig',
                            default=None,
                            help="Set the logging configuration file"
                            )
        
        parser.add_argument('--logfile',
                            default=None,
                            help="Enable logging to the specified file"
                            )
        
        parser.add_argument('--loglevel',
                            choices=['DEBUG','INFO','WARNING','ERROR',"CRITICAL"],
                            default=None,
                            help="Set the log level. Default is INFO"
                            )

        parser.add_argument('--print-sample-config', action='store_true',
                     help="print a sample configuration file and quit")
        parser.add_argument('--list-presets', action='store_true',
                     help="print all presets and quit")
        parser.add_argument('--print-default-logconfig', action='store_true',
                     help="print the default logging configuration file")
        
        args=parser.parse_args()

        if args.print_sample_config:
            print( YAML_SAMPLES[0] )
            sys.exit(0)

        if args.list_presets:
            for preset, fields in PRESETS.items():
                print("'{}'".format(preset))
                for k, v in fields.items():
                    if type(v) is str:
                        print("   {}: '{}'".format(k,v))
                    else:
                        print("   {}: {}".format(k,v))
                print()
            sys.exit(0)

        if args.print_default_logconfig:
            print( DEFAULT_LOGGING_INI )
            sys.exit(0)
            
        # Always validate the sample configurations to insure that they are kept up to date. 
        self.validate_yaml_samples()
        
        if args.config is None:
            self.logger.critical('No config file specified')
            sys.exit(1)
                    
        yamale_data = yamale.make_data(args.config)
        config = self.validate_yaml("'"+args.config+"'", yamale_data)

        global_config = {
            'lesyd_name'   : 'lesyd',
            'loglevel'     : 'INFO',
            'ha_discovery' : False,
            'ha_prefix'    : 'homeassistant',
        }
        global_config.update( config.get('global',None) or {} )
        
        logfile = global_config.get('logfile')
        if args.logfile is not None:       
            logfile = args.logfile 
        if not logfile:
            logfile = '' 
            
        logconfig = global_config.get('logconfig')
        if args.logconfig is not None:
            logconfig = args.logconfig 
        if not logconfig:
            logconfig = io.StringIO(DEFAULT_LOGGING_INI)
        
        loglevel = global_config.get('loglevel')
        if args.loglevel:
            loglevel = args.loglevel
        if not loglevel:
            loglevel = 'INFO'
        
        LoggingConfig.fileConfig(
            logconfig,
            defaults={
                'logfile': logfile ,
                'loglevel': loglevel,
                'has_logfile': 'yes' if logfile else "no" 
            },
            disable_existing_loggers=False
        )
            
        # self.logger.setLevel(logging.INFO)
        # self.logger.debug("hello")
        # self.logger.info("hello")
        # self.logger.warning("hello")
        # self.logger.error("hello")
        # self.logger.critical("hello")
        
        ### 'mqtt_client' section of configuration file 

        self.mqtt_client_config = self.get_mqtt_config( config, "mqtt_client" )
        self.mqtt_client_config['will'] = True
        
        ### 'mqtt_sydpower' section of configuration file
        
        if 'mqtt_sydpower' in config:
            self.mqtt_sydpower_config = self.get_mqtt_config( config, "mqtt_sydpower")            
        else:
            self.mqtt_sydpower_config = None
            self.logger.info("MQTT SYDPOWER is MQTT CLIENT")

        ### 'homeassistant' section of configuration file

        self.ha_discovery = global_config['ha_discovery']
        self.ha_prefix    = global_config['ha_prefix']
        self.loglevel     = global_config['loglevel']
        self.name         = global_config['lesyd_name']
        
                                     
        ### 'devices' section of configuration file
        
        self.devices = [] 
        for mac in config['devices'].keys():
            dev = Device(self, mac, config) 
            self.devices.append(dev)                
                
        self.message_handlers = {} 
        self.tic_interval = 0.2   # minimal interval in seconds between two tics 
        self._last_tic_time = time.time()   # When self.on_tic was last called
        self.event_queue = queue.Queue()    
        self.result = None   # Setting this to any value will stop the loop()      
        self.will_topic = self.name + '/bridge/status'

    def find_device_by_name(self, name):
        for dev in self.devices:
            if dev.name == name:
                return dev
        return None
    
    
    def get_mqtt_config(self, config, name):

        mqtt_config = {
            'transport': 'tcp',
            'hostname': 'localhost',
            'username': None,
            'password': None,
            'port':     None
        }
        
        mqtt_config.update( config.get(name,{}) or {} )
        
        with_tls = 'tls' in mqtt_config
        
        if mqtt_config['port'] is None:
            key = mqtt_config['transport']
            if with_tls:
                key=key+'+tls'
            mqtt_config['port'] = {
                'unix'          : 0,
                'unix+tls'      : 0,
                'tcp'           : 1883,
                'tcp+tls'       : 8883,
                'websocket'     : 8083,
                'websocket+tls' : 8084,                
            }.get(key,1883)             

        self.logger.info("%s: transport='%s' hostname='%s' port=%s username='%s' password=%s tls=",
                         name,
                         mqtt_config['transport'],
                         mqtt_config['hostname'],
                         mqtt_config['port'],
                         mqtt_config['username'],
                         "******" if mqtt_config['password'] else None,
                         )            
        return mqtt_config
    

    def start_mqtt_client(self, client, config):


        transport = config['transport']

        if transport=='tcp':
            pass
        else:
            self.logger.error("Sorry! Transport '%s' is not yet implemented", transport)
            sys.exit(1)

        if 'tls' in config:

            tls = config.get('tls')
            # but an empty tls can be None so 
            tls = tls or {}   
            
            insecure = tls.get('insecure', False)

            version = tls.get('tls_version')
            if version   == "default":
                tls_version = ssl.PROTOCOL_TLSv1_2
            elif version   == "tlsv1.2":
                tls_version = ssl.PROTOCOL_TLSv1_2
            elif version == "tlsv1.1":
                tls_version = ssl.PROTOCOL_TLSv1_1
            elif version == "tlsv1":
                tls_version = ssl.PROTOCOL_TLSv1
            elif version is None:
                tls_version = None
            else:
                self.logger.warning("Unknown TLS version - ignoring")
                tls_version = None

            client.tls_set(ca_certs=tls.get('ca_certs',None),
                           certfile=tls.get('certfile',None),
                           keyfile=tls.get('keyfile',None),
                           keyfile_password=tls.get('keyfile_password',None),
                           tls_version=tls_version,
                           ciphers=tls.get('ciphers',None),
                           )

            if insecure:
                client.tls_insecure_set(True)
            
        if 'username' in config:
            client.username_pw_set(config['username'], config['password'])
                      
        client.on_connect      = self._on_connect_cb
        client.on_connect_fail = self._on_connect_fail_cb
        client.on_disconnect   = self._on_disconnect_cb
        client.on_message      = self._on_message_cb
        client.on_subscribe    = self._on_subscribe_cb

        if 'will' in config :
            client.will_set( self.will_topic, payload='disconnected', qos=0, retain=True)
        
        client.connect_async(config['hostname'],
                             config['port'],
                             keepalive=60)
        client.loop_start()
        
        

    def validate_yaml_samples(self):
        n=0
        for sample in YAML_SAMPLES:
            yamale_data = yamale.make_data( content=sample)
            self.validate_yaml('YAML_SAMPLES['+str(n)+']',yamale_data)
            
    def validate_yaml(self, what, yamale_data):
        
        # Note: This is not officially documented but yamale.make_data() outputs
        # a list of tuple (data,filename) where
        #   - 'data' is the data as provided by the YAML parser  
        #   - 'filename' is the filename or None 
        if type(yamale_data) is not list:
            raise Exception("INTERNAL ERROR: Bad yamale data")
        if len(yamale_data) != 1 :
            raise Exception("Found multiple YAML documents")
        if type(yamale_data[0]) is not tuple:
            raise Exception("INTERNAL ERROR: Bad yamale data")
        if len(yamale_data[0]) != 2:
            raise Exception("INTERNAL ERROR: Bad yamale data")
              
        try :
            yamale.validate( YAMALE_SCHEMA, yamale_data)
        except yamale.yamale_error.YamaleError as e:
            self.logger.error('Validation of %s failed',what)
            for result in e.results:
                for error in result.errors:
                    self.logger.error("%s",error)
                sys.exit(1)

        config = yamale_data[0][0]
        
        return config

    def _on_connect_fail_cb(self, client, userdata):    
        self.event_queue.put( ['connect_fail', client, userdata ] )
        
    def _on_connect_cb(self, client, userdata, flags, reason_code, properties):
        self.event_queue.put( ['connect', client, userdata, flags, reason_code, properties ] )

    def _on_disconnect_cb(self, client, userdata, flags, reason_code, properties):
        # print('_on_disconnect_cb')
        self.event_queue.put( ['disconnect', client, userdata, flags, reason_code, properties ] )
        #if client == self.mqtt_client:
        #   print(self.will_topic, "OFFLINE")
        #   self.mqtt_client.publish(self.will_topic,'offline')
        pass
    
            
    def _on_message_cb(self, client, userdata, msg):
        self.event_queue.put( ['message', client, userdata, msg ] )

    def _on_subscribe_cb(self, client, userdata, mid, reason_code_list, properties):
        # TODO 
        # See /usr/lib/python3/dist-packages/paho/mqtt/reasoncodes.py
        # Note: is rc.value supposed to be a public attribute
        #       or are we supposed to use rc.is_failure to detect failure and
        #       then rc.getName() to display the reason?
        # Also the 'mid' would need to be matched with the result of
        # the client.subscribe() call.
        for rc in reason_code_list:
            if rc.is_failure:                
                print("==> Warning subscribe error mid=%d value=%d name='%s' "
                      % ( mid, rc.value, rc.getName() ) )
        pass

    def process_command_stop(self, msg):
        self.result = 1 
        
    #
    # For now, this is just an alias for self.client.subscribe(...)
    # 
    # TODO: Check for success in on_subscribe_cb
    #
    def subscribe(self, client, topic, handler, qos=0):
        self.logger.info("Subscribe to '%s'",topic)
        sid = client.subscribe(topic, qos=0)
        self.message_handlers[topic] = handler 
        return sid
          
    def on_message(self, client, userdata, msg):
        #print("# "+msg.topic+" "+ msg.payload.hex())

        handler = self.message_handlers.get(msg.topic)

        if handler: 
            handler(msg)
        else:
            self.logger.warning("Unknown topic '%s'",msg.topic) 

    # Called when the connection cannot be established (i.e. nobody
    # is listening there)
    def on_connect_fail(self, client, userdata):
        self.logger.error("Connection Failed: host is not responding");
        return 
        
    # Called after the connection is established.
    def on_connect(self, client, userdata, flags, reason_code, properties):
        
        if reason_code.is_failure:            
            self.logger.error("Connection Failed: %s",reason_code);
            return 
        
        if client == self.mqtt_sydpower:            
            for dev in self.devices:
                self.subscribe( self.mqtt_sydpower, dev.topic_response_04 , dev.process_sydpower_response)
                self.subscribe( self.mqtt_sydpower, dev.topic_response,     dev.process_sydpower_response)
                self.subscribe( self.mqtt_sydpower, dev.topic_response_state, dev.process_sydpower_state)

        if client == self.mqtt_client:

            self.mqtt_client.publish(self.will_topic, 'online', retain=True)

            for dev in self.devices:
                for command in [ '/set/ac_output' ,
                                 '/set/usb_output',
                                 '/set/dc_output',
                                 '/set/key_sound',
                                 '/set/ac_silent_charging',
                                 '/set/ac_charging_booking',
                                 '/set/dc_max_charging_current',
                                 '/set/led',                      
                                 '/set/key_sound',                      
                                 '/set/discharge_lower_limit', 
                                 '/set/ac_charging_upper_limit', 
                                ] :
                    self.subscribe( self.mqtt_client, dev.topic_state+command , dev.process_command )                

                if self.ha_discovery:
                    homeassistant_discovery(self, dev, self.mqtt_client)

                self.subscribe( self.mqtt_client, dev.topic_status , dev.process_status_msg )                

                dev.set_status('offline')
                
                
                
    def on_disconnect(self, client, userdata, flags, reason_code, properties):
        # TODO
        #if client == self.mqtt_client:
        #    self.mqtt_client.publish(self.will_topic,'offline')
        pass

    def on_signal(self, num):
        self.logger.info("Signal %s",num)
        self.graceful_shutdown(1)
    
    def on_tic(self): 
        for dev in self.devices:
            dev.on_tic(self)
            
    def loop(self) :

        
        self.mqtt_client = mqtt.Client(mqtt.CallbackAPIVersion.VERSION2)        
        self.start_mqtt_client( self.mqtt_client, self.mqtt_client_config )
    
        if self.mqtt_sydpower_config is None:
            self.mqtt_sydpower = self.mqtt_client
        else:            
            self.mqtt_sydpower = mqtt.Client(mqtt.CallbackAPIVersion.VERSION2)
            self.start_mqtt_client( self.mqtt_sydpower, self.mqtt_sydpower_config )
            
        signal.signal(signal.SIGINT, self.signal_handler)
        
        timeout = max(0.1,self.tic_interval)
        while True:
            try:
                event = self.event_queue.get(True, timeout) 
                if event[0] == 'message' :
                    self.on_message(*event[1:])
                elif event[0] == 'connect_fail' :
                    self.on_connect_fail(*event[1:]) 
                elif event[0] == 'connect' :
                    self.on_connect(*event[1:]) 
                elif event[0] == 'disconnect' :
                    self.on_disconnect(*event[1:]) 
                elif event[0] == 'signal' :                
                    self.on_signal(*event[1:]) 
                else:
                    self.logger.warning('Warning: Unexpected event kind %s', kind)
            except queue.Empty as err:
                pass
            except queue.Full as err:
                self.logger.error("%s",repr(err))            

            if not self.result is None:
                break
                
            now = time.time()
            next_tic = self._last_tic_time + self.tic_interval 
            if now >= next_tic: 
                self._last_tic_time = now 
                self.on_tic()
                timeout = max(0.1, self.tic_interval)
            else:
                timeout = max(0.1 ,next_tic-now)

            if not self.result is None:
                break

        self.graceful_shutdown(0)
        return self.result

    def graceful_shutdown(self,code):
        if self.mqtt_client.is_connected() :
            mid = self.mqtt_client.publish(self.will_topic,'offline', qos=0, retain=True)
            mid.wait_for_publish()
        self.mqtt_client.disconnect()
        self.mqtt_client.loop_stop()
        if self.mqtt_client != self.mqtt_sydpower:
            self.mqtt_sydpower.loop_stop()        
        sys.exit(code)

    def signal_handler(self, signum, frame):
        self.event_queue.put( ["signal", signum] )
        
if __name__ == "__main__":

#    logging.basicConfig(stream=sys.stdout, level=logging.DEBUG)

    
    main = LeSyd()
    try:                
        main.loop() 
    except KeyboardInterrupt :
        sys.exit(1)
    
