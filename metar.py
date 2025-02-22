#!/usr/bin/env python3
"""
metar.py – Streamlined METAR LED Display with Legend
-----------------------------------------------------
This script reads a list of airport codes from a file named "airports",
fetches the latest METAR weather data from aviationweather.gov for these airports,
parses the flight category, and updates a NeoPixel LED strip accordingly.

It reserves the first 8 LEDs as a legend:
  LED 0: VFR      (Green)
  LED 1: MVFR     (Blue)
  LED 2: IFR      (Red)
  LED 3: LIFR     (Magenta)
  LED 4: LIGHTNING (White)
  LED 5: WINDY    (Orange)
  LED 6: HIGH WINDS (Yellow)
  LED 7: UNKNOWN  (Gray)

The remaining LEDs display weather for each airport.

Before running, install dependencies:
    sudo pip3 install rpi_ws281x adafruit-circuitpython-neopixel
"""

import urllib.request
import xml.etree.ElementTree as ET
import board
import neopixel
import time
import logging
import os

# -------- Configuration --------
AIRPORT_FILE = "airports"  # File with airport codes (one per line)

# NeoPixel LED configuration
# Total LED count = number of airports (from file) + 8 for legend
LED_PIN = board.D18        # GPIO pin used (D18)
LED_BRIGHTNESS = 0.5       # Brightness (0.0 to 1.0)
LED_ORDER = neopixel.GRB

# Color definitions (RGB)
COLOR_VFR       = (0, 255, 0)       # Green
COLOR_MVFR      = (0, 0, 255)       # Blue
COLOR_IFR       = (255, 0, 0)       # Red
COLOR_LIFR      = (255, 0, 255)     # Magenta
COLOR_LIGHTNING = (255, 255, 255)   # White
COLOR_WINDY     = (255, 165, 0)     # Orange
COLOR_HIGH_WINDS= (255, 255, 0)     # Yellow
COLOR_UNKNOWN   = (128, 128, 128)   # Gray
COLOR_CLEAR     = (0, 0, 0)         # Off

# Update interval (in seconds) between METAR data refreshes (e.g., 300 seconds = 5 minutes)
UPDATE_INTERVAL = 300

# -------------------------------
# Setup logging (to both console and a log file)
logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s [%(levelname)s] %(message)s",
    handlers=[
        logging.FileHandler("metar_led.log"),
        logging.StreamHandler()
    ]
)

def load_airports(filename):
    """Read and return a list of airport codes from the specified file."""
    if not os.path.exists(filename):
        logging.error("Airports file '%s' does not exist.", filename)
        return []
    try:
        with open(filename, "r") as f:
            airports = [line.strip() for line in f if line.strip()]
        logging.info("Loaded %d airports from '%s'", len(airports), filename)
        return airports
    except Exception as e:
        logging.error("Error reading airports file: %s", e)
        return []

def fetch_metar_data(airports):
    """Fetch METAR data from aviationweather.gov for the given list of airports."""
    if not airports:
        logging.error("No airports provided for fetching METAR data.")
        return None

    station_str = ",".join(airports)
    url = (
        "https://aviationweather.gov/cgi-bin/data/dataserver.php?"
        "requestType=retrieve&dataSource=metars&stationString=" +
        station_str +
        "&hoursBeforeNow=5&format=xml&mostRecent=true&mostRecentForEachStation=constraint"
    )
    logging.info("Fetching METAR data from:\n%s", url)
    try:
        req = urllib.request.Request(
            url,
            headers={
                'User-Agent': (
                    "Mozilla/5.0 (Windows NT 10.0; Win64; x64) "
                    "AppleWebKit/537.36 (KHTML, like Gecko) "
                    "Chrome/86.0.4240.198 Safari/537.36"
                )
            }
        )
        with urllib.request.urlopen(req, timeout=10) as response:
            return response.read()
    except Exception as e:
        logging.error("Error fetching METAR data: %s", e)
        return None

def parse_metar(content):
    """Parse the METAR XML content and return a dictionary of weather conditions keyed by airport code."""
    conditions = {}
    try:
        root = ET.fromstring(content)
    except Exception as e:
        logging.error("Error parsing METAR XML: %s", e)
        return conditions

    for metar in root.iter('METAR'):
        station_elem = metar.find('station_id')
        flight_elem = metar.find('flight_category')
        if station_elem is None:
            logging.warning("Missing station id for a METAR entry, skipping.")
            continue
        # Check if flight category text is available
        if flight_elem is None or flight_elem.text is None:
            logging.warning("Missing flight category for %s, skipping.", station_elem.text.strip())
            continue

        station_id = station_elem.text.strip()
        flight_category = flight_elem.text.strip()
        conditions[station_id] = {"flightCategory": flight_category}
        logging.info("Parsed %s: %s", station_id, flight_category)
    return conditions

def get_color_for_category(category):
    """Return the LED color based on the flight category."""
    if category == "VFR":
        return COLOR_VFR
    elif category == "MVFR":
        return COLOR_MVFR
    elif category == "IFR":
        return COLOR_IFR
    elif category == "LIFR":
        return COLOR_LIFR
    else:
        return COLOR_CLEAR

def update_leds(pixels, airports, conditions):
    """Update the LED strip.
    
    The first 8 LEDs are reserved for the legend. The remaining LEDs correspond
    to the airports read from the file.
    """
    # Set the fixed legend on LEDs 0 to 7.
    legend_colors = [
         COLOR_VFR,       # Legend LED 0: VFR
         COLOR_MVFR,      # Legend LED 1: MVFR
         COLOR_IFR,       # Legend LED 2: IFR
         COLOR_LIFR,      # Legend LED 3: LIFR
         COLOR_LIGHTNING, # Legend LED 4: LIGHTNING
         COLOR_WINDY,     # Legend LED 5: WINDY
         COLOR_HIGH_WINDS,# Legend LED 6: HIGH WINDS
         COLOR_UNKNOWN    # Legend LED 7: UNKNOWN
    ]
    for i in range(8):
        try:
            pixels[i] = legend_colors[i]
            logging.info("Setting legend LED %d to %s", i, legend_colors[i])
        except Exception as e:
            logging.error("Error setting legend LED %d: %s", i, e)

    # Update the airport LEDs starting from index 8.
    offset = 8
    for j, airport in enumerate(airports):
        condition = conditions.get(airport)
        color = get_color_for_category(condition["flightCategory"]) if condition else COLOR_CLEAR
        try:
            pixels[offset + j] = color
            logging.info("Setting LED %d for %s to %s", offset + j, airport, color)
        except Exception as e:
            logging.error("Error setting LED %d: %s", offset + j, e)

def main():
    logging.info("Starting METAR LED Display")

    # Load airports from the file
    airports = load_airports(AIRPORT_FILE)
    if not airports:
        logging.error("No airports loaded. Exiting.")
        return

    # Total LED count = 8 (legend) + number of airports
    LED_COUNT = len(airports) + 8

    # Initialize the NeoPixel LED strip
    pixels = neopixel.NeoPixel(
        LED_PIN, LED_COUNT, brightness=LED_BRIGHTNESS,
        pixel_order=LED_ORDER, auto_write=False
    )

    while True:
        content = fetch_metar_data(airports)
        if content:
            conditions = parse_metar(content)
            update_leds(pixels, airports, conditions)
            pixels.show()
        else:
            logging.error("No METAR data available; skipping update.")

        # Wait for the next update cycle
        time.sleep(UPDATE_INTERVAL)

if __name__ == '__main__':
    try:
        main()
    except KeyboardInterrupt:
        logging.info("Exiting METAR LED Display")
