"""
Single source of truth for every ORIC submission type ("category").

One category = one kind of activity a faculty member (or ORIC) records, e.g.
"Non-HEC research proposal approved" or "Patent filed / granted". It ties
together the three places the same data lives:

* ``form``      – section of the live Google Forms (RIC Form-1/2/3, FY 2025-26)
* ``excel``     – table of the HEC "ORIC Self-Assessment Scorecard" workbook
                  (Index-B/C/D, e.g. ``B.vi``) – used by the importer and the
                  HEC workbook exporter
* ``kpis``      – Score Card KPI codes it feeds (scorecard/kpis.py)

Every submission row is one ``Submission``; its free-form answers live in
``Submission.data`` and are validated against ``fields``. People (PI, Co-PIs,
inventors, winners …) are not plain fields: they are ``Contributor`` rows
described by ``people`` so NED colleagues can be linked to their accounts.

Promoted columns (fast filters / exports / scorecard) are declared per
category: ``title_field``, ``date_field``, ``amount_field`` (+ ``amount_unit``
"M" = PKR million, "PKR" = rupees), ``scope_field`` (National/International)
and a fixed ``funding_source`` (HEC / NON_HEC / JOINT).

Field types: text, textarea, email, url, date, int, decimal, select, radio
(``other=True`` accepts free text), org (organization autocomplete, stored as
text), file (evidence upload), daterange is expressed as start_date/end_date.
"""
from __future__ import annotations

NAT_INT = ["National", "International"]
PROJECT_STATUS = ["Completed", "In Process", "Delayed"]
PROPOSAL_STATUS = ["Pending", "Under review", "Approved", "Not approved", "Withdrawn"]
IP_CATEGORY = ["Patent", "Trade mark", "Design patent", "Copyrights", "Product", "Process", "Technology",
               "Software", "Method"]
DEV_STATUS = ["Idea", "Design", "Prototype", "Validation", "Production"]
EVENT_KIND = ["Training", "Workshop", "Seminar", "Conference", "Webinar"]
AUDIENCE = ["Students", "Faculty", "Researchers", "Industry", "Mixed"]
THEMATIC_AREAS = [
    "Health Sciences", "Pharmacy & Medicinal Chemistry", "Psychology, Psychiatry and Neuroscience",
    "Plant Sciences", "Chemistry", "Animal Sciences", "Earth Systems and Environmental Sciences",
    "Biotechnology", "Engineering & Technology", "Mathematical Sciences", "Physics",
    "Social and Behavioral Sciences", "Management Sciences", "Computer Science and Informatics", "Education",
    "Arts and Humanities", "Economics", "Other sectors that have potential for growth and impact",
]

PILLARS = [
    {"key": "RE", "index": "B", "name": "Research Excellence",
     "tagline": "Research grants, contract research, linkages, policy advocacy & consultancy"},
    {"key": "IC", "index": "C", "name": "Innovation & Commercialization",
     "tagline": "IP, patents, licensing, prototypes, industry collaboration & awards"},
    {"key": "SCB", "index": "D", "name": "Sustainability & Capacity Building",
     "tagline": "Trainings, exhibitions, revenue & strategic planning"},
    {"key": "BIC", "index": "", "name": "Business Incubation (BIC)",
     "tagline": "Faculty startups, spin-offs, startup funding & entrepreneurship events"},
]
PILLAR_BY_KEY = {p["key"]: p for p in PILLARS}


def F(name, label, type="text", required=True, options=None, other=False, help=None, wide=False):
    f = {"name": name, "label": label, "type": type, "required": required}
    if options is not None:
        f["options"] = options
    if other:
        f["other"] = True
    if help:
        f["help"] = help
    if wide or type == "textarea":
        f["wide"] = True
    return f


def EVIDENCE(label="Evidence", required=False, help=None):
    return F("evidence", label, "file", required,
             help=help or "PDF, Word or image, max 10 MB. You can also paste a link below.")


def EVIDENCE_LINK():
    return F("evidence_link", "Evidence link", "url", required=False,
             help="Google Drive / web link, if the evidence is hosted elsewhere.")


def P(role, label, *, lead=False, many=False, external=True, required=True):
    """A contributor slot. ``lead`` = the record's owner (PI / lead inventor)."""
    return {"role": role, "label": label, "lead": lead, "many": many, "external": external, "required": required}


PI = P("pi", "Principal Investigator (PI)", lead=True)
CO_PI = P("co_pi", "Co-PI(s)", many=True, required=False)
LEAD_INVENTOR = P("inventor", "Lead inventor", lead=True)
CO_INVENTORS = P("co_inventor", "Co-inventor(s)", many=True, required=False)


def duration():
    return [F("start_date", "Start date", "date", required=False), F("end_date", "End date", "date", required=False)]


def grant_fields(*, date_name, date_label, amount_name, amount_label, nat_int=True, extra_before=(),
                 extra_after=(), grant_help=None):
    return [
        F("research_grant_name", "Name of research grant / scheme", help=grant_help),
        F("funding_agency", "Funding agency", "org", required=False),
        F(date_name, date_label, "date"),
        *([F("national_or_international", "National or international", "select", options=NAT_INT)]
          if nat_int else []),
        F("thematic_area", "Thematic area", "select", options=THEMATIC_AREAS, other=True),
        F("research_proposal_title", "Title of research proposal", wide=True),
        *duration(),
        *extra_before,
        F(amount_name, amount_label, "decimal"),
        F("collaborating_partners", "Collaborating partner(s)", "textarea", required=False),
        F("co_funding_partners", "Co-funding partner(s)", "textarea", required=False),
        *extra_after,
        F("remarks", "Remarks / other information", "textarea", required=False),
        EVIDENCE(), EVIDENCE_LINK(),
    ]


