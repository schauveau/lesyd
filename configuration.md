# LeSyd configuration file

The configuration file is written in YAML.

An sample configuration file can be obtained by running the python script with the option `--sample-config`

## `global` section

The `global` section is optional and contains miscellaneous settings with a global effect. 

All settings are optional unless specified otherwise.

- `loglevel: [DEBUG,INFO,WARNING,ERROR,CRITICAL]` 
  - Set the default logging level.
  - See also the `--loglevel` command line option.
  - The default is `INFO`

- `logconfig FILENAME`
  - Configure LeSyd logging configuration from a configparser-format file.
  - Refer to the [Python3 `logging.config` module][https://docs.python.org/3/library/logging.config.html] module for more details.
  - See also the `--loglevel` command line option.

- `logfile FILENAME`
  - Enable logging to a file.  

- `lesyd_name IDENTIFIER` 
   - Change the identifier used by LeSyd in mqtt topics.
   - the identifier must be a non-empty string containing only digits, letters and underscore (`_`).
   - The default is `lesyd`
   
- `ha_discovery BOOLEAN`
   - Enable autodiscovery  
   - The default is `false`
   
- `ha_prefix STRING`
   - change the prefix used by HomeAssistant MQTT discovery   
   - The default is `homeassistant`

## `mqtt_client` section

That section specifies how to connect to the client MQTT broker.
This is where the **LeSyd** messages are sent. 
  
- `transport [tcp,unix,websocket]`
  - Specify the type of connection to the MQTT Broker
  - Possible values are 
     - `tcp` this the default 
     - `unix` to use a UNIX socket (not yet implemented)
     - `websocket` (not yet implemented)

- `hostname STRING`
  - A hostname or IP address
  - Default is `localhost`   

- `port NUMBER `
  - A port number between 0 and 65535
  - The default port is set according to `transport` and `tls`:
     - 1883 for `tcp` without tsl
     - 8883 for `tcp` with tls
     - 0 for `unix` (i.e. no port needed)
     - 8083 for `websocket` 
     - 8084 for `websocket` with tls

- `username STRING`
  - An optional username.
  - If not specified, an anonymous connection will be attempted. 

- `password STRING` 
  - An optional password

- `tls`
  - a subsection that enable TLS encryption when present.
  - See `tls subsection` below 

## `mqtt_sydpower` section

The `mqtt_sydpower` section is similar to `mqtt_client` but it specifies how to connect to the MQTT broker that handles the device messages (i.e. the redirected `mqtt.sydpower.com` on port 1883).

That section is optional. When missing, the `mqtt_client` connection will be reused.  

**Warning:** An empty `mqtt_sydpower` section is not considered to be missing. It will use the default settings (i.e. `localhost`, port 1083, ...).
m
### `tls` subsection 

TLS encryption is enabled when that subsection is found in a `mqtt_client` or `mqtt_sydpower` section.

The entries in that subsection correspond to the argument of the `tls_set` and `tls_insecure` members of `paho.mqtt.client.Client`. See also https://eclipse.dev/paho/files/paho.mqtt.python/html/client.html#paho.mqtt.client.Client 

- `ca_certs STRING`
   - An optional path to the Certificate Authority certificate files that are to be treated
   as trusted by this client. If not set, the default certification authority of the system is used.

- `certfile STRING`   
   - An optional PEM encoded client certificate filename. Used with keyfile for client TLS based authentication

- `keyfile STRING`
   - An optional PEM encoded client private keys filename. Used with certfile for client TLS based authentication

- `keyfile_password STRING`
   - An optional password used when `keyfile` and `certfile` are encrypted. 
   
- `version [ default, tlsv1.2, tlsv1.1, tlsv1 ]`
   - An optional string that describes a TLS version.
   - Allowed values are `default`, `tlsv1.2`, `tlsv1.1` and `tlsv1`.   

- `ciphers STRING`
   - An optinal string describing the encryption ciphers that are allowed for this connection.
   - If not set the default ciphers are used. 

- `insecure BOOLEAN`
   - When set to True, disable the verification of the server hostname in the server certificate.
   - The default is False

## `devices` section

That section is a dictionnary of device settings. Each key shall be a device mac address in **lowercase**, so exactly 12 characters from `0123456789abcdef`.

Example:
```yaml
devices:
   48fe0aa424c6:
      name: 'myf2400'
      manufacturer: 'Fossibot'
   4562ffaa4444:
      name: 'myf3600'
      manufacturer: 'Fossibot'
```

*How to find a device mac address?*
   - in the topic of the MQTT messages sent by device. 
   - or in the device selection screen of the official BrightEMS application.
   - or in your WiFi router

At least one device must be specified.

The dictionary value is a structure containing the following fields:

- `name STRING`:
   - The device name used in mqtt topics and in HA entities.
   - All LeSyd devices shall have a different name.
   - The name shall only contain digits, letters and underscores.    
   - The default is to use the mac address.
    
- `preset STRING`
   - A preset name to automatically fill some the device fields.
   - Run `lesyd.py` with the option `--list-presets` to display the presets.
          
- `manufacturer STRING`
   - The name of the device manufacturer
   - Used only in HomeAssistant discovery
   - Default is `Unknown`
    
- `model_id STRING`
   - The device model identifier
   - Used only in HomeAssistant discovery
   - Default is `Unknown`
   
- `exclude  LIST_OF_STRING`
   - Optional.
   - Contain a list of field names to be excluded from the published states.
   - They are also excluded from HomeAssistant discovery.
   - Unknown field names are ignored
   - Reminder: List members are denoted by a leading hyphen (-) with one member
     per line or by enclosing them in square braquets [] and separated by a comma. 
   ```yaml
      # Single line
      exclude: [ charging_power, state_of_charge, led ]
      # Multiple line 
      exclude:
        - charging_power
        - state_of_charge
        - led
   ```
- `ac_charging_levels LIST_OF_INTEGERS`
  - Optional
  - A list of power values for the state field `ac_charging_rate` 
  - If specified then a field `ac_power_level` is added to the state.
  - For example, the Fossibot F2400 supports 5 AC charging levels so 
  ```
  ac_charging_levels: [300, 500, 700, 900, 1100] 
  ```
  
- `guess_ac_input_power BOOL`
  - For devices that do not provide a measure of their AC Input Power, guess that value
    in a field `ac_input_power` using the formula `max(0,total_input_power-dc_charging_power)`.
  - The default is False

- `state_refresh INTEGER`   
  - Specify after how many seconds, the state shall be re-published if it did not change. 
  - The allowed range is `[3,60]`
  - The default is 30

- `input_refresh INTEGER`   
  - Specify the delay in seconds between two queries of the device input registers.
  - The allowed range is `[3,60]`
  - The default is 6
  - Using a low value will increase the update frequency of most state fields.
  
- `holding_refresh INTEGER` 
  - Specify the delay in seconds between two queries of the device holding registers.
  - The allowed range is `[3,60]`
  - The default is 30
  - In practice, that setting should only affect the update frequency of:
     - `ac_silent_charging` if it was modified from another source (e.g. the official BrightEMS application)     
   
- `extension1 BOOLEAN`
  - a boolean value to indicate if the 1st extension battery is present.
  - if false then all fields related to that extension battery will be removed from the published state.  
  - default is false

- `extension2 BOOLEAN`
  - Same as `extension1` but for the 2nd extension battery

- `ac_manager BOOLEAN`
  - if `true` then enable `ac_mode` (see MQTT.md for more details)
  