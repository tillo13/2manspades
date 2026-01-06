import requests
from bs4 import BeautifulSoup
import re

def scrape_mudbay_jobs():
    url = "https://www.indeed.com/cmp/Mud-Bay/jobs"
    headers = {
        "User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/91.0.4472.124 Safari/537.36"
    }
    
    try:
        response = requests.get(url, headers=headers)
        response.raise_for_status()
        soup = BeautifulSoup(response.text, 'html.parser')
        
        jobs = []
        job_cards = soup.find_all('div', class_='jobsearch-JobCard')
        
        for card in job_cards:
            title = card.find('h2', class_='jobsearch-JobInfoHeader-title').text.strip() if card.find('h2', class_='jobsearch-JobInfoHeader-title') else "N/A"
            location = card.find('div', class_='jobsearch-JobMetadataHeader-location').text.strip() if card.find('div', class_='jobsearch-JobMetadataHeader-location') else "N/A"
            salary = card.find('div', class_='jobsearch-JobMetadataHeader-salary').text.strip() if card.find('div', class_='jobsearch-JobMetadataHeader-salary') else "N/A"
            job_type = card.find('div', class_='jobsearch-JobMetadataHeader-jobType').text.strip() if card.find('div', class_='jobsearch-JobMetadataHeader-jobType') else "N/A"
            
            jobs.append({
                'title': title,
                'location': location,
                'salary': salary,
                'job_type': job_type
            })
        
        return jobs
    
    except requests.RequestException as e:
        print(f"Error fetching page: {e}")
        return []

def main():
    jobs = scrape_mudbay_jobs()
    if jobs:
        for job in jobs:
            print(f"Title: {job['title']}")
            print(f"Location: {job['location']}")
            print(f"Salary: {job['salary']}")
            print(f"Job Type: {job['job_type']}")
            print("-" * 40)
    else:
        print("No jobs found or an error occurred.")

if __name__ == "__main__":
    main()