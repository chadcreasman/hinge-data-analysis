from datetime import datetime
from collections import defaultdict
import geoip2.database
from geopy.geocoders import Nominatim
import pandas as pd
import json
import os
import shutil
import logging

logging.basicConfig(level=logging.INFO)

class UserAnalytics:
    def __init__(self):
        self.assets_path = os.environ.get("ASSETS_PATH")
        self.user_file_path = os.environ.get("USER_FILE_PATH")
        self.geo_lite_db_path = os.environ.get("GEOLITE_DB_PATH")
        self.media_path = os.environ.get("MEDIA_PATH")

        # TODO: come back and fix this
        # if self.geo_lite_db_path is None:
            # raise Exception("GEOLITE_DB_PATH environment variable is not set.")

        if self.user_file_path is None:
            raise Exception("USER_FILE_PATH environment variable is not set.")
        
        if '.json' not in self.user_file_path:
            raise Exception("The user file needs to be a JSON file.")

        with open(self.user_file_path, 'r') as file:
            user_data = json.load(file)
        
        self.user_data = user_data
        
        # need to copy the files from the media_path to the assets_dir
        _copy_files(self.media_path, self.assets_path)

    def get_media_file_paths(self):
        jpg_files = [f for f in os.listdir(self.assets_path) if f.endswith(".jpg") or f.endswith(".jpeg") or f.endswith(".png")]
        return jpg_files
    
    def get_account_data(self):
        return self.user_data["account"]

    def get_devices_data(self):
        return self.user_data["devices"]
    
    def get_profile_data(self):
        return self.user_data["profile"] 
    
    def get_preferences_data(self):
        return self.user_data["preferences"]
    
    def get_location_data(self):
        return self.user_data["location"]

    def build_user_location_dict(self):
        location = self.get_location_data()
        user_location = {}

        user_location["city"] = location["cbsa"].split(",")[0]
        user_location["latitude"] = location["latitude"]
        user_location["longitude"] = location["longitude"]
        user_location["country"] = location["country_short"]
        user_location["neighborhood"] = location["neighborhood"]
        user_location["locality"] = location["admin_area_1_short"]

        return user_location

    def build_user_summary_dict(self):
        profile_data = self.get_profile_data()
        account_data = self.get_account_data()
        user_summary = {}

        # get profile data
        user_summary["first_name"] = profile_data["first_name"]
        user_summary["age"] = profile_data["age"]
        # convert height in cm to inches and ft
        feet, inches = _convert_height(profile_data["height_centimeters"])
        user_summary["height_feet"] = feet
        user_summary["height_inches"] = inches
        user_summary["gender"] = profile_data["gender"]
        user_summary["ethnicities"] = profile_data["ethnicities"]
        user_summary["religions"] = profile_data["religions"]
        user_summary["job_title"] = profile_data["job_title"]
        user_summary["workplaces"] = profile_data["workplaces"]
        user_summary["education_attained"] = profile_data["education_attained"]
        user_summary["hometowns"] = profile_data["hometowns"]
        user_summary["languages_spoken"] = profile_data["languages_spoken"]
        user_summary["politics"] = profile_data["politics"]
        user_summary["pets"] = profile_data["pets"]
        user_summary["relationship_types"] = profile_data["relationship_types"]
        user_summary["dating_intention"] = profile_data["dating_intention"]

        # capture duration paused and on app time
        # the pause times are only present if the user has paused the app, so have to check their presence first
        if "last_unpause_time" in account_data and "last_pause_time" in account_data:  
            user_summary["last_pause_duration"] = _timestamp_durations(
                leading_timestamp=account_data["last_unpause_time"],
                lagging_timestamp=account_data["last_pause_time"])
        else:
           user_summary["last_pause_duration"] = 0
        
        user_summary["on_app_duration"] = _timestamp_durations(
            leading_timestamp=account_data["last_seen"],
            lagging_timestamp=account_data["signup_time"])

        return user_summary
    
    def profile_preference_selections(self):
        profile_data = self.get_profile_data()
        preference_data = self.get_preferences_data()

        profile_fields = ["religions", "ethnicities", "smoking", "drinking", "marijuana", "drugs", "children", "family_plans", "education_attained", "politics"] 
        preference_fields = ["religion_preference", "ethnicity_preference", "smoking_preference", "drinking_preference", "marijuana_preference", "drugs_preference", "children_preference", "family_plans_preference", "education_attained_preference", "politics_preference"]

        profile_values = [profile_data[field] for field in profile_fields if field in profile_data]
        preference_values = [preference_data[field] for field in preference_fields if field in preference_data]

        return profile_values, preference_values

    def count_stringeny_attributes(self):
        preferences = self.get_preferences_data()

        dealbreaker_cats = {
            "physical": ["age_dealbreaker", "height_dealbreaker"],
            "identity": ["ethnicity_dealbreaker", "religion_dealbreaker", "politics_dealbreaker"],
            "lifestyle": ["smoking_dealbreaker", "drinking_dealbreaker", "marijuana_dealbreaker", "drugs_dealbreaker"],
            "career": ["education_attained_dealbreaker"],
            "future_plans": ["children_dealbreaker", "family_plans_dealbreaker"]
        }
        # initialize counters
        display_counts = defaultdict(lambda: {"true": 0, "false": 0})

        for category, fields in dealbreaker_cats.items():
            for field in fields:
                if field in preferences:
                    display_value = preferences[field]
                    display_counts[category]["true" if display_value else "false"] += 1
        return dict(display_counts)

    
    def count_displayed_attributes(self):
        profile_data = self.get_profile_data()
        
        categories = {
            "identity": ["gender_identity_displayed", "ethnicities_displayed", "religions_displayed", "politics_displayed", "languages_spoken_displayed", "hometowns_displayed"],
            "lifestyle": ["smoking_displayed", "drinking_displayed", "marijuana_displayed", "drugs_displayed", "vaccination_status_displayed", "pets_displayed", ],
            "career": ["workplaces_displayed", "job_title_displayed", "schools_displayed"],
            "future_plans": ["family_plans_displayed", "dating_intention_displayed", "children_displayed", "relationship_type_displayed"]
        }

        # initialize counters
        display_counts = defaultdict(lambda: {"true": 0, "false": 0})
        
        for category, fields in categories.items():
            for field in fields:
                if field in profile_data:
                    display_value = profile_data[field]
                    display_counts[category]["true" if display_value else "false"] += 1
        return dict(display_counts)

    def collect_location_from_ip(self):
        device_data = self.get_devices_data()
        ip_addresses = [device["ip_address"] for device in device_data]

        geolocation_data = [self._get_city_info(ip) for ip in ip_addresses if self._get_city_info(ip) is not None]

        return pd.DataFrame(geolocation_data)
    
