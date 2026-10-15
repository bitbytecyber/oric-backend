"""HEC ORIC Self-Assessment Scorecard: every KPI, declaratively (from the Score Card sheet, FY 2024-25).

Each KPI says where its reported number comes from and how that number is
scored. Bands are ``[(lower_bound, score), …]`` ascending; the score is the
last band whose lower bound the measure reaches (measure must be > 0).

measure kinds
  count      – number of records
  sum        – sum of ``amount_pkr`` (rupees)
  pct_phd    – count as % of total PhD faculty (fiscal year's Index-A figure)
  pct_of     – count as % of another KPI's reported number (acceptance / completion ratios)
  exists     – any record → full marks
  profile    – a value from the Index-A institution profile (section A)
"""
from __future__ import annotations

M = 1_000_000

PCT_2_5 = [(1, 0.5), (5, 1), (20, 1.5), (50, 2), (80, 2.5)]
PCT_3_HI = [(1, 1), (5, 1.5), (20, 2), (50, 2.5), (80, 3)]
COMPLETION = [(40, 0.5), (50, 1), (60, 1.5), (70, 2), (80, 2.5), (90, 3)]
VOLUME = [(10 * M, 0.5), (50 * M, 1), (150 * M, 1.5), (300 * M, 2), (500 * M, 2.5), (750 * M, 3)]

SECTIONS = [
    {"key": "A", "title": "Human Resource and Operations", "max": 10},
    {"key": "B", "title": "Research Excellence", "max": 45},
    {"key": "C", "title": "Innovation & Commercialization", "max": 30},
    {"key": "D", "title": "Sustainability & Capacity Building", "max": 15},
]

RANKING = [
    {"category": "W", "min": 80, "overhead": "15%"},
    {"category": "X", "min": 60, "overhead": "10%"},
    {"category": "Y", "min": 40, "overhead": "5%"},
    {"category": "Non-Complying", "min": 0, "overhead": "-"},
]


def K(code, section, area, title, max_score, *, kind, categories=(), filters=None, bands=None, of=None,
      rubric="", profile_key=None, evidence=""):
    return {"code": code, "section": section, "area": area, "title": title, "max": max_score, "kind": kind,
            "categories": list(categories), "filters": filters or {}, "bands": bands or [], "of": of,
            "rubric": rubric, "profile_key": profile_key, "evidence": evidence}


