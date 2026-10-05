"""Realistic demo content for `seed_oric --demo`.

Everything here is synthetic (names, titles, agencies, figures) and every demo
account lives on the reserved `.test` domain so no email can reach a real person.
"""
from __future__ import annotations

import datetime
import random

from submissions.registry import DEPARTMENTS

# --- people ---------------------------------------------------------------------
FIRST_M = ["Ahmed", "Ali", "Bilal", "Faisal", "Hamza", "Imran", "Junaid", "Kamran", "Moiz", "Noman", "Owais", "Rizwan",
           "Saad", "Salman", "Tariq", "Umair", "Usman", "Waqar", "Yasir", "Zeeshan", "Asad", "Danish", "Farhan", "Hasan"]
FIRST_F = ["Amna", "Ayesha", "Bushra", "Fatima", "Hina", "Iqra", "Javeria", "Kiran", "Maryam", "Nadia", "Rabia", "Saba",
           "Sadia", "Sana", "Shazia", "Sidra", "Tahira", "Uzma", "Zainab", "Mehwish", "Anum", "Faiza", "Huma", "Nida"]
LAST = ["Ahmed", "Ali", "Ansari", "Baig", "Chaudhry", "Farooqui", "Hashmi", "Hussain", "Iqbal", "Jafri", "Khan", "Malik",
        "Memon", "Mirza", "Naqvi", "Qureshi", "Rizvi", "Saeed", "Shaikh", "Siddiqui", "Soomro", "Usmani", "Zaidi", "Abbasi"]

DESIGNATIONS = [  # weight, title, honorific needs PhD
    (2, "Professor", True),
    (3, "Associate Professor", True),
    (5, "Assistant Professor", True),
    (3, "Lecturer", False),
]


def make_person(rng: random.Random, used: set[str]):
    female = rng.random() < 0.42
    for _ in range(50):
        first = rng.choice(FIRST_F if female else FIRST_M)
        last = rng.choice(LAST)
        key = f"{first}.{last}".lower()
        if key not in used:
            used.add(key)
            break
    else:
        key = f"{first}.{last}{len(used)}".lower()
        used.add(key)
    weights = [w for w, *_ in DESIGNATIONS]
    _, designation, phd = rng.choices(DESIGNATIONS, weights=weights)[0]
    honorific = "Dr." if phd else ("Ms." if female else "Engr.")
    return {
        "full_name": f"{honorific} {first} {last}",
        "email": f"{key}@faculty.oric.test",
        "designation": designation,
        "phone": f"+92 21 9926{rng.randint(1000, 9999)}",
        "employee_id": f"NED-{rng.randint(10000, 99999)}",
    }


# --- content pools ------------------------------------------------------------------
THEMES = [
    "Renewable Energy", "Water Resources", "AI & Data Science", "Smart Grids", "Advanced Materials", "Urban Mobility",
    "Biomedical Devices", "Climate Resilience", "Industry 4.0", "Food Security", "Cyber Security", "Telecommunications",
    "Petroleum & Gas", "Textile Innovation", "Earthquake Engineering", "Environmental Remediation",
]
PROJECT_TITLES = [
    "Low-cost solar microgrids for peri-urban Karachi",
    "Machine-learning flood early warning for the Lyari basin",
    "Graphene-enhanced concrete for coastal structures",
    "Edge-AI screening for tuberculosis in primary care",
    "Seismic retrofitting of non-engineered masonry houses in Sindh",
    "Wastewater reuse for peri-urban agriculture in Malir",
    "Predictive maintenance for textile looms using vibration analytics",
    "Biodegradable packaging from sugarcane bagasse",
    "5G small-cell planning for dense urban corridors",
    "Battery health estimation for electric rickshaws",
    "Desalination using solar thermal membranes for coastal villages",
    "Remote sensing of mangrove loss along the Indus delta",
    "Low-power IoT air-quality network for Karachi industrial zones",
    "Hybrid wind-solar forecasting for the Jhimpir corridor",
    "Recycled-plastic aggregates for pavement subbase",
    "Corrosion-resistant coatings for offshore pipelines",
    "Urdu speech recognition for public-service helplines",
    "Smart irrigation scheduling for cotton farms",
    "3D-printed prosthetic sockets for low-resource clinics",
    "Heat-stress mapping and cool-roof interventions for Karachi",
    "Blockchain-based land record verification",
    "Natural-dye fixation using enzymatic treatment in denim",
    "Fault-tolerant control for grid-tied inverters",
    "Rainwater harvesting design guide for public schools",
    "Computer-vision quality inspection for pharmaceutical blister packs",
]
GRANTS_HEC = ["NRPU", "TTSF", "GCF", "ICRG", "LCF", "SRGP"]
AGENCIES_NON_HEC = ["Pakistan Science Foundation", "Ignite National Technology Fund", "USAID PEER", "British Council",
                    "Sindh HEC", "PSF-NSFC", "Erasmus+", "Asian Development Bank", "UNDP Pakistan",
                    "Higher Education Development in Pakistan (HEDP)"]
