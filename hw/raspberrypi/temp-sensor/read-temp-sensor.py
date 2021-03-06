#!/usr/bin/env python
# Reads the temperature from a TMP36 chip via SPI data from an MCP3008.
# Outputs data to a log, and keeps a running average of the last few recent
# temp readings.
#
# This script writes to 3 external files: See LOG_FILE, PID_FILE, and
# CURRENT_TEMP_FILE. The init-script uses PID_FILE, the munin plugin uses
# CURRENT_TEMP_FILE, and nothing external uses LOG_FILE.
#
# Based on adafruit-cosm-temp.py from:
# https://gist.github.com/ladyada/3249416#file-adafruit-cosm-temp-py
# Changes:
# - Removed COSM stuff
# - Output date+time
#
# Michael Kelly (michael@michaelkelly.org)
# Sat Feb 16 21:47:25 EST 2013

import datetime
import logging
import logging.handlers
import os
import RPi.GPIO as GPIO
import sys
import time

# change these as desired - they're the pins connected from the
# SPI port on the ADC to the Cobbler
SPICLK = 18
SPIMISO = 23
SPIMOSI = 24
SPICS = 25

LOG_FILE = '/var/log/read-temp-sensor.py.log'
PID_FILE = '/var/run/read-temp-sensor.py.pid'
CURRENT_TEMP_FILE = '/var/tmp/current_temp_c'
SLEEP_TIME_S = 30


# Initialize logging object first so functions can use it.
logging_handler = logging.handlers.RotatingFileHandler(
    filename=LOG_FILE, maxBytes=100*1024*1024, backupCount=5)
logging_handler.setLevel(logging.INFO)
logging_handler.setFormatter(logging.Formatter(
    '%(asctime)s %(filename)s:%(lineno)s %(levelname)s %(message)s'))
logger = logging.getLogger('temp-logger')
logger.setLevel(logging.DEBUG)
logger.addHandler(logging_handler)

def readadc(adcnum, clockpin, mosipin, misopin, cspin):
  """Reads SPI data from MCP3008 chip, 8 possible adc's (0 thru 7)."""
  if ((adcnum > 7) or (adcnum < 0)):
    return -1
  GPIO.output(cspin, True)

  GPIO.output(clockpin, False)  # start clock low
  GPIO.output(cspin, False)     # bring CS low

  commandout = adcnum
  commandout |= 0x18  # start bit + single-ended bit
  commandout <<= 3    # we only need to send 5 bits here
  for i in range(5):
    if (commandout & 0x80):
      GPIO.output(mosipin, True)
    else:   
      GPIO.output(mosipin, False)
    commandout <<= 1
    GPIO.output(clockpin, True)
    GPIO.output(clockpin, False)

  adcout = 0
  # read in one empty bit, one null bit and 10 ADC bits
  for i in range(12):
    GPIO.output(clockpin, True)
    GPIO.output(clockpin, False)
    adcout <<= 1
    if (GPIO.input(misopin)):
      adcout |= 0x1

  GPIO.output(cspin, True)

  adcout /= 2       # first bit is 'null' so drop it
  return adcout

recent_temps = []

def output_data(data_read_time, read_adc0, millivolts, temp_C):
  # remove decimal point from millivolts
  millivolts = int(millivolts)

  # convert celsius to fahrenheit
  temp_F = (temp_C * 9.0 / 5.0) + 32

  logger.info("Read: time=%s, read_adc0=%s, mV=%s, "
               "temp_C=%.1f, temp_F=%.1f", data_read_time, read_adc0,
               millivolts, temp_C, temp_F)

  recent_temps.append(float(temp_C))
  while len(recent_temps) > 5:
    recent_temps.pop(0)
  logger.info("Last 5 temps (C): %s", recent_temps)

  recent_average = sum(recent_temps)/len(recent_temps)
  logger.info("Recent Average (C): %s", recent_average)
  try:
    with open(CURRENT_TEMP_FILE, 'w') as fh:
      fh.write("%.1f\n" % recent_average)
  except Exception as e:
    logger.error("Error writing current temperature: %s", e)


####################################################################
# daemonize
# (There are libraries to do this, but I'm trying to keep this as self-contained as possible.)

pid = os.fork()
if pid < 0:
  sys.exit(1)
if pid > 0:
  sys.exit(0)  # parent exits

# make our own process group
os.setsid()

# erase context from caller
os.chdir('/')

sys.stdout.flush()
sys.stderr.flush()

new_fd = os.open('/dev/null', os.O_RDWR)
os.dup2(new_fd, sys.stdout.fileno())
os.dup2(new_fd, sys.stderr.fileno())
os.dup2(new_fd, sys.stdin.fileno())
# done daemonizing


with open(PID_FILE, 'w') as fh:
  fh.write(str(os.getpid()))


GPIO.setmode(GPIO.BCM)

# set up the SPI interface pins
GPIO.setup(SPIMOSI, GPIO.OUT)
GPIO.setup(SPIMISO, GPIO.IN)
GPIO.setup(SPICLK, GPIO.OUT)
GPIO.setup(SPICS, GPIO.OUT)

logger.info('Starting.')

# temperature sensor connected channel 0 of mcp3008
adcnum = 0

while True:
  # read the analog pin (temperature sensor LM35)
  read_adc0 = readadc(adcnum, SPICLK, SPIMOSI, SPIMISO, SPICS)

  # convert analog reading to millivolts = ADC * (3300 / 1024)
  millivolts = read_adc0 * (3300.0 / 1024.0)

  # 10 mv per degree
  temp_C = ((millivolts - 100.0) / 10.0) - 40.0

  output_data(datetime.datetime.now(), read_adc0, millivolts, temp_C)

  time.sleep(SLEEP_TIME_S)
