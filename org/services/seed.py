"""Idempotent reference-data seeders (update_or_create)."""
import datetime

from org.models import Department, ReportingCycle, TeamMember
from submissions.registry import DEPARTMENTS

DEPARTMENT_META = {
    # name -> (code, faculty)
    "Department of Civil Engineering": ("CE", "Civil & Petroleum Engineering"),
    "Department of Urban and Infrastructure Engineering": ("UE", "Civil & Petroleum Engineering"),
    "Department of Petroleum Engineering": ("PE", "Civil & Petroleum Engineering"),
    "Department of Earthquake Engineering": ("EQ", "Civil & Petroleum Engineering"),
    "Department of Environmental Engineering": ("EN", "Civil & Petroleum Engineering"),
    "Department of Electrical Engineering": ("EE", "Electrical & Computer Engineering"),
    "Department of Electronic Engineering": ("EL", "Electrical & Computer Engineering"),
    "Department of Telecommunications Engineering": ("TC", "Electrical & Computer Engineering"),
    "Department of Computer and Information Systems Engineering": ("CIS", "Electrical & Computer Engineering"),
    "Department of Bio-Medical Engineering": ("BM", "Electrical & Computer Engineering"),
    "Department of Computer Science & Information Technology": ("CSIT", "Information Sciences & Humanities"),
    "Department of Software Engineering": ("SE", "Electrical & Computer Engineering"),
    "Department of Mechanical Engineering": ("ME", "Mechanical & Manufacturing Engineering"),
    "Department of Industrial and Manufacturing Engineering": ("IM", "Mechanical & Manufacturing Engineering"),
    "Department of Textile Engineering": ("TE", "Mechanical & Manufacturing Engineering"),
    "Department of Automotive and Marine Engineering": ("AM", "Mechanical & Manufacturing Engineering"),
    "Department of Chemical Engineering": ("CH", "Chemical & Process Engineering"),
    "Department of Polymer and Petrochemical Engineering": ("PP", "Chemical & Process Engineering"),
    "Department of Materials Engineering": ("MY", "Chemical & Process Engineering"),
    "Department of Metallurgical Engineering": ("MT", "Chemical & Process Engineering"),
    "Department of Food Engineering": ("FE", "Chemical & Process Engineering"),
    "Department of Architecture and Planning": ("AP", "Architecture & Management Sciences"),
    "Department of Economics and Management Sciences": ("EMS", "Architecture & Management Sciences"),
    "Department of Physics": ("PH", "Information Sciences & Humanities"),
    "Department of Chemistry": ("CY", "Information Sciences & Humanities"),
    "Department of Mathematics": ("MA", "Information Sciences & Humanities"),
    "Department of English Linguistics & Allied Studies": ("ELAS", "Information Sciences & Humanities"),
    "Department of Essential Studies": ("ES", "Information Sciences & Humanities"),
}

TEAM = [
    ("Dr. Riaz Uddin", "Director ORIC"),
    ("Dr. Saeeda Nadir Ali", "Manager — Tech Transfer & University-Industry Linkage"),
    ("Dr. Muhammad Uzair", "Manager — Research Operations & Development"),
    ("Dr. Sundus Ali", "Manager — Business Incubation"),
    ("Dr. Ashar Ahmed", "Manager — Intellectual Property"),
    ("Mr. Imran Ahmed", "Assistant Manager ORIC"),
]


def seed_departments() -> int:
    for name in DEPARTMENTS:
        code, faculty = DEPARTMENT_META.get(name, (name[:6].upper(), ""))
        Department.objects.update_or_create(name=name, defaults={"code": code, "faculty": faculty})
    return len(DEPARTMENTS)


def seed_cycles(today: datetime.date | None = None) -> None:
    """FY runs 1 July – 30 June; returns are filed after year-end. The FY that ended most
    recently is OPEN, older ones CLOSED."""
    today = today or datetime.date.today()
    latest_end_year = today.year if today.month >= 7 else today.year - 1
    for end_year in range(latest_end_year - 2, latest_end_year + 1):
        status = ReportingCycle.Status.OPEN if end_year == latest_end_year else ReportingCycle.Status.CLOSED
        ReportingCycle.objects.update_or_create(
            year=end_year,
            defaults={
                "label": f"FY {end_year - 1}-{str(end_year)[-2:]}",
                "starts_on": datetime.date(end_year - 1, 7, 1),
                "ends_on": datetime.date(end_year, 6, 30),
                "submission_deadline": datetime.date(end_year, 12, 15),
                "status": status,
            },
        )


def seed_team() -> None:
    for i, (name, title) in enumerate(TEAM):
        TeamMember.objects.update_or_create(name=name, defaults={"title": title, "order": i})
