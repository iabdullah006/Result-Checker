from flask import Flask, request, jsonify, render_template
from flask_cors import CORS
import requests
from bs4 import BeautifulSoup
import time
import threading
import uuid
from datetime import datetime
import random

app = Flask(__name__)
app.secret_key = 'your-secret-key-here'
CORS(app)

active_jobs = {}

class SmartResultChecker:
    def __init__(self, roll, cls, year, job_id):
        self.roll = roll
        self.cls = cls
        self.year = year
        self.job_id = job_id
        self.status = "waiting_for_result"  # waiting_for_result, checking, completed
        self.attempts = 0
        self.result = None
        self.error = None
        self.start_time = datetime.now()
        self.is_running = True
        self.year_available = False
        
    def is_result_available_for_year(self):
        """Check if result for this year is uploaded on website"""
        try:
            url = "https://bisesahiwal.edu.pk/allresult/"
            response = requests.get(url, timeout=10)
            soup = BeautifulSoup(response.text, "html.parser")
            
            # Check if year exists in dropdown
            year_select = soup.find("select", {"name": "year"})
            if year_select:
                for option in year_select.find_all("option"):
                    option_text = option.get_text(strip=True)
                    if self.year in option_text:
                        print(f"[{self.job_id}] ✅ Year {self.year} is NOW AVAILABLE on website!")
                        return True
            
            # Also check page text for year
            if self.year in response.text:
                print(f"[{self.job_id}] ✅ Year {self.year} found in page content!")
                return True
                
            print(f"[{self.job_id}] ⏳ Year {self.year} not available yet. Waiting...")
            return False
            
        except Exception as e:
            print(f"[{self.job_id}] Error checking year availability: {e}")
            return False
    
    def check_single_time(self):
        """Single attempt to fetch result"""
        try:
            url = "https://bisesahiwal.edu.pk/allresult/"
            session = requests.Session()
            
            res = session.get(url, timeout=10)
            soup = BeautifulSoup(res.text, "html.parser")
            token_input = soup.find("input", {"name": "csrf_token"})
            
            if not token_input:
                return None
                
            token = token_input["value"]
            
            data = {
                "class": "1" if self.cls == "9th" else "2",
                "year": self.year,
                "sess": "1",
                "rno": self.roll,
                "csrf_token": token,
                "commit": "GET RESULT"
            }
            
            headers = {"User-Agent": "Mozilla/5.0", "Referer": url}
            res2 = session.post(url + "route.php", data=data, headers=headers, timeout=10)
            
            if res2.status_code != 200:
                return None
                
            soup2 = BeautifulSoup(res2.text, "html.parser")
            
            results = []
            total_marks = None
            
            for row in soup2.find_all("tr"):
                cols = [c.get_text(strip=True) for c in row.find_all("td")]
                
                if len(cols) < 4:
                    continue
                    
                subject = cols[1].upper()
                
                if self.cls == "9th":
                    marks = int(cols[3]) if cols[3].isdigit() else 0
                    if marks > 0:
                        results.append({
                            "subject": subject,
                            "marks": marks
                        })
                else:
                    marks9 = int(cols[3]) if len(cols) > 3 and cols[3].isdigit() else 0
                    marks10 = int(cols[4]) if len(cols) > 4 and cols[4].isdigit() else 0
                    practical = int(cols[5]) if len(cols) > 5 and cols[5].isdigit() else 0
                    
                    total = marks9 + marks10 + practical
                    if total > 0:
                        results.append({
                            "subject": subject,
                            "total": total,
                            "class9": marks9,
                            "class10": marks10,
                            "practical": practical
                        })
                
                if "TOTAL" in cols[0].upper():
                    total_marks = cols[-1]
            
            if results:
                return {
                    "success": True,
                    "results": results,
                    "total": total_marks,
                    "attempts": self.attempts + 1
                }
            else:
                return None
                
        except Exception as e:
            print(f"Attempt {self.attempts + 1} failed: {str(e)}")
            return None
    
    def start_smart_checking(self):
        """Smart checking: First wait for result availability, then fast check"""
        
        # PHASE 1: Wait for result to be uploaded
        print(f"[{self.job_id}] 📡 Waiting for {self.year} result to be uploaded...")
        
        while self.is_running and self.status == "waiting_for_result":
            if self.is_result_available_for_year():
                self.status = "checking"
                print(f"[{self.job_id}] 🚀 Result available! Starting fast checking...")
                break
            else:
                # Wait 30 seconds before checking again for year availability
                time.sleep(30)
        
        # PHASE 2: Fast checking (every 1-2 seconds) once result is available
        while self.is_running and self.status == "checking":
            self.attempts += 1
            
            print(f"[{self.job_id}] 🔍 Fast Attempt #{self.attempts} for Roll {self.roll}")
            
            result = self.check_single_time()
            
            if result:
                self.result = result
                self.status = "completed"
                print(f"[{self.job_id}] 🎉 RESULT FOUND after {self.attempts} fast attempts!")
                break
            else:
                # Ultra fast: 1-2 seconds delay for checking
                delay = random.randint(1, 2)  # 🔥 1-2 seconds only!
                time.sleep(delay)
        
        if self.status == "checking":
            self.status = "stopped"

