"""
Single source of truth for every ORIC data-collection form.

Reverse-engineered from the legacy portal (http://111.68.109.211:8080) and
cleaned up: labels fixed, "(if any)" fields made optional, consistent
snake_case names. ``legacy`` keeps the original field name so old data can be
migrated (see knowledge/04-data-model.md).

Structure
---------
PILLARS  -> one per legacy "RicForm" (RE = RicForm1, IC = RicForm2, SCB = RicForm3)
  counts   -> the header form ("how many X did you do this year?")
  sections -> one per legacy sub-form (A1..A15, B1..B13, C1..C4); each entry a
              faculty member adds is one SectionEntry row whose ``data`` is
              validated against ``fields``.

Field types: text, textarea, email, url, date, int, decimal, select, radio,
department, file.  ``radio`` with ``other=True`` accepts free text when the
user picks "Other".
"""
from __future__ import annotations

DEPARTMENTS = [
    "Department of Civil Engineering",
    "Department of Urban and Infrastructure Engineering",
    "Department of Petroleum Engineering",
    "Department of Earthquake Engineering",
    "Department of Environmental Engineering",
    "Department of Electrical Engineering",
    "Department of Electronic Engineering",
    "Department of Telecommunications Engineering",
    "Department of Computer and Information Systems Engineering",
    "Department of Bio-Medical Engineering",
    "Department of Computer Science & Information Technology",
    "Department of Software Engineering",
    "Department of Mechanical Engineering",
    "Department of Industrial and Manufacturing Engineering",
    "Department of Textile Engineering",
    "Department of Automotive and Marine Engineering",
    "Department of Chemical Engineering",
    "Department of Polymer and Petrochemical Engineering",
    "Department of Materials Engineering",
    "Department of Metallurgical Engineering",
    "Department of Food Engineering",
    "Department of Architecture and Planning",
    "Department of Economics and Management Sciences",
    "Department of Physics",
    "Department of Chemistry",
    "Department of Mathematics",
    "Department of English Linguistics & Allied Studies",
    "Department of Essential Studies",
]

NAT_INT = ["National", "International"]
PROJECT_STATUS = ["Completed", "In Process", "Delayed"]
IP_CATEGORY = ["Patent", "Trade mark", "Design patent", "Copyrights", "Other"]
DEV_STATUS = ["Idea", "Prototype", "Validation", "Production", "Other"]
EVENT_KIND = ["Training", "Workshop", "Seminar", "Conference", "Other"]
AUDIENCE = ["Student", "Faculty", "Researchers"]


def F(name, label, type="text", required=True, options=None, legacy=None,
      other=False, help=None, money=False):
    f = {"name": name, "label": label, "type": type, "required": required}
    if options is not None:
        f["options"] = options
    if other:
        f["other"] = True
    if help:
        f["help"] = help
    if money:
        f["money"] = True
    f["legacy"] = legacy or name
    return f


def EVIDENCE(label="Evidence", legacy="evidence", required=True, help=None):
    return F("evidence", label, "file", required, legacy=legacy,
             help=help or "PDF or image, max 10 MB.")


# Common blocks ---------------------------------------------------------------
def pi_block(legacy_pi="PI_name", legacy_desig="designation", legacy_dept="department"):
    return [
        F("pi_name", "Name of PI", legacy=legacy_pi),
        F("pi_designation", "PI designation", legacy=legacy_desig),
        F("pi_department", "PI department", "department", legacy=legacy_dept),
    ]


def co_pi_block(univ_legacy="co_PI_University", desig_legacy="co_PI_designation"):
    return [
        F("co_pi_name", "Name of Co-PI", legacy="co_PI_name"),
        F("co_pi_designation", "Co-PI designation", legacy=desig_legacy),
        F("co_pi_department", "Co-PI department", "text", legacy="co_PI_department",
          help="Free text: the Co-PI may belong to another university."),
        F("co_pi_university", "Co-PI university", legacy=univ_legacy),
    ]


def duration():
    return [
        F("start_date", "Duration — start date", "date"),
        F("end_date", "Duration — end date", "date"),
    ]


def invention_block():
    return [
        F("lead_inventor_name", "Name of lead inventor", legacy="leadinventorname"),
        F("lead_inventor_designation", "Designation of lead inventor", legacy="leadinventordesignation"),
        F("lead_inventor_department", "Department of lead inventor", "department", legacy="leadinventordepartment"),
        F("invention_title", "Title of invention", legacy="inventiontitle"),
        F("ip_category", "Category of IP", "radio", options=IP_CATEGORY, other=True, legacy="ipcategory"),
        F("development_status", "Development status", "radio", options=DEV_STATUS, other=True, legacy="developmentstatus"),
        F("key_scientific_aspects", "Key scientific aspects", "textarea", legacy="keyscientificaspects"),
    ]


