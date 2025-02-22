#!/usr/bin/env python3
"""
METARMap Script – Cleaned up version

This script retrieves METAR weather data for a list of airports,
parses conditions, and displays them on a NeoPixel LED strip along
with an optional external display. It also supports sunrise/sunset
based brightness adjustments.
"""

import urllib.request
import xml.etree.ElementTree as ET
import board
import neopixel
import time
import datetime

try:
    import astral
    import astral.geocoder
    import astral.sun
except ImportError:
    astral = None

try:
    import displaymetar
except ImportError:
    displaymetar = None

# ------------------ CONFIGURATION ------------------
# NeoPixel Configuration
LED_COUNT = 95               # Total number of LED pixels (airports + legend)
LED_PIN = board.D18          # GPIO pin (using PCM)
LED_BRIGHTNESS = 0.5         # Normal brightness (0.0 to 1.0)
LED_ORDER = neopixel.GRB

# Color definitions (adjusted so that comments match typical conventions)
COLOR_VFR = (0, 255, 0)        # Green for VFR
COLOR_VFR_FADE = (0, 125, 0)   # Green fade for windy VFR
COLOR_MVFR = (0, 0, 255)       # Blue for MVFR
COLOR_MVFR_FADE = (0, 0, 125)  # Blue fade for windy MVFR
COLOR_IFR = (255, 0, 0)        # Red for IFR
COLOR_IFR_FADE = (125, 0, 0)   # Red fade for windy IFR
COLOR_LIFR = (255, 0, 255)     # Magenta for LIFR
COLOR_LIFR_FADE = (125, 0, 125)  # Magenta fade for windy LIFR
COLOR_CLEAR = (0, 0, 0)        # LED off/clear
COLOR_LIGHTNING = (255, 255, 255)  # White for lightning
COLOR_HIGH_WINDS = (255, 255, 0)     # Yellow for high winds

# Animation configuration
ACTIVATE_WIND_ANIMATION = False
ACTIVATE_LIGHTNING_ANIMATION = True
FADE_INSTEAD_OF_BLINK = True
WIND_BLINK_THRESHOLD = 15      # Knots for wind blinking/fading
HIGH_WINDS_THRESHOLD = 25      # Knots to trigger high winds (set -1 to disable)
ALWAYS_BLINK_FOR_GUSTS = False
BLINK_SPEED = 0.5              # Seconds between LED updates
BLINK_TOTALTIME_SECONDS = 300  # Total animation time

# Daytime dimming configuration
ACTIVATE_DAYTIME_DIMMING = True
# Default times if not using sunrise/sunset:
BRIGHT_TIME_START = datetime.time(7, 0)
DIM_TIME_START = datetime.time(19, 0)
LED_BRIGHTNESS_DIM = 0.1       # Dimming brightness
USE_SUNRISE_SUNSET = True
LOCATION = "Little Rock"       # Location for sunrise/sunset calculation

# External Display support
ACTIVATE_EXTERNAL_METAR_DISPLAY = False
DISPLAY_ROTATION_SPEED = 5.0   # Seconds to display each METAR on external display

# Legend configuration (set of LEDs reserved for legend info)
SHOW_LEGEND = True
LEGEND_LED_COUNT = 7           # Number of LEDs reserved for legend
OFFSET_LEGEND_BY = 0           # Offset from the end of airport LEDs

# ----------------------------------------------------

def get_sun_times():
    """Return sunrise and sunset times for today (as time objects)."""
    now = datetime.datetime.now()
    if astral and USE_SUNRISE_SUNSET:
        try:
            # Try Astral v1 style first
            ast = astral.Astral()
            city = ast[LOCATION]
            sun = city.sun(date=now.date(), local=True)
        except (KeyError, AttributeError):
            try:
                # Use Astral v2 style
                city = astral.geocoder.lookup(LOCATION, astral.geocoder.database())
                sun = astral.sun.sun(city.observer, date=now.date(), tzinfo=city.timezone)
            except KeyError:
                print("Error: Location not recognized for sunrise/sunset")
                return BRIGHT_TIME_START, DIM_TIME_START
        return sun['sunrise'].time(), sun['sunset'].time()
    else:
        return BRIGHT_TIME_START, DIM_TIME_START

