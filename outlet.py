#! /usr/bin/env python

"""
Script to turn on/off outlets
"""
import datetime
import json
import logging
import logging.handlers
import os
import sys
import time

import Adafruit_DHT
from gpiozero import DigitalInputDevice, LED, OutputDevice
from influxdb import InfluxDBClient


LOG_FILE = "~/thermostat_outlet.log"
CONFIG_FILE = os.path.expanduser("~/.outlet.config")
INFLUXDB_CONFIG_FILE = os.path.expanduser("~/.influxdb.config")

MULTI_LOOPS = 3
ON_PAUSE = 20
OFF_PAUSE = 5

CYCLE_COUNT = 2
CYCLE_DELAY = datetime.timedelta(minutes=18)
LOOP_DELAY = datetime.timedelta(minutes=5)

config = {
    "heaters": {
        "heater_a": {
            "outlet_pin": 18,
            "led_pin": 17,
            "invert_output": False,
            "feedback_pin": 4,
            "multistart": True,
            "cycle": True,
            "running": False,
            "capacity": 11*60,
            "used": 0
        },
        "heater_b": {
            "outlet_pin": 23,
            "led_pin": 22,
            "invert_output": False,
            "feedback_pin": 5,
            "multistart": True,
            "cycle": True,
            "running": False,
            "capacity": 8.5*60,
            "used": 0
        },
        "heater_c": {
            "outlet_pin": 12,
            "led_pin": 6,
            "invert_output": False,
            "feedback_pin": 13,
            "multistart": True,
            "cycle": False,
            "running": False,
            "capacity": 10.75*60,
            "used": 0
        }
    },
    "temps": [
        (54,3),
        (55, 2),
        (60, 1),
        (65, 0),
        (99, 0)
    ],
    "dht22": {
        "pin": 21
    },
    "site": {
        "location": "farmhouse",
        "controller": "thermostatOutlet1"
    }
}


def writeState(name, conf):
    global config
    config["heaters"][name] = conf
    with open(CONFIG_FILE, "w") as f:
        f.write(json.dumps(config))


class Heater(object):
    def __init__(self, name, log, conf, influx):
        self.Log = log
        self.Name = name
        self.Outlet = OutputDevice(conf["outlet_pin"])
        self.Led = LED(conf["led_pin"])
        self.Feedback = DigitalInputDevice(conf["feedback_pin"], pull_up=True)
        self.Config = conf
        self.StartTime = None
        self.Influx = influx

        self.Log.info("%s Should be running? %s"%(self.Name, self.Running))
        if self.Config["running"]:
            self.on()
        else:
            self.off()

    @property
    def Multistart(self):
        return self.Config.get("multistart", False)

    @property
    def Inverted(self):
        return self.Config.get("invert_output", False)


    @property
    def PeriodicCycle(self):
        return self.Config.get("cycle", False)

    @property
    def Capacity(self):
        return self.Config["capacity"]

    @property
    def RemainingTime(self):
        return self.Capacity - self.Used

    @property
    def Used(self):
        return self.Config["used"]

    @Used.setter
    def Used(self, value):
        self.Config["used"] = value
        writeState(self.Name, self.Config)

    @property
    def Running(self):
        return self.Config["running"]

    @Running.setter
    def Running(self, value):
        self.Config["running"] = value
        writeState(self.Name, self.Config)

    def on(self):
        self.Log.info("%s - %s is STARTING"%(datetime.datetime.now(), self.Name))
        self.StartTime = datetime.datetime.now()
        self.Running = True
        if self.Multistart:
            self.multiStartup()

        #invert output if needed
        self.Led.on()
        if self.Inverted:
            self.Outlet.off()
        else:
            self.Outlet.on()
        time.sleep(0.5)
        self.Log.info("%s - %s is ON"%(datetime.datetime.now(), self.Name))

    def off(self):
        self.Running = False
        self.Led.off()
        if self.Inverted:
            self.Outlet.on()
        else:
            self.Outlet.off()
        self.Log.info("%s - %s is OFF"%(datetime.datetime.now(), self.Name))
        if self.StartTime is not None:
            self.Used = (datetime.datetime.now() - self.StartTime).seconds/60
            self.StartTime = None

    def multiStartup(self, loops=MULTI_LOOPS):
        for x in range(loops):
            self.Led.on()
            if self.Inverted:
                self.Outlet.off()
            else:
                self.Outlet.on()
            time.sleep(ON_PAUSE)

            if self.Inverted:
                self.Outlet.on()
            else:
                self.Outlet.off()

            self.Led.off()
            time.sleep(OFF_PAUSE)

    def cycle(self):
        if self.PeriodicCycle:
            self.Log.info("%s - %s is CYCLING"%(datetime.datetime.now(), self.Name))
            if self.Inverted:
                self.Outlet.on()
            else:
                self.Outlet.off()

            self.Led.off()
            time.sleep(OFF_PAUSE)

            self.multiStartup(CYCLE_COUNT)
            self.Led.on()

            if self.Inverted:
                self.Outlet.off()
            else:
                self.Outlet.on()
            self.Log.info("%s - %s is RUNNING"%(datetime.datetime.now(), self.Name))

    def outletCheck(self):
        if self.Running and not self.Feedback.is_active:
            self.Influx.sendMeasurement("working_outlet", self.Name, 0)
            return False

        self.Influx.sendMeasurement("working_outlet", self.Name, 1)
        return True

    def updateRuntime(self):
        running = 1 if self.Running else 0
        self.Influx.sendMeasurement("running_heater", self.Name, running)
        if self.StartTime is not None:
            self.Used = (datetime.datetime.now() - self.StartTime).seconds/60
            self.Influx.sendMeasurement("remaining_runtime", self.Name, self.RemainingTime)
            if self.RemainingTime <= 0:
                self.Log.error("%s - %s shutting off because runtime exceeded"%(datetime.datetime.now(), self.Name))
                self.off()


