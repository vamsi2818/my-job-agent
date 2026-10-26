import json
import os
import sys
import requests
import smtplib
from email.mime.text import MIMEText
from email.mime.multipart import MIMEMultipart
from google import genai

# Configuration and Secrets via Environment Variables
SERPAPI_KEY = os.environ.get('SERPAPI_API_KEY')
GEMINI_KEY = os.environ.get('GOOGLE_API_KEY')

# Retrieve SMTP configurations from Environment Variables
SMTP_SERVER = os.environ.get('SMTP_SERVER', 'smtp.gmail.com')
SMTP_PORT = int(os.environ.get('SMTP_PORT', '587'))
SENDER_EMAIL = os.environ.get('SENDER_EMAIL')
SENDER_PASSWORD = os.environ.get('SENDER_PASSWORD')
RECIPIENT_EMAIL = os.environ.get('RECIPIENT_EMAIL', SENDER_EMAIL)

if not SERPAPI_KEY or not GEMINI_KEY:
    print("Error: Both SERPAPI_API_KEY and GOOGLE_API_KEY must be set in your environment variables.")
    sys.exit(1)

# Initialize Gemini client
client = genai.Client(api_key=GEMINI_KEY)

TRACKER_FILE = 'processed_jobs.json'

# Helper to load previously processed job IDs
def load_processed_jobs():
    if os.path.exists(TRACKER_FILE):
        with open(TRACKER_FILE, 'r') as f:
            try:
                return set(json.load(f))
            except json.JSONDecodeError:
                return set()
    return set()

# Helper to save processed job IDs
def save_processed_jobs(processed_ids):
    with open(TRACKER_FILE, 'w') as f:
        json.dump(list(processed_ids), f, indent=2)

# Step 1: Query SerpApi for Google Jobs
def fetch_jobs(query, location="India"):
    url = "https://serpapi.com/search.json"
    params = {
        "engine": "google_jobs",
        "q": query,
        "location": location,
        "hl": "en",
        "gl": "in",
        "api_key": SERPAPI_KEY
    }

    try:
        response = requests.get(url, params=params)
        response.raise_for_status()
        data = response.json()
        return data.get("jobs_results", [])
    except Exception as e:
        print(f"Error querying SerpApi for query '{query}': {e}")
        return []

# Step 2: Score Job listing using Gemini API
def score_job(job):
    system_prompt = """You are an expert IT recruiter specializing in Modern Workplace and Endpoint Management roles in India.
Evaluate the following Job Posting against the Candidate Profile provided below.

Candidate Profile:
- Experience: ~2 years in IT endpoint operations (SCCM and Intune administration).
- Key Skills: MDM/MAM, Autopilot, co-management, OSD, Conditional Access, Defender for Endpoint, BitLocker, patching.
- Target Roles: Intune Administrator, SCCM Administrator, Endpoint Engineer, Modern Workplace Engineer.
- Desired Locations: Bengaluru, Hyderabad, Chennai, or Remote in India.

Evaluation Rules:
1. Give a score from 1 to 10 based on candidate matching.
   - 9-10: Perfect match (requires SCCM/Intune, ~2 years exp, matching target roles and location).
   - 7-8: Great match (has some skill gaps or requires 3 years exp, but highly relevant technology overlap).
   - 5-6: Fair match (contains desktop support, but less focus on engineering/administration).
   - 1-4: Poor match (wrong location, senior architect roles requiring 8+ years, or unrelated IT fields).
2. Provide a single-sentence justification explaining the reasoning behind the score.
3. Your output MUST be strictly formatted as valid JSON with two keys: "score" (integer) and "reason" (string).
"""

    prompt = f"""Job Posting:
Title: {job.get('title')}
Company: {job.get('company_name')}
Location: {job.get('location')}
Description:
{job.get('description', '')}"""

    try:
        response = client.models.generate_content(
            model='gemini-1.5-flash',
            contents=prompt,
            config={                'system_instruction': system_prompt,
                'response_mime_type': 'application/json'
            }
        )
        result = json.loads(response.text.strip())
        return result
    except Exception as e:
        return {"score": 1, "reason": f"Failed to score due to API error: {e}"}