def load_airports():
    """Load the list of airports from file(s)."""
    try:
        with open("/home/admin/METARMAP/airports") as f:
            airports = [line.strip() for line in f if line.strip()]
    except IOError:
        print("Error: Could not read airports file.")
        airports = []
    # Try loading subset for display (optional)
    try:
        with open("/home/pi/displayairports") as f2:
            display_airports = [line.strip() for line in f2 if line.strip()]
        print("Using subset of airports for external display.")
    except IOError:
        print("Rotating through all airports on LED display.")
        display_airports = None
    return airports, display_airports

def fetch_metar_data(airports):
    """Fetch METAR data from aviationweather.gov and return the XML content."""
    # Filter out any placeholder entries like "NULL"
    station_str = ",".join([st for st in airports if st.upper() != "NULL"])
    url = ("https://aviationweather.gov/cgi-bin/data/dataserver.php?"
           "requestType=retrieve&dataSource=metars&stationString=" +
           station_str +
           "&hoursBeforeNow=5&format=xml&mostRecent=true&mostRecentForEachStation=constraint")
    print("Fetching METAR data from:")
    print(url)
    req = urllib.request.Request(url, headers={
        'User-Agent': ('Mozilla/5.0 (Windows NT 10.0; Win64; x64) '
                       'AppleWebKit/537.36 (KHTML, like Gecko) '
                       'Chrome/86.0.4240.198 Safari/537.36 Edg/86.0.622.69')
    })
    with urllib.request.urlopen(req) as response:
        content = response.read()
    return content

def parse_metar(content):
    """Parse the METAR XML and return a dictionary of conditions and a list for display."""
    root = ET.fromstring(content)
    condition_dict = {}
    display_station_list = []
    for metar in root.iter('METAR'):
        station_elem = metar.find('station_id')
        flight_elem = metar.find('flight_category')
        if station_elem is None or station_elem.text is None:
            print("Missing station id, skipping.")
            continue
        if flight_elem is None or flight_elem.text is None:
            print("Missing flight condition for " + station_elem.text + ", skipping.")
            continue

        station_id = station_elem.text.strip()
        flight_category = flight_elem.text.strip()

        # Get wind information
        wind_speed = int(metar.find('wind_speed_kt').text) if metar.find('wind_speed_kt') is not None else 0
        wind_gust = False
        wind_gust_speed = 0
        if metar.find('wind_gust_kt') is not None:
            wind_gust_speed = int(metar.find('wind_gust_kt').text)
            wind_gust = ALWAYS_BLINK_FOR_GUSTS or (wind_gust_speed > WIND_BLINK_THRESHOLD)
        wind_dir = metar.find('wind_dir_degrees').text if metar.find('wind_dir_degrees') is not None else ""

        # Other weather details
        temp_c = int(round(float(metar.find('temp_c').text))) if metar.find('temp_c') is not None else 0
        dewpoint_c = int(round(float(metar.find('dewpoint_c').text))) if metar.find('dewpoint_c') is not None else 0

        # Visibility – remove any '+' signs and round off
        vis = 0
        if metar.find('visibility_statute_mi') is not None:
            vis_str = metar.find('visibility_statute_mi').text.replace('+', '')
            vis = int(round(float(vis_str)))
        altim_hg = float(round(float(metar.find('altim_in_hg').text), 2)) if metar.find('altim_in_hg') is not None else 0.0
        obs = metar.find('wx_string').text if metar.find('wx_string') is not None else ""
        obs_time = datetime.datetime.fromisoformat(metar.find('observation_time').text.replace("Z", "+00:00")) if metar.find('observation_time') is not None else datetime.datetime.now()

        # Determine lightning based on raw text
        raw_text = metar.find('raw_text').text if metar.find('raw_text') is not None else ""
        lightning = (("LTG" in raw_text or "TS" in raw_text) and "TSNO" not in raw_text)

        # (Sky conditions could be processed here if needed)
        condition_dict[station_id] = {
            "flightCategory": flight_category,
            "windDir": wind_dir,
            "windSpeed": wind_speed,
            "windGustSpeed": wind_gust_speed,
            "windGust": wind_gust,
            "vis": vis,
            "obs": obs,
            "tempC": temp_c,
            "dewpointC": dewpoint_c,
            "altimHg": altim_hg,
            "lightning": lightning,
            "obsTime": obs_time
        }
        print(f"{station_id}:{flight_category}:{wind_dir}@{wind_speed}"
              f"{'G'+str(wind_gust_speed) if wind_gust else ''}:{vis}SM:{obs}:"
              f"{temp_c}/{dewpoint_c}:{altim_hg}:{lightning}")
        # Add to display list if using external display
        display_station_list.append(station_id)
    return condition_dict, display_station_list

