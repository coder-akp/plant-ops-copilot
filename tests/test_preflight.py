from scripts import azure_preflight as pf

LOCATIONS = [
    {"name": "eastus", "displayName": "East US"},
    {"name": "westeurope", "displayName": "West Europe"},
    {"name": "germanywestcentral", "displayName": "Germany West Central"},
    {"name": "swedencentral", "displayName": "Sweden Central"},
]


def test_region_names_are_normalized_between_display_and_programmatic_forms():
    lookup = pf.region_lookup(LOCATIONS)
    assert pf.supported_regions(["East US", "West Europe", "Nowhere"], lookup) == {"eastus", "westeurope", "nowhere"}
    allowed = pf.allowed_regions([{"allowed": ["eastus", "Germany West Central"]}], lookup)
    assert allowed == {"eastus", "germanywestcentral"}


def test_no_policy_means_no_restriction():
    lookup = pf.region_lookup(LOCATIONS)
    assert pf.allowed_regions([], lookup) is None
    assert pf.allowed_regions([{"allowed": None}], lookup) is None


def test_quota_filter_keeps_only_relevant_openai_models():
    usage = [
        {"name": {"value": "OpenAI.GlobalStandard.gpt-5-mini"}, "limit": 50, "currentValue": 0},
        {"name": {"value": "OpenAI.Standard.gpt-4o-mini"}, "limit": 0, "currentValue": 0},
        {"name": {"value": "OpenAI.GlobalStandard.o3"}, "limit": 100, "currentValue": 0},
        {"name": {"value": "AIServices.Something"}, "limit": 5, "currentValue": 1},
    ]
    rows = pf.model_quota(usage)
    assert ("OpenAI.GlobalStandard.gpt-5-mini", 50.0, 0.0) in rows
    assert len(rows) == 2 and all(r[0].startswith("OpenAI.") for r in rows)
