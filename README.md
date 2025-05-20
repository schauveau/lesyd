# LeSyd - A MQTT wrapper for Sydpower/Fossibot/... portable energy stations

IMPORTANT: The connection to the Sydpower mqtt server is not yet implemented. For now, Lesyd requires a WiFi connection that redirects `mqtt.sydpower.com`  to a local server.

## How to redirect the device MQTT traffic?

The goal here is to change the DNS entry for `mqtt.sydpower.com`.

On most home network, that should be possible in the DNS settings of the WiFi router by adding an entry for `mqtt.sydpower.com`.

If your WiFi router cannot do that of if you do not have access to the WiFi router settingsthen your only alternative is probably to create a new WiFi hostspot.

The device may have to be restarted in order to connect to the fake `mqtt.sydpower.com`.

Note: The official BrightEMS application will not work properly on a WiFi network with a fake `mqtt.sydpower.com`. Bluetooth connections are still possible but only with an internet connection where `mqtt.sydpower.com` is not redirected.

The MQTT broker on the redirected `mqtt.sydpower.com` must allow anonymous non-encrypted tcp connections on port 1883.

Remark: the device still need internet access ; probably to obtain MQTT credentials from the Sydpower Cloud. Of course, those credentials will not be needed since the local MQTT broker allows for anonynous connections but unfortunately, the device does not know that.   

It is unfortunate that the device is using the MQTT standard port. People that are already  

### Example using the Mosquitto broker

Here is the required configuration for the listener: 

```
per_listener_settings true

listener 1883
protocol mqtt
allow_anonymous true
```

Now, if you want to reuse the same MQTT broker for LeSyd, HomeAssistant, or other client then you probably want
to secure it a little bit with a second listener port that does not allow anonymous access:

Your Mosquitto listener configuration could look like that:

```
listener 1884 
allow_anonymous false
password_file /etc/mosquitto/passwords

# Listener used by the Fossibot device.
listener 1883
protocol mqtt
allow_anonymous true
acl_file /etc/mosquitto/acl-sydpower-device
```

The ACL file `/etc/mosquitto/acl-sydpower-device` is used to restrict what can be done using port 1883.

If your device MAC address is '7C2C34AEF1AA' then the file should contain  

```
pattern read  7C2C34AEF1AA/client/#
pattern write 7C2C34AEF1AA/device/#
```
or the more generic version to
```
pattern readwrite 7C2C34AEF1AA/#
```

Note: 'pattern' cannot be omited here because this is a not a true anonymous connection. The device is connecting with a username and a password obtained the cloud. `pattern` rules are the only ones that are applied to ALL users.

## LeSyd Requirements

- Python 3   (tested with version 3.13.3)
- Python packages:
   - paho-mqtt  "MQTT client"
   - json       
   - yaml   
   - yamale     "a schema and validator for YAML"
   
Those Python packages are available from `pip` or as system packages on most Linux distributions.

## Using LeSyd

Lets assume that you are using an MQTT server with port 1884 enabled and a Fossibot F2400 with MAC address `7C2C67ABFD1`

A basic configuration file could look like that:

```
global:
  loglevel: info
  ha_discovery: false
  
mqtt_client:
  hostname: 'mymqtt.mydomain'   
  port: 1884
  username: 'USERNAME'  
  password: 'PASSWORD'  

devices:
  # Reminder: MAC address must be lowercase 
  '7c2c67abfd1a':
     name:   'myf2400'
     preset: 'F2400-B'
     input_refresh: 3
     holding_refresh: 30
     state_refresh: 30
```

See in (configuration.md)[configuration.md] for a more detailed description of the YAML configuration file.

Start LeSyd with

```
python3 lesyd.py -c config.yaml 
```

If case of success, then the device state should start being published on topic `/lesyd/7c2c67abfd1a/#` 

If nothing happens then that probably means that the MQTT server is not properly connected to the device.  

## Home Assistant MQTT auto-discovery

If you have Home Assistant with the MQTT integration then enable `ha_discovery` in theconfiguration file.

A new device shoudl appear in the MQTT devices with the specified name (that would be `myf2400` in the previous example).


