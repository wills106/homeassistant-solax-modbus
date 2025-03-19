# Sofar FAQ

## My RS485 Adaptor does not work reliably

Have you double checked that the termination resistor is installed on both ends? On the adaptor side make sure that it has a termination resistor in the adaptor (check the adaptor's manual or measure it). If this is missing add a 120 Ohm resistor between A and B to properly terminate the adaptor side. On the inverter side Sofar inverters also require a termination on the last connected inverter. Note that on the COM Port the PINs 1 and 2 (A+) and PINs 3 and 4 (B-) are internally connected with each other. So if your signal cable is connected to PINs 1 and 4 you can use the PINs 2 and 3 to connect your termination resistor.

The by-far best and easiest ModBus connection is provided by the replacing the LSW-3 WiFi Stick Logger with the LSE-3 Ethernet Stick Logger. The later provides Modbus TCP out of the box via the port 8899.

## RS485 communication stops after a few hours

There was an issue in recent firmware versions (introduced at around V110000) that cause the firmware communication to fail after a few hours. Install a newer firmware of at least version V110051.

## I am using the LSW-3 Wifi Stick Logger, but ModBus TCP does not work

LSW-3 Wifi Stick Logger also listens on the port 8899 but uses proprietary solarman protocol which is supported by [ha-solarman](https://github.com/davidrapan/ha-solarman) or you need to replace your logger with the LSE-3 LAN Stick Logger.

## I am using the LSE-3 LAN Stick Logger, but the port 8899 is not open

Running a port scanner like nmap on the LSE-3's IP address does not report port 8899 as being open.

I have seen that it might take a while until the port 8899 gets opened by the LAN Stick Logger. Try again the next day.

If that does still not help check the LAN Stick Loggers Firmware: Open the web interface at `http://\<LSE-3 IP Address\>` and on the 'Status' page expand the 'Device Information'. Check that the Firmware version is 'ME_0D_270A_1.09' or newer.

## Using the LSE-3 logger stick, write requests fail with errors.

You are using the LSE-3 logger stick to connect home assistant to your Sofar Solar inverter. When setting values you get error messages like the following:

`Modbus Error: [Input/Output] ERROR: No response received after 3 retries`

There is an issue with the LSE-3 logger stick that does not return response codes for write requests in the standard format. Thus the write attempt is considered as failed, even though it was successful.

When using the UI you can ignore these errors.

In automations and scripts these errors will cause your automation to stop. Workaround: Add `continue_on_error: true` to the YAML of your service calls that set values to the inverter. More details on `continue_on_error` can be found in the [Home Assistant documentation](https://www.home-assistant.io/docs/scripts/#continuing-on-error).

## I am using the LSE-3 logger stick, but requests timeout frequently.

There are multiple possible root causes for this:

- You have assigned a fixed IP address in the config UI of the logger stick. To solve this, let the logger stick fetch an IP address via DHCP, but use your router configuration to assign the same IP address to the logger stick.
- Wrong firmware. Make sure your logger stick is using the firmware version `ME_0D_270A_1.09`. The newer firmware version `ME_0D_270A_1.11` is causing issues. Older firmwares are also not reliable. If your logger stick's firmware is not the correct version, get in touch with the [SolarMan support](https://www.solarmanpv.com/supportservice/service-contact/) and ask them to update the firmware of your logger. SolarMan support will need the serial number of your logger to do this.
- Too many requests. Especially if you also use other software that accesses the LSE-3, too many requests can lead to time out issues. Increase the request intervals to solve this issue.


## I have changed some values, but they seem to have no impact on the inverter's operation.

The Sofar Hybrid inverters have several registers that cannot be written on their own. These need to be written in batch of several registers. The integration for Sofar therefore provides several buttons that trigger the write actions to the inverter. For example after changing "Passive: Desired Grid Power", "Passive: Maximum Battery Power", or "Passive: Minimum Battery Power" you have to press "Passive: Update Battery Charge/Discharge" to commit the changed values to the inverter.

Please see the [entity documentation](sofar-entity-description.md) for more information.
