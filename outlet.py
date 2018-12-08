#! /usr/bin/env python

"""
Script to turn on/off outlets
"""
import datetime
import glob
import json
import logging
import logging.handlers
import os
import serial
import subprocess
import sys
import time

from influxdb import InfluxDBClient

DEFAULT_SERIAL_DEVICE = "/dev/ttyUSB0"
LOG_FILE = "~/logs/thermostat_outlet.log"
CONFIG_FILE = os.path.expanduser("~/.outlet.config")
INFLUXDB_CONFIG_FILE = os.path.expanduser("~/.influxdb.config")

MULTI_LOOPS = 2
ON_PAUSE = 20
OFF_PAUSE = 5

# only re-balance heaters after their differences is greater than N minutes
HEATER_BALANCE = 20


CYCLE_COUNT = 2
CYCLE_DELAY = datetime.timedelta(minutes=18)
LOOP_DELAY = datetime.timedelta(minutes=5)
FAILURE_THRESHOLD = datetime.timedelta(minutes=3)


config = {
    "heaters": {
        "heater_a": {
            "outlet": 'a',
            "feedback": '1',
            "multistart": False,
            "cycle": True,
            "running": False,
            "capacity": int(10*60),
            "used": 0.0
        },
        "heater_b": {
            "outlet": 'b',
            "feedback": '2',
            "multistart": True,
            "cycle": True,
            "running": False,
            "capacity": int(8.5*60),
            "used": 0.0
        },
        "heater_c": {
            "outlet": 'c',
            "feedback": '3',
            "multistart": False,
            "cycle": True,
            "running": False,
            "capacity": int(10*60),
            "used": 0.0
        }
    },
    "temp_setpoint": 60.0,
    "temp_tolerance": 3.0,
    "dht22": {
        "pin": 21
    },
    "site": {
        "location": "greenhouse",
        "controller": "thermostatOutlet1"
    }
}


def writeState(name, conf):
    global config
    config["heaters"][name] = conf
    with open(CONFIG_FILE, "w") as f:
        f.write(json.dumps(config, sort_keys=True, indent=4, separators=(',', ': ')))


class Arduino(object):
    def __init__(self, log):
        self.Log = log
        self.Stream = None
        self._newSerial()

    def _newSerial(self):
        '''
        Reset the serial device using the DTR lines
        '''
        try:
            self.Stream.close()
        except:
            pass

        serial_devices = glob.glob("/dev/ttyUSB*")
        if len(serial_devices) < 1:
            self.Log.error("NO Serial devices detected. Restarting ...")
            subprocess.call("sudo reboot", shell=True)

        self.SerialDevice = sorted(serial_devices)[-1]
        self.Stream = serial.Serial(self.SerialDevice, 57600, timeout=1)

        for x in range(5):
            self.Stream.write("H")
            if self.Stream.readline().strip() == "H":
                return
            else:
                time.sleep(1)

        # still not reset
        self.Log.error("Failed to reset Serial!!!")

    def resetSerial(self):
        try:
            self.Stream.close()
        except:
            pass

        # FIXME: match device to the actual
        subprocess.call("sudo ./usbreset /dev/bus/usb/001/002", shell=True, cwd=os.path.expanduser("~/"))
        time.sleep(2)
        self._newSerial()

    def _sendData(self, value):
        try:
                discard = self.Stream.readline()
                while len(discard) > 0:
                    discard = self.Stream.readline()

                for x in range(3):
                    self.Stream.write((str(value)))
                    response = self.Stream.readline()
                    if len(response) > 0:
                        return str(response.strip())

                # got no response
                self.Log.error("Serial not responding")
                self.resetSerial()
        except Exception as e:
            self.Log.error("Serial exception: %s"%(e), exc_info=1)
            self.resetSerial()

            return None

    def outletOn(self, outlet):
        if self._sendData(outlet.upper()) == str(outlet.upper()):
            return True
        return False

    def outletOff(self, outlet):
        if self._sendData(outlet.lower()) == str(outlet.lower()):
            return True
        return False

    def outletFeedback(self, feedback):
        if self._sendData(feedback) == '0':
            return True
        return False

    def getTemp(self):
        return self._sendData('F')

    def refuelCheck(self):
        return self._sendData('R') == 'R'