UNIVERSITIES = ["University of Leeds, UK", "Nanyang Technological University, Singapore", "University of Karachi",
                "LUMS, Lahore", "NUST, Islamabad", "Universiti Teknologi Malaysia", "Aga Khan University, Karachi",
                "TU Delft, Netherlands", "Mehran UET, Jamshoro", "Shanghai Jiao Tong University, China"]
COMPANIES = ["K-Electric", "Engro Corporation", "Pakistan State Oil", "Lucky Cement", "Sui Southern Gas Company",
             "Habib Bank Limited", "Jazz", "Nishat Mills", "Indus Motor Company", "Karachi Water & Sewerage Corporation",
             "Pakistan Steel Mills", "Gul Ahmed Textiles", "Systems Ltd", "Atlas Honda"]
GOV_BODIES = ["Sindh Environmental Protection Agency", "Karachi Metropolitan Corporation", "Ministry of Climate Change",
              "Sindh Energy Department", "Planning Commission of Pakistan", "Sindh Irrigation Department",
              "National Disaster Management Authority"]
NGOS = ["Hisaar Foundation", "The Citizens Foundation", "Shehri", "Edhi Foundation", "WWF-Pakistan", "Saylani Welfare Trust"]
INVENTIONS = [
    "Self-cleaning solar panel coating", "Low-cost portable water purifier", "Smart energy meter with theft detection",
    "Wearable fall detector for the elderly", "Modular bamboo-reinforced shelter", "Automated drip-irrigation controller",
    "Biodegradable surgical sutures from silk fibroin", "Noise-cancelling ventilator for vehicles",
    "Microbial fuel cell for wastewater treatment", "Tamper-proof medicine dispenser",
]
STARTUPS = [
    ("SolarDhoop", "Clean energy"), ("AquaPure Labs", "Water treatment"), ("Shehr.ai", "Urban analytics"),
    ("KisanTech", "Agri-tech"), ("Rehaish Builders", "Construction materials"), ("MedScan", "Health-tech"),
    ("RickshawEV", "E-mobility"), ("TextileTrace", "Supply-chain traceability"),
]
EVENT_TITLES = [
    "Workshop on research proposal writing for NRPU", "IP awareness seminar for faculty",
    "Industry-academia linkage roundtable", "Hackathon: AI for Karachi", "Startup pitching bootcamp",
    "Training on patent search and drafting", "Seminar on commercialization of research",
    "Open innovation challenge with K-Electric", "Women in engineering entrepreneurship forum",
]
AWARDS = ["Best Paper Award", "HEC Best Teacher Award", "PEC Engineering Excellence Award",
          "Gold medal, ITEX Kuala Lumpur", "Tamgha-e-Imtiaz nomination", "IEEE Region 10 Outstanding Volunteer"]