def invention_fields(*, dev_options=DEV_STATUS):
    return [
        F("invention_title", "Title of invention", wide=True),
        F("ip_category", "Category of IP", "radio", options=IP_CATEGORY, other=True),
        F("development_status", "Development status", "radio", options=dev_options, other=True),
        F("key_scientific_aspects", "Key scientific aspects / milestones", "textarea"),
    ]


def event_fields(*, organizer=False, audience=True, kinds=EVENT_KIND, staff=False):
    return [
        F("event_type", "Type of event", "radio", options=kinds, other=True),
        F("national_or_international", "National or international", "select", options=NAT_INT),
        F("title", "Title of event", wide=True),
        F("event_date", "Date of event", "date"),
        F("participants", "Number of participants", "int", required=False),
        F("focus_and_outcomes", "Major focus area & outcomes", "textarea"),
        *([F("organizer", "Organizer", "org")] if organizer else []),
        *([F("audience_type", "Audience type", "select", options=AUDIENCE)] if audience else []),
        *([F("oric_personnel", "ORIC personnel who attended", "textarea")] if staff else []),
        EVIDENCE(), EVIDENCE_LINK(),
    ]


def C(key, pillar, title, *, form="", excel="", kpis=(), fields, people=(), oric_only=False, title_field=None,
      date_field=None, amount_field=None, amount_unit="M", scope_field=None, funding_source=None,
      next_stages=(), short=None, help=None, group=None):
    return {
        "key": key, "pillar": pillar, "title": title, "short": short or title, "form": form, "excel": excel,
        "kpis": list(kpis), "fields": fields, "people": list(people), "oric_only": oric_only,
        "title_field": title_field, "date_field": date_field, "amount_field": amount_field,
        "amount_unit": amount_unit, "scope_field": scope_field, "funding_source": funding_source,
        "next_stages": list(next_stages), "help": help, "group": group or title,
    }


