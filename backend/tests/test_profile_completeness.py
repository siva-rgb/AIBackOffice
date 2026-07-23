"""Profile completeness — tolerating a raw JSONB dict.

Regression for a real 500 found during live testing: some store paths hand back
`user.profile` as a plain dict rather than a `BusinessProfile`, and the
completeness helper assumed attribute access.
"""
from __future__ import annotations

from app.models import BusinessProfile
from app.routers.users import _profile_completeness


def test_completeness_of_an_empty_profile_is_zero():
    result = _profile_completeness(BusinessProfile())
    assert result["percent"] == 0
    assert all(v is False for v in result["sections"].values())


def test_completeness_accepts_a_profile_built_from_a_raw_dict():
    """The shape that caused the 500 — nested domains arriving as plain dicts."""
    profile = BusinessProfile(**{
        "displayName": "Alex Rivera",
        "industry": "Design",
        "brand": {"mission": "Make small brands look big", "voice": "warm, direct"},
        "offerings": [{"name": "Brand identity", "pricing": "$4,000"}],
    })

    result = _profile_completeness(profile)

    assert result["sections"]["identity"] is True
    assert result["sections"]["brand"] is True
    assert result["sections"]["offerings"] is True
    assert result["sections"]["operations"] is False
    assert 0 < result["percent"] < 100


def test_null_jsonb_domains_do_not_crash():
    """Supabase hands back JSON null for an unset domain; it must coerce to {}."""
    profile = BusinessProfile(**{
        "displayName": "Alex",
        "brand": None,
        "customers": None,
        "operations": None,
        "marketing": None,
        "legalFinancial": None,
    })

    result = _profile_completeness(profile)

    assert result["sections"]["identity"] is True
    assert result["sections"]["brand"] is False
    assert isinstance(result["percent"], int)


def test_percent_is_a_whole_number_between_0_and_100():
    profile = BusinessProfile(**{
        "displayName": "Alex",
        "roleTitle": "Designer",
        "industry": "Design",
        "description": "Independent brand designer",
        "brand": {"mission": "m", "vision": "v", "usp": "u", "voice": "w"},
        "offerings": [{"name": "Identity"}],
        "customers": {"industriesServed": ["SaaS"]},
        "operations": {"tools": ["Figma"]},
        "marketing": {"competitors": ["Someone"]},
        "legalFinancial": {"taxInfo": "VAT 123"},
        "monthlyRevenueGoal": 8000,
    })

    result = _profile_completeness(profile)

    assert result["percent"] == 100
    assert all(result["sections"].values())
