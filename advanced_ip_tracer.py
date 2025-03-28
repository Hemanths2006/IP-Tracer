#!/usr/bin/env python3
"""
Advanced IP Tracer Tool
Author: YourName
GitHub: https://github.com/yourusername/IP-Tracer
"""

import requests
import json
import argparse
import sqlite3
import time
import os
import sys
import webbrowser
from datetime import datetime
from concurrent.futures import ThreadPoolExecutor
import socket
import pyfiglet
from colorama import init, Fore, Style
import folium

# Initialize colorama
init(autoreset=True)

class IPTracer:
    def __init__(self):
        """Initialize the IP tracer with database and API configurations"""
        self.db_conn = self._init_db()
        self.api_providers = self._configure_api_providers()
        self.current_provider = 'ip-api'
        self.rate_limits = {}
        self._load_rate_limits()

    def _init_db(self):
        """Initialize SQLite database for caching"""
        db_conn = sqlite3.connect('ip_cache.db')
        cursor = db_conn.cursor()
        
        # Create IP cache table
        cursor.execute('''
            CREATE TABLE IF NOT EXISTS ip_cache (
                ip TEXT PRIMARY KEY,
                data TEXT,
                timestamp INTEGER,
                provider TEXT
            )
        ''')
        
        # Create rate limits table
        cursor.execute('''
            CREATE TABLE IF NOT EXISTS rate_limits (
                provider TEXT PRIMARY KEY,
                last_request REAL,
                requests_left INTEGER
            )
        ''')
        
        db_conn.commit()
        return db_conn

    def _configure_api_providers(self):
        """Configure available API providers and their field mappings"""
        return {
            'ip-api': {
                'url': 'http://ip-api.com/json/{ip}',
                'fields': {
                    'ip': 'query',
                    'city': 'city',
                    'region': 'regionName',
                    'country': 'country',
                    'lat': 'lat',
                    'lon': 'lon',
                    'isp': 'isp',
                    'asn': 'as',
                    'timezone': 'timezone',
                    'proxy': 'proxy',
                    'hosting': 'hosting'
                },
                'params': {'fields': 'status,message,country,regionName,city,lat,lon,timezone,isp,as,query,proxy,hosting'}
            },
            'ipapi': {
                'url': 'https://ipapi.co/{ip}/json/',
                'fields': {
                    'ip': 'ip',
                    'city': 'city',
                    'region': 'region',
                    'country': 'country_name',
                    'lat': 'latitude',
                    'lon': 'longitude',
                    'isp': 'org',
                    'asn': 'asn',
                    'timezone': 'timezone',
                    'proxy': 'proxy'
                }
            },
            'ipwhois': {
                'url': 'https://ipwho.is/{ip}',
                'fields': {
                    'ip': 'ip',
                    'city': 'city',
                    'region': 'region',
                    'country': 'country',
                    'lat': 'latitude',
                    'lon': 'longitude',
                    'isp': 'connection.isp',
                    'asn': 'connection.asn',
                    'timezone': 'timezone.id',
                    'proxy': 'security.proxy',
                    'hosting': 'security.hosting'
                }
            }
        }

    def _load_rate_limits(self):
        """Load rate limits from database"""
        cursor = self.db_conn.cursor()
        cursor.execute('SELECT provider, last_request, requests_left FROM rate_limits')
        self.rate_limits = {row[0]: {'last_request': row[1], 'requests_left': row[2]} 
                          for row in cursor.fetchall()}

    def _save_rate_limit(self, provider):
        """Save current rate limit info to database"""
        cursor = self.db_conn.cursor()
        cursor.execute('''
            INSERT OR REPLACE INTO rate_limits 
            (provider, last_request, requests_left)
            VALUES (?, ?, ?)
        ''', (provider, 
              self.rate_limits[provider]['last_request'],
              self.rate_limits[provider]['requests_left']))
        self.db_conn.commit()

    def _check_cache(self, ip, provider):
        """Check if IP data exists in cache and is still valid (24 hours)"""
        cursor = self.db_conn.cursor()
        cursor.execute('''
            SELECT data FROM ip_cache 
            WHERE ip = ? AND provider = ? AND timestamp > ?
        ''', (ip, provider, int(time.time()) - 86400))
        row = cursor.fetchone()
        return json.loads(row[0]) if row else None

    def _save_to_cache(self, ip, data, provider):
        """Save IP data to cache"""
        cursor = self.db_conn.cursor()
        cursor.execute('''
            INSERT OR REPLACE INTO ip_cache 
            (ip, data, timestamp, provider)
            VALUES (?, ?, ?, ?)
        ''', (ip, json.dumps(data), int(time.time()), provider))
        self.db_conn.commit()

    def _handle_rate_limit(self, provider):
        """Manage API rate limits with automatic waiting"""
        if provider not in self.rate_limits:
            self.rate_limits[provider] = {'last_request': 0, 'requests_left': 45}
            return True

        now = time.time()
        last = self.rate_limits[provider]['last_request']
        remaining = self.rate_limits[provider]['requests_left']

        # Reset if more than a minute has passed
        if now - last > 60:
            remaining = 45
        elif remaining <= 0:
            wait_time = 60 - (now - last)
            print(Fore.YELLOW + f"Rate limit reached. Waiting {wait_time:.1f} seconds...")
            time.sleep(wait_time)
            remaining = 45

        self.rate_limits[provider]['last_request'] = now
        self.rate_limits[provider]['requests_left'] = remaining - 1
        self._save_rate_limit(provider)
        return True

    def _fetch_from_api(self, ip, provider):
        """Fetch IP data from the specified API provider"""
        if not self._handle_rate_limit(provider):
            return None

        config = self.api_providers[provider]
        url = config['url'].format(ip=ip)
        
        try:
            params = config.get('params', {})
            headers = {'User-Agent': 'AdvancedIPTracer/1.0'}
            response = requests.get(url, params=params, headers=headers, timeout=10)
            data = response.json()
            
            # Handle provider-specific response formats
            if provider == 'ip-api' and data.get('status') != 'success':
                print(Fore.RED + f"Error from {provider}: {data.get('message', 'Unknown error')}")
                return None
            
            # Standardize the data structure
            standardized = {'provider': provider}
            for field, source in config['fields'].items():
                value = data
                for key in source.split('.'):
                    if isinstance(value, dict) and key in value:
                        value = value[key]
                    else:
                        value = None
                        break
                standardized[field] = value
            
            return standardized
            
        except Exception as e:
            print(Fore.RED + f"Error fetching from {provider}: {str(e)}")
            return None

    def get_ip_info(self, ip_address=None, provider=None):
        """Get information about an IP address"""
        provider = provider or self.current_provider
        ip_address = ip_address or self.get_public_ip()
        
        if not ip_address:
            return None

        # Check cache first
        cached_data = self._check_cache(ip_address, provider)
        if cached_data:
            print(Fore.CYAN + f"Using cached data for {ip_address} (from {provider})")
            return cached_data
        
        # Fetch from API
        data = self._fetch_from_api(ip_address, provider)
        if data:
            self._save_to_cache(ip_address, data, provider)
            return data
        
        # Try fallback providers if primary fails
        if provider != 'ip-api':
            print(Fore.YELLOW + f"Trying fallback provider: ip-api")
            return self.get_ip_info(ip_address, 'ip-api')
        
        return None

    def get_public_ip(self):
        """Get the public IP of the current machine"""
        services = [
            'https://api.ipify.org',
            'https://ident.me',
            'https://ipinfo.io/ip'
        ]
        
        for service in services:
            try:
                return requests.get(service, timeout=5).text.strip()
            except:
                continue
        
        print(Fore.RED + "Could not determine public IP")
        return None

    def bulk_lookup(self, ip_list, provider=None, max_workers=5):
        """Perform bulk IP lookups with threading"""
        provider = provider or self.current_provider
        results = {}
        
        with ThreadPoolExecutor(max_workers=max_workers) as executor:
            future_to_ip = {
                executor.submit(self.get_ip_info, ip, provider): ip 
                for ip in ip_list
            }
            
            for future in future_to_ip:
                ip = future_to_ip[future]
                try:
                    results[ip] = future.result()
                except Exception as e:
                    results[ip] = {'error': str(e)}
        
        return results

    def create_map(self, ip_data, filename='ip_map.html'):
        """Create a map visualization of IP locations"""
        if not ip_data:
            print(Fore.RED + "No IP data to map")
            return
        
        if isinstance(ip_data, dict):
            ip_data = [ip_data]  # Convert single IP to list
        
        valid_ips = [ip for ip in ip_data if ip and ip.get('lat') and ip.get('lon')]
        if not valid_ips:
            print(Fore.RED + "No valid location data to map")
            return
        
        # Calculate center of all points
        avg_lat = sum(float(ip['lat']) for ip in valid_ips) / len(valid_ips)
        avg_lon = sum(float(ip['lon']) for ip in valid_ips) / len(valid_ips)
        
        m = folium.Map(location=[avg_lat, avg_lon], zoom_start=2)
        
        for ip in valid_ips:
            popup_text = f"""
                <b>IP:</b> {ip.get('ip', 'N/A')}<br>
                <b>Location:</b> {ip.get('city', 'N/A')}, {ip.get('region', 'N/A')}, {ip.get('country', 'N/A')}<br>
                <b>ISP:</b> {ip.get('isp', 'N/A')}<br>
                <b>ASN:</b> {ip.get('asn', 'N/A')}<br>
                <b>Proxy:</b> {'Yes' if ip.get('proxy') else 'No'}<br>
                <b>Hosting:</b> {'Yes' if ip.get('hosting') else 'No'}
            """
            folium.Marker(
                location=[ip['lat'], ip['lon']],
                popup=folium.Popup(popup_text, max_width=250),
                tooltip=ip.get('ip', 'Unknown IP'),
                icon=folium.Icon(
                    color='red' if ip.get('proxy') or ip.get('hosting') else 'blue',
                    icon='server' if ip.get('hosting') else 'globe'
                )
            ).add_to(m)
        
        m.save(filename)
        print(Fore.GREEN + f"Map saved to {filename}")
        webbrowser.open(f'file://{os.path.abspath(filename)}')

