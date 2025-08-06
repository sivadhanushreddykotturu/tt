from fastapi import FastAPI, Form, HTTPException
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import StreamingResponse
from bs4 import BeautifulSoup
import requests
from io import BytesIO
import uuid
import time

app = FastAPI()
print("✅ FastAPI app starting...")

# Allow CORS
app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],
    allow_methods=["*"],
    allow_headers=["*"],
)

# In-memory CAPTCHA token cache
captcha_cache = {}  # token -> { session, csrf, expires_at }
CAPTCHA_TTL_SECONDS = 180  # 3 minutes

@app.get("/")
def health():
    return {"message": "Backend running ✅"}

@app.get("/get-captcha")
def get_captcha():
    session = requests.Session()
    base_url = "https://newerp.kluniversity.in"
    login_url = f"{base_url}/index.php?r=site%2Flogin"
    headers = {"User-Agent": "Mozilla/5.0"}

    # Step 1: Get CSRF
    res = session.get(login_url, headers=headers)
    soup = BeautifulSoup(res.text, "html.parser")
    csrf = soup.find("meta", {"name": "csrf-token"})["content"]

    # Step 2: Trigger CAPTCHA
    dummy_data = {
        "_csrf": csrf,
        "LoginForm[username]": "",
        "LoginForm[password]": ""
    }
    res_post = session.post(login_url, data=dummy_data, headers=headers)
    soup_post = BeautifulSoup(res_post.text, "html.parser")
    captcha_img_tag = soup_post.find("img", src=lambda x: x and "r=site%2Fcaptcha" in x)
    if not captcha_img_tag:
        raise HTTPException(status_code=500, detail="CAPTCHA not found")

    captcha_url = base_url + captcha_img_tag["src"].replace("&amp;", "&")
    captcha_response = session.get(captcha_url)

    # Step 3: Generate token and cache session info
    token = str(uuid.uuid4())
    captcha_cache[token] = {
        "session": session,
        "csrf": csrf,
        "expires_at": time.time() + CAPTCHA_TTL_SECONDS
    }

    # Send token in header and image in body
    headers = {"X-Captcha-Token": token}
    return StreamingResponse(BytesIO(captcha_response.content), media_type="image/jpeg", headers=headers)

@app.post("/fetch-timetable")
def fetch_timetable(
    username: str = Form(...),
    password: str = Form(...),
    captcha: str = Form(...),
    captcha_token: str = Form(...),
    academic_year_code: str = Form(...),
    semester_id: str = Form(...)
):
    if captcha_token not in captcha_cache:
        return {"success": False, "message": "CAPTCHA expired or invalid. Please try again."}

    cached = captcha_cache.pop(captcha_token)  # Remove after one use
    if cached["expires_at"] < time.time():
        return {"success": False, "message": "CAPTCHA expired. Please refresh."}

    session = cached["session"]
    csrf = cached["csrf"]

    base_url = "https://newerp.kluniversity.in"
    login_url = f"{base_url}/index.php?r=site%2Flogin"
    headers = {"User-Agent": "Mozilla/5.0"}

    login_payload = {
        "_csrf": csrf,
        "LoginForm[username]": username,
        "LoginForm[password]": password,
        "LoginForm[captcha]": captcha
    }

    login_response = session.post(login_url, data=login_payload, headers=headers)
    if "Logout" not in login_response.text:
        return {"success": False, "message": "Invalid credentials or CAPTCHA."}

    tt_url = f"{base_url}/index.php?r=timetables%2Funiversitymasteracademictimetableview%2Findividualstudenttimetableget&UniversityMasterAcademicTimetableView%5Bacademicyear%5D={academic_year_code}&UniversityMasterAcademicTimetableView%5Bsemesterid%5D={semester_id}"
    tt_response = session.get(tt_url, headers=headers)
    soup_tt = BeautifulSoup(tt_response.text, "html.parser")
    table = soup_tt.find("table")
    if not table:
        return {"success": False, "message": "Timetable not found."}

    thead = table.find("thead")
    headers = [th.text.strip() for th in thead.find_all("th")][1:]
    tbody = table.find("tbody")
    timetable = {}
    for row in tbody.find_all("tr"):
        cols = row.find_all("td")
        day = cols[0].text.strip()
        slots = [td.text.strip() for td in cols[1:]]
        timetable[day] = dict(zip(headers, slots))

    return {"success": True, "timetable": timetable}
