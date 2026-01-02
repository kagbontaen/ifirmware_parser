#!/usr/bin/env python3
import json
import urllib.request
import time
import os
import argparse

# ------------------------------
# Configuration
# ------------------------------
USER_AGENT = "kinc-firmwareKeysFetcher/1.0"
BASE = "https://theapplewiki.com/wiki/Special:Ask"
CACHE_DIR = ".cache"
CACHE_TTL = 7 * 24 * 60 * 60  # 7 days
POLITE_DELAY = 2  # seconds
os.makedirs(CACHE_DIR, exist_ok=True)

# ------------------------------
# Helpers
# ------------------------------
def smw_path_escape(text):
    return text.replace("[", "-5B").replace("]", "-5D").replace(" ", "-20").replace(":", "-3A").replace(",", "%2C")

def cache_path(device, build=None, version=None):
    if build and version:
        return os.path.join(CACHE_DIR, f"{device}_{build}_{version}.json")
    elif build:
        return os.path.join(CACHE_DIR, f"{device}_{build}.json")
    elif version:
        return os.path.join(CACHE_DIR, f"{device}_{version}.json")
    else:
        return os.path.join(CACHE_DIR, f"{device}_unknown.json")

def cache_valid(path):
    return os.path.exists(path) and (time.time() - os.path.getmtime(path)) < CACHE_TTL

def load_cache(device, build=None, version=None, debug=False):
    # Exact match
    exact_path = cache_path(device, build, version)
    if cache_valid(exact_path):
        if debug:
            print(f"[DEBUG] Using exact cache: {exact_path}")
        with open(exact_path, "r") as f:
            return json.load(f), exact_path

    # Fallback: search for any file containing build or version
    for fname in os.listdir(CACHE_DIR):
        if device in fname and ((build and build in fname) or (version and version in fname)):
            path = os.path.join(CACHE_DIR, fname)
            if cache_valid(path):
                if debug:
                    print(f"[DEBUG] Using fallback cache: {path}")
                with open(path, "r") as f:
                    return json.load(f), path
    return None, None

def save_cache(data, device, build=None, version=None):
    path = cache_path(device, build, version)
    with open(path, "w") as f:
        json.dump(data, f, separators=(",", ":"))
    print(f"[+] Saved cache {path}")

# ------------------------------
# Step 1: Discovery
# ------------------------------
def discover_update_line(device, version=None, build=None, verbose=False):
    query = "[[:Keys:+]]"
    query += f"[[Has_firmware_device::{device}]]"
    if version: query += f"[[Has_firmware_version::{version}]]"
    if build: query += f"[[Has_firmware_build::{build}]]"

    # Request fields: include version
    query += "/-3FHas-20firmware-20build%3Dbuild"
    query += "/-3FHas-20firmware-20version%3Dversion"
    query += "/-3FHas-20firmware-20device%3Ddevice"
    query += "/-3FHas-20firmware-20codename%3Dcodename"
    query += "/limit%3D1/offset%3D0/format%3Djson/searchlabel%3DKeys/type%3Dbroadtable"

    url = BASE + "/" + smw_path_escape(query)
    if verbose:
        print(f"[DEBUG] Discovery URL: {url}")

    req = urllib.request.Request(url, headers={"User-Agent": USER_AGENT})
    try:
        with urllib.request.urlopen(req, timeout=15) as r:
            data = json.load(r)
    except Exception as e:
        print(f"[-] Discovery request failed: {e}")
        return None, None, None

    results = data.get("results", {})
    if not results:
        return None, None, None

    for page_title, entry in results.items():
        if page_title.startswith("Keys:"):
            update_line = page_title[len("Keys:"):].split(" ", 1)[0]
            discovered_build = None
            discovered_version = None
            # Extract build and version from printouts
            printouts = entry.get("printouts", {})
            if "build" in printouts and printouts["build"]:
                discovered_build = printouts["build"][0]
            if "version" in printouts and printouts["version"]:
                discovered_version = printouts["version"][0]

            # fallback: parse build from page_title if not found
            if not discovered_build:
                parts = page_title[len("Keys:"):].split(" ")
                if len(parts) > 1:
                    discovered_build = parts[1]

            if verbose:
                print(f"[DEBUG] Update line: {update_line}, build: {discovered_build}, version: {discovered_version}")
            return update_line, discovered_build, discovered_version

    return None, None, None