# =============================================================================
# RE — Research Excellence (Index-B, RIC Form-1)
# =============================================================================
RE = [
    C("grant_opportunity", "RE", "Research grant opportunity circulated", short="Grant opportunity",
      excel="B.i", kpis=["B.i"], oric_only=True, group="ORIC operations",
      title_field="opportunity_title", date_field="circulation_date", scope_field="national_or_international",
      fields=[
          F("opportunity_title", "Title of grant opportunity (funding agency)", wide=True),
          F("funding_agency", "Funding agency", "org", required=False),
          F("circulation_date", "Date of circulation", "date"),
          F("national_or_international", "National or international", "select", options=NAT_INT),
          F("thematic_area", "Thematic area", "select", options=THEMATIC_AREAS, other=True, required=False),
          F("research_proposal_title", "Resulting proposal title (if any)", required=False),
          *duration(),
          F("collaborating_partners", "Collaborating partner(s)", "textarea", required=False),
          F("co_funding_partners", "Co-funding partner(s)", "textarea", required=False),
          F("award_status", "Status", "select", options=["Not Awarded", "Awarded", "Pending"], required=False),
          F("remarks", "Remarks", "textarea", required=False),
          EVIDENCE(), EVIDENCE_LINK(),
      ]),

    # ---- HEC grants -----------------------------------------------------------
    C("grant_hec_submitted", "RE", "HEC research proposal submitted", short="HEC proposal submitted",
      form="F1 · 1(a)(i)-A", excel="B.ii", kpis=["B.ii", "B.iii"], group="Research grants",
      people=[PI, CO_PI], title_field="research_proposal_title", date_field="proposal_submission_date",
      amount_field="total_funding_requested", funding_source="HEC", next_stages=["grant_hec_approved"],
      fields=grant_fields(date_name="proposal_submission_date", date_label="Date of proposal submission",
                          amount_name="total_funding_requested", amount_label="Total funding requested (PKR million)",
                          nat_int=False, grant_help="NRPU, GCF, TTSF, ICRG, LCF, TDF …",
                          extra_after=[F("status", "Status", "select", options=PROPOSAL_STATUS)])),
    C("grant_hec_approved", "RE", "HEC research project approved", short="HEC project approved",
      form="F1 · 1(a)(ii)-A", excel="B.iii", kpis=["B.iii", "B.ix"], group="Research grants",
      people=[PI, CO_PI], title_field="research_proposal_title", date_field="proposal_approval_date",
      amount_field="total_funding_approved", funding_source="HEC", next_stages=["grant_hec_completed"],
      fields=grant_fields(date_name="proposal_approval_date", date_label="Date of approval",
                          amount_name="total_funding_approved", amount_label="Total funding approved (PKR million)",
                          nat_int=False,
                          extra_after=[F("oric_overhead", "ORIC overhead in approved funding (PKR million)",
                                         "decimal", required=False)])),
    C("grant_hec_completed", "RE", "HEC research project completed", short="HEC project completed",
      form="F1 · 1(a)(iii)-A", excel="B.iv", kpis=["B.iv"], group="Research grants",
      people=[PI, CO_PI], title_field="research_proposal_title", date_field="project_completion_date",
      amount_field="total_funding_utilized", funding_source="HEC",
      fields=grant_fields(date_name="project_completion_date", date_label="Date of project completion",
                          amount_name="total_funding_utilized", amount_label="Total funding utilized (PKR million)",
                          nat_int=False,
                          extra_before=[F("project_status", "Status of project", "select", options=PROJECT_STATUS)],
                          extra_after=[
                              F("total_funding_released", "Total funding released (PKR million)", "decimal",
                                required=False),
                              F("key_project_deliverables", "Key project deliverables & outcomes", "textarea"),
                          ])),

    # ---- Non-HEC grants -------------------------------------------------------
    C("grant_nonhec_submitted", "RE", "Non-HEC research proposal submitted", short="Non-HEC proposal submitted",
      form="F1 · 1(a)(i)-B", excel="B.v", kpis=["B.v", "B.vi"], group="Research grants",
      people=[PI, CO_PI], title_field="research_proposal_title", date_field="proposal_submission_date",
      amount_field="total_funding_requested", funding_source="NON_HEC", scope_field="national_or_international",
      next_stages=["grant_nonhec_approved"],
      fields=grant_fields(date_name="proposal_submission_date", date_label="Date of proposal submission",
                          amount_name="total_funding_requested", amount_label="Total funding requested (PKR million)",
                          extra_after=[F("status", "Status", "select", options=PROPOSAL_STATUS)])),
    C("grant_nonhec_approved", "RE", "Non-HEC research project approved", short="Non-HEC project approved",
      form="F1 · 1(a)(ii)-B", excel="B.vi", kpis=["B.vi", "B.ix"], group="Research grants",
      people=[PI, CO_PI], title_field="research_proposal_title", date_field="proposal_approval_date",
      amount_field="total_funding_approved", funding_source="NON_HEC", scope_field="national_or_international",
      next_stages=["grant_nonhec_completed"],
      fields=grant_fields(date_name="proposal_approval_date", date_label="Date of approval",
                          amount_name="total_funding_approved", amount_label="Total funding approved (PKR million)",
                          extra_after=[F("oric_overhead", "ORIC overhead in approved funding (PKR million)",
                                         "decimal", required=False)])),
    C("grant_nonhec_completed", "RE", "Non-HEC research project completed", short="Non-HEC project completed",
      form="F1 · 1(a)(iii)-B", excel="B.vii", kpis=["B.vii"], group="Research grants",
      people=[PI, CO_PI], title_field="research_proposal_title", date_field="project_completion_date",
      amount_field="total_funding_utilized", funding_source="NON_HEC", scope_field="national_or_international",
      fields=grant_fields(date_name="project_completion_date", date_label="Date of project completion",
                          amount_name="total_funding_utilized", amount_label="Total funding utilized (PKR million)",
                          extra_before=[F("project_status", "Status of project", "select", options=PROJECT_STATUS)],
                          extra_after=[
                              F("total_funding_released", "Total funding released (PKR million)", "decimal",
                                required=False),
                              F("key_project_deliverables", "Key project deliverables & outcomes", "textarea"),
                          ])),

    # ---- Joint projects -------------------------------------------------------
    C("joint_submitted", "RE", "Joint research project submitted", short="Joint project submitted",
      form="F1 · 1(a)(iv)-A", excel="B.viii-a", kpis=["B.viii"], group="Research grants",
      people=[PI, CO_PI], title_field="research_proposal_title", date_field="submission_date",
      amount_field="total_funding_requested", funding_source="JOINT", scope_field="national_or_international",
      next_stages=["joint_approved"],
      fields=grant_fields(date_name="submission_date", date_label="Date of joint project submission",
                          amount_name="total_funding_requested", amount_label="Total funding requested (PKR million)",
                          extra_after=[F("status", "Status / remarks", required=False)])),
    C("joint_approved", "RE", "Joint research project approved", short="Joint project approved",
      form="F1 · 1(a)(iv)-B", excel="B.viii-b", kpis=["B.viii", "B.ix"], group="Research grants",
      people=[PI, CO_PI], title_field="research_proposal_title", date_field="approval_date",
      amount_field="total_funding_approved", funding_source="JOINT", scope_field="national_or_international",
      next_stages=["joint_completed"],
      fields=grant_fields(date_name="approval_date", date_label="Date of joint project approval",
                          amount_name="total_funding_approved", amount_label="Total funding approved (PKR million)",
                          extra_after=[F("status", "Status / remarks", required=False)])),
    C("joint_completed", "RE", "Joint research project completed", short="Joint project completed",
      form="F1 · 1(a)(iv)-C", excel="B.viii-c", kpis=[], group="Research grants",
      people=[PI, CO_PI], title_field="research_proposal_title", date_field="completion_date",
      amount_field="total_funding_utilized", funding_source="JOINT", scope_field="national_or_international",
      fields=grant_fields(date_name="completion_date", date_label="Date of joint project completion",
                          amount_name="total_funding_utilized", amount_label="Total funding utilized (PKR million)",
                          extra_before=[F("project_status", "Status of project", "select", options=PROJECT_STATUS)],
                          extra_after=[
                              F("total_funding_released", "Total funding released (PKR million)", "decimal",
                                required=False),
                              F("key_project_deliverables", "Key project deliverables & outcomes", "textarea"),
                          ])),

    C("irb_review", "RE", "Proposal reviewed by IRB", short="IRB review", excel="B.x", kpis=["B.x"],
      oric_only=True, group="ORIC operations", people=[PI], title_field="research_proposal_title",
      date_field="review_date", amount_field="total_amount_requested",
      fields=[
          F("research_grant_name", "Research grant & funding body applied"),
          F("review_date", "Date of review", "date"),
          F("thematic_area", "Thematic area", "select", options=THEMATIC_AREAS, other=True, required=False),
          F("research_proposal_title", "Title of research proposal", wide=True),
          F("total_amount_requested", "Total amount requested (PKR million)", "decimal", required=False),
          *duration(),
          F("irb_decision", "IRB meeting decision", "select",
            options=["Approved", "Require modification", "Deferred", "Disapproved"]),
          F("key_deliverables", "Key expected deliverables & outcomes", "textarea", required=False),
          EVIDENCE("IRB meeting minutes"), EVIDENCE_LINK(),
      ]),

    # ---- Other RE activities -----------------------------------------------------
    C("contract_research", "RE", "Contract research awarded", short="Contract research",
      form="F1 · 1(b)", excel="B.xiii / B.xiv", kpis=["B.xiii", "B.xiv", "B.xv"], group="Industry & linkages",
      people=[PI, CO_PI], title_field="research_proposal_title", date_field="contract_signed_date",
      amount_field="total_amount_approved", scope_field="national_or_international",
      fields=[
          F("thematic_area", "Thematic area", "select", options=THEMATIC_AREAS, other=True, required=False),
          F("research_proposal_title", "Title of research / contract", wide=True),
          F("contract_signed_date", "Date contract signed", "date"),
          F("sponsoring_agency", "Sponsoring agency (name, address & country)", "org"),
          F("national_or_international", "National or international", "select", options=NAT_INT),
          F("counterpart_industry", "Counterpart from industry (address with country)", required=False),
          *duration(),
          F("total_amount_approved", "Total amount approved (PKR million)", "decimal"),
          F("expected_deliverables", "Expected deliverables & outcomes", "textarea", required=False),
          EVIDENCE("Contract research agreement"), EVIDENCE_LINK(),
      ]),
    C("policy_advocacy", "RE", "Policy advocacy / case study presented", short="Policy advocacy",
      form="F1 · 2(a)", excel="B.xi", kpis=["B.xi"], group="Industry & linkages", people=[PI],
      title_field="brief", date_field="presentation_date",
      fields=[
          F("government_body_presented", "Government body presented to", "org"),
          F("presentation_date", "Date of presentation", "date"),
          F("advocacy_area", "Area advocated", "select",
            options=["Education", "Economic Development", "Construction", "Security", "Cybersecurity",
                     "Political", "Law & Order", "Social Progress", "Health", "Environment", "Energy"],
            other=True),
          F("brief", "Brief", "textarea"),
          *duration(),
          F("coalition_partners", "Coalition partners in advocacy", required=False),
          F("research_status", "Issue verification / backing research status", required=False),
          F("advocacy_tools", "Advocacy tools adopted", required=False,
            help="Briefings, meetings, websites, social media debates …"),
          EVIDENCE("Policy / case-study brief"), EVIDENCE_LINK(),
      ]),
    C("research_link", "RE", "Research link / MoU established", short="Research link (MoU)",
      form="F1 · 2(b)", excel="B.xii", kpis=["B.xii"], group="Industry & linkages", people=[
          P("focal", "NED focal person", lead=True, required=False)],
      title_field="collaborating_agency", date_field="mou_agreement_date", scope_field="national_or_international",
      fields=[
          F("linkage_type", "Type of linkage", "select", options=["Academic", "Research"]),
          F("mou_agreement_date", "Date of MoU / agreement", "date"),
          F("national_or_international", "National or international", "select", options=NAT_INT),
          F("host_institution", "Host institution (name, address & country)", required=False),
          F("collaborating_agency", "Collaborating agency / institution (name, address & country)", "org"),
          F("field_of_study", "Field of study / broad research areas"),
          F("scope_of_collaboration", "Scope of collaboration", "textarea"),
          F("salient_features", "Salient features of linkage", "textarea", required=False),
          EVIDENCE("MoU copy"), EVIDENCE_LINK(),
      ]),
    C("civic_engagement", "RE", "Civic engagement event / initiative", short="Civic engagement",
      form="F1 · 3(a)", excel="B.xvi", kpis=["B.xvi"], group="Industry & linkages",
      people=[P("lead", "Lead / organizer", lead=True)], title_field="event_title", date_field="event_date",
      amount_field="grant_value", amount_unit="PKR",
      fields=[
          F("event_title", "Title of event / initiative", wide=True),
          F("event_date", "Date of event", "date"),
          F("community_component", "Component of community involved / addressed"),
          F("outcome", "Outcome (case study, policy advice …)", "textarea"),
          F("collaboration_developed", "Collaboration developed (local authorities, government departments)",
            required=False),
          F("engaged_csos_ngos", "CSOs / NGOs engaged", required=False),
          F("sponsoring_agency", "Sponsoring agency / sponsors", "org", required=False),
          F("grant_value", "Grant value / sponsorship (PKR)", "decimal", required=False),
          F("arranged_or_participated", "Arranged or participated", "select", options=["Arranged", "Participated"]),
          F("dissemination_material", "Dissemination / outcome material (brochure, report, web link)",
            required=False),
          F("remarks", "Remarks", "textarea", required=False),
          EVIDENCE("Event report / brochure"), EVIDENCE_LINK(),
      ]),
    C("consultancy_opportunity", "RE", "Consultancy opportunity circulated", short="Consultancy opportunity",
      excel="B.xvii", kpis=["B.xvii"], oric_only=True, group="ORIC operations", people=[PI],
      title_field="project_title", date_field="circulation_date", amount_field="contract_value",
      fields=[
          F("project_title", "Title of project", wide=True),
          F("circulation_date", "Date of circulation", "date"),
          F("company_details", "Company details (name, country …)", "org"),
          F("contract_value", "Contract value (PKR million)", "decimal", required=False),
          *duration(),
          F("consultancy_type", "Type of consultancy services", required=False),
          F("key_deliverables", "Key deliverables", "textarea", required=False),
          F("remarks", "Remarks", "textarea", required=False),
          EVIDENCE(), EVIDENCE_LINK(),
      ]),
    C("consultancy_contract", "RE", "Consultancy contract executed through ORIC", short="Consultancy contract",
      form="F1 · 3(b)", excel="B.xviii", kpis=["B.xviii"], group="Industry & linkages", people=[PI],
      title_field="project_title", date_field="execution_date", amount_field="contract_value",
      fields=[
          F("project_title", "Title of project", wide=True),
          F("execution_date", "Date of execution", "date"),
          F("company_details", "Company details (name, country …)", "org"),
          F("contract_value", "Contract value (PKR million)", "decimal"),
          *duration(),
          F("consultancy_type", "Type of consultancy services", "radio",
            options=["Testing", "Training", "Feasibility", "Prototype Development", "Analysis", "Design"],
            other=True),
          F("key_deliverables", "Key deliverables", "textarea", required=False),
          F("oric_percentage", "ORIC share (%)", "decimal", required=False),
          F("remarks", "Remarks", "textarea", required=False),
          EVIDENCE("Contract copy"), EVIDENCE_LINK(),
      ]),
    C("asrb_liaison", "RE", "Liaison with AS&RB", short="AS&RB liaison", form="F1 · 3(c)", excel="B.xix",
      kpis=["B.xix"], group="Industry & linkages", people=[P("lead", "Faculty member", lead=True)],
      title_field="liaison_with", date_field="execution_date",
      fields=[
          F("liaison_with", "Liaison developed with", wide=True),
          F("execution_date", "Date of execution", "date"),
          EVIDENCE(), EVIDENCE_LINK(),
      ]),
    C("publication", "RE", "Research publication (HJRS)", short="Publication", form="F2 · 13", excel="",
      group="Publications", people=[P("author", "NED author", lead=True), P("co_author", "Co-author(s)", many=True,
                                                                             required=False)],
      title_field="publication_title", date_field="publication_date",
      fields=[
          F("publication_title", "Title of paper", wide=True),
          F("publication_category", "HJRS category", "select", options=["W", "X", "Y"]),
          F("journal", "Journal / venue"),
          F("publication_date", "Publication date", "date"),
          F("publication_reference", "Full reference", "textarea",
            help="e.g. Khalid A., Ali S.N. (2025) Title. Journal, vol(issue), pages."),
          F("publication_link", "Publication link / DOI", "url"),
          EVIDENCE("First page of publication"),
      ]),
]

