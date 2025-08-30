from fastapi import FastAPI, HTTPException, Query
from pydantic import BaseModel, Field
from typing import List, Optional
from datetime import datetime, time, timedelta
from dateutil import tz@app.get("/", response_class=HTMLResponse)
def root():
    return Path("index.html").read_text(encoding="utf-8")

app = FastAPI(title="Berber Randevu (Basit)", version="0.0.1")

# --- Bellek içi basit depolar (sunucu yeniden başlarsa sıfırlanır) ---
services = []
barbers = []
working_hours = []
customers = []
appointments = []
idc = {"service":0, "barber":0, "wh":0, "cust":0, "appt":0}

LOCAL_TZ = tz.gettz("Europe/Istanbul")

def next_id(k):
    idc[k] += 1
    return idc[k]

def parse_hhmm(s: str) -> time:
    h, m = [int(x) for x in s.split(":")]
    return time(h, m)

def local_date_bounds(date_str: str):
    y, m, d = [int(x) for x in date_str.split("-")]
    start_local = datetime(y, m, d, 0, 0, 0, tzinfo=LOCAL_TZ)
    end_local = start_local + timedelta(days=1)
    return start_local, end_local

# --- Şemalar ---
class ServiceCreate(BaseModel):
    name: str
    duration_min: int = Field(gt=0)
    price: int = Field(ge=0)

class ServiceOut(BaseModel):
    id: int
    name: str
    duration_min: int
    price: int

class BarberCreate(BaseModel):
    full_name: str
    color_hex: Optional[str] = None

class BarberOut(BaseModel):
    id: int
    full_name: str
    color_hex: str

class WorkingHourCreate(BaseModel):
    barber_id: int
    weekday: int = Field(ge=1, le=7)
    start_time: str
    end_time: str

class WorkingHourOut(BaseModel):
    id: int
    barber_id: int
    weekday: int
    start_time: str
    end_time: str

class CustomerCreate(BaseModel):
    full_name: str
    phone: str

class CustomerOut(BaseModel):
    id: int
    full_name: str
    phone: str

class AppointmentCreate(BaseModel):
    shop_id: int = 1
    barber_id: int
    customer_id: int
    service_id: int
    starts_at: datetime
    duration_override_min: Optional[int] = None

class AppointmentOut(BaseModel):
    id: int
    barber_id: int
    customer_id: int
    service_id: int
    starts_at: datetime
    ends_at: datetime
    status: str

class SlotList(BaseModel):
    slots: List[str]

# --- Endpointler ---
@app.get("/health")
def health():
    return {"status": "ok"}

@app.post("/services", response_model=ServiceOut, status_code=201)
def create_service(p: ServiceCreate):
    s = {"id": next_id("service"), "name": p.name, "duration_min": p.duration_min, "price": p.price}
    services.append(s)
    return s

@app.get("/services", response_model=List[ServiceOut])
def list_services():
    return services

@app.post("/barbers", response_model=BarberOut, status_code=201)
def create_barber(p: BarberCreate):
    b = {"id": next_id("barber"), "full_name": p.full_name, "color_hex": p.color_hex or "#777777"}
    barbers.append(b)
    return b

@app.get("/barbers", response_model=List[BarberOut])
def list_barbers():
    return barbers

@app.post("/working-hours", response_model=WorkingHourOut, status_code=201)
def create_wh(p: WorkingHourCreate):
    wh = {"id": next_id("wh"), "barber_id": p.barber_id, "weekday": p.weekday,
          "start_time": p.start_time, "end_time": p.end_time}
    working_hours.append(wh)
    return wh

@app.get("/working-hours/{barber_id}", response_model=List[WorkingHourOut])
def list_wh(barber_id: int):
    return [w for w in working_hours if w["barber_id"] == barber_id]

@app.post("/customers", response_model=CustomerOut, status_code=201)
def create_customer(p: CustomerCreate):
    c = {"id": next_id("cust"), "full_name": p.full_name, "phone": p.phone}
    customers.append(c)
    return c

@app.get("/barbers/{barber_id}/slots", response_model=SlotList)
def get_slots(barber_id: int, date: str = Query(...), service_id: int = Query(...)):
    svc = next((s for s in services if s["id"] == service_id), None)
    if not svc:
        raise HTTPException(404, "Service not found")
    duration = timedelta(minutes=svc["duration_min"])
    start_day, end_day = local_date_bounds(date)
    weekday = ((start_day.isoweekday() - 1) % 7) + 1
    whs = [w for w in working_hours if w["barber_id"] == barber_id and w["weekday"] == weekday]

    slots = []
    for w in whs:
        st = parse_hhmm(w["start_time"])
        en = parse_hhmm(w["end_time"])
        ws = datetime(start_day.year, start_day.month, start_day.day, st.hour, st.minute, tzinfo=LOCAL_TZ)
        we = datetime(start_day.year, start_day.month, start_day.day, en.hour, en.minute, tzinfo=LOCAL_TZ)
        t = ws
        while t + duration <= we:
            end_t = t + duration
            conflict = any(
                (t < a["ends_at"] and end_t > a["starts_at"])
                for a in appointments
                if a["barber_id"] == barber_id and a["status"] in ("pending", "confirmed", "completed")
            )
            if not conflict:
                slots.append(t.isoformat())
            t += duration
    return {"slots": slots}

@app.post("/appointments", response_model=AppointmentOut, status_code=201)
def create_appt(p: AppointmentCreate):
    svc = next((s for s in services if s["id"] == p.service_id), None)
    if not svc:
        raise HTTPException(400, "Invalid service")
    dur_min = p.duration_override_min or svc["duration_min"]
    ends = p.starts_at + timedelta(minutes=dur_min)

    for a in appointments:
        if a["barber_id"] == p.barber_id and a["status"] in ("pending", "confirmed", "completed"):
            if p.starts_at < a["ends_at"] and ends > a["starts_at"]:
                raise HTTPException(409, "Time slot not available")

    a = {"id": next_id("appt"), "shop_id": p.shop_id, "barber_id": p.barber_id,
         "customer_id": p.customer_id, "service_id": p.service_id,
         "starts_at": p.starts_at, "ends_at": ends, "status": "confirmed"}
    appointments.append(a)
    return a

@app.get("/appointments", response_model=List[AppointmentOut])
def list_appts(date: Optional[str] = None, barber_id: Optional[int] = None):
    out = appointments[:]
    if barber_id:
        out = [a for a in out if a["barber_id"] == barber_id]
    if date:
        s, e = local_date_bounds(date)
        out = [a for a in out if a["starts_at"] >= s and a["starts_at"] < e]
    return sorted(out, key=lambda x: x["starts_at"])
