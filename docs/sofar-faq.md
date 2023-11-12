# Sofar FAQ

## RS485 Connection

### My RS485 Adapter does not work reliably

SofarSolar inverters are picky with RS485 adapters. When trying to connect my HYD xxKTL-3PH via RS485 USB I tried a couple of options. Best working adaptor was the Waveshare USB to RS485 adaptor. However even with that one I was not able to get a 100% reliable connection.

The by-far best RS485 connection is provided by the replacing the LSW-3 WiFi Stick Logger with the LSE-3 Ethernet Stick Logger. The later provides Modbus TCP out of the box via the port 8899.

### I am using the LSW-3 Wifi Stick Logger, but ModBus TCP does not work

Even though also on the LSW-3 Wifi Stick Logger shows that port 8899 is open, Modbus TCP connection attempts time out. Replace our stick logger with the LSE-3 LAN Stick Logger.

### I am using the LSE-3 LAN Stick Logger, but the port 8899 is not open

Running a port scanner like nmap on the LSE-3's IP address does not report port 8899 as being open.

I have seen that it might take a while until the port 8899 gets opened by the LAN Stick Logger. Try again the next day.

If that does still not help check the LAN Stick Loggers Firmware: Open the web interface at `http://\<LSE-3 IP Address\>` and on the 'Status' page expand the 'Device Information'. Check that the Firmware version is 'ME_0D_270A_1.09' or newer.

### How do I connect a RS485 Adaptor to the Sofar Solar HYD xxKTL inverters?

1. Shutdown the inverter.
2. Disassemble the COM Port connector, by unscrewing the handle from the connector. Then press the clips on the front and gently pull out the connector. Be careful not to disconnect any of the other wires.
3. Recommended cable is an Ethernet LAN cable. Take a twisted pair, e.g. orange, and connect one to PIN 1 (A), e.g. orange solid, and the other to PIN 3 (B), e.g. orange/white. Alternatively you can use PINs 2 and 4.
4. If your RS 485 Adapter provides a GND Input, you can connect it to pin 12.
5. Carefully assemble the COM Port connector again.
6. Connect the other sides of the RS485 cable to your adaptor.
7. Turn on the inverter.
8. After a while you should be able to see an RS485 symbol on the top left. When this symbol is visible RS485 communication is established.

## Using the Home Assistant Integration

### I have activated passive mode, but changing the 'Passive Mode Battery Power' has no impact

After changing 'Passive Mode Battery Power' you have to press 'Passive Mode Battery Charge/Discharge' to commit the changes.