def display_banner():
    """Display the tool banner"""
    banner = pyfiglet.figlet_format("IP TRACER", font="small")
    print(Fore.CYAN + banner)
    print(Fore.YELLOW + "Advanced IP Tracing Tool")
    print(Fore.YELLOW + "=" * 50 + "\n")

def display_ip_info(info):
    """Display IP information in a structured format"""
    if not info:
        print(Fore.RED + "No IP information available")
        return
    
    print(Fore.GREEN + "\n[+] Basic Information:")
    print(Fore.WHITE + f"  IP Address: {info.get('ip', 'N/A')}")
    print(Fore.WHITE + f"  Data Source: {info.get('provider', 'N/A')}")
    
    print(Fore.GREEN + "\n[+] Geographic Information:")
    print(Fore.WHITE + f"  City: {info.get('city', 'N/A')}")
    print(Fore.WHITE + f"  Region: {info.get('region', 'N/A')}")
    print(Fore.WHITE + f"  Country: {info.get('country', 'N/A')}")
    print(Fore.WHITE + f"  Coordinates: {info.get('lat', 'N/A')}, {info.get('lon', 'N/A')}")
    print(Fore.WHITE + f"  Timezone: {info.get('timezone', 'N/A')}")
    
    print(Fore.GREEN + "\n[+] Network Information:")
    print(Fore.WHITE + f"  ISP: {info.get('isp', 'N/A')}")
    print(Fore.WHITE + f"  ASN: {info.get('asn', 'N/A')}")
    
    print(Fore.GREEN + "\n[+] Security Information:")
    print(Fore.WHITE + f"  Proxy/VPN: {'Yes' if info.get('proxy') else 'No'}")
    print(Fore.WHITE + f"  Hosting/Datacenter: {'Yes' if info.get('hosting') else 'No'}")
    
    print(Fore.YELLOW + "\n" + "=" * 50 + "\n")