KPIS = [
    # ---- A. Human resource & operations (Index-A profile) --------------------------
    K("A.i", "A", "Human Resource & Management", "ORIC Head (PVC / VP / Pro-Rector or Director, full time)", 1,
      kind="profile", profile_key="head", rubric="Appointment of HR as per ORIC Policy 2021"),
    K("A.ii", "A", "Human Resource & Management", "Manager Research Management (full time)", 1,
      kind="profile", profile_key="manager_rm"),
    K("A.iii", "A", "Human Resource & Management", "Manager Innovation & Commercialization (full time)", 1,
      kind="profile", profile_key="manager_ic"),
    K("A.iv", "A", "Human Resource & Management", "Support position(s)", 1, kind="profile", profile_key="support"),
    K("A.v", "A", "Functioning & Operations", "ORIC Steering Committee (notified & active)", 0.5,
      kind="profile", profile_key="steering_committee"),
    K("A.vi", "A", "Functioning & Operations", "ORIC Steering Committee meetings", 1.5, kind="profile",
      profile_key="sc_meetings", bands=[(1, 0.5), (4, 1), (7, 1.5)], rubric="<=3 meetings = 0.5, >6 = 1.5"),
    K("A.vii", "A", "Functioning & Operations", "Ethical Institutional Review Board (IRB) meetings", 1,
      kind="profile", profile_key="irb_meetings", bands=[(1, 0.5), (5, 1)], rubric="<=4 meetings = 0.5, >=5 = 1"),
    K("A.viii", "A", "Functioning & Operations", "Functional offices and ICT facilities in ORIC", 1,
      kind="profile", profile_key="offices_ict"),
    K("A.ix", "A", "Functioning & Operations", "Interactive ORIC webpage", 1, kind="profile", profile_key="webpage"),
    K("A.x", "A", "Functioning & Operations", "ORIC centralized database for research management", 1,
      kind="profile", profile_key="database", rubric="Excel / Access = 1; customized portal = 2 (capped at max)"),

    # ---- B. Research excellence ------------------------------------------------------
    K("B.i", "B", "Research Grants Management", "Competitive research grant opportunities identified & circulated",
      1, kind="count", categories=["grant_opportunity"], bands=[(10, 0.5), (50, 1)]),
    K("B.ii", "B", "Research Grants Management", "Research proposals submitted for funding to HEC", 2.5,
      kind="pct_phd", categories=["grant_hec_submitted"], bands=PCT_2_5),
    K("B.iii", "B", "Research Grants Management", "Research proposals approved by HEC (acceptance ratio)", 2.5,
      kind="pct_of", of="B.ii", categories=["grant_hec_approved"], bands=PCT_2_5),
    K("B.iv", "B", "Research Grants Management", "HEC projects due to be completed this year", 0,
      kind="due", categories=["grant_hec_approved"]),
    K("B.iva", "B", "Research Grants Management", "HEC projects completed this year (vs due)", 3,
      kind="pct_of", of="B.iv", categories=["grant_hec_completed"], bands=COMPLETION),
    K("B.v", "B", "Research Grants Management", "Research proposals submitted to non-HEC sources", 2.5,
      kind="pct_phd", categories=["grant_nonhec_submitted"], bands=PCT_2_5),
    K("B.vi", "B", "Research Grants Management", "Research proposals approved by non-HEC sources (acceptance ratio)",
      2.5, kind="pct_of", of="B.v", categories=["grant_nonhec_approved"], bands=PCT_2_5),
    K("B.vii.due", "B", "Research Grants Management", "Non-HEC projects due to be completed this year", 0,
      kind="due", categories=["grant_nonhec_approved"]),
    K("B.vii", "B", "Research Grants Management", "Non-HEC projects completed this year (vs due)", 3,
      kind="pct_of", of="B.vii.due", categories=["grant_nonhec_completed"], bands=COMPLETION),
    K("B.viii.sub", "B", "Research Grants Management", "Joint research projects submitted", 0, kind="count",
      categories=["joint_submitted"]),
    K("B.viii", "B", "Research Grants Management", "Joint research projects approved (acceptance ratio)", 3,
      kind="pct_of", of="B.viii.sub", categories=["joint_approved"], bands=PCT_3_HI),
    K("B.ix", "B", "Research Grants Management", "Volume of R&D funding secured (PKR)", 3, kind="sum",
      categories=["grant_hec_approved", "grant_nonhec_approved", "joint_approved"], bands=VOLUME),
    K("B.x", "B", "Research Grants Management", "Proposals reviewed by IRB before submission", 1, kind="pct_of",
      of="proposals", categories=["irb_review"], bands=[(70, 0.5), (100, 1)]),
    K("B.xi", "B", "Research Grants Management", "Policy advocacy / case studies presented to government", 2.5,
      kind="pct_phd", categories=["policy_advocacy"], bands=PCT_2_5),
    K("B.xii", "B", "Research Linkages, Coordination & Networking", "Research links established", 2,
      kind="pct_phd", categories=["research_link"], bands=[(1, 0.5), (5, 1), (20, 1.5), (50, 2)]),
    K("B.xiii", "B", "Research Linkages, Coordination & Networking", "Contract research awarded (national)", 2.5,
      kind="pct_phd", categories=["contract_research"], filters={"scope_level": "National"}, bands=PCT_2_5),
    K("B.xiv", "B", "Research Linkages, Coordination & Networking", "Contract research awarded (international)", 3,
      kind="pct_phd", categories=["contract_research"], filters={"scope_level": "International"}, bands=PCT_3_HI),
    K("B.xv", "B", "Research Linkages, Coordination & Networking", "Volume of contract research awarded (PKR)", 3,
      kind="sum", categories=["contract_research"], bands=VOLUME),
    K("B.xvi", "B", "Research Linkages, Coordination & Networking", "Civic engagement events / initiatives", 3,
      kind="count", categories=["civic_engagement"], bands=[(1, 1), (5, 1.5), (20, 2), (50, 2.5), (80, 3)]),
    K("B.xvii", "B", "Research Linkages, Coordination & Networking", "Consultancy opportunities circulated", 1,
      kind="count", categories=["consultancy_opportunity"], bands=[(1, 0.5), (10, 1)]),
    K("B.xviii", "B", "Research Linkages, Coordination & Networking", "Consultancy contracts executed through ORIC",
      3, kind="pct_phd", categories=["consultancy_contract"], bands=PCT_3_HI),
    K("B.xix", "B", "Research Linkages, Coordination & Networking", "Liaison with AS&RB", 1, kind="exists",
      categories=["asrb_liaison"]),

    # ---- C. Innovation & commercialization --------------------------------------------
    K("C.i", "C", "Research & IP Legislation", "Research policy of the HEI", 1, kind="exists",
      categories=["policy"], filters={"data__policy_type": "Research policy"}),
    K("C.ii", "C", "Research & IP Legislation", "Intellectual property rights policy", 1, kind="exists",
      categories=["policy"], filters={"data__policy_type": "IP policy"}),
    K("C.iii", "C", "Research & IP Legislation", "Other research policies (ethics, tech transfer, CoI …)", 1,
      kind="exists", categories=["policy"], filters={"data__policy_type": "Other policy"}),
    K("C.iv", "C", "Patents / Trademarks / Copyrights", "IP disclosures made", 2, kind="pct_phd",
      categories=["ip_disclosure"], bands=[(1, 0.5), (5, 1), (20, 1.5), (70, 2)]),
    K("C.v", "C", "Patents / Trademarks / Copyrights", "Patents / TM / designs / copyrights FILED (national)", 1,
      kind="pct_phd", categories=["patent"],
      filters={"data__filed_or_granted": "Filed", "scope_level": "National"}, bands=[(1, 0.5), (5, 1)]),
    K("C.vi", "C", "Patents / Trademarks / Copyrights", "Patents / TM / designs / copyrights GRANTED (national)", 2,
      kind="count", categories=["patent"], filters={"data__filed_or_granted": "Granted", "scope_level": "National"},
      bands=[(1, 0.5), (5, 1), (10, 1.5), (15, 2)]),
    K("C.vii", "C", "Patents / Trademarks / Copyrights", "Patents / TM / designs / copyrights FILED (international)",
      2, kind="pct_phd", categories=["patent"],
      filters={"data__filed_or_granted": "Filed", "scope_level": "International"}, bands=[(1, 1), (5, 2)]),
    K("C.viii", "C", "Patents / Trademarks / Copyrights",
      "Patents / TM / designs / copyrights GRANTED (international)", 3, kind="count", categories=["patent"],
      filters={"data__filed_or_granted": "Granted", "scope_level": "International"},
      bands=[(1, 1), (2, 1.5), (5, 2), (10, 3)]),
    K("C.ix", "C", "Commercialization & IP Licensing", "IP licensing negotiations initiated (national)", 1,
      kind="pct_phd", categories=["licensing_negotiation"], filters={"scope_level": "National"},
      bands=[(1, 0.5), (5, 1)]),
    K("C.x", "C", "Commercialization & IP Licensing", "Licenses signed (national)", 2, kind="count",
      categories=["license_signed"], filters={"scope_level": "National"},
      bands=[(1, 0.5), (2, 1), (5, 1.5), (10, 2)]),
    K("C.xi", "C", "Commercialization & IP Licensing", "IP licensing negotiations initiated (international)", 2,
      kind="pct_phd", categories=["licensing_negotiation"], filters={"scope_level": "International"},
      bands=[(1, 1), (5, 2)]),
    K("C.xii", "C", "Commercialization & IP Licensing", "Licenses signed (international)", 3, kind="count",
      categories=["license_signed"], filters={"scope_level": "International"},
      bands=[(1, 1), (2, 1.5), (5, 2), (10, 3)]),
    K("C.xiii", "C", "Commercialization & IP Licensing", "Products / processes / prototypes (prefeasibility / "
      "industrial scale)", 2, kind="count", categories=["prototype"], bands=[(1, 0.5), (5, 1), (10, 1.5), (20, 2)]),
    K("C.xiv", "C", "Commercialization & IP Licensing", "Science / arts products displayed", 2, kind="count",
      categories=["creative_product"], bands=[(1, 0.5), (3, 1), (10, 1.5), (20, 2)]),
    K("C.xv", "C", "I&C Linkages, Coordination & Networking", "Visits by industry / community representatives", 1,
      kind="count", categories=["industry_visit"], bands=[(1, 0.5), (5, 1)]),
    K("C.xvi", "C", "I&C Linkages, Coordination & Networking", "Collaboration agreements signed", 2, kind="count",
      categories=["collaboration_agreement"], bands=[(1, 1), (10, 2)]),
    K("C.xvii", "C", "I&C Linkages, Coordination & Networking", "National / international honours or awards", 2,
      kind="count", categories=["award"], bands=[(1, 1), (5, 2)]),

    # ---- D. Sustainability & capacity building ------------------------------------------
    K("D.ia", "D", "Sustainability", "Five-year strategic plan", 2, kind="exists", categories=["strategic_plan"]),
    K("D.i", "D", "Sustainability", "Annual research revenue generated by ORIC (PKR)", 2, kind="sum",
      categories=["research_revenue"], bands=[(1 * M, 0.5), (5 * M, 1), (10 * M, 1.5), (20 * M, 2)]),
    K("D.ii", "D", "Sustainability", "Revenue from licensing, royalties, advocacy … (PKR)", 3, kind="sum",
      categories=["licensing_revenue"], bands=[(10 * M, 0.5), (50 * M, 1), (100 * M, 3)]),
    K("D.iii", "D", "Trainings, Mentoring & Workshops", "Trainings / workshops arranged by ORIC", 2, kind="count",
      categories=["training_oric"], bands=[(1, 1), (5, 2)]),
    K("D.iv", "D", "Trainings, Mentoring & Workshops", "Trainings arranged by other HEIs / CB partners", 2,
      kind="count", categories=["training_external"], bands=[(1, 1), (10, 2)]),
    K("D.v", "D", "Trainings, Mentoring & Workshops", "Exhibitions / showcasing events / linkage fairs", 2,
      kind="count", categories=["exhibition"], bands=[(1, 1), (3, 2)]),
    K("D.vi", "D", "Trainings, Mentoring & Workshops", "Trainings attended by ORIC personnel", 2, kind="count",
      categories=["training_oric_staff"], bands=[(1, 1), (4, 2)]),
]
KPI_BY_CODE = {k["code"]: k for k in KPIS}
SCORED = [k for k in KPIS if k["max"]]

assert sum(k["max"] for k in SCORED) == 100, sum(k["max"] for k in SCORED)
