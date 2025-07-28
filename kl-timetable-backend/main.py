from fastapi import FastAPI, Form
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import StreamingResponse
from bs4 import BeautifulSoup
import requests
from io import BytesIO

app = FastAPI()

# Allow API access from any frontend (e.g., Expo app)
app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],
    allow_methods=["*"],
    allow_headers=["*"],
)

# Global store for temporary session and CSRF
captcha_cache = {}

# ------------------ CAPTCHA ROUTE ------------------
@app.get("/get-captcha")
def get_captcha():
    session = requests.Session()
    base_url = "https://newerp.kluniversity.in"
    login_url = f"{base_url}/index.php?r=site%2Flogin"

    headers = {
        "User-Agent": "Mozilla/5.0"
    }

    # Step 1: Get CSRF token
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

    # Step 3: Extract CAPTCHA URL
    captcha_img_tag = soup_post.find("img", src=lambda x: x and "r=site%2Fcaptcha" in x)
    if not captcha_img_tag:
        return {"success": False, "message": "CAPTCHA not found"}

    captcha_url = base_url + captcha_img_tag["src"].replace("&amp;", "&")
    captcha_response = session.get(captcha_url)

    # Store session + csrf for reuse
    captcha_cache["session"] = session
    captcha_cache["csrf"] = csrf

    # Return CAPTCHA image as HTTP response
    return StreamingResponse(BytesIO(captcha_response.content), media_type="image/jpeg")


# ------------------ LOGIN + FETCH TIMETABLE ------------------
@app.post("/fetch-timetable")
def fetch_timetable(
    username: str = Form(...),
    password: str = Form(...),
    captcha: str = Form(...),
    academic_year_code: str = Form(default="19"),  # 2025–26
    semester_id: str = Form(default="1")  # Odd semester
):
    session = captcha_cache.get("session")
    csrf = captcha_cache.get("csrf")

    if not session or not csrf:
        return {"success": False, "message": "You must call /get-captcha first"}

    base_url = "https://newerp.kluniversity.in"
    login_url = f"{base_url}/index.php?r=site%2Flogin"

    headers = {
        "User-Agent": "Mozilla/5.0"
    }

    # Step 3: Login
    login_payload = {
        "_csrf": csrf,
        "LoginForm[username]": username,
        "LoginForm[password]": password,
        "LoginForm[captcha]": captcha,
    }

    login_response = session.post(login_url, data=login_payload, headers=headers)
    if "Logout" not in login_response.text:
        return {"success": False, "message": "Invalid credentials or captcha"}

    # Step 4: Fetch timetable
    tt_url = f"{base_url}/index.php?r=timetables%2Funiversitymasteracademictimetableview%2Findividualstudenttimetableget&UniversityMasterAcademicTimetableView%5Bacademicyear%5D={academic_year_code}&UniversityMasterAcademicTimetableView%5Bsemesterid%5D={semester_id}"

    tt_response = session.get(tt_url, headers=headers)
    soup_tt = BeautifulSoup(tt_response.text, "html.parser")
    table = soup_tt.find("table")
    if not table:
        return {"success": False, "message": "Timetable not found"}

    # Parse timetable
    thead = table.find("thead")
    headers = [th.text.strip() for th in thead.find_all("th")][1:]  # Skip 'Day'

    tbody = table.find("tbody")
    timetable = {}
    for row in tbody.find_all("tr"):
        cols = row.find_all("td")
        day = cols[0].text.strip()
        slots = [td.text.strip() for td in cols[1:]]
        timetable[day] = dict(zip(headers, slots))

    return {
        "success": True,
        "timetable": timetable
    }
