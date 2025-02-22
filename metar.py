#!/usr/bin/env python3
"""
metar.py – METAR LED Display with High Wind and Lightning Detection
--------------------------------------------------------------------
This script reads a list of airport codes (ICAO format) from a file named "airports",
fetches the latest METAR data from AviationWeather, and updates a NeoPixel LED strip.
It extracts the flight category, wind speed/gust values, and lightning conditions from each METAR.
If the wind speed or gust exceeds a specified threshold, the LED color is overridden.
If lightning is detected, the LED color is overridden with the lightning color.
If no METAR data is available for an airport, its LED is set to off.
The first 9 LEDs are reserved as a fixed legend.
 
Dependencies:
    sudo pip3 install --break-system-packages rpi_ws281x adafruit-circuitpython-neopixel
"""

import urllib.request
import xml.etree.ElementTree as ET
import board
import neopixel
import time
import logging
import os

# -------- Configuration --------
AIRPORT_FILE = "airports"  # File with ICAO airport codes (one per line)

# NeoPixel configuration:
# Total LED count = number of airports + 9 (for legend)
LED_PIN = board.D18          # GPIO pin (D18)
LED_BRIGHTNESS = 0.5         # Brightness (0.0 to 1.0)
LED_ORDER = neopixel.GRB

# Color definitions (RGB)
COLOR_VFR       = (0, 255, 0)       # Green
COLOR_MVFR      = (0, 0, 255)       # Blue
COLOR_IFR       = (255, 0, 0)       # Red
COLOR_LIFR      = (255, 0, 255)     # Magenta
COLOR_CLEAR     = (0, 0, 0)         # Off

# High wind override color
COLOR_HIGH_WIND = (255, 255, 0)     # Yellow

# Lightning override color
COLOR_LIGHTNING = (255, 255, 255)   # White

# Legend colors (positions 0-8)
LEGEND_COLORS = [
    COLOR_LIGHTNING,  # Legend LED 0: LIGHTNING
    COLOR_HIGH_WIND,  # Legend LED 1: HIGH WINDS
    COLOR_MVFR,       # Legend LED 2: MVFR
    COLOR_LIFR,       # Legend LED 3: LIFR
    COLOR_IFR,        # Legend LED 4: IFR
    COLOR_VFR,        # Legend LED 5: VFR
    COLOR_CLEAR,      # Legend LED 6: Clear (no data)
    COLOR_CLEAR,      # Legend LED 7: (reserved)
    COLOR_CLEAR       # Legend LED 8: (reserved)
]

# Timing interval in seconds between fetching new METAR data (e.g., 5 minutes)
UPDATE_INTERVAL = 300

# Wind threshold (knots) for high wind override
HIGH_WIND_THRESHOLD = 15

# -------------------------------
# Setup logging to console and file
logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s [%(levelname)s] %(message)s",
    handlers=[
        logging.FileHandler("metar_led.log"),
        logging.StreamHandler()
    ]
)

def load_airports(filename):
    """Load and return a list of ICAO airport codes from the specified file."""
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
    """Fetch METAR data from AviationWeather for the given list of airports."""
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
    """Parse METAR XML content and return a dictionary keyed by airport code.
       Extract flight category, wind speed (kt), wind gust (kt), and lightning status."""
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
        if flight_elem is None or flight_elem.text is None:
            logging.warning("Missing flight category for %s, skipping.", station_elem.text.strip())
            continue

        station_id = station_elem.text.strip()
        flight_category = flight_elem.text.strip()

        # Parse wind speed and gust if available.
        wind_speed = 0
        wind_gust = 0
        wind_speed_elem = metar.find('wind_speed_kt')
        if wind_speed_elem is not None and wind_speed_elem.text is not None:
            try:
                wind_speed = int(wind_speed_elem.text.strip())
            except ValueError:
                wind_speed = 0
        wind_gust_elem = metar.find('wind_gust_kt')
        if wind_gust_elem is not None and wind_gust_elem.text is not None:
            try:
                wind_gust = int(wind_gust_elem.text.strip())
            except ValueError:
                wind_gust = 0

        # Determine lightning condition.
        lightning = False
        raw_text_elem = metar.find('raw_text')
        if raw_text_elem is not None and raw_text_elem.text is not None:
            raw_text = raw_text_elem.text
            # Check if the raw text contains lightning indicators, but not TSNO (which indicates no lightning)
            if ("LTG" in raw_text or "TS" in raw_text) and "TSNO" not in raw_text:
                lightning = True

        conditions[station_id] = {
            "flightCategory": flight_category,
            "windSpeed": wind_speed,
            "windGust": wind_gust,
            "lightning": lightning
        }
        logging.info("Parsed %s: %s, wind %d kt, gust %d kt, lightning %s",
                     station_id, flight_category, wind_speed, wind_gust, lightning)
    return conditions