# =============================================================================
# IC — Innovation & Commercialization (Index-C, RIC Form-2)
# =============================================================================
IC = [
    C("policy", "IC", "Research / IP / other policy", short="Policy", excel="C.i–iii", kpis=["C.i", "C.ii", "C.iii"],
      oric_only=True, group="ORIC operations", title_field="policy_title", date_field="approval_date",
      fields=[
          F("policy_type", "Policy type", "select", options=["Research policy", "IP policy", "Other policy"]),
          F("policy_title", "Title of policy", wide=True),
          F("policy_ref_no", "Policy reference no.", required=False),
          F("approval_date", "Date of approval", "date", required=False),
          F("approved_by", "Approved by", required=False),
          EVIDENCE(), EVIDENCE_LINK(),
      ]),
    C("ip_disclosure", "IC", "IP disclosure made", short="IP disclosure", form="F2 · 5(a)", excel="C.iv",
      kpis=["C.iv"], group="Intellectual property", people=[LEAD_INVENTOR, CO_INVENTORS],
      title_field="invention_title", date_field="disclosure_date",
      fields=[
          *invention_fields(),
          F("commercial_partner", "Commercial partner", required=False),
          F("disclosure_made_with", "Disclosure made with (patent dept / attorney)"),
          F("disclosure_date", "Date of disclosure", "date"),
          F("national_or_international", "National or international", "select", options=NAT_INT, required=False),
          F("financial_support", "Financial support", required=False),
          F("previous_disclosure", "Previous disclosure", required=False),
          EVIDENCE("Patent disclosure form"), EVIDENCE_LINK(),
      ]),
    C("patent", "IC", "Patent / trademark / design / copyright filed or granted", short="Patent / IP filed or granted",
      form="F2 · 5(b)", excel="C.v–viii", kpis=["C.v", "C.vi", "C.vii", "C.viii"], group="Intellectual property",
      people=[LEAD_INVENTOR, CO_INVENTORS], title_field="invention_title", date_field="filing_date",
      scope_field="national_or_international", next_stages=["patent"],
      fields=[
          F("filed_or_granted", "Filed or granted", "select", options=["Filed", "Granted"]),
          F("national_or_international", "National or international", "select", options=NAT_INT),
          *invention_fields(),
          F("commercial_partner", "Commercial partner", required=False),
          F("filed_with", "Filed with / granting authority (name & details)", "org",
            help="e.g. IPO-Pakistan"),
          F("application_no", "Application / patent no.", required=False),
          F("filing_date", "Date of filing / grant", "date"),
          F("financial_support", "Financial support", required=False),
          EVIDENCE("Filing / granting proof"), EVIDENCE_LINK(),
      ]),
    C("licensing_negotiation", "IC", "IP licensing negotiation initiated", short="Licensing negotiation",
      form="F2 · 5(c)(i)", excel="C.ix / C.xi", kpis=["C.ix", "C.xi"], group="Intellectual property",
      people=[LEAD_INVENTOR], title_field="invention_title", date_field="negotiation_date",
      scope_field="national_or_international", next_stages=["license_signed"],
      fields=[
          F("national_or_international", "National or international", "select", options=NAT_INT),
          *invention_fields(dev_options=["Prototype", "Validation", "Production"]),
          F("field_of_use", "Field of use"),
          F("negotiation_date", "Date negotiation initiated", "date", required=False),
          F("duration_of_agreement", "Duration of agreement", required=False),
          F("licensee", "Licensee (name, organization)", "org"),
          F("negotiation_status", "Status of negotiation"),
          EVIDENCE("Negotiation proof"), EVIDENCE_LINK(),
      ]),
    C("license_signed", "IC", "Exclusive / non-exclusive license signed", short="License signed",
      form="F2 · 5(c)(ii)", excel="C.x / C.xii", kpis=["C.x", "C.xii"], group="Intellectual property",
      people=[LEAD_INVENTOR], title_field="invention_title", date_field="agreement_date",
      scope_field="national_or_international",
      fields=[
          F("license_type", "Exclusive or non-exclusive", "select", options=["Exclusive", "Non-Exclusive"]),
          F("national_or_international", "National or international", "select", options=NAT_INT),
          *invention_fields(),
          F("field_of_use", "Field of use"),
          F("agreement_date", "Date of agreement", "date"),
          F("agreement_duration", "Duration of agreement", required=False),
          F("licensee", "Licensee (name, organization)", "org"),
          EVIDENCE("Agreement cover copy"), EVIDENCE_LINK(),
      ]),
    C("prototype", "IC", "Product / process / prototype developed", short="Prototype / product",
      form="F2 · 5(d)", excel="C.xiii", kpis=["C.xiii"], group="Products & industry",
      people=[LEAD_INVENTOR, CO_INVENTORS], title_field="invention_title", scope_field="national_or_international",
      date_field="development_date",
      fields=[
          F("national_or_international", "National or international", "select", options=NAT_INT),
          *invention_fields(),
          F("development_date", "Date", "date", required=False),
          F("field_of_use", "Field of use"),
          F("industrial_partner", "Collaborating industrial partner", "org", required=False),
          F("financial_support", "Financial support", required=False),
          F("remarks", "Remarks", "textarea", required=False),
          EVIDENCE("Proof from industrial partner"), EVIDENCE_LINK(),
      ]),
    C("creative_product", "IC", "Science / arts / design product displayed", short="Science / arts product",
      form="F2 · 5(e)", excel="C.xiv", kpis=["C.xiv"], group="Products & industry",
      people=[P("lead", "Lead", lead=True), P("team", "Team member(s)", many=True, required=False)],
      title_field="title", scope_field="national_or_international", date_field="display_date",
      fields=[
          F("title", "Title", wide=True),
          F("product_category", "Category", "radio", options=["Science", "Arts", "Design Product", "Exhibition"],
            other=True),
          F("national_or_international", "National or international", "select", options=NAT_INT),
          F("forum", "Forum where registered / performed / displayed"),
          F("display_date", "Date", "date", required=False),
          F("status", "Status", required=False),
          F("financial_support", "Financial support", required=False),
          F("field_of_use", "Field of use", required=False),
          EVIDENCE(), EVIDENCE_LINK(),
      ]),
    C("industry_visit", "IC", "Visit by industry / community representatives", short="Industry visit",
      form="F2 · 6(a)", excel="C.xv", kpis=["C.xv"], group="Products & industry",
      people=[P("host", "NED host", lead=True, required=False)], title_field="visitor_name", date_field="visit_date",
      fields=[
          F("visitor_name", "Visitor / organization", "org"),
          F("visit_date", "Date of visit", "date"),
          F("agenda", "Agenda of visit", "textarea"),
          EVIDENCE(), EVIDENCE_LINK(),
      ]),
    C("collaboration_agreement", "IC", "Collaboration agreement with industry / government / community",
      short="Collaboration agreement", form="F2 · 6(b)", excel="C.xvi", kpis=["C.xvi"], group="Products & industry",
      people=[P("focal", "NED focal person", lead=True, required=False)], title_field="partner_institution",
      date_field="establishment_date", scope_field="national_or_international",
      fields=[
          F("linkage_type", "Type of linkage", "select",
            options=["Academic", "Research", "Industry", "Government", "Community"]),
          F("national_or_international", "National or international", "select", options=NAT_INT),
          F("partner_institution", "Partner institution (name, address & country)", "org"),
          F("duration", "Duration", required=False),
          F("key_initiatives", "Key initiatives to be undertaken", "textarea"),
          F("field", "Field", required=False),
          F("scope_of_collaboration", "Scope of collaboration", "textarea", required=False),
          F("establishment_date", "Linkage establishment date", "date"),
          F("financial_support", "Financial support", required=False),
          EVIDENCE("MoU copy"), EVIDENCE_LINK(),
      ]),
    C("award", "IC", "National / international honour or award", short="Honour / award", form="F2 · 7",
      excel="C.xvii", kpis=["C.xvii"], group="Products & industry",
      people=[P("winner", "Award winner", lead=True), P("team", "Team member(s)", many=True, required=False)],
      title_field="title", date_field="award_date", amount_field="prize_money", amount_unit="PKR",
      scope_field="national_or_international",
      fields=[
          F("title", "Title of award / honour", wide=True),
          F("conferring_organization", "Forum / conferring organization", "org"),
          F("national_or_international", "National or international", "select", options=NAT_INT, required=False),
          F("award_date", "Date", "date", required=False),
          F("award_received", "Award / prize / certificate received"),
          F("work_details", "Brief details of work honoured", "textarea"),
          F("prize_money", "Prize money (PKR)", "decimal", required=False),
          F("remarks", "Remarks", "textarea", required=False),
          EVIDENCE(), EVIDENCE_LINK(),
      ]),
]