# =============================================================================
# Pillar RE — Research Excellence (legacy RicForm1, "Research Grants-Industrial
# Linkage-Policy Advocacy FY")
# =============================================================================
RE_COUNTS = [
    F("research_grants_submitted_hec", "Research grants submitted to HEC", "int"),
    F("research_grants_submitted_non_hec", "Research grants submitted to non-HEC sources", "int"),
    F("research_grants_approved_hec", "Research grants approved by HEC", "int"),
    F("research_grants_approved_non_hec", "Research grants approved by non-HEC sources", "int"),
    F("hec_funded_projects_completed", "HEC-funded research projects completed", "int"),
    F("non_hec_funded_projects_completed", "Non-HEC-funded research projects completed", "int"),
    F("joint_projects_submitted", "Joint research projects submitted (national/international agencies)", "int"),
    F("joint_projects_approved", "Joint research projects approved (national/international agencies)", "int"),
    F("joint_projects_completed", "Joint research projects completed (national/international agencies)", "int"),
    F("contract_research_awarded", "Contract research projects awarded", "int"),
    F("policy_advocacy_case_studies", "Policy advocacy / case studies", "int"),
    F("research_links_established", "Research links established", "int"),
    F("civic_engagements", "Civic engagement events", "int"),
    F("consultancy_contracts_executed", "Consultancy contracts executed through ORIC", "int"),
    F("liaison_with_asrb", "Liaisons developed with the university's AS&RB", "int",
      help="Advanced Studies & Research Board."),
]

