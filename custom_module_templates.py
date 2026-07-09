"""
custom_module_templates.py — Pre-built templates for common team modules.

Users pick a template → get schema hints + sample data structure + analytics presets.
"""

TEMPLATES = {
    "hr_recruiting": {
        "name": "HR - Recruiting Pipeline",
        "team": "HR",
        "description": "Track candidates through hiring stages",
        "required_columns": ["candidate_name", "email", "role", "stage", "applied_date"],
        "optional_columns": ["source", "recruiter", "rejected_reason", "hired_date"],
        "stages": ["applied", "screening", "interview", "offer", "hired", "rejected"],
        "example_row": {
            "candidate_name": "Jane Doe", "email": "jane@example.com",
            "role": "Engineer", "stage": "interview",
            "applied_date": "2026-06-01", "source": "LinkedIn",
        },
    },
    "finance_expenses": {
        "name": "Finance - Expenses",
        "team": "Finance",
        "description": "Track team expenses & categorization",
        "required_columns": ["date", "amount", "category", "description"],
        "optional_columns": ["paid_by", "receipt_url", "approved"],
        "example_row": {
            "date": "2026-07-01", "amount": 250.00,
            "category": "Software", "description": "Adobe subscription",
            "paid_by": "founder",
        },
    },
    "sales_pipeline": {
        "name": "Sales - Deals Pipeline",
        "team": "Sales",
        "description": "Track deals through sales stages",
        "required_columns": ["company", "contact_email", "deal_value", "stage", "opened_date"],
        "optional_columns": ["owner", "notes", "close_date"],
        "stages": ["lead", "qualified", "proposal", "negotiation", "won", "lost"],
        "example_row": {
            "company": "Acme Corp", "contact_email": "buyer@acme.com",
            "deal_value": 5000.00, "stage": "proposal",
            "opened_date": "2026-06-15", "owner": "sales_rep_1",
        },
    },
    "product_feedback": {
        "name": "Product - User Feedback",
        "team": "Product",
        "description": "Track user feedback / feature requests",
        "required_columns": ["date", "user_email", "type", "message"],
        "optional_columns": ["priority", "status", "product_area"],
        "types": ["bug", "feature_request", "complaint", "praise"],
        "example_row": {
            "date": "2026-07-05", "user_email": "user@example.com",
            "type": "feature_request", "message": "Add dark mode",
            "priority": "medium",
        },
    },
    "content_calendar": {
        "name": "Marketing - Content Calendar",
        "team": "Marketing",
        "description": "Plan & track content publishing",
        "required_columns": ["publish_date", "title", "platform", "status"],
        "optional_columns": ["author", "url", "views"],
        "platforms": ["YouTube", "LinkedIn", "Blog", "Twitter"],
        "statuses": ["draft", "review", "scheduled", "published"],
        "example_row": {
            "publish_date": "2026-07-15", "title": "How to Pixel Stream",
            "platform": "YouTube", "status": "scheduled",
        },
    },
    "customer_calls": {
        "name": "CS - Customer Calls Log",
        "team": "Customer Success",
        "description": "Log customer calls & outcomes",
        "required_columns": ["date", "customer_email", "call_type", "outcome"],
        "optional_columns": ["duration_min", "csm", "notes"],
        "call_types": ["onboarding", "check_in", "support", "renewal"],
        "example_row": {
            "date": "2026-07-08", "customer_email": "customer@company.com",
            "call_type": "check_in", "outcome": "satisfied",
            "duration_min": 30, "csm": "amit",
        },
    },
    "vendor_contracts": {
        "name": "Ops - Vendor Contracts",
        "team": "Ops",
        "description": "Track vendor agreements & renewal dates",
        "required_columns": ["vendor", "service", "start_date", "renewal_date", "monthly_cost"],
        "optional_columns": ["contract_url", "notes", "auto_renew"],
        "example_row": {
            "vendor": "AWS", "service": "EC2 hosting",
            "start_date": "2026-01-01", "renewal_date": "2027-01-01",
            "monthly_cost": 450.00, "auto_renew": True,
        },
    },
}


def get_template_names():
    return list(TEMPLATES.keys())


def get_template(slug):
    return TEMPLATES.get(slug)


def render_template_picker_ui():
    """Streamlit UI to pick a template."""
    import streamlit as st
    st.markdown("### Choose a template (optional)")
    st.caption("Pre-built structures for common team dashboards.")

    template_choice = st.selectbox(
        "Template",
        ["(none — I'll upload my own)"] + [f"{k}: {v['name']}" for k, v in TEMPLATES.items()],
        key="cm_template_pick",
    )

    if template_choice.startswith("(none"):
        return None

    slug = template_choice.split(":")[0]
    t = TEMPLATES[slug]

    with st.expander(f"About '{t['name']}'", expanded=True):
        st.markdown(f"**Team:** {t['team']}")
        st.markdown(f"**Purpose:** {t['description']}")
        st.markdown(f"**Required columns:** `{', '.join(t['required_columns'])}`")
        if t.get("optional_columns"):
            st.markdown(f"**Optional:** `{', '.join(t['optional_columns'])}`")
        st.markdown("**Example row:**")
        st.json(t["example_row"])

    return t
