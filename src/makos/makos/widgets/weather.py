"""Weather helpers. Off by default; the network is touched only when the user enables it for a location they entered."""
import json
import time
import urllib.parse
import urllib.request

WMO = {0: 'Clear', 1: 'Mostly clear', 2: 'Partly cloudy', 3: 'Overcast', 45: 'Fog', 48: 'Rime fog', 51: 'Light drizzle', 53: 'Drizzle', 55: 'Heavy drizzle', 56: 'Freezing drizzle', 57: 'Freezing drizzle',
       61: 'Light rain', 63: 'Rain', 65: 'Heavy rain', 66: 'Freezing rain', 67: 'Freezing rain', 71: 'Light snow', 73: 'Snow', 75: 'Heavy snow', 77: 'Snow grains', 80: 'Rain showers', 81: 'Rain showers',
       82: 'Violent showers', 85: 'Snow showers', 86: 'Snow showers', 95: 'Thunderstorm', 96: 'Thunderstorm, hail', 99: 'Thunderstorm, hail'}
HOST = 'api.open-meteo.com'


def wmo_text(code):
    return WMO.get(int(code), 'Unknown') if isinstance(code, (int, float)) else 'Unknown'


def url(lat, lon):
    if not (-90 <= lat <= 90 and -180 <= lon <= 180):
        raise ValueError('Coordinates out of range')
    query = urllib.parse.urlencode({'latitude': f'{lat:.4f}', 'longitude': f'{lon:.4f}', 'current': 'temperature_2m,weather_code,wind_speed_10m', 'timezone': 'auto'})
    return f'https://{HOST}/v1/forecast?{query}'


def parse(payload):
    cur = payload.get('current') if isinstance(payload, dict) else None
    if not isinstance(cur, dict) or not isinstance(cur.get('temperature_2m'), (int, float)):
        raise ValueError('Unexpected weather response')
    return {'temp_c': float(cur['temperature_2m']), 'text': wmo_text(cur.get('weather_code')), 'wind_kmh': float(cur.get('wind_speed_10m') or 0), 'fetched': int(time.time())}


def fetch(lat, lon, timeout=8):
    """One bounded HTTPS request to open-meteo; caller is responsible for checking that the user enabled it."""
    request = urllib.request.Request(url(lat, lon), headers={'User-Agent': 'MakOS-Widgets/0.1'})
    with urllib.request.urlopen(request, timeout=timeout) as reply:
        return parse(json.loads(reply.read(65536)))