class Heater(object):
    def __init__(self, name, log, conf, influx, arduino):
        self.Log = log
        self.Name = name
        self.Arduino = arduino
        self.Config = conf
        self.UpdateTime = None
        self.Influx = influx

        self._off()

    def startup(self):
        self.Log.info("%s Should be running? %s"%(self.Name, self.Running))
        if self.Config["running"]:
            self.on()

    @property
    def Multistart(self):
        return self.Config.get("multistart", False)

    @property
    def Outlet(self):
        return self.Config["outlet"]

    @property
    def Feedback(self):
        return self.Config["feedback"]

    @property
    def PeriodicCycle(self):
        return self.Config.get("cycle", False)

    @property
    def Capacity(self):
        return self.Config["capacity"]

    @property
    def RemainingTime(self):
        return int(self.Capacity - self.Used)

    @property
    def Used(self):
        return self.Config["used"]

    @Used.setter
    def Used(self, value):
        self.Config["used"] = int(value)
        writeState(self.Name, self.Config)

    @property
    def Running(self):
        return self.Config["running"]

    @Running.setter
    def Running(self, value):
        self.Config["running"] = value
        writeState(self.Name, self.Config)

    def _on(self):
        self.Arduino.outletOn(self.Outlet)

    def on(self):
        self.Log.info("%s - %s is STARTING"%(datetime.datetime.now(), self.Name))
        self.UpdateTime = datetime.datetime.now()
        self.Running = True
        if self.Multistart:
            self.multiStartup()

        self._on()
        time.sleep(0.5)
        self.Log.info("%s - %s is ON"%(datetime.datetime.now(), self.Name))

    def _off(self):
        self.Arduino.outletOff(self.Outlet)

    def off(self):
        self.Running = False
        self._off()
        self.Log.info("%s - %s is OFF"%(datetime.datetime.now(), self.Name))
        if self.UpdateTime is not None:
            self.Used += (datetime.datetime.now() - self.UpdateTime).seconds/60.0
            self.UpdateTime = None

    def multiStartup(self, loops=MULTI_LOOPS):
        for x in range(loops):
            self._on()
            time.sleep(ON_PAUSE)
            self._off()
            time.sleep(OFF_PAUSE)

    def cycle(self):
        if self.PeriodicCycle and self.Running:
            self.Log.info("%s - %s is CYCLING"%(datetime.datetime.now(), self.Name))
            self._off()
            time.sleep(OFF_PAUSE)

            self.multiStartup(CYCLE_COUNT)
            self._on()
            self.Log.info("%s - %s is RUNNING"%(datetime.datetime.now(), self.Name))
            time.sleep(OFF_PAUSE)

    def outletCheck(self):
        active = self.Arduino.outletFeedback(self.Feedback)
        if self.Running and not active:
            self.Influx.sendMeasurement("working_outlet", self.Name, 0)
            return False

        self.Influx.sendMeasurement("working_outlet", self.Name, 1)
        return True

    def updateRuntime(self):
        running = 1 if self.Running else 0
        self.Influx.sendMeasurement("running_heater", self.Name, running)
        if self.UpdateTime is not None:
            now = datetime.datetime.now()
            self.Used += (now - self.UpdateTime).seconds/60.0
            self.UpdateTime = now

            if self.RemainingTime <= 0:
                self.Log.error("%s - %s shutting off because runtime exceeded"%(datetime.datetime.now(), self.Name))
                self.off()

        self.Influx.sendMeasurement("remaining_runtime", self.Name, self.RemainingTime)

    ## Compare functions for determining which heater to run
    def __eq__(self, other):
        if abs(self.RemainingTime - other.RemainingTime) < HEATER_BALANCE:
            if self.Running == other.Running:
                if self.Capacity == other.Capacity:
                    return True
        return False

    def __ne__(self, other):
        return not self.__eq__(other)

    def __lt__(self, other):
        # NOTE: the ordering of these checks is critical
        if abs(self.RemainingTime - other.RemainingTime) > HEATER_BALANCE:
            if self.RemainingTime > other.RemainingTime:
            # This heater has more runtime (comes first)
                return True
            else:
                # Early out, the other has more runtime and the threshold has been exceeded
                return False
            return True
        elif self.Running and not other.Running:
            # This heater is already running and the other isn't
            return True
        elif other.Running:
            # Early out. If the other heater is running than it comes first
            return False
        elif self.Capacity > other.Capacity:
            # This heater has more capacity so list it first
            return True
        return False

    def __le__(self, other):
        return self.__le__(other) or self.__eq__(other)

    def __gt__(self, other):
        if abs(other.RemainingTime - self.RemainingTime) > HEATER_BALANCE:
            if other.RemainingTime > self.RemainingTime:
               # The other heater has more runtime (it should come first)
              return True
            else:
                # Early out, the other has less runtime and the threshold has been exceeded
                return False
        elif other.Running and not self.Running:
            # The other heater is already running
            return True
        elif self.Running:
            # Early out. If this heater is running it comes first
            return False
        elif other.Capacity > self.Capacity:
            # The other heater has a higher capacity
            return True
        return False

    def __ge__(self, other):
        return self.__gt__(other) or self.__eq__(other)

    def __repr__(self):
        return "%s: (%d/%d) %s"%(self.Name, self.RemainingTime, self.Capacity, "On" if self.Running else "Off")