RE_SECTIONS = [
    {
        "key": "A1", "slug": "research-submitted-hec", "template": 1, "code": "1(a)(i)-A",
        "title": "Research projects submitted for funding to HEC",
        "count_field": "research_grants_submitted_hec",
        "legacy_endpoint": "api/RicForm1/research_project_submitted_hec",
        "amount_field": "total_funding_requested",
        "fields": [
            F("research_grant_name", "Name of research grant", help="NRPU, GCF, TTSF, ICRG, LCF etc."),
            F("proposal_submission_date", "Date of proposal submission", "date"),
            *pi_block(),
            F("thematic_area", "Thematic area"),
            F("research_proposal_title", "Title of research proposal"),
            *duration(),
            F("total_funding_requested", "Total funding requested (PKR million)", "decimal", money=True),
            F("collaborating_partners", "Collaborating partner(s) details", required=False),
            F("co_funding_partners", "Co-funding partner(s) details", required=False),
            F("status", "Status", "select", options=["Pending", "Completed", "Rejected"]),
            F("remarks", "Remarks / any other information", "textarea", required=False),
            EVIDENCE(help="Attach proof of submission (PDF or image, max 10 MB)."),
        ],
    },
    {
        "key": "A2", "slug": "research-submitted-non-hec", "template": 1, "code": "1(a)(i)-B",
        "title": "Research projects submitted for funding to non-HEC sources (national or international)",
        "count_field": "research_grants_submitted_non_hec",
        "legacy_endpoint": "api/RicForm1/research_project_submitted_non_hec",
        "amount_field": "total_funding_requested",
        "fields": [
            F("research_grant_name", "Name of research grant"),
            F("proposal_submission_date", "Date of proposal submission", "date"),
            F("national_or_international", "National or international", "select", options=NAT_INT),
            *pi_block(),
            F("thematic_area", "Thematic area"),
            F("research_proposal_title", "Title of research proposal"),
            *duration(),
            F("total_funding_requested", "Total funding requested (PKR million)", "decimal", money=True),
            F("collaborating_partners", "Collaborating partner(s) details", required=False),
            F("co_funding_partners", "Co-funding partner(s) details", required=False),
            F("status", "Status", "select", options=["Pending", "Completed", "Rejected"]),
            F("remarks", "Remarks / any other information", "textarea", required=False),
            EVIDENCE(),
        ],
    },
    {
        "key": "A3", "slug": "research-approved-hec", "template": 2, "code": "1(a)(ii)-A",
        "title": "Research projects approved for funding by HEC",
        "count_field": "research_grants_approved_hec",
        "legacy_endpoint": "api/RicForm1/submit-research-project-approved-hec",
        "amount_field": "total_funding_approved",
        "fields": [
            F("research_grant_name", "Name of research grant"),
            F("proposal_approval_date", "Date of proposal approval", "date"),
            F("national_or_international", "National or international", "select", options=NAT_INT),
            *pi_block(legacy_desig="PI_name", legacy_dept="PI_name"),
            F("thematic_area", "Thematic area"),
            F("research_proposal_title", "Title of research proposal"),
            *duration(),
            F("total_funding_approved", "Total funding approved (PKR million)", "decimal", money=True),
            F("collaborating_partners", "Collaborating partner(s) details", required=False),
            F("co_funding_partners", "Co-funding partner(s) details", required=False),
            F("approval_date", "Date of approval", "date"),
            EVIDENCE(),
        ],
    },
    {
        "key": "A4", "slug": "research-approved-non-hec", "template": 2, "code": "1(a)(ii)-B",
        "title": "Research projects approved for funding by non-HEC sources",
        "count_field": "research_grants_approved_non_hec",
        "legacy_endpoint": "api/RicForm1/submit-research-project-approved-non-hec",
        "amount_field": "total_funding_approved",
        "fields": [
            F("research_grant_name", "Name of research grant"),
            F("proposal_approval_date", "Date of proposal approval", "date"),
            F("national_or_international", "National or international", "select", options=NAT_INT),
            *pi_block(legacy_desig="PI_name", legacy_dept="PI_name"),
            F("thematic_area", "Thematic area"),
            F("research_proposal_title", "Title of research proposal"),
            *duration(),
            F("total_funding_approved", "Total funding approved (PKR million)", "decimal", money=True),
            F("collaborating_partners", "Collaborating partner(s) details", required=False),
            F("co_funding_partners", "Co-funding partner(s) details", required=False),
            F("approval_date", "Date of approval", "date"),
            EVIDENCE(),
        ],
    },
    {
        "key": "A5", "slug": "hec-projects-completed", "template": 3, "code": "1(a)(iii)-A",
        "title": "HEC-funded research projects completed",
        "count_field": "hec_funded_projects_completed",
        "legacy_endpoint": "api/RicForm1/submit-hec-funded-research-project-completed",
        "amount_field": "total_funding_released",
        "fields": [
            F("research_grant_name", "Name of research grant", help="NRPU, GCF, TTSF, ICRG, LCF etc."),
            F("project_completion_date", "Date of project completion", "date"),
            *pi_block(legacy_desig="PI_name", legacy_dept="PI_name"),
            F("thematic_area", "Thematic area"),
            F("research_proposal_title", "Title of research proposal"),
            *duration(),
            F("total_funding_utilized", "Total funding utilized (PKR million)", "decimal", money=True,
              legacy="total_funding_approved"),
            F("total_funding_released", "Total funding released (PKR million)", "decimal", money=True),
            F("project_status", "Project status", "select", options=PROJECT_STATUS),
            F("key_project_deliverables", "Key project deliverables & outcomes (brief summary)", "file",
              help="Attach a brief summary document."),
            EVIDENCE(),
        ],
    },
    {
        "key": "A6", "slug": "non-hec-projects-completed", "template": 3, "code": "1(a)(iii)-B",
        "title": "Non-HEC-funded research projects completed",
        "count_field": "non_hec_funded_projects_completed",
        "legacy_endpoint": "api/RicForm1/submit-non-hec-funded-research-project-completed",
        "amount_field": "total_funding_released",
        "fields": [
            F("research_grant_name", "Name of research grant"),
            F("project_completion_date", "Date of project completion", "date"),
            *pi_block(legacy_desig="PI_name", legacy_dept="PI_name"),
            F("thematic_area", "Thematic area"),
            F("research_proposal_title", "Title of research proposal"),
            *duration(),
            F("total_funding_utilized", "Total funding utilized (PKR million)", "decimal", money=True),
            F("total_funding_released", "Total funding released (PKR million)", "decimal", money=True),
            F("project_status", "Project status", "select", options=PROJECT_STATUS),
            F("key_project_deliverables", "Key project deliverables & outcomes (brief summary)", "file"),
            EVIDENCE(),
        ],
    },
    {
        "key": "A7", "slug": "joint-projects-submitted", "template": 4, "code": "1(a)(iv)-A",
        "title": "Joint research projects submitted (national / international funding agencies)",
        "count_field": "joint_projects_submitted",
        "legacy_endpoint": "api/RicForm1/submit-joint-research-projects",
        "amount_field": "total_funding_requested",
        "fields": [
            F("joint_research_grant_name", "Name of joint research grant & funding agency"),
            F("submission_date", "Date of joint project submission", "date"),
            F("national_or_international", "National or international", "select", options=NAT_INT),
            *pi_block(),
            *co_pi_block(),
            F("thematic_area", "Thematic area"),
            F("research_proposal_title", "Title of research proposal"),
            *duration(),
            F("total_funding_requested", "Total funding requested (PKR million)", "decimal", money=True),
            F("co_funding_partners_details", "Co-funding partner(s) details", required=False),
            F("status", "Status", "select", options=PROJECT_STATUS),
            F("remarks", "Remarks / any other information", "textarea", required=False),
            EVIDENCE(),
        ],
    },
    {
        "key": "A8", "slug": "joint-projects-approved", "template": 4, "code": "1(a)(iv)-B",
        "title": "Joint research projects approved (national / international funding agencies)",
        "count_field": "joint_projects_approved",
        "legacy_endpoint": "api/RicForm1/submit-joint-research-projects-approved",
        "amount_field": "total_funding_approved",
        "fields": [
            F("joint_research_grant_name", "Name of joint research grant"),
            F("funding_agency", "Name of funding agency"),
            F("approval_date", "Date of joint project approval", "date"),
            F("national_or_international", "National or international", "select", options=NAT_INT),
            *pi_block(),
            *co_pi_block(desig_legacy="coPI_designation"),
            F("thematic_area", "Thematic area"),
            F("research_proposal_title", "Title of research proposal"),
            *duration(),
            F("total_funding_approved", "Total funding approved (PKR million)", "decimal", money=True),
            F("co_funding_partners_details", "Co-funding partner(s) details", required=False),
            F("status", "Status", "select", options=PROJECT_STATUS),
            F("remarks", "Remarks / any other information", "textarea", required=False),
            EVIDENCE(),
        ],
    },
    {
        "key": "A9", "slug": "joint-projects-completed", "template": 4, "code": "1(a)(iv)-C",
        "title": "Joint research projects completed (national / international funding agencies)",
        "count_field": "joint_projects_completed",
        "legacy_endpoint": "api/RicForm1/submit-joint-research-projects-completed",
        "amount_field": "total_funding_utilized",
        "fields": [
            F("joint_research_grant_name", "Name of joint research grant"),
            F("funding_agency", "Funding agency"),
            F("completion_date", "Date of joint project completion", "date"),
            F("national_or_international", "National or international", "select", options=NAT_INT),
            *pi_block(),
            *co_pi_block(univ_legacy="co_PI_university"),
            F("thematic_area", "Thematic area"),
            F("research_proposal_title", "Title of research proposal"),
            *duration(),
            F("total_funding_utilized", "Total funding utilized (PKR million)", "decimal", money=True),
            F("total_funding_released", "Total funding released (PKR million)", "decimal", money=True,
              legacy="total_funding_requested"),
            F("co_funding_partners_details", "Co-funding partner(s) details", required=False),
            F("status", "Status", "select", options=PROJECT_STATUS),
            F("key_project_deliverables", "Key project deliverables & outcomes", "file"),
            EVIDENCE(),
        ],
    },
    {
        "key": "A10", "slug": "contract-research", "template": 5, "code": "1(b)",
        "title": "Contract research awarded",
        "count_field": "contract_research_awarded",
        "legacy_endpoint": "api/RicForm1/contract-research-awarded",
        "amount_field": "total_amount_approved",
        "fields": [
            F("thematic_area", "Thematic area(s)"),
            F("research_proposal_title", "Title of research proposal"),
            F("contract_signed_date", "Date contract signed", "date"),
            *pi_block(legacy_desig="PI_designation", legacy_dept="PI_department"),
            F("co_pi_name", "Name of Co-PI", required=False, legacy="co_PI_name"),
            F("co_pi_designation", "Co-PI designation (if other than parent HEI)", required=False, legacy="co_PI_designation"),
            F("co_pi_department", "Co-PI department (if other than parent HEI)", required=False, legacy="co_PI_department"),
            F("co_pi_university", "Co-PI university (if other than parent HEI)", required=False, legacy="co_PI_university"),
            F("sponsoring_agency_name", "Sponsoring agency name"),
            F("sponsoring_agency_address", "Sponsoring agency address & country"),
            F("national_or_international", "National or international", "select", options=NAT_INT),
            F("counterpart_industry", "Counterpart from industry (address with country)"),
            *duration(),
            F("total_amount_approved", "Total amount approved (PKR million)", "decimal", money=True),
            F("expected_deliverables", "Expected deliverables & outcomes", "textarea"),
            EVIDENCE(),
        ],
    },
    {
        "key": "A11", "slug": "policy-advocacy", "template": 5, "code": "1(c)",
        "title": "Policy advocacy / case studies",
        "count_field": "policy_advocacy_case_studies",
        "legacy_endpoint": "api/RicForm1/submit-policy-advocacy-case-study",
        "fields": [
            F("government_body_presented", "Government body presented to"),
            F("presentation_date", "Date of presentation", "date"),
            *pi_block(legacy_desig="PI_designation", legacy_dept="PI_department"),
            F("advocacy_area", "Area advocated",
              help="Political, law & order, economic development, social protection, etc."),
            F("brief", "Brief", "textarea"),
            *duration(),
            F("coalition_partners", "Coalition partners in advocacy", required=False),
            F("research_status", "Issue verification / backing research status", "select", options=PROJECT_STATUS),
            F("advocacy_tools", "Advocacy tools adopted",
              help="Briefings, meetings, websites, social media, etc."),
            EVIDENCE(),
        ],
    },
    {
        "key": "A12", "slug": "research-links", "template": 5, "code": "1(d)",
        "title": "Research links established (academic / research linkages)",
        "count_field": "research_links_established",
        "legacy_endpoint": "api/RicForm1/submit-research-link",
        "fields": [
            F("linkage_type", "Type of linkage", "select", options=["Academic", "Research"]),
            F("mou_agreement_date", "Date of MoU / agreement", "date", legacy="MoU_agreement_date"),
            F("national_or_international", "National or international", "select", options=NAT_INT),
            F("host_institution_name", "Name of host institution"),
            F("host_institution_address", "Address & country of host institution"),
            F("collaborating_agency_name", "Name of collaborating agency / institution"),
            F("collaborating_agency_address", "Address & country of collaborating agency / institution"),
            F("field_of_study", "Field of study / broad research areas"),
            F("scope_of_collaboration", "Scope of collaboration", "textarea"),
            F("salient_features", "Salient features of linkage", "textarea"),
            EVIDENCE(),
        ],
    },
    {
        "key": "A13", "slug": "civic-engagement", "template": 5, "code": "1(e)",
        "title": "Civic engagement events / initiatives",
        "count_field": "civic_engagements",
        "legacy_endpoint": "api/RicForm1/submit-civic-engagement-event",
        "amount_field": "grant_value",
        "fields": [
            F("event_title", "Title of event / initiative"),
            F("event_date", "Date of event", "date"),
            F("community_component", "Component of community involved / addressed",
              legacy="community_component_involved"),
            F("outcome", "Outcome (case study, policy advice or relevant)", "textarea"),
            F("collaboration_developed", "Collaboration developed (local authorities, government departments)"),
            F("engaged_csos_ngos", "CSOs / NGOs engaged", legacy="engaged_CSOs_Or_NGOs"),
            F("sponsoring_agency", "Sponsoring agency"),
            F("grant_value", "Grant value / sponsorship (PKR)", "decimal", money=True),
            F("arranged_or_participated", "Arranged or participated", "select", options=["Arranged", "Participated"]),
            F("dissemination_material", "Dissemination / outcome material (brochure, report, web link)", required=False),
            F("remarks", "Remarks", "textarea", required=False),
            EVIDENCE(),
        ],
    },
    {
        "key": "A14", "slug": "consultancy-contracts", "template": 5, "code": "1(f)",
        "title": "Consultancy contracts executed through ORIC",
        "count_field": "consultancy_contracts_executed",
        "legacy_endpoint": "api/RicForm1/submit-consultancy-contract",
        "amount_field": "contract_value",
        "fields": [
            F("project_title", "Project title"),
            F("execution_date", "Date of execution", "date"),
            *pi_block(legacy_desig="PI_designation", legacy_dept="PI_department"),
            F("company_details", "Company details"),
            F("contract_value", "Contract value (PKR)", "decimal", money=True),
            *duration(),
            F("consultancy_type", "Consultancy type"),
            F("key_deliverables", "Key deliverables", "textarea"),
            F("oric_percentage", "ORIC share (%)", "decimal", legacy="ORIC_percentage"),
            F("remarks", "Remarks", "textarea", required=False),
            EVIDENCE(),
        ],
    },
    {
        "key": "A15", "slug": "asrb-liaison", "template": 5, "code": "1(g)",
        "title": "Liaison developed with Advanced Studies & Research Board (AS&RB)",
        "count_field": "liaison_with_asrb",
        "legacy_endpoint": "api/RicForm1/submit-liaison-asrb",
        "fields": [
            F("liaison_with", "Liaison developed with"),
            F("execution_date", "Date of execution", "date"),
            EVIDENCE(),
        ],
    },
]