# =============================================================================
# SCB — Sustainability & Capacity Building (Index-D, RIC Form-2 §8)
# =============================================================================
SCB = [
    C("strategic_plan", "SCB", "Five-year strategic plan", short="Strategic plan", excel="D.ia", kpis=["D.ia"],
      oric_only=True, group="ORIC operations", title_field="title", date_field="approval_date",
      fields=[
          F("title", "Title", wide=True),
          F("approval_date", "Date of approval", "date", required=False),
          F("period", "Plan period", required=False),
          F("notes", "Notes", "textarea", required=False),
          EVIDENCE(), EVIDENCE_LINK(),
      ]),
    C("research_revenue", "SCB", "ORIC research revenue / overhead", short="Research revenue", excel="D.i",
      kpis=["D.i"], oric_only=True, group="ORIC operations", people=[PI], title_field="research_proposal_title",
      date_field="approval_date", amount_field="oric_overhead_released", amount_unit="PKR",
      scope_field="national_or_international",
      fields=[
          F("research_grant_name", "Research grant (individual or joint)"),
          F("national_or_international", "National or international", "select", options=NAT_INT, required=False),
          F("research_proposal_title", "Title of research proposal", wide=True),
          F("approval_date", "Date", "date", required=False),
          *duration(),
          F("total_funding_approved", "Total funding approved (PKR million)", "decimal", required=False),
          F("total_funding_released", "Total funding released (PKR million)", "decimal", required=False),
          F("oric_overhead_approved", "ORIC overhead in approved funding (PKR)", "decimal", required=False),
          F("oric_overhead_released", "ORIC overhead in released funding (PKR)", "decimal", required=False),
          F("remarks", "Remarks", "textarea", required=False),
          EVIDENCE("Audited statement"), EVIDENCE_LINK(),
      ]),
    C("licensing_revenue", "SCB", "Licensing / royalty revenue", short="Licensing revenue", excel="D.ii",
      kpis=["D.ii"], oric_only=True, group="ORIC operations", people=[LEAD_INVENTOR], title_field="invention_title",
      date_field="agreement_date", amount_field="total_amount", scope_field="national_or_international",
      fields=[
          F("invention_title", "Title of invention", wide=True),
          F("national_or_international", "National or international", "select", options=NAT_INT, required=False),
          F("agreement_date", "Date of agreement", "date", required=False),
          F("agreement_duration", "Duration of agreement", required=False),
          F("licensee", "Licensee (name, organization)", "org"),
          F("share_percentages", "Fee / royalty share % (ORIC / University / Inventor)", required=False),
          F("total_amount", "Total amount in lieu of royalty / fee (PKR million)", "decimal"),
          F("oric_approved_share", "ORIC approved share (PKR million)", "decimal", required=False),
          F("oric_received_share", "ORIC received share (PKR million)", "decimal", required=False),
          F("remarks", "Remarks", "textarea", required=False),
          EVIDENCE("Audited statement"), EVIDENCE_LINK(),
      ]),
    C("training_oric", "SCB", "Training / workshop arranged by ORIC", short="ORIC training / workshop",
      form="F2 · 8(a)", excel="D.iii", kpis=["D.iii"], group="Trainings & events",
      people=[P("lead", "Organizer / resource person", lead=True, required=False)], title_field="title",
      date_field="event_date", scope_field="national_or_international", fields=event_fields()),
    C("training_external", "SCB", "Training / workshop by other HEIs / partners", short="External training",
      form="F2 · 8(b)", excel="D.iv", kpis=["D.iv"], group="Trainings & events",
      people=[P("lead", "Faculty member", lead=True, required=False)], title_field="title", date_field="event_date",
      scope_field="national_or_international", fields=event_fields(organizer=True)),
    C("exhibition", "SCB", "Exhibition / showcasing event / linkage fair", short="Exhibition / showcase",
      form="F2 · 8(c)", excel="D.v", kpis=["D.v"], group="Trainings & events",
      people=[P("lead", "Organizer", lead=True, required=False)], title_field="title", date_field="event_date",
      scope_field="national_or_international",
      fields=event_fields(organizer=True, kinds=["Exhibition", "Showcasing Event", "Industry Linkages Fair",
                                                 "Seminar", "Industry or IP & Licensing Stimulus"])),
    C("training_oric_staff", "SCB", "Training attended by ORIC personnel", short="ORIC staff training",
      excel="D.vi", kpis=["D.vi"], oric_only=True, group="ORIC operations", title_field="title",
      date_field="event_date", scope_field="national_or_international",
      fields=event_fields(organizer=True, audience=False, staff=True)),
]