# Step 3: Dispatch email notification using SMTP
def send_email_digest(high_score_jobs):
    if not SENDER_EMAIL or not SENDER_PASSWORD:
        print("⚠️ SMTP Credentials (SENDER_EMAIL, SENDER_PASSWORD) are not configured. Skipping email send.")
        return

    if not high_score_jobs:
        print("ℹ️ No matches above threshold. No digest email will be sent today.")
        return

    msg = MIMEMultipart('alternative')
    msg['Subject'] = f"🎯 Job Agent Report: {len(high_score_jobs)} New Matches Found!"
    msg['From'] = f"Job Search Agent <{SENDER_EMAIL}>"
    msg['To'] = RECIPIENT_EMAIL

    html_content = """
    <html>
      <body style="font-family: Arial, sans-serif; color: #333; line-height: 1.6;">
        <h2 style="color: #1a73e8; border-bottom: 2px solid #1a73e8; padding-bottom: 10px;">
          🎯 Job Search Agent Matches
        </h2>
        <p>We found the following matching jobs for your SCCM & Intune profile (~2 years exp):</p>
    """

    for match in high_score_jobs:
        html_content += f"""
        <div style="margin-bottom: 20px; padding: 15px; border-left: 5px solid #34a853; background-color: #f8f9fa;">
          <h3 style="margin: 0 0 5px 0;">
            <span style="background-color: #e6f4ea; color: #137333; padding: 2px 8px; border-radius: 4px; font-size: 0.9em;">
              {match['score']}/10
            </span>
            {match['title']}
          </h3>
          <p style="margin: 5px 0; font-weight: bold; color: #5f6368;">{match['company']} &bull; {match['location']}</p>
          <p style="margin: 10px 0; font-style: italic; color: #3c4043;"><strong>Reasoning:</strong> {match['reason']}</p>
          <a href="{match['link']}" target="_blank" style="display: inline-block; padding: 8px 16px; background-color: #1a73e8; color: white; text-decoration: none; border-radius: 4px; font-weight: bold; margin-top: 5px;">
            Apply Now
          </a>
        </div>
        """

    html_content += """
        <br>
        <p style="font-size: 0.8em; color: #70757a; border-top: 1px solid #dadce0; padding-top: 10px;">
          This matches report was automatically built and triggered by your Job Search Agent.
        </p>
      </body>
    </html>
    """
    msg.attach(MIMEText(html_content, 'html'))

    try:
        print(f"📧 Logging into SMTP server {SMTP_SERVER}:{SMTP_PORT}...")
        server = smtplib.SMTP(SMTP_SERVER, SMTP_PORT)
        server.starttls()
        server.login(SENDER_EMAIL, SENDER_PASSWORD)
        server.sendmail(SENDER_EMAIL, RECIPIENT_EMAIL, msg.as_string())
        server.quit()
        print("✅ Success! Digest email dispatched to your inbox.")
    except Exception as e:
        print(f"❌ Failed to send SMTP email: {e}")

# Orchestrator Flow
def run_job_agent():
    processed_ids = load_processed_jobs()
    queries = ["Intune Administrator", "SCCM Engineer"]
    raw_jobs = []

    print("Fetching new jobs...")
    for query in queries:
        results = fetch_jobs(query)
        raw_jobs.extend(results)

    unique_jobs = {job['job_id']: job for job in raw_jobs if 'job_id' in job}

    new_jobs_found = []
    for job_id, job in unique_jobs.items():
        if job_id not in processed_ids:
            new_jobs_found.append(job)

    print(f"Found {len(new_jobs_found)} new jobs to evaluate.")

    scored_jobs = []
    for job in new_jobs_found:
        evaluation = score_job(job)
        job_score = evaluation.get("score", 1)
        job_reason = evaluation.get("reason", "No reasoning returned.")

        scored_jobs.append({
            "title": job.get('title'),
            "company": job.get('company_name'),
            "location": job.get('location'),
            "link": job.get('related_links', [{}])[0].get('link', 'No link available'),
            "score": job_score,
            "reason": job_reason
        })
        processed_ids.add(job['job_id'])

    save_processed_jobs(processed_ids)

    # Filter and Display Top Matching Jobs (Score >= 7)
    high_score_jobs = [j for j in scored_jobs if j['score'] >= 7]
    high_score_jobs.sort(key=lambda x: x['score'], reverse=True)

    print(f"\n--- Job Digest ({len(high_score_jobs)} matches above threshold) ---")
    for match in high_score_jobs:
        print(f"\n[{match['score']}/10] {match['title']} - {match['company']} ({match['location']})")
        print(f"Reason: {match['reason']}")
        print(f"Apply: {match['link']}")

    # Trigger Email Alerts
    send_email_digest(high_score_jobs)

if __name__ == '__main__':
    run_job_agent()