def save_to_file(data, filename=None):
    """Save IP data to a JSON file"""
    if not filename:
        if isinstance(data, list):
            ips = [d.get('ip', 'unknown')[:10] for d in data if d]
            filename = f"ip_info_{'_'.join(ips)}_{datetime.now().strftime('%Y%m%d_%H%M%S')}.json"
        else:
            filename = f"ip_info_{data.get('ip', 'local')}_{datetime.now().strftime('%Y%m%d_%H%M%S')}.json"
    
    try:
        with open(filename, 'w') as f:
            json.dump(data, f, indent=4)
        print(Fore.GREEN + f"Information saved to {filename}")
    except Exception as e:
        print(Fore.RED + f"Error saving file: {str(e)}")

def check_dependencies():
    """Verify all required packages are installed"""
    required = {
        'requests': '2.25.1',
        'colorama': '0.4.4',
        'folium': '0.12.1',
        'pyfiglet': '0.8.post1'
    }
    
    missing = []
    for pkg, ver in required.items():
        try:
            mod = __import__(pkg)
            if hasattr(mod, '__version__') and mod.__version__ < ver:
                missing.append(f"{pkg}>={ver}")
        except ImportError:
            missing.append(f"{pkg}>={ver}")
    
    if missing:
        print(Fore.RED + "Missing dependencies detected!")
        print(Fore.YELLOW + "Please install with: pip install " + " ".join(missing))
        sys.exit(1)