def update_led_strip(pixels, airports, condition_dict, wind_cycle):
    """Set LED colors based on conditions for each airport and add legend LEDs if enabled."""
    led_index = 0
    for airport in airports:
        if airport.upper() == "NULL":
            led_index += 1
            continue

        # Default color is off
        color = COLOR_CLEAR
        conditions = condition_dict.get(airport, None)
        windy = False
        high_winds = False
        lightning_cond = False

        if conditions:
            windy = (ACTIVATE_WIND_ANIMATION and wind_cycle and 
                     (conditions["windSpeed"] >= WIND_BLINK_THRESHOLD or conditions["windGust"]))
            high_winds = (windy and HIGH_WINDS_THRESHOLD != -1 and 
                          (conditions["windSpeed"] >= HIGH_WINDS_THRESHOLD or conditions["windGustSpeed"] >= HIGH_WINDS_THRESHOLD))
            lightning_cond = (ACTIVATE_LIGHTNING_ANIMATION and (not wind_cycle) and conditions["lightning"])
            
            fc = conditions["flightCategory"]
            if fc == "VFR":
                if not (windy or lightning_cond):
                    color = COLOR_VFR
                elif lightning_cond:
                    color = COLOR_LIGHTNING
                elif high_winds:
                    color = COLOR_HIGH_WINDS
                else:
                    color = COLOR_VFR_FADE if FADE_INSTEAD_OF_BLINK else COLOR_CLEAR
            elif fc == "MVFR":
                if not (windy or lightning_cond):
                    color = COLOR_MVFR
                elif lightning_cond:
                    color = COLOR_LIGHTNING
                elif high_winds:
                    color = COLOR_HIGH_WINDS
                else:
                    color = COLOR_MVFR_FADE if FADE_INSTEAD_OF_BLINK else COLOR_CLEAR
            elif fc == "IFR":
                if not (windy or lightning_cond):
                    color = COLOR_IFR
                elif lightning_cond:
                    color = COLOR_LIGHTNING
                elif high_winds:
                    color = COLOR_HIGH_WINDS
                else:
                    color = COLOR_IFR_FADE if FADE_INSTEAD_OF_BLINK else COLOR_CLEAR
            elif fc == "LIFR":
                if not (windy or lightning_cond):
                    color = COLOR_LIFR
                elif lightning_cond:
                    color = COLOR_LIGHTNING
                elif high_winds:
                    color = COLOR_HIGH_WINDS
                else:
                    color = COLOR_LIFR_FADE if FADE_INSTEAD_OF_BLINK else COLOR_CLEAR
        print(f"Setting LED {led_index} for {airport} to {color} "
              f"({'lightning' if lightning_cond else ''}"
              f"{'high winds' if high_winds else ''}"
              f"{'windy' if windy else ''})")
        try:
            pixels[led_index] = color
        except IndexError:
            print(f"IndexError: LED index {led_index} is out of range.")
        led_index += 1

    # Set legend LEDs if enabled and if there is space.
    if SHOW_LEGEND:
        legend_start = led_index + OFFSET_LEGEND_BY
        if legend_start + LEGEND_LED_COUNT <= LED_COUNT:
            pixels[legend_start] = COLOR_VFR
            pixels[legend_start + 1] = COLOR_MVFR
            pixels[legend_start + 2] = COLOR_IFR
            pixels[legend_start + 3] = COLOR_LIFR
            # Use lightning color if enabled; else default to VFR color.
            if ACTIVATE_LIGHTNING_ANIMATION:
                pixels[legend_start + 4] = COLOR_LIGHTNING if wind_cycle else COLOR_VFR
            if ACTIVATE_WIND_ANIMATION:
                pixels[legend_start + 5] = COLOR_VFR if not wind_cycle else (COLOR_VFR_FADE if FADE_INSTEAD_OF_BLINK else COLOR_CLEAR)
                if HIGH_WINDS_THRESHOLD != -1:
                    pixels[legend_start + 6] = COLOR_VFR if not wind_cycle else COLOR_HIGH_WINDS
        else:
            print("Not enough LED pixels available for legend display.")