def get_color_for_condition(condition):
    """
    Return an LED color based on flight category.
    Lightning takes precedence over other conditions.
    If wind speed or gust exceeds the threshold, override with high wind color.
    """
    # Check for lightning first
    if condition.get("lightning", False):
        return COLOR_LIGHTNING

    # Check wind condition
    wind_speed = condition.get("windSpeed", 0)
    wind_gust = condition.get("windGust", 0)
    if wind_speed >= HIGH_WIND_THRESHOLD or wind_gust >= HIGH_WIND_THRESHOLD:
        return COLOR_HIGH_WIND

    # Otherwise, choose based on flight category
    category = condition.get("flightCategory", "")
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
    """
    Update the LED strip:
      - First 9 LEDs: fixed legend.
      - Remaining LEDs: one per airport.
        If METAR data exists, show its color; otherwise, set to off.
    """
    total_leds = len(pixels)
    # Set fixed legend (LEDs 0-8)
    for i in range(9):
        if i >= total_leds:
            logging.error("Legend LED index %d is out-of-range (total LEDs: %d).", i, total_leds)
            continue
        try:
            pixels[i] = LEGEND_COLORS[i]
            logging.info("Setting legend LED %d to %s", i, LEGEND_COLORS[i])
        except Exception as e:
            logging.error("Error setting legend LED %d: %s", i, e)

    offset = 9
    for j, airport in enumerate(airports):
        idx = offset + j
        if idx >= total_leds:
            logging.error("Calculated LED index %d for airport %s is out-of-range (total LEDs: %d).",
                          idx, airport, total_leds)
            continue
        condition = conditions.get(airport)
        if condition:
            color = get_color_for_condition(condition)
        else:
            # No data available: set LED off
            color = COLOR_CLEAR
        try:
            pixels[idx] = color
            logging.info("Setting LED %d for %s to %s", idx, airport, color)
        except Exception as e:
            logging.error("Error setting LED %d: %s", idx, e)

def main():
    logging.info("Starting METAR LED Display")

    # Load airport ICAO codes from file
    airports = load_airports(AIRPORT_FILE)
    if not airports:
        logging.error("No airports loaded. Exiting.")
        return

    # Total LED count = 9 (legend) + number of airports
    LED_COUNT = len(airports) + 9

    # Initialize the NeoPixel LED strip
    pixels = neopixel.NeoPixel(
        LED_PIN, LED_COUNT, brightness=LED_BRIGHTNESS,
        pixel_order=LED_ORDER, auto_write=False
    )

    conditions = {}
    last_fetch = 0

    while True:
        current_time = time.time()
        # Fetch new METAR data every UPDATE_INTERVAL seconds
        if current_time - last_fetch > UPDATE_INTERVAL:
            content = fetch_metar_data(airports)
            if content:
                conditions = parse_metar(content)
            else:
                logging.error("No METAR data available; keeping previous data.")
            last_fetch = current_time

        update_leds(pixels, airports, conditions)
        pixels.show()
        time.sleep(1)  # Update display every 1 second

if __name__ == '__main__':
    try:
        main()
    except KeyboardInterrupt:
        logging.info("Exiting METAR LED Display")
