import requests
from bs4 import BeautifulSoup
import json
import re

def scrape_paylocity(url):
    """Scrape job listings from Paylocity by extracting embedded JSON."""
    headers = {
        'User-Agent': 'Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/91.0.4472.124 Safari/537.36'
    }
    response = requests.get(url, headers=headers)
    if response.status_code != 200:
        print(f"Failed to fetch Paylocity: {response.status_code}")
        return []
    
    soup = BeautifulSoup(response.content, 'html.parser')
    scripts = soup.find_all('script')
    
    page_data = None
    for script in scripts:
        if script.string and 'window.pageData' in script.string:
            # Extract the JSON part after 'window.pageData = ' and before ';'
            content = script.string
            start_idx = content.find('window.pageData = ') + len('window.pageData = ')
            end_idx = content.find(';', start_idx)
            json_str = content[start_idx:end_idx].strip()
            # Clean up any trailing commas or issues
            json_str = re.sub(r',\s*}', '}', json_str)
            json_str = re.sub(r',\s*]', ']', json_str)
            try:
                page_data = json.loads(json_str)
                break
            except json.JSONDecodeError as e:
                print(f"JSON parse error: {e}")
                continue
    
    if not page_data:
        print("No pageData found in scripts.")
        return []
    
    jobs = page_data.get('Jobs', [])
    formatted_jobs = []
    for job in jobs:
        title = job.get('JobTitle', 'N/A')
        location_name = job.get('LocationName', 'N/A')
        published = job.get('PublishedDate', 'N/A')
        job_loc = job.get('JobLocation', {})
        address = job_loc.get('Address', 'N/A')
        city = job_loc.get('City', '')
        state = job_loc.get('State', '')
        zip_code = job_loc.get('Zip', '')
        full_location = f"{address}, {city}, {state} {zip_code}".strip(', ')
        
        formatted_jobs.append({
            'title': title,
            'location': location_name,
            'full_address': full_location,
            'published': published,
            'site': 'Pet Pros (Paylocity)'
        })
    
    return formatted_jobs

def scrape_ultipro(base_url):
    """Scrape job listings from UKG Ultipro via POST to LoadSearchResults API."""
    api_url = f"{base_url}/JobBoardView/LoadSearchResults"
    headers = {
        'User-Agent': 'Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/91.0.4472.124 Safari/537.36',
        'Content-Type': 'application/json',
        'Accept': 'application/json, text/javascript, */*; q=0.01',
        'X-Requested-With': 'XMLHttpRequest',
        'Referer': f"{base_url}/?q=&o=postedDateDesc"
    }
    
    # POST body for empty search, ordered by postedDateDesc, fetch all (high Top)
    post_data = {
        "opportunitySearch": {
            "Top": 1000,  # High number to get all
            "Skip": 0,
            "QueryString": "",
            "OrderBy": [
                {
                    "Value": "postedDateDesc",
                    "PropertyName": "PostedDate",
                    "Ascending": False
                }
            ],
            "Filters": [
                {"t": "TermsSearchFilterDto", "fieldName": 4, "extra": None, "values": []},
                {"t": "TermsSearchFilterDto", "fieldName": 5, "extra": None, "values": []},
                {"t": "TermsSearchFilterDto", "fieldName": 6, "extra": None, "values": []}
            ]
        },
        "matchCriteria": {
            "PreferredJobs": [],
            "Educations": [],
            "LicenseAndCertifications": [],
            "Skills": [],
            "hasNoLicenses": False,
            "SkippedSkills": []
        }
    }
    
    response = requests.post(api_url, headers=headers, json=post_data)
    if response.status_code != 200:
        print(f"Failed to fetch Ultipro API: {response.status_code}")
        print(f"Response: {response.text[:500]}")
        return []
    
    try:
        data = response.json()
        opportunities = data.get('Opportunities', [])
        formatted_jobs = []
        for opp in opportunities:
            title = opp.get('Title', 'N/A')
            locations = opp.get('Locations', [])
            location = locations[0].get('LocalizedName', 'N/A') if locations else 'N/A'
            posted = opp.get('PostedDateString', 'N/A')
            category = opp.get('JobCategoryName', 'N/A')
            schedule = opp.get('FullTimeText', 'N/A')
            desc = opp.get('BriefDescription', 'N/A')
            
            formatted_jobs.append({
                'title': title,
                'location': location,
                'posted': posted,
                'category': category,
                'schedule': schedule,
                'description': desc[:200] + '...' if len(desc) > 200 else desc,
                'site': 'Mud Bay (Ultipro)'
            })
        return formatted_jobs
    except json.JSONDecodeError as e:
        print(f"Failed to parse Ultipro response as JSON: {e}")
        print(f"Response text: {response.text[:1000]}")
        return []

def display_jobs(jobs, site_name):
    """Display jobs cleanly in console."""
    if not jobs:
        print(f"No jobs found at {site_name}.")
        return
    
    print(f"\nFound {len(jobs)} open jobs at {site_name}:\n")
    print("-" * 80)
    for job in jobs:
        print(f"Title: {job['title']}")
        print(f"Location: {job['location']}")
        if 'full_address' in job:
            print(f"Full Address: {job['full_address']}")
        print(f"Published: {job['published']}")
        if 'category' in job:
            print(f"Category: {job['category']}")
        if 'schedule' in job:
            print(f"Schedule: {job['schedule']}")
        if 'description' in job:
            print(f"Description: {job['description']}")
        print("-" * 80)

def main():
    paylocity_url = 'https://recruiting.paylocity.com/Recruiting/Jobs/All/768a9b7d-a635-4e27-9c86-174b2ea197a8/Pet-Pros'
    ultipro_base_url = 'https://recruiting2.ultipro.com/MUD1000MUD/JobBoard/40dc9c2a-06f4-4c0d-9b95-c9e2ff5fea47'
    
    print("Scraping Pet Pros (Paylocity)...")
    paylocity_jobs = scrape_paylocity(paylocity_url)
    display_jobs(paylocity_jobs, 'Pet Pros')
    
    print("\nScraping Mud Bay (Ultipro)...")
    ultipro_jobs = scrape_ultipro(ultipro_base_url)
    display_jobs(ultipro_jobs, 'Mud Bay')

if __name__ == "__main__":
    main()