def main():
    print("Running metar.py at", datetime.datetime.now().strftime('%d/%m/%Y %H:%M'))
    sunrise, sunset = get_sun_times()
    print("Sunrise:", sunrise.strftime('%H:%M'), "Sunset:", sunset.strftime('%H:%M'))

    # Determine brightness based on time of day
    now_time = datetime.datetime.now().time()
    is_bright = sunrise < now_time < sunset
    current_brightness = LED_BRIGHTNESS if is_bright else LED_BRIGHTNESS_DIM

    print("Wind animation:", ACTIVATE_WIND_ANIMATION)
    print("Lightning animation:", ACTIVATE_LIGHTNING_ANIMATION)
    print("Daytime Dimming:", ACTIVATE_DAYTIME_DIMMING, ("using Sunrise/Sunset" if USE_SUNRISE_SUNSET and ACTIVATE_DAYTIME_DIMMING else ""))
    print("External Display:", ACTIVATE_EXTERNAL_METAR_DISPLAY)

    # Initialize the LED strip
    pixels = neopixel.NeoPixel(LED_PIN, LED_COUNT,
                               brightness=current_brightness,
                               pixel_order=LED_ORDER,
                               auto_write=False)

    # Load airport lists
    airports, display_airports = load_airports()
    if len(airports) > LED_COUNT:
        print("WARNING: Too many airports in airports file. Increase LED_COUNT or reduce the number of airports.")
        return

    # Fetch and parse METAR data
    metar_content = fetch_metar_data(airports)
    condition_dict, display_station_list = parse_metar(metar_content)

    # Setup external display if enabled
    disp = None
    if displaymetar and ACTIVATE_EXTERNAL_METAR_DISPLAY:
        print("Setting up external display")
        disp = displaymetar.startDisplay()
        displaymetar.clearScreen(disp)

    # Determine loop count for blinking/animation
    loop_limit = int(round(BLINK_TOTALTIME_SECONDS / BLINK_SPEED)) if (
        ACTIVATE_WIND_ANIMATION or ACTIVATE_LIGHTNING_ANIMATION or ACTIVATE_EXTERNAL_METAR_DISPLAY) else 1
    wind_cycle = False
    display_time = 0.0
    display_airport_index = 0
    num_airports = len(display_station_list)

    while loop_limit > 0:
        update_led_strip(pixels, airports, condition_dict, wind_cycle)
        pixels.show()

        # External display update
        if disp is not None and display_station_list:
            if display_time <= DISPLAY_ROTATION_SPEED:
                displaymetar.outputMetar(disp,
                                         display_station_list[display_airport_index],
                                         condition_dict.get(display_station_list[display_airport_index], None))
                display_time += BLINK_SPEED
            else:
                display_time = 0.0
                display_airport_index = (display_airport_index + 1) % num_airports
                print("Showing METAR Display for", display_station_list[display_airport_index])

        time.sleep(BLINK_SPEED)
        wind_cycle = not wind_cycle
        loop_limit -= 1

    print("Done.")

if __name__ == '__main__':
    main()