class TempSensor(object):
    def __init__(self, pin):
        self.Pin = pin
        f = self.fahrenheit

    @property
    def fahrenheit(self):
        rh, t = Adafruit_DHT.read_retry(Adafruit_DHT.DHT22, self.Pin)
        return t * 1.8 + 32


class InfluxWrapper(object):
    def __init__(self, log, influx_config, site_config):
        # import pdb; pdb.set_trace()
        self.Influx = InfluxDBClient(influx_config['host'],
                                     influx_config['port'],
                                     influx_config['login'],
                                     influx_config['password'],
                                     influx_config['database'],
                                     ssl=True,
                                     timeout=60)
        self.Log = log
        self.Points = []
        self.Location = site_config['location']
        self.Controller = site_config['controller']
        self.LastSent = datetime.datetime.now()
        self.Interval = influx_config['interval']
        self.MaxPoints = influx_config['max_points']

    def getTime(self):
        now = datetime.datetime.utcnow()
        return now.strftime('%Y-%m-%dT%H:%M:%SZ')

    def writePoints(self):
        ret = None
        for x in range(10):
            ret = self.Influx.write_points(self.Points)
            if ret:
                self.Log.info("%s - Sent %d points to Influx"%(datetime.datetime.now(), len(self.Points)))
                self.LastSent = datetime.datetime.now()
                self.Points = []
                return ret

            time.sleep(0.2)

        self.Log.error("%s - Failed to send %d points to Influx: %s"%(datetime.datetime.now(), len(self.Points), ret))
        return ret

    def sendMeasurement(self, measurement, outlet, value):
        point = {
            "measurement": measurement,
            "tags": {
                "location": self.Location,
                "controller": self.Controller,
                "outlet": outlet
            },
            "time": self.getTime(),
            "fields": {
                "value": value
            }
        }

        self.Points.append(point)

        now = datetime.datetime.now()
        if len(self.Points) > self.MaxPoints or (now - self.LastSent).seconds >= self.Interval:
            return self.writePoints()
        return True


def sortHeaters(log, heaters):
    # only heaters with runtime can be used
    runnable_heaters = []
    for heater in heaters:
        log.info("%s - %s has %d minutes of runtime remaining. Currently running? %s"%(datetime.datetime.now(), heater.Name, heater.RemainingTime, heater.Running))
        if heater.RemainingTime > LOOP_DELAY.seconds/60 or heater.Running:
            runnable_heaters.append(heater)

    # Prioritize heaters that are already running
    first = []
    last = []
    for heater in runnable_heaters:
        if heater.Running:
            first.append(heater)
        else:
            last.append(heater)
    return first + last


