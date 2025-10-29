# Introducing Lightweave

Lightweave is a modular hardware and software system for mechanised costumes &amp; cosplay.

The goal of this project is to provide a modular base system of wearables which can be extended and decorated to create elaborate costumes with lights and moving parts. The system can be broken down into modules, which are independent devices which communicate with each other over ESP-NOW.

## Hardware

Each module consists of at least:

 - A battery: In this case, 2x 18650s in an enclosure. This provides enough voltage for driving servos, LEDs, and the mcu. If no servos are used on a module, it could be powered with a single 18650.
 - A voltage regulator: In the case of multiple 18650s, a 5V regulator is used to drive all the electrical components. 3A is typically enough, but 5A or more is reccomended if you have more than a few servos.
 - A microcontroller: Lightweave is designed to use the ESP32C3, a low cost microcontroller running micropython. Other ESPs should work but are not tested.

And can also include:

 - Servos: Typically MG90S servos are good for driving smaller parts, while MG990s may be needed for larger moving parts.
 - LEDs: WS2812s are reccomended for 5V operation and allow each LED to be individually addressed.
 - Sensors: Currently, ADXL345 and MPU6050 accel/gyro sensors are supported, and can be integrated with custom scripts for cool functionality.

## Software

Lightweave runs micropython and the software aspect is designed to be as easy to operate as possible. To create a module, you must flash the ESP32C3 with micropython and upload the standard code package. After that, the module can be customized by simply editing the json config file. This allows you to easily edit pin assignments and macros. 