class TempSensor(object):
    def __init__(self, pin, influx, arduino, log):
        self.Pin = pin
        self.Influx = influx
        self.Log = log
        self.Last = 57.0
        self.LastReading = datetime.datetime.now()

        self.Arduino = arduino

    @property
    def fahrenheit(self):
        t1 = self.Arduino.getTemp()
        time.sleep(2)
        t2 = self.Arduino.getTemp()
        t = t2 if t2 else t1
        if t:
            try:
                self.Last = float(t)
            except:
                self.Log.error("%s - DHT read error: %s"%(datetime.datetime.now(), t))
                self.Influx.sendMeasurement("working_dht22", "none", 0)
                temp = self.queryFallbackTemp()
                if temp:
                    self.Last = temp
                return self.Last

            self.Influx.sendMeasurement("working_dht22", "none", 1)
            self.LastReading = datetime.datetime.now()

        else:
            self.Log.error("%s DHT timeout"%(datetime.datetime.now()))
            self.Influx.sendMeasurement("working_dht22", "none", 0)
            temp = self.queryFallbackTemp()
            if temp:
                self.Last = temp

        return self.Last

    def queryFallbackTemp(self):
        result = self.Influx.query('''SELECT "value" FROM "temperature_fahrenheit" WHERE ("location" = 'Greenhouse') AND time >= now() - 5m ORDER by time DESC LIMIT 1''')
        points = [p for p in result]
        if len(points) > 0:
            return float(points[0][0]['value'])
        return self.Last


class InfluxWrapper(object):
    def __init__(self, log, influx_config, site_config):
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

        # drop old points if there are too many
        if len(self.Points) > self.MaxPoints:
            self.Points = self.Points[self.MaxPoints:]

        for x in range(10):
            try:
                ret = self.Influx.write_points(self.Points)
            except Exception as e:
                self.Log.error("Influxdb point failure: %s"%(e))
                ret = 0
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
        if len(self.Points) >= self.MaxPoints or (now - self.LastSent).seconds >= self.Interval:
            return self.writePoints()
        return True

    def query(self, *args, **kwargs):
        return self.Influx.query(*args, **kwargs)