def main():
    """Main entry point for the IP tracer tool"""
    check_dependencies()
    display_banner()
    
    parser = argparse.ArgumentParser(
        description="Advanced IP Tracer Tool",
        formatter_class=argparse.ArgumentDefaultsHelpFormatter
    )
    parser.add_argument('-i', '--ip', help="IP address to trace (default: your public IP)")
    parser.add_argument('-f', '--file', help="File containing list of IPs (one per line)")
    parser.add_argument('-p', '--provider', 
                        choices=['ip-api', 'ipapi', 'ipwhois'], 
                        default='ip-api',
                        help="API provider to use")
    parser.add_argument('-m', '--map', action='store_true', 
                        help="Create a map visualization")
    parser.add_argument('-b', '--bulk', action='store_true', 
                        help="Process IPs in bulk (use with -f/--file)")
    parser.add_argument('-o', '--output', help="Output file name")
    parser.add_argument('-t', '--threads', type=int, default=5,
                        help="Max threads for bulk processing")
    args = parser.parse_args()
    
    tracer = IPTracer()
    tracer.current_provider = args.provider
    
    try:
        if args.file:
            try:
                with open(args.file) as f:
                    ip_list = [line.strip() for line in f if line.strip()]
                
                if not ip_list:
                    print(Fore.RED + "No valid IPs found in the file")
                    return
                
                if args.bulk:
                    print(Fore.CYAN + f"\nProcessing {len(ip_list)} IPs using {args.threads} threads...")
                    results = tracer.bulk_lookup(ip_list, max_workers=args.threads)
                    
                    for ip, data in results.items():
                        print(Fore.YELLOW + f"\nResults for {ip}:")
                        display_ip_info(data)
                    
                    save_to_file(results, args.output)
                    
                    if args.map:
                        valid_data = [data for data in results.values() if data and not data.get('error')]
                        tracer.create_map(valid_data)
                else:
                    for ip in ip_list:
                        data = tracer.get_ip_info(ip)
                        display_ip_info(data)
                        if args.output:
                            save_to_file(data, f"{args.output}_{ip}.json")
                        if args.map:
                            tracer.create_map(data, f"ip_map_{ip}.html")
            except FileNotFoundError:
                print(Fore.RED + f"File not found: {args.file}")
        else:
            ip = args.ip
            data = tracer.get_ip_info(ip)
            display_ip_info(data)
            
            if data:
                save_to_file(data, args.output)
                if args.map:
                    tracer.create_map(data)
    except KeyboardInterrupt:
        print(Fore.RED + "\nOperation cancelled by user")
        sys.exit(1)
    except Exception as e:
        print(Fore.RED + f"\nAn error occurred: {str(e)}")
        sys.exit(1)

if __name__ == "__main__":
    main()