JOURNALS = ["Energy Reports", "Journal of Cleaner Production", "IEEE Access", "Construction and Building Materials",
            "Water Research", "Scientific Reports", "Applied Sciences", "Sustainable Cities and Society"]


def fy_date(rng: random.Random, year: int) -> datetime.date:
    """A date inside fiscal year ending 30 June `year`."""
    start = datetime.date(year - 1, 7, 1)
    return start + datetime.timedelta(days=rng.randint(0, 360))


def value_for(field: dict, section_key: str, ctx: dict, rng: random.Random):
    """Plausible value for one registry field. ctx: user, department, year, project, i."""
    n, t = field["name"], field["type"]
    user, dept, year = ctx["user"], ctx["department"], ctx["year"]
    project = ctx["project"]

    if t == "date":
        return fy_date(rng, year).isoformat()
    if t == "department":
        return dept
    if t in ("select", "radio"):
        opts = [o for o in field.get("options") or [] if o != "Other"]
        if n == "status" and section_key in ("A1", "A2"):
            return rng.choices(["Pending", "Completed", "Rejected"], [6, 3, 1])[0]
        return rng.choice(opts) if opts else ""
    if t == "int":
        return rng.choice([18, 25, 32, 40, 55, 70, 85, 120, 150]) if "particip" in n else rng.randint(1, 6)
    if t == "decimal":
        if n == "oric_percentage":
            return rng.choice([10, 15, 20])
        if field.get("money"):
            label = field["label"].lower()
            if "million" in label:
                return round(rng.uniform(0.8, 25.0), 2)
            return float(rng.choice([150000, 250000, 400000, 750000, 1200000, 2500000, 5000000]))
        return round(rng.uniform(1, 20), 1)
    if t == "url":
        return f"https://doi.org/10.1016/j.demo.{year}.{rng.randint(100000, 999999)}"

    # text / textarea by name
    simple = {
        "pi_name": user.full_name, "lead_inventor_name": user.full_name, "lead_name": user.full_name,
        "pi_designation": user.designation, "lead_inventor_designation": user.designation,
        "lead_designation": user.designation,
        "thematic_area": project["theme"], "field_of_study": project["theme"], "sector": project["theme"],
        "field": project["theme"], "field_of_use": project["theme"],
        "research_proposal_title": project["title"], "project_title": project["title"],
        "research_grant_name": rng.choice(GRANTS_HEC) if section_key in ("A1", "A3", "A5") else rng.choice(AGENCIES_NON_HEC),
        "joint_research_grant_name": f"{rng.choice(AGENCIES_NON_HEC)} joint call {year}",
        "funding_agency": rng.choice(AGENCIES_NON_HEC),
        "sponsoring_agency": rng.choice(AGENCIES_NON_HEC + COMPANIES),
        "sponsoring_agency_name": rng.choice(COMPANIES),
        "sponsoring_agency_address": "Karachi, Pakistan",
        "counterpart_industry": f"{rng.choice(COMPANIES)}, Karachi, Pakistan",
        "co_pi_name": f"Dr. {rng.choice(FIRST_M + FIRST_F)} {rng.choice(LAST)}",
        "co_pi_designation": rng.choice(["Professor", "Associate Professor", "Senior Lecturer"]),
        "co_pi_department": rng.choice(["Civil Engineering", "Computer Science", "Electrical Engineering", "Chemistry"]),
        "co_pi_university": rng.choice(UNIVERSITIES),
        "collaborating_partners": rng.choice(["", rng.choice(UNIVERSITIES), rng.choice(COMPANIES)]),
        "co_funding_partners": rng.choice(["", "", rng.choice(COMPANIES)]),
        "co_funding_partners_details": rng.choice(["", rng.choice(COMPANIES)]),
        "company_details": f"{rng.choice(COMPANIES)}, Karachi",
        "consultancy_type": rng.choice(["Feasibility study", "Design review", "Testing & certification", "Energy audit",
                                        "Third-party validation"]),
        "key_deliverables": "Technical report, design drawings and a one-day training for client engineers.",
        "expected_deliverables": "Validated prototype, two journal papers and a technology-transfer workshop.",
        "government_body_presented": rng.choice(GOV_BODIES),
        "advocacy_area": rng.choice(["Economic development", "Environment", "Social protection", "Urban planning"]),
        "brief": f"Policy brief drawing on '{project['title']}' with recommendations for provincial adoption.",
        "coalition_partners": rng.choice(["", rng.choice(NGOS)]),
        "advocacy_tools": "Policy brief, stakeholder meeting and a media briefing.",
        "host_institution_name": rng.choice(UNIVERSITIES), "host_institution_address": "See institution name",
        "host_institution": rng.choice(UNIVERSITIES),
        "collaborating_agency_name": rng.choice(UNIVERSITIES + COMPANIES), "collaborating_agency_address": "Karachi, Pakistan",
        "scope_of_collaboration": "Joint supervision of graduate students, shared lab access and co-authored proposals.",
        "salient_features": "Five-year MoU with annual review, faculty exchange and joint seminar series.",
        "key_initiatives": "Joint research projects, student internships and an annual industry day.",
        "duration": rng.choice(["2 years", "3 years", "5 years"]),
        "event_title": rng.choice(["Clean water awareness drive in Lyari", "Heat-wave preparedness camp",
                                   "Road safety audit with the community", "Solar lantern distribution in Thatta"]),
        "community_component": rng.choice(["Residents of Lyari", "Fishing communities of Ibrahim Hyderi",
                                           "Government school students", "Small traders of Saddar"]),
        "outcome": "Case study prepared and shared with the district administration.",
        "collaboration_developed": rng.choice(GOV_BODIES),
        "engaged_csos_ngos": rng.choice(NGOS),
        "arranged_or_participated": rng.choice(["Arranged", "Participated"]),
        "dissemination_material": "Brochure and event report on the ORIC website.",
        "liaison_with": rng.choice(["AS&RB — PhD admissions committee", "AS&RB — research ethics review",
                                    "AS&RB — postgraduate curriculum committee"]),
        "invention_title": rng.choice(INVENTIONS),
        "key_scientific_aspects": "Novel low-cost design using locally available materials; lab-validated at TRL 4.",
        "commercial_partner": rng.choice(["", rng.choice(COMPANIES)]),
        "disclosure_made_with": "IPO Pakistan through NED ORIC patent cell",
        "patent_filed_with": "Intellectual Property Organization of Pakistan (IPO-Pakistan)",
        "granting_authority": "", "financial_support": rng.choice(["", "ORIC seed grant", "HEC TTSF"]),
        "previous_disclosure": "",
        "licensee_details": f"{rng.choice(COMPANIES)} (licensee)",
        "negotiation_status": rng.choice(["Term sheet shared", "Under legal review", "Draft agreement agreed"]),
        "duration_of_agreement": rng.choice(["3 years", "5 years"]),
        "agreement_duration": rng.choice(["3 years", "5 years"]),
        "industrial_partner": rng.choice(COMPANIES),
        "forum": rng.choice(["NED Open House", "ITEAP Expo Karachi", "Pakistan Science Festival"]),
        "status": rng.choice(["Displayed", "Registered", "Performed"]),
        "visitor_name": f"{rng.choice(COMPANIES)} delegation",
        "agenda": "Lab tour, discussion on joint projects and student internships.",
        "award_received": "Certificate and medal",
        "conferring_organization": rng.choice(["IEEE Karachi Section", "PEC", "HEC", "ITEX Malaysia"]),
        "work_details": f"Recognised for work on '{project['title']}'.",
        "winner_details": f"{user.full_name}, {user.designation}, {dept.replace('Department of ', '')}",
        "focus_and_outcomes": "Hands-on sessions; participants drafted proposals and received feedback.",
        "organizer": rng.choice(UNIVERSITIES), "organizers": "ORIC, NED University",
        "panelist_details": f"Dr. {rng.choice(FIRST_M + FIRST_F)} {rng.choice(LAST)} ({rng.choice(COMPANIES)})",
        "venue": rng.choice(["NED Main Auditorium", "ORIC Seminar Hall", "NED City Campus"]),
        "publication_reference": f"{user.full_name.split(' ', 1)[1]} et al. ({year}) {project['title']}. "
                                 f"{rng.choice(JOURNALS)}, {rng.randint(8, 40)}({rng.randint(1, 12)}), "
                                 f"{rng.randint(100, 900)}–{rng.randint(901, 1500)}.",
        "license_agreement": rng.choice(["N/A", f"Licensed from NED to the startup, {year}"]),
        "funding_source": rng.choice(["N/A", "Ignite NIC Karachi", "Angel investor"]),
        "stage": rng.choice(["Initial", "Prototype developed", "Pilot with first customers"]),
        "startup_details": f"{project['startup'][0]} — {project['startup'][1]}",
        "in_kind_support": rng.choice(["", "Co-working space at NIC Karachi"]),
        "remarks": "",
    }
    if n in simple:
        return simple[n]
    if n == "title":
        if section_key in ("B10", "B11", "B12", "C4"):
            return rng.choice(EVENT_TITLES)
        if section_key == "B9":
            return rng.choice(AWARDS)
        return rng.choice(INVENTIONS)
    if n == "startup_name":
        return project["startup"][0]
    if n == "spinoff_name":
        return f"{project['startup'][0]} Technologies (Pvt) Ltd"
    return f"{field['label'].split('(')[0].strip()}"


