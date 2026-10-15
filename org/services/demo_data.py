"""Realistic demo content for `seed_oric --demo`.

Everything here is synthetic (names, titles, agencies, figures) and every demo
account lives on the reserved `.test` domain so no email can reach a real person.
"""
from __future__ import annotations

import datetime
import random

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


def value_for(field: dict, category: str, ctx: dict, rng: random.Random):
    """Plausible value for one registry field. ctx: person, year, project."""
    n, t = field["name"], field["type"]
    year, project = ctx["year"], ctx["project"]
    if t == "date":
        if n == "end_date":
            return (fy_date(rng, year) + datetime.timedelta(days=rng.choice([365, 540, 730]))).isoformat()
        return fy_date(rng, year).isoformat()
    if t in ("select", "radio"):
        opts = field.get("options") or []
        if n == "national_or_international":
            return rng.choices(opts, [4, 1])[0]
        if n == "status":
            return rng.choices(opts, [5, 2, 1, 1, 0.3][:len(opts)])[0] if opts else ""
        if n == "thematic_area":
            return rng.choice(["Engineering & Technology", "Computer Science and Informatics",
                               "Earth Systems and Environmental Sciences", "Physics", "Chemistry",
                               "Management Sciences"])
        return rng.choice(opts) if opts else ""
    if t == "int":
        return rng.choice([18, 25, 32, 40, 55, 70, 85, 120]) if "particip" in n else rng.randint(1, 6)
    if t == "decimal":
        label = field["label"].lower()
        if "%" in label:
            return rng.choice([10, 15, 20])
        if "million" in label:
            return round(rng.uniform(0.8, 25.0), 2)
        return float(rng.choice([150000, 250000, 400000, 750000, 1200000, 2500000]))
    if t == "url":
        return f"https://doi.org/10.1016/j.demo.{year}.{rng.randint(100000, 999999)}"
    if t == "file":
        return None
    simple = {
        "research_grant_name": rng.choice(GRANTS_HEC) if "hec" in category and "non" not in category
        else rng.choice(AGENCIES_NON_HEC),
        "funding_agency": rng.choice(AGENCIES_NON_HEC), "research_proposal_title": project["title"],
        "project_title": project["title"], "opportunity_title": f"{rng.choice(AGENCIES_NON_HEC)} call {year}",
        "collaborating_partners": rng.choice(["", rng.choice(UNIVERSITIES), rng.choice(COMPANIES)]),
        "co_funding_partners": rng.choice(["", "", rng.choice(COMPANIES)]),
        "sponsoring_agency": rng.choice(COMPANIES), "counterpart_industry": f"{rng.choice(COMPANIES)}, Karachi",
        "expected_deliverables": "Validated prototype, two journal papers and a technology-transfer workshop.",
        "key_project_deliverables": "Final technical report, prototype and two journal publications.",
        "government_body_presented": rng.choice(GOV_BODIES),
        "brief": f"Policy brief drawing on '{project['title']}' with recommendations for provincial adoption.",
        "advocacy_tools": "Policy brief, stakeholder meeting and a media briefing.",
        "coalition_partners": rng.choice(["", rng.choice(NGOS)]),
        "research_status": "Backed by completed field study",
        "host_institution": "NED University of Engineering & Technology, Karachi, Pakistan",
        "collaborating_agency": rng.choice(UNIVERSITIES + COMPANIES), "partner_institution": rng.choice(UNIVERSITIES + COMPANIES),
        "field_of_study": project["theme"], "field": project["theme"], "field_of_use": project["theme"],
        "sector": project["theme"],
        "scope_of_collaboration": "Joint supervision of graduate students, shared lab access and co-authored proposals.",
        "salient_features": "Five-year MoU with annual review, faculty exchange and joint seminar series.",
        "key_initiatives": "Joint research projects, student internships and an annual industry day.",
        "duration": rng.choice(["2 years", "3 years", "5 years"]),
        "event_title": rng.choice(["Clean water awareness drive in Lyari", "Heat-wave preparedness camp",
                                   "Road safety audit with the community"]),
        "community_component": rng.choice(["Residents of Lyari", "Government school students", "Small traders of Saddar"]),
        "outcome": "Case study prepared and shared with the district administration.",
        "collaboration_developed": rng.choice(GOV_BODIES), "engaged_csos_ngos": rng.choice(NGOS),
        "dissemination_material": "Brochure and event report on the ORIC website.",
        "company_details": f"{rng.choice(COMPANIES)}, Pakistan",
        "key_deliverables": "Technical report, test certificates and a one-day training for client engineers.",
        "liaison_with": "AS&RB annual research report & priority areas",
        "invention_title": rng.choice(INVENTIONS),
        "key_scientific_aspects": "Novel low-cost design using locally available materials; lab-validated at TRL 4.",
        "commercial_partner": rng.choice(["", rng.choice(COMPANIES)]),
        "disclosure_made_with": "IPO-Pakistan through NED ORIC patent cell", "filed_with": "IPO-Pakistan",
        "application_no": f"{rng.randint(100, 999)}/{year}", "financial_support": rng.choice(["", "ORIC seed grant"]),
        "licensee": rng.choice(COMPANIES), "negotiation_status": rng.choice(["Term sheet shared", "Under legal review"]),
        "duration_of_agreement": "5 years", "agreement_duration": "5 years",
        "industrial_partner": rng.choice(COMPANIES),
        "forum": rng.choice(["NED Open House", "ITEAP Expo Karachi", "Pakistan Science Festival"]),
        "title": rng.choice(EVENT_TITLES) if category.startswith(("training", "exhibition")) else
        (rng.choice(AWARDS) if category == "award" else project["title"]),
        "conferring_organization": rng.choice(["Pakistan Engineering Council", "HEC", "IEEE Karachi Section"]),
        "award_received": rng.choice(["Gold medal", "Certificate & shield", "Cash prize"]),
        "work_details": f"Recognised for work on {project['theme'].lower()}.",
        "focus_and_outcomes": "Hands-on sessions; participants drafted proposals reviewed by ORIC.",
        "organizer": rng.choice(["NIC Karachi", "Sindh HEC", "K-Electric", "IoBM"]),
        "visitor_name": rng.choice(COMPANIES), "agenda": "Lab visit and discussion on joint testing projects.",
        "publication_title": project["title"], "journal": rng.choice(JOURNALS),
        "publication_reference": f"{ctx['person'].full_name} et al. ({year}) {project['title']}. {rng.choice(JOURNALS)}.",
        "startup_name": project["startup"][0], "spinoff_name": project["startup"][0] + " Labs",
        "startup_details": f"{project['startup'][0]} ({project['startup'][1]})",
        "stage": "Prototype developed", "venue": "NED BIC, Karachi", "organizers": "NED BIC",
    }
    return simple.get(n, "" if not field["required"] else project["theme"])


def make_project(rng: random.Random) -> dict:
    return {"title": rng.choice(PROJECT_TITLES), "theme": rng.choice(THEMES), "startup": rng.choice(STARTUPS)}


# --- evidence ---------------------------------------------------------------------------
def _pdf_escape(s: str) -> str:
    return s.replace("\\", "\\\\").replace("(", "\\(").replace(")", "\\)").encode("latin-1", "replace").decode("latin-1")


def make_pdf(lines: list[str]) -> bytes:
    """A small, valid single-page PDF (Helvetica) with the given lines."""
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


__all__ = ["make_person", "make_project", "value_for", "make_pdf", "fy_date"]