class HeatController(object):
    def __init__(self, log, heaters, temp_sensor, influx, arduino, config):
        self.Log = log
        self.Heaters = heaters
        self.TempSensor = temp_sensor
        self.Influx = influx
        self.Arduino = arduino

        self.OutletFails = {}

        self.Setpoint = config["temp_setpoint"]
        self.Tolerance = config["temp_tolerance"]


    def startup(self):
        # Startup the heaters after everything has been initialized
        self.Log.info("%s - Starting heaters..."%(datetime.datetime.now()))
        for heater in self.Heaters:
            heater.startup()

    def runnableHeaters(self):
        # Sort heaters in descending order by remaining runtime
        sorted_heaters = sorted(self.Heaters)

        # Split the heaters into the ones that can be run and the empty ones
        runnable_heaters = []
        for heater in sorted_heaters:
            if heater.RemainingTime > LOOP_DELAY.seconds/60:
                runnable_heaters.append(heater)

        return runnable_heaters


    def caclulateHeaters(self, temp):
        if temp >= self.Setpoint:
            # No heat necessary
            return 0

        # Scale the heaters to the tolerance
        diff = self.Setpoint - temp
        temp_range = (self.Tolerance - 0)
        heater_range = (len(self.Heaters) - 0)
        # Leaving the parts of the basic scale function in place for clarity
        heaters_needed = (((min(diff, self.Tolerance) - 0) * heater_range) / temp_range) + 0
        return round(heaters_needed)


    def adjustHeat(self, temp):
        # Log heater info
        for heater in self.Heaters:
            self.Log.info("%s - %s has %d minutes of runtime remaining. Currently running? %s"%(datetime.datetime.now(), heater.Name, heater.RemainingTime, heater.Running))

        # Determine number of heaters to run
        needed_heaters = self.caclulateHeaters(temp)
        self.Log.info("%s - Current Temp: %0.1fF, Heaters needed: %d"%(datetime.datetime.now(), temp, needed_heaters))

        # Determine which heaters to run
        ordered_heaters = self.runnableHeaters()
        if len(ordered_heaters) < needed_heaters:
            self.Log.error("Need to run %d heaters, but only %d are available. Running what we have..."%(needed_heaters, len(ordered_heaters)))
            needed_heaters = len(ordered_heaters)

        running_heaters = 0
        for heater in self.Heaters:
            if heater.Running:
                running_heaters += 1

        self.Log.info("%s - Temp is %0.1fF, Desired heaters is %d. Already running heaters is %d."%(datetime.datetime.now(), temp, needed_heaters, running_heaters))

        # Turn On/Off heaters
        if running_heaters < needed_heaters:
            # Turn on Heaters
            enabled = 0
            remaining = needed_heaters - running_heaters
            self.Log.info("%s - Turning ON %d heater(s)"%(datetime.datetime.now(), remaining))
            for heater in ordered_heaters:
                if not heater.Running:
                    heater.on()
                    enabled += 1

                if enabled >= remaining:
                    break

        elif running_heaters > needed_heaters:
            # Turn off heaters
            disabled = 0
            remaining = running_heaters - needed_heaters
            self.Log.info("%s - Turning OFF %d heater(s)"%(datetime.datetime.now(), remaining))
            for heater in sorted(self.Heaters, reverse=True):
                if heater.Running:
                    heater.off()
                    disabled += 1

                if disabled >= remaining:
                    break
        else:
            # Needed vs Running counts match. Re-balance
            self.Log.info("Running and desired heater counts match. Re-balancing..")
            running = 0
            for heater in sorted(self.Heaters):
                if running < needed_heaters:
                    if not heater.Running:
                        heater.on()
                    running += 1
                else:
                    if heater.Running:
                        heater.off()

    def refueled(self):
        self.Log.info("%s - Resetting fuel levels"%(datetime.datetime.now()))
        for heater in self.Heaters:
            heater.Used = 0

    def refuelCheck(self, length):
        start = datetime.datetime.now()
        while True:
            if self.Arduino.refuelCheck():
                self.refueled()
                return

            time.sleep(5)
            now = datetime.datetime.now()
            if (now - start).seconds >= length:
                return

    def run(self):
        prev_loop = datetime.datetime.now() - LOOP_DELAY
        prev_cycle = datetime.datetime.now()

        while True:
            now = datetime.datetime.now()
            temp = self.TempSensor.fahrenheit
            self.Log.info("%s - Current Temp: %.1f"%(datetime.datetime.now(), temp))
            self.Influx.sendMeasurement("temperature_fahrenheit", "none", float(temp))

            # adjust running heaters
            if now - prev_loop > LOOP_DELAY:
                prev_loop = now
                self.adjustHeat(temp)

            # Cycle heaters that need it
            if now - prev_cycle > CYCLE_DELAY:
                prev_cycle = now
                for heater in self.Heaters:
                    heater.cycle()

            # Check outlets for running
            for heater in self.Heaters:
                if not heater.outletCheck():
                    self.OutletFails.setdefault(heater.Name, datetime.datetime.now())
                    self.Log.error("%s - %s outlet is not functioning"%(datetime.datetime.now(), heater.Name))
                else:
                    if heater.Name in self.OutletFails:
                        del self.OutletFails[heater.Name]

            # if any outlets have failed for too long, restart the process
            now = datetime.datetime.now()
            for name, t in self.OutletFails.items():
                if now - t > FAILURE_THRESHOLD:
                    self.Log.error("%s - Restarting serial"%(now))
                    self.Arduino.resetSerial()

            # Update runtime of heaters
            for heater in self.Heaters:
                heater.updateRuntime()


            # Force everything into the state it should be
            for heater in self.Heaters:
                if heater.Running:
                    heater._on()
                else:
                    heater._off()

            self.refuelCheck(60)