# =============================================================================
# Pillar IC — Innovation & Commercialization (legacy RicForm2, "Intellectual
# Property and Product Development")
# =============================================================================
IC_COUNTS = [
    F("ip_disclosures_made", "IP disclosures made with patent department / attorney", "int", legacy="ipdisclosurescount"),
    F("patents_filed", "Patents / trademarks / design patents / copyrights FILED", "int", legacy="patentsfiledcount"),
    F("patents_granted", "Patents / trademarks / design patents / copyrights GRANTED", "int", legacy="patentsgrantedcount"),
    F("ip_licensing_negotiations_initiated", "IP licensing negotiations initiated", "int", legacy="licensingnegotiationscount"),
    F("licenses_signed", "Exclusive or non-exclusive licenses signed", "int", legacy="licensessignedcount"),
    F("products_prototypes_developed", "Products / prototypes developed", "int", legacy="productsdevelopedcount"),
    F("products_prototypes_displayed", "Products / prototypes displayed (science, arts, design)", "int", legacy="productsdisplayedcount"),
    F("industry_visits", "Visits by industry / community representatives", "int", legacy="industryvisitscount"),
    F("agreements_signed", "Collaboration agreements signed (industry, government, community)", "int", legacy="collaborationagreementscount"),
    F("honors_awards_won", "National or international honors / awards won", "int", legacy="honorsawardscount"),
    F("oric_trainings_arranged", "Trainings / workshops / seminars / conferences arranged by ORIC", "int", legacy="orictrainingscount"),
    F("external_trainings_arranged", "Trainings / workshops / seminars / conferences by other HEIs, attended", "int", legacy="externaltrainingscount"),
    F("exhibitions_arranged", "Exhibitions / showcasing events / linkage fairs arranged by ORIC", "int",
      legacy="(none — added; legacy had no count for B12)"),
    F("research_publications", "Research publications (HJRS W/X/Y)", "int", legacy="researchpublicationscount"),
]

