# LeSyd - MQTT messages

Messages sent to and from LeSyd are prefixed with 'lesyd' by default. That prefix can be changed using the `lesyd_prefix` option in the config file. In the rest of the document we will assume that the default prefix is used.

Similarly, we will assume that the Home Assistant MQTT discovery prefix is `homeassistant`. It can also be changed in the Lesyd configuration file (or in the HA MQTT integratoin)  

That document does not descibe the messages sent to and received from the `sydpower` MQTT broker. See https://github.com/schauveau/sydpower-mqtt if you are interested by those messages.

Each device is given a unique name that is either its mac address (12 lowercase hexadecimal characters) or a user defined name (see in `configure.md`). In the rest of the document we will refer to that name as `DEVICE`.  

## lesyd/bridge/status

Contains the availability status of the whole LeSyd service.
- The online payload is `online` 
- The offline payload is `offline`
- This is a 'will' message. It has the retain attribute and should accurately reflect the
  availability of the availability of LeSyd. 

## lesyd/DEVICE/status

Contains the availability status of a specific device.
- The online payload is `online` 
- The offline payload is `offline`
- This message has the retain attribute but unlike `lesyd/bridge/status` this is not a `will` message so it may remain `online` after LeSyd becomes disconnected.   


## lesyd/DEVICE/state

Contain the device state in JSON format. 

- `ac_charging_booking`
  - A number of minutes during which AC charging will be disabled.
  - Valid range is 0 to 1440 (24h)
  - The value will automatically decrease by 1 every minute until it reaches 0.
  - Writable at `lesyd/DEVICE/set/ac_charging_booking` when `ac_mode` is `manual` or is not enabled.  
  
- `ac_charging_level`
  - A user-defined conversion of `ac_charging_rate` to a value in Watts.
  - That field is only generated if the option `ac_charging_levels` is in the configuration file. 
  
- `ac_charging_power`
  - Provide the amount of AC power in Watts used to charge the battery.

- `ac_charging_rate`
  - Provide the AC charging rate as defined by the rotating wheel (Fossibot F2400, F3600Pro,...)
    or via a menu on the device. 
  - This is an integer value between 1 (low) and 5 (high)
  - It is currently not possible to change that value from LeSyd.   

- `ac_charging_upper_limit`
  - AC charging is disabled once the state of charge reaches that value.
  - Value is a percentage between `60.0` and `100.0` 
  - Writable at `lesyd/DEVICE/set/ac_charging_upper_limit`

- `ac_input_power`
  - An estimate of the amount of power in Watts consumed by the AC Input port.
  - That field is not provided by default.
  - See the option `guess_ac_input_power` in the configuration file.
  
- `ac_mode`
  - That field is only present when `ac_manager` is set to `true` in the configuration file.
  - It provide a simplified way to choose the level of AC Charging.  
  - Writable at `lesyd/DEVICE/set/ac_mode`
  - The possible values are
    - `manual`: The user can manually set `ac_charging_booking` and `ac_silent_charging`.
    - `standby`: Disable AC Charging by insuring that `ac_charging_charging` remains non-zero.
    - `low` or `high`: Enable or disable `ac_silent_charging` to select the lowest or the highest possible charging power.
  - Examples for a F2400 that charges at 500W with AC silent charging: 
     - If the charging wheel is set to 300W then `low` means 300W and `high` means 500W.
     - If the charging wheel is set to 500W then both `low` and `high` mean 500W.
     - If the charging wheel is set to 700W then `low` means 500W and `high` means 700W.
  - Remark: there is currently no known way to disconnect AC output from AC input. 

- `ac_output_power`
  - The amount of power in Watts consumed by all AC Output ports.

- `ac_output`
  - The state of the AC output switch. 
  - Can be `true` or `false`.
  - Writable at `lesyd/DEVICE/set/ac_output`

- `ac_silent_charging`
  - The state of the AC Silent Charging. 
  - Can be `true` or `false`.
  - When `true` the device is supposed to limit its charge to remain silent.    
  - In practice, the charge becomes limited to 500W (on the F2400).   
  - Writable at `lesyd/DEVICE/set/ac_silent_charging` when `ac_mode` is `manual` or is not enabled.

- `charging_power`
  - Provide the total amount of power in Watts used to charge the battery.
  - This is equivalent to `ac_charging_power+dc_charging_power`

- `dc_charging_power`
  - Provide the amount of DC power in Watts used to charge the battery.  

- `dc_max_charging_current`
  - Limit the maximum DC charging current in Amps.
  - An integer value between 1 and 20.
  - Writable at `lesyd/DEVICE/set/dc_max_charging_current`
  
- `dc_output_power`
  - The amount of power in Watts consumed by all DC Output ports.

- `dc_output`
  - The state of the DC output switch. 
  - Can be `true` or `false`.
  - Writable at `lesyd/DEVICE/set/dc_output`

- `discharge_lower_limit`
  - Disable all output ports if `state_of_charge` is below that value.
  - Value is a percentage between `0.0` and `50.0` 
  - Writable at `lesyd/DEVICE/set/discharge_lower_limit`

- `key_sound`
  - When `true` a sound is produced when switches are activated.
  - Writable at `lesyd/DEVICE/set/key_sound`

- `led`
  - The state of the Led panel.
  - Can be one of `Off`, `On`, `SOS`, `Flash`
  - Writable at `lesyd/DEVICE/set/led`  

- `state_of_charge`
  - Provide the state of charge of the battery
  - A percentage between `0.0` and `100.0`  

- `total_input_power`
  - The total input power (AC+DC) in Watts
  
- `usb_output_power`
   - The amount of power in Watts consumed by all USB Output ports.

- `usb_output`
  - The state of the USB output switch. 
  - Can be `true` or `false`.
  - Writable at `lesyd/DEVICE/set/usb_output`






