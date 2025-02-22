#!/usr/bin/env python3
"""
metar.py – Streamlined METAR LED Display
-----------------------------------------
This script reads a list of airport codes from a file named "airports",
fetches the latest METAR weather data from aviationweather.gov for these airports,
parses the flight category, and updates a NeoPixel LED strip accordingly.

Features:
  - Reads a list of airports from a local file called "airports" (one per line)
  - Takes a single static snapshot until the next update (no animation)
  - Logs errors and continues running
  - Designed for a Raspberry Pi Zero W using GPIO D18

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

# NeoPixel LED configuration; LED_COUNT will be determined by the number of airport codes
LED_PIN = board.D18        # GPIO pin used (D18)
LED_BRIGHTNESS = 0.5       # Brightness (0.0 to 1.0)
LED_ORDER = neopixel.GRB

# Color definitions (RGB)
COLOR_VFR  = (0, 255, 0)    # Green
COLOR_MVFR = (0, 0, 255)    # Blue
COLOR_IFR  = (255, 0, 0)    # Red
COLOR_LIFR = (255, 0, 255)  # Magenta
COLOR_CLEAR = (0, 0, 0)     # Off

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
        if station_elem is None or flight_elem is None:
            logging.warning("Missing data for a METAR entry, skipping.")
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
    """Update each LED based on the weather conditions for its corresponding airport."""
    for i, airport in enumerate(airports):
        condition = conditions.get(airport)
        color = get_color_for_category(condition["flightCategory"]) if condition else COLOR_CLEAR
        try:
            pixels[i] = color
            logging.info("Setting LED %d for %s to %s", i, airport, color)
        except Exception as e:
            logging.error("Error setting LED %d: %s", i, e)

def main():
    logging.info("Starting METAR LED Display")

    # Load airports from the file
    airports = load_airports(AIRPORT_FILE)
    if not airports:
        logging.error("No airports loaded. Exiting.")
        return

    # Set the number of LEDs equal to the number of airports
    LED_COUNT = len(airports)

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