IC_SECTIONS = [
    {
        "key": "B1", "slug": "ip-disclosures", "template": 1, "code": "2(a)",
        "title": "IP disclosures made with patent department / patent attorney",
        "count_field": "ip_disclosures_made",
        "legacy_endpoint": "api/ricforms/ip-disclosure",
        "fields": [
            *invention_block(),
            F("commercial_partner", "Commercial partner", required=False, legacy="commercialpartner"),
            F("disclosure_made_with", "Disclosure made with (patent dept / attorney name & details)", legacy="disclosuremadewith"),
            F("disclosure_date", "Date of disclosure", "date", legacy="disclosuremadedate"),
            F("financial_support", "Financial support", required=False, legacy="financialsupport"),
            F("previous_disclosure", "Previous disclosure", required=False, legacy="previousdisclosure"),
            EVIDENCE(),
        ],
    },
    {
        "key": "B2", "slug": "patents", "template": 1, "code": "2(b)",
        "title": "Patents / trademarks / design patents / copyrights filed or granted",
        "count_field": ["patents_filed", "patents_granted"],
        "count_split": {"field": "filed_or_granted", "Filed": "patents_filed", "Granted": "patents_granted"},
        "legacy_endpoint": "api/ricforms/patent",
        "fields": [
            F("filed_or_granted", "Filed or granted", "select", options=["Filed", "Granted"], legacy="filedorgranted"),
            F("national_or_international", "National or international", "select", options=NAT_INT, legacy="nationalorinternational"),
            *invention_block(),
            F("commercial_partner", "Commercial partner", required=False, legacy="commercialpartner"),
            F("patent_filed_with", "Patent filed with (dept / authority name & details)", legacy="patentfiledwith"),
            F("granting_authority", "Patent granting authority (name & details)", required=False, legacy="patentgrantingauthority",
              help="Required when the patent is granted."),
            F("financial_support", "Financial support", required=False, legacy="financialsupport"),
            F("filing_date", "Date of filing", "date", legacy="dateoffiling"),
            F("filing_evidence", "Filing evidence", "file", legacy="filingevidence"),
            F("granting_evidence", "Granting evidence", "file", required=False, legacy="grantingevidence"),
        ],
    },
    {
        "key": "B3", "slug": "ip-licensing-negotiations", "template": 2, "code": "2(c)",
        "title": "IP licensing negotiations initiated",
        "count_field": "ip_licensing_negotiations_initiated",
        "legacy_endpoint": "api/ricforms/ip-licensing-negotiation",
        "fields": [
            F("national_or_international", "National or international", "select", options=NAT_INT, legacy="licensingtype"),
            *invention_block(),
            F("field_of_use", "Field of use", legacy="fieldofuse"),
            F("duration_of_agreement", "Duration of agreement", legacy="durationofagreement"),
            F("licensee_details", "Licensee details (name, organization)", legacy="licensedetails"),
            F("negotiation_status", "Status of negotiation", legacy="statusofnegotiation"),
            EVIDENCE(),
        ],
    },
    {
        "key": "B4", "slug": "licenses-signed", "template": 2, "code": "2(d)",
        "title": "Exclusive or non-exclusive licenses signed",
        "count_field": "licenses_signed",
        "legacy_endpoint": "api/ricforms/exclusive-or-nonexclusive",
        "fields": [
            F("license_type", "Exclusive or non-exclusive", "select", options=["Exclusive", "Non-exclusive"], legacy="licensetype"),
            F("national_or_international", "National or international", "select", options=NAT_INT, legacy="licenseregion"),
            *invention_block(),
            F("field_of_use", "Field of use", legacy="fieldofuse"),
            F("agreement_date", "Date of agreement", "date", legacy="dateanddurationofagreement"),
            F("agreement_duration", "Duration of agreement",
              legacy="(split from dateanddurationofagreement)"),
            F("licensee_details", "Licensee details (name, organization)", legacy="licensedetails"),
            EVIDENCE(),
        ],
    },
    {
        "key": "B5", "slug": "research-products", "template": 2, "code": "2(e)",
        "title": "Products / prototypes developed",
        "count_field": "products_prototypes_developed",
        "legacy_endpoint": "api/ricforms/research-product",
        "fields": [
            F("national_or_international", "National or international", "select", options=NAT_INT, legacy="researchregion"),
            *invention_block(),
            F("field_of_use", "Field of use", legacy="fieldofuse"),
            F("industrial_partner", "Collaborating industrial partner (name & details)", legacy="collaboratingindustrialpartner"),
            F("financial_support", "Financial support", required=False, legacy="financialsupport"),
            F("remarks", "Remarks", "textarea", required=False),
            EVIDENCE(),
        ],
    },
    {
        "key": "B6", "slug": "science-arts-products", "template": 3, "code": "2(f)",
        "title": "Science / arts / design products displayed",
        "count_field": "products_prototypes_displayed",
        "legacy_endpoint": "api/ricforms/science-arts-product",
        "fields": [
            F("national_or_international", "National or international", "select", options=NAT_INT, legacy="displayregion"),
            F("title", "Title"),
            F("lead_name", "Name of lead", legacy="leadname"),
            F("lead_designation", "Designation of lead", legacy="leaddesignation"),
            F("lead_department", "Department of lead", "department", legacy="leaddepartment"),
            F("product_category", "Category of product", "radio",
              options=["Science", "Arts", "Design Product", "Exhibition", "Other"], other=True, legacy="productcategory"),
            F("forum", "Forum where registered / performed / displayed"),
            F("status", "Status"),
            F("financial_support", "Financial support", required=False, legacy="financialsupport"),
            F("field_of_use", "Field of use", legacy="fieldofuse"),
            EVIDENCE(),
        ],
    },
    {
        "key": "B7", "slug": "industry-visits", "template": 3, "code": "2(g)",
        "title": "Visits by representatives of industry or community",
        "count_field": "industry_visits",
        "legacy_endpoint": "api/ricforms/visit-representative",
        "fields": [
            F("visitor_name", "Name of visitor / organization", legacy="visitorname"),
            F("visit_date", "Date of visit", "date", legacy="visitdate"),
            F("agenda", "Agenda of visit", "textarea"),
            EVIDENCE(),
        ],
    },
    {
        "key": "B8", "slug": "agreements", "template": 3, "code": "2(h)",
        "title": "Agreements signed for collaboration with industry, government or community",
        "count_field": "agreements_signed",
        "legacy_endpoint": "api/ricforms/agreement",
        "fields": [
            F("linkage_type", "Type of linkage", "select", options=["Academic", "Research", "Industry", "Government", "Community"],
              legacy="typeoflinkage"),
            F("national_or_international", "National or international", "select", options=NAT_INT, legacy="nationalorinternational"),
            F("host_institution", "Name & address (with country) of partner institution", legacy="hostinstitutionnameandaddress"),
            F("duration", "Duration"),
            F("key_initiatives", "Key initiatives to be undertaken", "textarea", legacy="keyinitiatives"),
            F("field", "Field"),
            F("scope_of_collaboration", "Scope of collaboration", "textarea", legacy="scopeofcollaboration"),
            F("establishment_date", "Linkage establishment date", "date", legacy="linkageestablishmentdate"),
            F("financial_support", "Financial support", required=False, legacy="financialsupport"),
            EVIDENCE(),
        ],
    },
    {
        "key": "B9", "slug": "honors-awards", "template": 4, "code": "2(i)",
        "title": "National or international honors / awards won",
        "count_field": "honors_awards_won",
        "legacy_endpoint": "api/ricforms/honor-award",
        "amount_field": "prize_money",
        "fields": [
            F("title", "Title of award / honor"),
            F("conferring_organization", "Forum / conferring authority / organization (name, contacts)", legacy="forumororganization"),
            F("award_received", "Award / prize / certificate received", legacy="awardreceived"),
            F("work_details", "Brief details of work honored", "textarea", legacy="workdetails"),
            F("prize_money", "Prize money (PKR)", "decimal", required=False, money=True, legacy="prizemoney"),
            F("winner_details", "Name, designation & department of award winner", legacy="awardwinnerdetails"),
            F("remarks", "Remarks / other details", "textarea", required=False),
            EVIDENCE(),
        ],
    },
    {
        "key": "B10", "slug": "oric-trainings", "template": 4, "code": "2(j)",
        "title": "Trainings / workshops / seminars / conferences arranged by ORIC",
        "count_field": "oric_trainings_arranged",
        "legacy_endpoint": "api/ricforms/training-workshop-seminar",
        "fields": [
            F("event_type", "Type of event", "radio", options=EVENT_KIND, other=True, legacy="eventtype"),
            F("event_level", "National or international", "select", options=NAT_INT, legacy="eventlevel"),
            F("title", "Title of event"),
            F("event_date", "Date of event", "date", legacy="eventdate"),
            F("participants", "Number of participants", "int", legacy="numberofparticipants"),
            F("focus_and_outcomes", "Major focus area & outcomes", "textarea", legacy="focusandoutcomes"),
            EVIDENCE(),
        ],
    },
    {
        "key": "B11", "slug": "external-trainings", "template": 4, "code": "2(k)",
        "title": "Trainings / workshops / seminars / conferences by other HEIs or organizations (attended)",
        "count_field": "external_trainings_arranged",
        "legacy_endpoint": "api/ricforms/conference-arranged",
        "fields": [
            F("event_type", "Type of event", "radio", options=EVENT_KIND, other=True, legacy="eventtype"),
            F("event_level", "National or international", "select", options=NAT_INT, legacy="eventlevel"),
            F("title", "Title of event"),
            F("event_date", "Date of event", "date", legacy="eventdate"),
            F("participants", "Number of participants", "int", legacy="numberofparticipants"),
            F("focus_and_outcomes", "Major focus area & outcomes", "textarea", legacy="focusandoutcomes"),
            F("organizer", "Organizer"),
            F("audience_type", "Audience type", "select", options=AUDIENCE, legacy="audiencetype"),
            EVIDENCE(),
        ],
    },
    {
        "key": "B12", "slug": "exhibitions", "template": 4, "code": "2(l)",
        "title": "Exhibitions / showcasing events / industry linkage fairs / IP stimulus arranged by ORIC",
        "count_field": "exhibitions_arranged",
        "legacy_endpoint": "api/ricforms/exhibition-event",
        "fields": [
            F("event_type", "Type of event", "select",
              options=["Exhibitions", "Showcasing Event", "Industry Linkages Fair", "Seminars",
                       "Industry or IP & Licensing Stimulus"], legacy="eventtype"),
            F("title", "Title of event", legacy="(added — legacy form had no title)"),
            F("event_level", "National or international", "select", options=NAT_INT, legacy="eventlevel"),
            F("event_date", "Date of event", "date", legacy="eventdate"),
            F("participants", "Number of participants", "int", legacy="numberofparticipants"),
            F("focus_and_outcomes", "Major focus area & outcomes", "textarea", legacy="focusandoutcomes"),
            F("audience_type", "Audience type", "select", options=AUDIENCE, legacy="audiencetype"),
            EVIDENCE(),
        ],
    },
    {
        "key": "B13", "slug": "research-publications", "template": 5, "code": "2(m)",
        "title": "Research publications",
        "count_field": "research_publications",
        "legacy_endpoint": "api/ricforms/research-publication",
        "fields": [
            F("publication_category", "Publication category (HJRS)", "select", options=["W", "X", "Y"],
              legacy="publicationcategory"),
            F("publication_reference", "Publication reference", "textarea", legacy="publicationreference",
              help="Full citation, e.g. Author (2024) Title. Journal, vol(issue), pages."),
            F("publication_link", "Publication link / DOI", "url", legacy="publicationlink"),
            EVIDENCE(help="First page of the paper. Name it like 'Author (2024) Short title.pdf'."),
        ],
    },
]