def _copy_files(src_dir, dest_dir):
    os.makedirs(dest_dir, exist_ok=True)
    logging.info(f"Copying images files from media directory: {src_dir} to asset directory; {dest_dir}." )

    # only proceed if the destination directory is empty
    if os.listdir(dest_dir):
        logging.info(f"Asset directory: '{dest_dir}' is not empty. Skipping copy...")
        return

    # loop through all files in source directory
    for file_name in os.listdir(src_dir):
        src_path = os.path.join(src_dir, file_name)
        dest_path = os.path.join(dest_dir, file_name)

        # only copy files (not subdirectories)
        if os.path.isfile(src_path):
            shutil.copy2(src_path, dest_path)  # copy2 preserves metadata

    def _get_city_info(self, ip):
        # initialize GeoLite2 reader & geocoder
        geolite_db_path = self.geo_lite_db_path
        reader = geoip2.database.Reader(geolite_db_path)
        geolocator = Nominatim(user_agent="geoip_mapper")
        try:
            response = reader.city(ip)
            city = response.city.name
            region = response.subdivisions.most_specific.name
            country = response.country.name

            # get latitude & longitude
            location = geolocator.geocode(f"{city}, {region}, {country}")
            if location:
                return {
                    "ip": ip,
                    "city": city,
                    "region": region,
                    "country": country,
                    "latitude": location.latitude,
                    "longitude": location.longitude
                }
        except:
            return None  # invalid or private IP

    
def _convert_height(cm):
    inches = cm / 2.54
    feet = int(inches // 12)  # whole feet
    # remaining inches, rounded to 1 decimal place
    remaining_inches = round(inches % 12, 1)  

    return feet, remaining_inches 

def _timestamp_durations(leading_timestamp, lagging_timestamp):
    lead_dt_format = "%Y-%m-%d %H:%M:%S.%f"
    lag_dt_format = "%Y-%m-%d %H:%M:%S.%f"

    # parse timestamps
    lag_time = datetime.strptime(lagging_timestamp, lag_dt_format)
    lead_time = datetime.strptime(leading_timestamp, lead_dt_format)

    # calculate difference in days
    days_difference = (lead_time - lag_time).days

    return days_difference