# =============================================================================
# BIC — Business Incubation Centre (RIC Form-3)
# =============================================================================
BIC = [
    C("startup", "BIC", "Faculty-led startup", short="Faculty startup", form="F3 · Startups", group="Startups",
      people=[P("founder", "Founder (faculty)", lead=True), P("co_founder", "Co-founder(s)", many=True,
                                                              required=False)],
      title_field="startup_name", amount_field="revenue", amount_unit="PKR",
      fields=[
          F("startup_name", "Name of the startup"),
          F("sector", "Sector / field (thematic area)"),
          F("stage", "Stage of product or service", help="Initial, prototype developed, …"),
          F("ip_status", "IP status", "select",
            options=["Not applicable", "Not filed (will file in future)", "Disclosed", "Filed/under process",
                     "Granted"]),
          F("license_agreement", "License agreement signed (and with whom)", required=False),
          F("funding_source", "Funds secured and source of funding", required=False),
          F("revenue", "Revenue generated (PKR)", "decimal", required=False),
          F("internships_created", "Internships created", "int", required=False),
          F("jobs_created", "Jobs created", "int", required=False),
          EVIDENCE("Registration / fundraising evidence"), EVIDENCE_LINK(),
      ]),
    C("spinoff", "BIC", "Faculty startup spin-off", short="Spin-off", form="F3 · Spin-offs", group="Startups",
      people=[P("founder", "Founder (faculty)", lead=True)], title_field="spinoff_name", amount_field="revenue",
      amount_unit="PKR",
      fields=[
          F("spinoff_name", "Name of the spin-off"),
          F("stage", "Stage of spin-off", "select",
            options=["Not applicable", "Initial", "Pilot", "Commercial Production"], other=True),
          F("license_agreement", "License agreement signed", required=False),
          F("revenue", "Revenue generated (PKR)", "decimal", required=False),
          EVIDENCE(), EVIDENCE_LINK(),
      ]),
    C("startup_funding", "BIC", "Funding secured by startup / spin-off", short="Startup funding",
      form="F3 · Funding", group="Startups", people=[P("founder", "Founder (faculty)", lead=True)],
      title_field="startup_details", amount_field="amount", amount_unit="PKR",
      fields=[
          F("startup_details", "Startup (name and sector / field)"),
          F("funding_agency", "Funding agency", "org"),
          F("funding_type", "Type of funding", "select",
            options=["Award prize (competition win)", "Pre-seed", "Seed", "Angel investment", "VC"], other=True),
          F("amount", "Amount secured and utilized (PKR)", "decimal"),
          F("agreement_signed", "Agreement signed with funding agency", "select", options=["Yes", "No"]),
          F("in_kind_support", "In-kind support (details)", required=False),
          EVIDENCE(), EVIDENCE_LINK(),
      ]),
    C("entrepreneurship_event", "BIC", "Entrepreneurship training / event participation",
      short="Entrepreneurship event", form="F3 · Events", group="Startups",
      people=[P("participant", "Faculty member", lead=True)], title_field="title", date_field="event_date",
      fields=[
          F("title", "Title of event / activity", wide=True),
          F("event_date", "Date(s) held", "date"),
          F("venue", "Venue"),
          F("field", "Field / thematic area", required=False),
          F("panelist_details", "Panelists / mentors / advisors", "textarea", required=False),
          F("organizers", "Arranged by (organizers)", "org"),
          F("audience", "Targeted audience", "select", options=["Faculty", "Students", "Both"]),
          F("participants_count", "Number of participants (approx.)", "int", required=False),
          EVIDENCE(), EVIDENCE_LINK(),
      ]),
    C("bic_annual", "BIC", "BIC annual figures", short="BIC annual figures", form="F3 · Scorecard data",
      group="Startups", people=[P("faculty", "Faculty member", lead=True)], title_field=None,
      help="One per faculty member per fiscal year.",
      fields=[
          F("jobs_created_retained", "Jobs created & retained over 2 years (faculty startups)", "int"),
          F("students_placed", "Students placed in faculty startups / spin-offs (internships, trainees)", "int"),
          F("participation_count", "Participation of faculty / students in entrepreneurship trainings", "int"),
      ]),
]

CATEGORIES: list[dict] = [*RE, *IC, *SCB, *BIC]
CATEGORY_BY_KEY: dict[str, dict] = {c["key"]: c for c in CATEGORIES}
CATEGORY_CHOICES = [(c["key"], c["short"]) for c in CATEGORIES]
PILLAR_CHOICES = [(p["key"], p["name"]) for p in PILLARS]
ORIC_ONLY_KEYS = frozenset(c["key"] for c in CATEGORIES if c["oric_only"])

assert len(CATEGORY_BY_KEY) == len(CATEGORIES), "duplicate category key"


def lead_slot(category: dict) -> dict | None:
    return next((p for p in category["people"] if p["lead"]), None)


def public_schema() -> dict:
    return {
        "pillars": PILLARS,
        "thematic_areas": THEMATIC_AREAS,
        "categories": CATEGORIES,
    }
