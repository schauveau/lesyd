# LeSyd - A MQTT wrapper for Sydpower/Fossibot/... portable energy stations

IMPORTANT: The connection to the Sydpower mqtt server is not yet implemented. For now, Lesyd requires a WiFi connection that redirects `mqtt.sydpower.com`  to a local server.

## Known issues / TODO LIST

- Not tested with AFERIY batteries such as the P210 and P310. That may work or brick your device so, please, contact me if you own one of those.
- Probably a lot of small bugs everywhere. Do not hesitate to fill but reports
- transport 'tcp+tls' is not tested and is probably broken. Help wanted. Please use 'tcp' for now.
- option 'loglevel' is ignored. Logging is currenly using level 'info'
- options `extension1` and `extension2` are not yet implemented. The StateOfCharge is not reported for extension batteries.
- Changing the value of number entities (`ac_charging_booking`, `dc_max_charging_current`,`discharge_lower_limit`, ...) is not smooth at all in HomeAssistant: Too much traffic and lag between HA, LeSyd and the device.

## FAQ

### Why LeSyd?

Because of Sydpower, the OEM company that provides the devices.

Also, I am French and this is a reference to [Le Cid](https://en.wikipedia.org/wiki/Le_Cid), a well known French tragicomedy written by Pierre Corneille in 1636.


## How to redirect the device MQTT traffic?

The goal here is to change the DNS entry for `mqtt.sydpower.com` so that it points to a server running another MQTT Broker.

On most home networks, that can be done in the DNS settings of the WiFi router by adding an entry for `mqtt.sydpower.com`.

If your WiFi router cannot do that of if you do not configure it then your only alternative is probably to create a new WiFi hostspot.

The device may have to be restarted in order to connect to the fake `mqtt.sydpower.com`.

Note: The official BrightEMS application will not work properly on a WiFi network with a fake `mqtt.sydpower.com`. Bluetooth connections are still possible but only with an internet connection where `mqtt.sydpower.com` is not redirected.

The MQTT broker on the redirected `mqtt.sydpower.com` must allow anonymous non-encrypted tcp connections on port 1883.

Remark: the device still need internet access ; probably to obtain MQTT credentials from the Sydpower Cloud. Of course, those credentials will not be needed since the local MQTT broker allows for anonynous connections but unfortunately, the device does not know that.   

If your MQTT server is already using port 1883 without anonymous access, the you may want to move all your MQTT clients to another ports (see below for an example with Mosquitto). An alternative is to install a second MQTT broker on another machine (see `mqtt_sydpower` in the configuration file of LeSyd). 


### Example using the Mosquitto broker

Here is the required configuration for the listener: 

```
per_listener_settings true

listener 1883
protocol mqtt
allow_anonymous true
```

Now, if you want to reuse the same MQTT broker for LeSyd, HomeAssistant, or other client then you probably want to secure with a second listener port that does not allow anonymous access:

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
or to allow read and write for everyone
```
pattern readwrite 7C2C34AEF1AA/#
```

Note: 'pattern' cannot be omited here because this is a not a true anonymous connection. The device is connecting with a username and a password obtained the cloud. `pattern` rules are the only ones that are applied to ALL users.

## LeSyd Requirements

- Python 3 (tested with version 3.13.3)
- Python packages:
   - paho-mqtt  "MQTT client"
   - yaml   
   - yamale     "a schema and validator for YAML"
   
Those Python packages are available from `pip`.

They may also be provided as system packages by most Linux distributions.

On Debian: `apt install python3-paho-mqtt python3-yaml python3-yamale`

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

See [configuration.md](configuration.md) for a more detailed description of the YAML configuration file.

Start LeSyd with

```
python3 lesyd.py -c config.yaml 
```

If case of success, then the device state should start being published on topic `/lesyd/7c2c67abfd1a/#` 

If nothing happens then that probably means that the MQTT server is not properly connected to the device.  

## Home Assistant MQTT auto-discovery

If you have Home Assistant with the MQTT integration then enable `ha_discovery` in theconfiguration file.

A new device shoudl appear in the MQTT devices with the specified name (that would be `myf2400` in the previous example).