def make_project(rng: random.Random) -> dict:
    return {"title": rng.choice(PROJECT_TITLES), "theme": rng.choice(THEMES), "startup": rng.choice(STARTUPS)}


# --- evidence ---------------------------------------------------------------------------
def _pdf_escape(s: str) -> str:
    return s.replace("\\", "\\\\").replace("(", "\\(").replace(")", "\\)").encode("latin-1", "replace").decode("latin-1")


def make_pdf(lines: list[str]) -> bytes:
    """A small, valid single-page PDF (Helvetica) with the given lines."""
    y, ops = 780, ["BT", "/F1 16 Tf", "50 800 Td"]
    content = ["BT /F1 15 Tf 50 790 Td (" + _pdf_escape(lines[0]) + ") Tj ET"]
    for i, line in enumerate(lines[1:]):
        y = 760 - i * 18
        content.append(f"BT /F1 10.5 Tf 50 {y} Td (" + _pdf_escape(line[:110]) + ") Tj ET")
    content.append("BT /F1 8 Tf 50 40 Td (Synthetic demo evidence generated by seed_oric. Not a real document.) Tj ET")
    stream = "\n".join(content).encode("latin-1", "replace")
    objs = [
        b"<</Type/Catalog/Pages 2 0 R>>",
        b"<</Type/Pages/Kids[3 0 R]/Count 1>>",
        b"<</Type/Page/Parent 2 0 R/MediaBox[0 0 595 842]/Contents 4 0 R/Resources<</Font<</F1 5 0 R>>>>>>",
        b"<</Length " + str(len(stream)).encode() + b">>stream\n" + stream + b"\nendstream",
        b"<</Type/Font/Subtype/Type1/BaseFont/Helvetica>>",
    ]
    out = b"%PDF-1.4\n"
    offsets = []
    for i, o in enumerate(objs, 1):
        offsets.append(len(out))
        out += f"{i} 0 obj".encode() + o + b"endobj\n"
    xref = len(out)
    out += f"xref\n0 {len(objs) + 1}\n0000000000 65535 f \n".encode()
    for off in offsets:
        out += f"{off:010d} 00000 n \n".encode()
    out += f"trailer<</Size {len(objs) + 1}/Root 1 0 R>>\nstartxref\n{xref}\n%%EOF\n".encode()
    return out


__all__ = ["DEPARTMENTS", "make_person", "make_project", "value_for", "make_pdf", "fy_date"]