# ------------------------------
# Step 2: Fetch Keys
# ------------------------------
def fetch_keys(device, build, update, verbose=False):
    subobject = f"Keys:{update} {build} ({device})"
    path = "/-5B-5B-2DHas-20subobject::" + smw_path_escape(subobject) + "-5D-5D"
    path += "/-3FHas-20filename%3Dfilename"
    path += "/-3FHas-20firmware-20device%3Ddevice"
    path += "/-3FHas-20key%3Dkey"
    path += "/-3FKey-20DevKBAG%3Ddevkbag"
    path += "/-3FHas-20key-20IV%3Div"
    path += "/-3FKey-20KBAG%3Dkbag"
    path += "/mainlabel%3Dfilename"
    path += "/limit%3D100/offset%3D0/format%3Djson/searchlabel%3DKeys/type%3Dsimple"

    url = BASE + path
    if verbose:
        print(f"[DEBUG] Fetch keys URL: {url}")

    req = urllib.request.Request(url, headers={"User-Agent": USER_AGENT})
    try:
        with urllib.request.urlopen(req, timeout=15) as r:
            data = json.load(r)
    except Exception as e:
        print(f"[-] Fetch keys request failed: {e}")
        return None

    return data if isinstance(data, dict) and data else None

# ------------------------------
# Fetch workflow
# ------------------------------
def fetch_firmware_keys(device, version=None, build=None, debug=False):
    cached, cache_file = load_cache(device, build, version, debug=debug)
    final_build = build

    if cached:
        keys = cached
        if not build and cache_file:
            parts = os.path.basename(cache_file).replace(".json", "").split("_")
            if len(parts) >= 2:
                final_build = parts[1]
            if debug:
                print(f"[DEBUG] Extracted build from cache filename: {final_build}")
    else:
        update_line, discovered_build, discovered_version = discover_update_line(device, version, build, verbose=debug)
        if not update_line:
            print(f"[-] Failed to discover update line for {device}")
            return None, None

        final_build = build if build else discovered_build
        # Use discovered_version if you need it for later
        version = version if version else discovered_version


        if debug:
            print(f"[DEBUG] Waiting {POLITE_DELAY}s before fetching keys...")
        time.sleep(POLITE_DELAY)

        keys = fetch_keys(device, final_build, update_line, verbose=debug)
        if not keys:
            print(f"[-] Failed to fetch keys for {device} {final_build}")
            return None, None

        save_cache(keys, device, final_build, version)

    # Always write output file as <device>_<build>.json
    output_file = f"{device}_{final_build}.json"
    with open(output_file, "w") as f:
        json.dump(keys, f, separators=(",", ":"))
    if debug:
        print(f"[DEBUG] Keys written to {output_file}")
    return keys, output_file

# ------------------------------
# CLI / Bulk mode
# ------------------------------
def main():
    parser = argparse.ArgumentParser(description="Fetch iOS firmware keys from TheAppleWiki")
    parser.add_argument("-p", "--product", required=True, help="Device identifier, e.g., iPhone9,3")
    parser.add_argument("-s", "--ios", help="iOS version, e.g., 15.0.1")
    parser.add_argument("-b", "--build", help="Firmware build, e.g., 19H370")
    parser.add_argument("--bulk", nargs="+", help="Bulk fetch: space-separated list of product,version,build triples, e.g., 'iPhone9,3,15.0.1,19H370'")
    parser.add_argument("-d", "--debug", action="store_true", help="Enable debug output")
    args = parser.parse_args()

    if args.bulk:
        for entry in args.bulk:
            parts = entry.split(",")
            product = parts[0]
            version = parts[1] if len(parts) > 1 and parts[1] else None
            build = parts[2] if len(parts) > 2 and parts[2] else None
            if not version and not build:
                print(f"[-] Entry '{entry}' must include at least version or build")
                continue
            fetch_firmware_keys(product, version, build, debug=args.debug)
    else:
        if not args.ios and not args.build:
            parser.error("You must provide at least one of --ios (-s) or --build (-b)")
        fetch_firmware_keys(args.product, args.ios, args.build, debug=args.debug)

if __name__ == "__main__":
    main()
