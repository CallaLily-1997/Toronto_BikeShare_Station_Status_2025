import urllib.request
import json
import pandas as pd
import folium
import datetime as dt
from geopy.distance import geodesic
from geopy.geocoders import Nominatim
import streamlit as st
import requests
from geopy.exc import GeocoderTimedOut, GeocoderUnavailable

# =========================
# STATION STATUS
# =========================
@st.cache_data
def query_station_status(url):
    with urllib.request.urlopen(url) as data_url:
        data = json.loads(data_url.read().decode())

    if "data" not in data or "stations" not in data["data"]:
        raise ValueError("URL KHÔNG phải station_status.json")

    df = pd.DataFrame(data["data"]["stations"])

    # filter nếu tồn tại cột
    if "is_renting" in df.columns:
        df = df[df["is_renting"] == 1]

    if "is_returning" in df.columns:
        df = df[df["is_returning"] == 1]

    if "last_reported" in df.columns:
        df = df.drop_duplicates(["station_id", "last_reported"])
        df["last_reported"] = df["last_reported"].apply(
            lambda x: dt.datetime.utcfromtimestamp(x)
        )

    df["time"] = dt.datetime.utcfromtimestamp(data["last_updated"])
    df = df.set_index("time")
    df.index = df.index.tz_localize("UTC")

    # expand bike types nếu có
    if "num_bikes_available_types" in df.columns:
        df = pd.concat(
            [df, df["num_bikes_available_types"].apply(pd.Series)],
            axis=1
        )

    return df


# =========================
# STATION INFORMATION (LAT/LON)
# =========================
@st.cache_data
def get_station_latlon(url):
    with urllib.request.urlopen(url) as data_url:
        data = json.loads(data_url.read().decode())

    if "data" not in data or "stations" not in data["data"]:
        raise ValueError("URL KHÔNG phải station_information.json")

    df = pd.DataFrame(data["data"]["stations"])
    return df


# =========================
# JOIN LAT/LON
# =========================
def join_latlon(df_status, df_latlon):
    return df_status.merge(
        df_latlon[["station_id", "lat", "lon"]],
        how="left",
        on="station_id"
    )


# =========================
# MAP UTILS
# =========================
def get_marker_color(num_bikes_available):
    if num_bikes_available > 3:
        return "green"
    elif num_bikes_available > 0:
        return "yellow"
    else:
        return "red"
    
def get_status_label(num_bikes_available):
    if num_bikes_available > 3:
        return "Many bikes available"
    elif num_bikes_available > 0:
        return "Few bikes available"
    else:
        return "No bikes available"



# =========================
# GEOCODING
# =========================
cache = {}

def geocode(address):
    if address in cache:
        return cache[address]
    
    geolocator = Nominatim(user_agent="bikeshare-app", timeout=10)
    try:
        location = geolocator.geocode(address)
        result = (location.latitude, location.longitude) if location else None
        cache[address] = result
        return result
    except (GeocoderTimedOut, GeocoderUnavailable) as e:
        print(f"Geocoding error for '{address}': {e}")
        cache[address] = None
        return None

# =========================
# BIKE AVAILABILITY
# =========================
def get_bike_availability(user_latlon, df, input_bike_modes):
    df = df.copy()
    df["distance"] = df.apply(
        lambda row: geodesic(user_latlon, (row["lat"], row["lon"])).km,
        axis=1
    )

    if len(input_bike_modes) == 1:
        df = df[df[input_bike_modes[0]] > 0]
    else:
        df = df[(df["ebike"] > 0) | (df["mechanical"] > 0)]

    closest = df.loc[df["distance"].idxmin()]

    return [
        closest["station_id"],
        closest["lat"],
        closest["lon"]
    ]


# =========================
# DOCK AVAILABILITY
# =========================
def get_dock_availability(user_latlon, df):
    df = df.copy()
    df["distance"] = df.apply(
        lambda row: geodesic(user_latlon, (row["lat"], row["lon"])).km,
        axis=1
    )

    df = df[df["num_docks_available"] > 0]
    closest = df.loc[df["distance"].idxmin()]

    return [
        closest["station_id"],
        closest["lat"],
        closest["lon"]
    ]


# =========================
# OSRM ROUTING
# =========================
def run_osrm(chosen_station, iamhere):
    start = f"{iamhere[1]},{iamhere[0]}"
    end = f"{chosen_station[2]},{chosen_station[1]}"

    url = (
        "http://router.project-osrm.org/route/v1/driving/"
        f"{start};{end}?geometries=geojson"
    )

    r = requests.get(url)
    routejson = r.json()

    coords = [
        [lat, lon]
        for lon, lat in routejson["routes"][0]["geometry"]["coordinates"]
    ]

    duration = round(routejson["routes"][0]["duration"] / 60, 1)

    return coords, duration