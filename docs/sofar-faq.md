# Sofar FAQ - WIP

## My RS485 Adapter does not work reliably

SofarSolar inverters are picky with RS485 adapters. When trying to connect my HYD xxKTL-3PH via RS485 USB I tried a couple of options. Best working adapter was the Waveshare USB to RS485 adapter. However even with that one I was not able to get a 100% reliable connection.

The by-far best RS485 connection is provided by the replacing the LSW-3 WiFi Stick Logger with the LSE-3 Ethernet Stick Logger. The later provides Modbus TCP out of the box via the port 8899.

## I am using the LSW-3 Wifi Stick Logger, but ModBus TCP does not work

Even though also on the LSW-3 Wifi Stick Logger shows that port 8899 is open, Modbus TCP connection attempts time out. Replace our stick logger with the LSE-3 LAN Stick Logger.

## I am using the LSE-3 LAN Stick Logger, but the port 8899 is not open

Running a port scanner like nmap on the LSE-3's IP address does not report port 8899 as being open.

I have seen that it might take a while until the port 8899 gets opened by the LAN Stick Logger. Try again the next day.

If that does still not help check the LAN Stick Loggers Firmware: Open the web interface at `http://\<LSE-3 IP Address\>` and on the 'Status' page expand the 'Device Information'. Check that the Firmware version is 'ME_0D_270A_1.09' or newer.