# =============================================================================
# Pillar SCB — Sustainability & Capacity Building / entrepreneurship
# (legacy RicForm3: faculty startups, spin-offs, funding, events)
# =============================================================================
SCB_COUNTS = [
    F("faculty_led_startups", "Faculty-led startups", "int", legacy="number_faculty_led_startups"),
    F("spin_offs", "Faculty startups that are spin-offs", "int", legacy="number_spin_offs"),
    F("startup_fundings", "Funding rounds / awards secured by startups", "int",
      legacy="(added — legacy had no count for C3)"),
    F("entrepreneurship_events", "Entrepreneurship events / activities held", "int",
      legacy="(added — legacy had no count for C4)"),
    F("jobs_created_retained", "Jobs created and retained over 2 years (faculty startups)", "int",
      legacy="jobs_created_retained"),
    F("students_placed", "Students placed in faculty startups or spin-offs (internships / jobs)", "int",
      legacy="students_placed"),
    F("participation_count", "Faculty / student participation in entrepreneurship trainings, workshops, seminars",
      "int", legacy="participation_count"),
]

SCB_SECTIONS = [
    {
        "key": "C1", "slug": "faculty-startups", "template": 1, "code": "3(a)",
        "title": "Faculty-led startups",
        "count_field": "faculty_led_startups",
        "legacy_endpoint": "api/RicForm3/faculty_startups",
        "amount_field": "revenue",
        "fields": [
            F("startup_name", "Name of the startup"),
            F("sector", "Sector / field (thematic area)"),
            F("stage", "Stage of product or service", help="Initial, prototype developed, etc."),
            F("license_agreement", "License agreement signed (and with whom)", required=False),
            F("funding_source", "Funds secured and source of funding", required=False, help="Write N/A if none."),
            F("revenue", "Revenue generated (PKR)", "decimal", money=True),
            F("internships_created", "Internships created", "int"),
            F("jobs_created", "Jobs created", "int"),
            F("ip_status", "IP status", "select",
              options=["Not applicable", "Not filed (will file in future)", "Disclosed", "Filed/under process", "Granted"]),
            EVIDENCE(),
        ],
    },
    {
        "key": "C2", "slug": "spin-offs", "template": 1, "code": "3(b)",
        "title": "Faculty startups as spin-offs",
        "count_field": "spin_offs",
        "legacy_endpoint": "api/RicForm3/spin_offs",
        "amount_field": "revenue",
        "fields": [
            F("spinoff_name", "Name of the spin-off"),
            F("stage", "Stage of spin-off", "select",
              options=["Not applicable", "Initial", "Pilot", "Commercial Production", "Other"]),
            F("license_agreement", "License agreement signed", required=False, help="Write N/A if none."),
            F("revenue", "Revenue generated (PKR)", "decimal", money=True),
            EVIDENCE(),
        ],
    },
    {
        "key": "C3", "slug": "startup-funding", "template": 2, "code": "3(c)",
        "title": "Funding secured by startups / spin-offs",
        "count_field": "startup_fundings",
        "legacy_endpoint": "api/RicForm3/funding",
        "amount_field": "amount",
        "fields": [
            F("startup_details", "Startup (name and sector / field)"),
            F("funding_agency", "Name of funding agency"),
            F("funding_type", "Type of funding", "select",
              options=["Award prize (competition win)", "Pre-seed", "Seed", "Angel investment", "VC", "Other"]),
            F("amount", "Amount secured and utilized (PKR)", "decimal", money=True),
            F("agreement_signed", "Agreement signed with funding agency", "select", options=["Yes", "No"]),
            F("in_kind_support", "In-kind support from funding agency (details)", required=False),
            EVIDENCE(),
        ],
    },
    {
        "key": "C4", "slug": "entrepreneurship-events", "template": 2, "code": "3(d)",
        "title": "Entrepreneurship events / activities",
        "count_field": "entrepreneurship_events",
        "legacy_endpoint": "api/RicForm3/events",
        "fields": [
            F("title", "Title of event / activity"),
            F("event_date", "Date(s) held", "date"),
            F("venue", "Venue"),
            F("field", "Field / thematic area"),
            F("panelist_details", "Panelist / mentor / advisor details", "textarea"),
            F("organizers", "Arranged by (organizers)"),
            F("audience", "Targeted audience", "select", options=["Faculty", "Students", "Both"]),
            F("participants_count", "Number of participants (approx.)", "int"),
            EVIDENCE(),
        ],
    },
]