def reboot(log):
    if os.path.isfile(os.path.expanduser("~/.reboot")):
        os.remove(os.path.expanduser("~/.reboot"))

    if not os.path.isfile(os.path.expanduser("~/.reboot2")):
        with open(os.path.expanduser("~/.reboot2"), "w") as f:
            f.write("%s\n"%(datetime.datetime.now()))

        log.error("############ REBOOTING ###########")
        subprocess.call("sudo reboot", shell=True)


def main():
    log = logging.getLogger('OutletThermostatLogger')
    log.setLevel(logging.INFO)
    log_file = os.path.realpath(os.path.expanduser(LOG_FILE))
    # FIXME: TimedFileHandler
    handler = logging.handlers.RotatingFileHandler(log_file, maxBytes=500000, backupCount=5)

    log.addHandler(handler)
    log.addHandler(logging.StreamHandler())
    log.info("%s - THERMOSTAT OUTLET STARTED"%(datetime.datetime.now()))

    reboot(log)

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

    log.info("%s - Initializing Influx"%(datetime.datetime.now()))
    influx = InfluxWrapper(log, influx_config, config['site'])

    log.info("%s - Initializing Arduino"%(datetime.datetime.now()))
    arduino = Arduino(log)

    log.info("%s - Setting up heater objects"%(datetime.datetime.now()))
    heaters = []
    for name, conf in config["heaters"].items():
        heaters.append(Heater(name, log, conf, influx, arduino))


    log.info("%s - Initializing Temp Sensor"%(datetime.datetime.now()))
    temp_sensor = TempSensor(config["dht22"]["pin"], influx, arduino, log)

    controller = HeatController(log, heaters, temp_sensor, influx, arduino, config)
    if not os.path.isfile(os.path.expanduser("~/.refueled3")):
        with open(os.path.expanduser("~/.refueled3"), "w") as f:
            f.write("%s\n"%(datetime.datetime.now()))
        # controller.refueled()
        for heater in heaters:
            if heater.Name == "heater_c":
                heater.Used = 150.0
            elif heater.Name == "heater_a":
                heater.Used = 200.0
            else:
                heater.Used = 110.0

    # import pdb
    # pdb.set_trace()

    controller.startup()

    ######################################################
    log.info("%s - ENTERING RUN LOOP"%(datetime.datetime.now()))
    try:
        controller.run()
    except Exception as e:
        log.error("Main loop failed: %s"%(e), exc_info=1)
        return 1
    return 1


if __name__ == "__main__":
    sys.exit(main())
