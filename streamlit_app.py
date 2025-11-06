#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
Kalendarz Gross Team (Streamlit)
- widok tygodniowy (Pn–Pt)
- logo w panelu bocznym (nad "Administrator")
- nawigacja tygodnia: ◀ | Tydzień bieżący | ▶
- ramki wokół zadań
- zarządzanie pracownikami (CRUD)
- wyszukiwanie zadań (fraza, daty, pracownik)
- eksport PDF (polskie znaki + logo)
- zmiana hasła admina (persist w admin_pass.txt)
"""

import os
from datetime import date, timedelta
from typing import List
from io import BytesIO

import streamlit as st
from sqlalchemy import (
    Column, Date, ForeignKey, Integer, String, Text,
    create_engine, text as sql_text, or_
)
from sqlalchemy.orm import declarative_base, relationship, sessionmaker, scoped_session

# PDF
from reportlab.lib.pagesizes import A4
from reportlab.lib.styles import getSampleStyleSheet
from reportlab.platypus import SimpleDocTemplate, Paragraph, Spacer, Image as RLImage
from reportlab.lib.units import cm
from reportlab.pdfbase import pdfmetrics
from reportlab.pdfbase.ttfonts import TTFont

# =============================
# KONFIGURACJA
# =============================
DB_URL = os.environ.get("DATABASE_URL", "sqlite:///kalendarz_gross_team.db")
PASS_FILE = "admin_pass.txt"
DEFAULT_PASSWORD = "admin123"
BASE_DIR = os.path.dirname(__file__)
LOGO_PATH = os.path.join(BASE_DIR, "logo_gross.jpg")
FONT_PATH = os.path.join(BASE_DIR, "DejaVuSans.ttf")

def load_admin_password():
    if os.path.exists(PASS_FILE):
        with open(PASS_FILE, "r", encoding="utf-8") as f:
            return f.read().strip() or DEFAULT_PASSWORD
    return DEFAULT_PASSWORD

def save_admin_password(new_pass: str):
    with open(PASS_FILE, "w", encoding="utf-8") as f:
        f.write(new_pass.strip())

ADMIN_PASSWORD = load_admin_password()

# =============================
# BAZA DANYCH
# =============================
engine = create_engine(
    DB_URL,
    connect_args={"check_same_thread": False} if DB_URL.startswith("sqlite") else {},
    future=True,
)
SessionLocal = scoped_session(sessionmaker(bind=engine, autoflush=False, autocommit=False))
Base = declarative_base()

class Employee(Base):
    __tablename__ = "employees"
    id = Column(Integer, primary_key=True)
    first_name = Column(String(80), nullable=False)
    last_name = Column(String(80), nullable=False)
    phone = Column(String(40))
    assignments = relationship("TaskAssignment", back_populates="employee", cascade="all, delete-orphan")

class Task(Base):
    __tablename__ = "tasks"
    id = Column(Integer, primary_key=True)
    work_date = Column(Date, nullable=False)
    title = Column(String(200), nullable=False)
    notes = Column(Text)
    team = Column(String(100))
    assignments = relationship("TaskAssignment", back_populates="task", cascade="all, delete-orphan")

class TaskAssignment(Base):
    __tablename__ = "task_assignments"
    id = Column(Integer, primary_key=True)
    task_id = Column(Integer, ForeignKey("tasks.id"), nullable=False)
    employee_id = Column(Integer, ForeignKey("employees.id"), nullable=False)
    task = relationship("Task", back_populates="assignments")
    employee = relationship("Employee", back_populates="assignments")

def ensure_schema():
    Base.metadata.create_all(engine)
    if DB_URL.startswith("sqlite"):
        with engine.connect() as conn:
            cols = conn.execute(sql_text("PRAGMA table_info(tasks)")).mappings().all()
            if "team" not in {c["name"] for c in cols}:
                conn.execute(sql_text("ALTER TABLE tasks ADD COLUMN team VARCHAR(100)"))
                conn.commit()
ensure_schema()

# =============================
# FUNKCJE POMOCNICZE
# =============================
WEEKDAYS_PL = ["poniedziałek", "wtorek", "środa", "czwartek", "piątek", "sobota", "niedziela"]

def weekday_pl(d: date):
    return WEEKDAYS_PL[d.weekday()]

def next_team_label_for_day(db, d):
    tasks = db.query(Task).filter(Task.work_date == d).all()
    used = {int(t.team.split(" ")[1]) for t in tasks if t.team and t.team.startswith("Zespół ")}
    n = 1
    while n in used:
        n += 1
    return f"Zespół {n}"

def employees_select_options(db):
    return [(f"{e.first_name} {e.last_name}", e.id) for e in db.query(Employee).order_by(Employee.last_name, Employee.first_name)]

def guard_admin():
    if not st.session_state.get("is_admin"):
        st.warning("🔐 Wymagane zalogowanie jako administrator.")
        return False
    return True

# =============================
# GENEROWANIE PDF
# =============================
def generate_pdf(db, week_days):
    buf = BytesIO()
    font_name = "DejaVuSans" if os.path.exists(FONT_PATH) else "Helvetica"
    if os.path.exists(FONT_PATH):
        pdfmetrics.registerFont(TTFont("DejaVuSans", FONT_PATH))
    doc = SimpleDocTemplate(buf, pagesize=A4, rightMargin=1.5*cm, leftMargin=1.5*cm)
    styles = getSampleStyleSheet()
    for s in styles.byName:
        styles[s].fontName = font_name
    story = []
    if os.path.exists(LOGO_PATH):
        story += [RLImage(LOGO_PATH, width=5*cm, height=2.5*cm), Spacer(1, 6)]
    story += [Paragraph("<b>Kalendarz Gross Team – Plan tygodnia</b>", styles["Title"]), Spacer(1, 12)]
    for d in week_days:
        story.append(Paragraph(f"<b>{d.strftime('%d.%m.%Y')} ({weekday_pl(d)})</b>", styles["Heading2"]))
        tasks = db.query(Task).filter(Task.work_date == d).order_by(Task.id.desc()).all()
        if not tasks:
            story.append(Paragraph("<i>Brak zadań</i>", styles["Normal"]))
        for t in tasks:
            assigned = ", ".join(f"{a.employee.first_name} {a.employee.last_name}" for a in t.assignments) or "brak pracowników"
            story.append(Paragraph(f"<b>{t.title}</b><br/>({t.team} – {assigned})", styles["Normal"]))
            if t.notes:
                story.append(Paragraph(f"Zakres: {t.notes}", styles["Italic"]))
            story.append(Spacer(1, 8))
        story.append(Spacer(1, 12))
    doc.build(story)
    buf.seek(0)
    return buf

# =============================
# UI
# =============================
st.set_page_config(page_title="Kalendarz Gross Team", layout="wide")

with st.sidebar:
    if os.path.exists(LOGO_PATH):
        st.image(LOGO_PATH, width="stretch")
    st.header("🔐 Administrator")

    if "is_admin" not in st.session_state:
        st.session_state.is_admin = False
    if "week_offset" not in st.session_state:
        st.session_state.week_offset = 0

    if not st.session_state.is_admin:
        passwd = st.text_input("Hasło administratora", type="password")
        if st.button("Zaloguj"):
            if passwd == ADMIN_PASSWORD:
                st.session_state.is_admin = True
                st.success("Zalogowano jako administrator.")
            else:
                st.error("Błędne hasło.")
    else:
        st.success("Zalogowano jako admin.")
        if st.button("Wyloguj"):
            st.session_state.is_admin = False
            st.info("Wylogowano.")

    st.markdown("---")
    section = st.radio("📋 Sekcja", ["Plan tygodnia", "Pracownicy", "Wyszukiwanie", "Ustawienia"])

st.markdown("<h1 style='margin-top:0;'>📅 Kalendarz Gross Team</h1>", unsafe_allow_html=True)

db = SessionLocal()

# =============================
# PLAN TYGODNIA
# =============================
if section == "Plan tygodnia":
    today = date.today() + timedelta(weeks=st.session_state.week_offset)
    monday = today - timedelta(days=today.weekday())
    week_days = [monday + timedelta(days=i) for i in range(5)]

    col1, col2, col3 = st.columns(3)
    if col1.button("◀ Poprzedni tydzień"):
        st.session_state.week_offset -= 1
        st.rerun()
    if col2.button("Tydzień bieżący"):
        st.session_state.week_offset = 0
        st.rerun()
    if col3.button("▶ Następny tydzień"):
        st.session_state.week_offset += 1
        st.rerun()

    st.markdown(f"### 📅 {monday.strftime('%d.%m')} – {(monday+timedelta(days=4)).strftime('%d.%m.%Y')}")

    if st.session_state.is_admin and st.button("📤 Eksportuj PDF"):
        pdf_buf = generate_pdf(db, week_days)
        st.download_button("⬇️ Pobierz PDF", data=pdf_buf, file_name=f"plan_{monday}.pdf", mime="application/pdf")

    cols = st.columns(5)
    for d, col in zip(week_days, cols):
        with col:
            st.subheader(f"{weekday_pl(d).capitalize()} ({d.strftime('%d.%m')})")
            tasks = db.query(Task).filter(Task.work_date == d).order_by(Task.id.desc()).all()
            if not tasks:
                st.info("Brak zadań.")
            for t in tasks:
                assigned = ", ".join(f"{a.employee.first_name} {a.employee.last_name}" for a in t.assignments) or "brak pracowników"
                st.markdown(f"<div style='border:1px solid #ccc;background:#fafafa;padding:8px;border-radius:10px;margin-bottom:8px;'>"
                            f"<b>📍 {t.title}</b><br/><small>({t.team} – {assigned})</small></div>", unsafe_allow_html=True)
                with st.expander("Szczegóły"):
                    if t.notes:
                        st.write(f"**Zakres:** {t.notes}")
                    for a in t.assignments:
                        st.write(f"- {a.employee.first_name} {a.employee.last_name}" + (f" · 📞 {a.employee.phone}" if a.employee.phone else ""))
                        if st.session_state.is_admin and st.button("Usuń", key=f"del_{a.id}"):
                            db.delete(a)
                            db.commit()
                            st.success("Usunięto przypisanie.")
                            st.rerun()
                    if st.session_state.is_admin:
                        opts = employees_select_options(db)
                        if opts:
                            idx = st.selectbox("Dodaj pracownika", range(len(opts)), format_func=lambda i: opts[i][0], key=f"add_{t.id}_{d}")
                            if st.button("➕ Dodaj", key=f"addbtn_{t.id}_{d}"):
                                emp_id = opts[idx][1]
                                if not db.query(TaskAssignment).filter_by(task_id=t.id, employee_id=emp_id).first():
                                    db.add(TaskAssignment(task_id=t.id, employee_id=emp_id))
                                    db.commit()
                                    st.success("Dodano pracownika.")
                                    st.rerun()
                                else:
                                    st.warning("Już przypisany.")
                    if st.session_state.is_admin and st.button("🗑️ Usuń zadanie", key=f"taskdel_{t.id}"):
                        db.delete(t)
                        db.commit()
                        st.success("Zadanie usunięte.")
                        st.rerun()
            if st.session_state.is_admin:
                with st.expander("➕ Dodaj zadanie"):
                    with st.form(key=f"add_{d}"):
                        title = st.text_input("Lokalizacja")
                        notes = st.text_area("Zakres prac")
                        if st.form_submit_button("Zapisz") and title.strip():
                            t = Task(work_date=d, title=title.strip(), notes=notes.strip() or None,
                                     team=next_team_label_for_day(db, d))
                            db.add(t)
                            db.commit()
                            st.success("Dodano zadanie.")
                            st.rerun()

# =============================
# POZOSTAŁE SEKCJE
# =============================
elif section == "Pracownicy" and guard_admin():
    st.subheader("👥 Zarządzanie pracownikami")
    with st.form("add_emp"):
        st.markdown("**➕ Dodaj nowego**")
        first, last, phone = st.text_input("Imię"), st.text_input("Nazwisko"), st.text_input("Telefon")
        if st.form_submit_button("Dodaj") and first and last:
            db.add(Employee(first_name=first.strip(), last_name=last.strip(), phone=phone.strip() or None))
            db.commit()
            st.success("Dodano pracownika.")
            st.rerun()
    for e in db.query(Employee).order_by(Employee.last_name):
        with st.expander(f"{e.first_name} {e.last_name}" + (f" · 📞 {e.phone}" if e.phone else "")):
            with st.form(f"edit_{e.id}"):
                first = st.text_input("Imię", e.first_name)
                last = st.text_input("Nazwisko", e.last_name)
                phone = st.text_input("Telefon", e.phone or "")
                c1, c2 = st.columns(2)
                if c1.form_submit_button("💾 Zapisz"):
                    e.first_name, e.last_name, e.phone = first.strip(), last.strip(), phone.strip() or None
                    db.commit()
                    st.success("Zaktualizowano.")
                    st.rerun()
                if c2.form_submit_button("🗑️ Usuń"):
                    db.delete(e)
                    db.commit()
                    st.success("Usunięto.")
                    st.rerun()

elif section == "Wyszukiwanie" and guard_admin():
    st.subheader("🔎 Wyszukiwanie zadań")
    q = st.text_input("Fraza (np. miejscowość, zakres)")
    c1, c2 = st.columns(2)
    d1, d2 = c1.date_input("Data od"), c2.date_input("Data do")
    opts = employees_select_options(db)
    emp_id = None
    if opts:
        ids = [None] + [o[1] for o in opts]
        idx = st.selectbox("Pracownik", range(len(ids)), format_func=lambda i: "— dowolny —" if i == 0 else opts[i-1][0])
        emp_id = ids[idx]
    if st.button("Szukaj"):
        query = db.query(Task)
        if q:
            query = query.filter(or_(Task.title.ilike(f"%{q}%"), Task.notes.ilike(f"%{q}%")))
        if d1:
            query = query.filter(Task.work_date >= d1)
        if d2:
            query = query.filter(Task.work_date <= d2)
        tasks = query.order_by(Task.work_date.desc()).all()
        if emp_id:
            tasks = [t for t in tasks if any(a.employee_id == emp_id for a in t.assignments)]
        if not tasks:
            st.info("Brak wyników.")
        for t in tasks:
            assigned = ", ".join(f"{a.employee.first_name} {a.employee.last_name}" for a in t.assignments) or "brak"
            st.markdown(f"<div style='border:1px solid #ddd;padding:8px;border-radius:8px;background:#fbfbfb;'>"
                        f"<b>{t.work_date.strftime('%d.%m.%Y')}</b> — {t.title}<br/><small>({t.team} – {assigned})</small></div>", unsafe_allow_html=True)
            if t.notes:
                st.caption(t.notes)

elif section == "Ustawienia":
    st.subheader("⚙️ Ustawienia")
    st.write(f"📂 Baza: `{DB_URL}`")
    st.write(f"🔑 Tryb admina: {'ON' if st.session_state.is_admin else 'OFF'}")
    if guard_admin():
        st.markdown("### 🔑 Zmień hasło administratora")
        old = st.text_input("Stare", type="password")
        new = st.text_input("Nowe", type="password")
        conf = st.text_input("Powtórz", type="password")
        if st.button("💾 Zmień hasło"):
            if old != ADMIN_PASSWORD:
                st.error("Błędne stare hasło.")
            elif not new:
                st.error("Nowe hasło puste.")
            elif new != conf:
                st.error("Hasła się nie zgadzają.")
            else:
                save_admin_password(new)
                st.success("Hasło zmienione. Zaloguj się ponownie.")
                st.session_state.is_admin = False
                st.rerun()

db.close()