PILLARS = [
    {
        "key": "RE",
        "name": "Research Excellence",
        "tagline": "Research grants, industrial linkage & policy advocacy",
        "legacy_form": "RicForm1",
        "counts": RE_COUNTS,
        "sections": RE_SECTIONS,
    },
    {
        "key": "IC",
        "name": "Innovation & Commercialization",
        "tagline": "Intellectual property, products & industry engagement",
        "legacy_form": "RicForm2",
        "counts": IC_COUNTS,
        "sections": IC_SECTIONS,
    },
    {
        "key": "SCB",
        "name": "Sustainability & Capacity Building",
        "tagline": "Faculty startups, spin-offs, funding & entrepreneurship events",
        "legacy_form": "RicForm3",
        "counts": SCB_COUNTS,
        "sections": SCB_SECTIONS,
    },
]

PILLAR_BY_KEY = {p["key"]: p for p in PILLARS}
SECTION_BY_KEY = {s["key"]: s for p in PILLARS for s in p["sections"]}
SECTION_PILLAR = {s["key"]: p["key"] for p in PILLARS for s in p["sections"]}


def section_count_fields(section) -> list[str]:
    cf = section["count_field"]
    return cf if isinstance(cf, list) else [cf]


def public_schema() -> dict:
    """JSON-safe schema served to the frontend (drops legacy-only metadata)."""
    def clean_field(f):
        return {k: v for k, v in f.items() if k != "legacy"}

    return {
        "departments": DEPARTMENTS,
        "pillars": [
            {
                "key": p["key"],
                "name": p["name"],
                "tagline": p["tagline"],
                "counts": [clean_field(f) for f in p["counts"]],
                "sections": [
                    {
                        "key": s["key"],
                        "slug": s["slug"],
                        "code": s["code"],
                        "template": s["template"],
                        "title": s["title"],
                        "count_fields": section_count_fields(s),
                        "count_split": s.get("count_split"),
                        "amount_field": s.get("amount_field"),
                        "fields": [clean_field(f) for f in s["fields"]],
                    }
                    for s in p["sections"]
                ],
            }
            for p in PILLARS
        ],
    }