@app.route('/')
def home():
    return render_template("index.html")

@app.route('/start-auto-check', methods=['POST'])
def start_auto_check():
    try:
        data = request.get_json()
        roll = data.get('roll')
        cls = data.get('class')
        year = data.get('year')
        
        if not roll or not roll.isdigit() or len(roll) != 6:
            return jsonify({"error": "Invalid roll number (6 digits required)"}), 400
        
        # Check if already checking
        for job_id, job in active_jobs.items():
            if job.roll == roll and job.year == year and job.status in ["waiting_for_result", "checking"]:
                return jsonify({
                    "job_id": job_id,
                    "message": f"Already checking for Roll #{roll}",
                    "status": "already_running"
                })
        
        job_id = str(uuid.uuid4())[:8]
        checker = SmartResultChecker(roll, cls, year, job_id)
        active_jobs[job_id] = checker
        
        thread = threading.Thread(target=checker.start_smart_checking)
        thread.daemon = True
        thread.start()
        
        return jsonify({
            "job_id": job_id,
            "message": f"Smart checker started for Roll #{roll}. Will wait for {year} result, then check every 1-2 seconds!",
            "status": "started"
        })
        
    except Exception as e:
        return jsonify({"error": str(e)}), 500

@app.route('/check-status/<job_id>', methods=['GET'])
def check_status(job_id):
    if job_id not in active_jobs:
        return jsonify({"error": "Job not found"}), 404
    
    job = active_jobs[job_id]
    
    elapsed = (datetime.now() - job.start_time).total_seconds()
    minutes = int(elapsed // 60)
    seconds = int(elapsed % 60)
    
    rpm = (job.attempts / (elapsed / 60)) if elapsed > 0 and job.status == "checking" else 0
    
    status_message = ""
    if job.status == "waiting_for_result":
        status_message = f"⏳ Waiting for {job.year} result to be uploaded on BISE website..."
    elif job.status == "checking":
        status_message = f"⚡ FAST CHECKING every 1-2 seconds! - {job.attempts} attempts so far"
    elif job.status == "completed":
        status_message = "✅ Result found!"
    
    return jsonify({
        "status": job.status,
        "attempts": job.attempts,
        "result": job.result,
        "roll": job.roll,
        "year": job.year,
        "cls": job.cls,
        "elapsed_time": f"{minutes}m {seconds}s",
        "requests_per_minute": round(rpm, 1) if job.status == "checking" else 0,
        "message": status_message,
        "phase": "waiting" if job.status == "waiting_for_result" else "fast_checking" if job.status == "checking" else "done"
    })

@app.route('/stop-check/<job_id>', methods=['POST'])
def stop_check(job_id):
    if job_id in active_jobs:
        active_jobs[job_id].is_running = False
        active_jobs[job_id].status = "stopped"
        return jsonify({"message": "Auto-check stopped"})
    return jsonify({"error": "Job not found"}), 404

@app.route('/check-year-availability', methods=['GET'])
def check_year_availability():
    """Check if 2026 result is available"""
    year = request.args.get('year', '2026')
    try:
        url = "https://bisesahiwal.edu.pk/allresult/"
        response = requests.get(url, timeout=10)
        
        if year in response.text:
            return jsonify({"available": True, "year": year, "message": f"{year} result is available!"})
        else:
            return jsonify({"available": False, "year": year, "message": f"{year} result not uploaded yet"})
    except:
        return jsonify({"available": False, "year": year, "message": "Cannot check availability"})

if __name__ == '__main__':
    app.run(debug=True, host='127.0.0.1', port=5000)