def runHeaters(log, heaters, heat_map, temp):
    # Determine number of heaters to run
    for heater_temp, heater_count in heat_map:
        if temp <= heater_temp:
            log.info("%s - Current Temp: %0.1fF, Heaters needed: %d"%(datetime.datetime.now(), temp, heater_count))
            break

    # Determine which heaters to run
    ordered_heaters = sortHeaters(log, heaters)
    if len(ordered_heaters) < heater_count:
        log.error("Too many heaters in the heat map (%d) and not enough heaters (%d)"%(heater_count, len(ordered_heaters)))
        heater_count = len(ordered_heaters)

    running_heaters = 0
    for heater in ordered_heaters:
        if heater.Running:
            running_heaters += 1

    log.info("%s - Temp is %0.1fF, Desired heaters is %d. Running heaters is %d."%(datetime.datetime.now(), temp, heater_count, running_heaters))

    # Turn On/Off heaters
    if running_heaters < heater_count:
        # Turn on Heaters
        enabled = 0
        needed = heater_count - running_heaters
        for heater in heaters:
            if not heater.Running:
                heater.on()
                enabled += 1

            if enabled >= needed:
                break

    elif running_heaters > heater_count:
        # Turn off heaters
        disabled = 0
        not_needed = running_heaters - heater_count
        for heater in reversed(heaters):
            if heater.Running:
                heater.off()
                disabled += 1

            if disabled >= not_needed:
                break
    else:
        # Do nothing, they match
        log.info("Running and Desired heater counts match. Nothing to do")


def loop(log, influx, temp_sensor, heat_map, heaters):
    prev_loop = datetime.datetime.now() - LOOP_DELAY
    prev_cycle = datetime.datetime.now()

    while True:
        now = datetime.datetime.now()
        # adjust running heaters
        if now - prev_loop > LOOP_DELAY:
            prev_loop = now

            temp = temp_sensor.fahrenheit
            runHeaters(log, heaters, heat_map, temp)

        # Cycle heaters that need it
        if now - prev_cycle > CYCLE_DELAY:
            prev_cycle = now
            for heater in heaters:
                heater.cycle()

        # Check outlets for running
        for heater in heaters:
            if not heater.outletCheck():
                log.error("%s - %s outlet is not functioning"%(datetime.datetime.now(), heater.Name))

        # TODO: Add a reset button or something to reset runtime when re-fueled
        am11 = datetime.time(11, 0, 0)
        am1102 = datetime.time(11, 2, 0)
        if now.time() > am11 and now.time() < am1102:
            log.info("%s - Reseting fuel levels"%(now))
            for heater in heaters:
                heater.Used = 0

        # Update runtime of heaters
        for heater in heaters:
            heater.updateRuntime()
        time.sleep(60)


def main():
    log = logging.getLogger('OutletThermostatLogger')
    log.setLevel(logging.INFO)
    log_file = os.path.realpath(os.path.expanduser(LOG_FILE))
    # FIXME: TimedFileHandler
    handler = logging.handlers.RotatingFileHandler(log_file, maxBytes=500000, backupCount=5)

    log.addHandler(handler)
    log.addHandler(logging.StreamHandler())
    log.info("%s - TIMER STARTED"%(datetime.datetime.now()))

    # Setup influxdb
    with open(INFLUXDB_CONFIG_FILE) as f:
        influx_config = json.loads(f.read())


    # Handle start state
    global config

    if os.path.isfile(CONFIG_FILE):
        with open(CONFIG_FILE) as f:
            config = json.loads(f.read())
    else:
        log.error("No config file '%s' found. Defaulting to builtin config"%(CONFIG_FILE))

    influx = InfluxWrapper(log, influx_config, config['site'])

    heaters = []
    for name, conf in config["heaters"].items():
        heaters.append(Heater(name, log, conf, influx))

    temp_sensor = TempSensor(config["dht22"]["pin"])
    heat_map = config["temps"]


    ######################################################
    log.info("%s - ENTERING RUN LOOP"%(datetime.datetime.now()))
    loop(log, influx, temp_sensor, heat_map, heaters)

    return


if __name__ == "__main__":
    main()